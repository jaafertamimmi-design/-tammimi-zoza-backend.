"""
محرك سعر الذهب الحقيقي (Live Feed) - نسخة async مبنية فوق goldprice_client.py.

لا يوجد أي عشوائية أو بيانات مصطنعة بهذا الملف. المصدر الوحيد: goldprice.dev
عبر GoldPriceClient (تحقق صارم: يرفض شموع مستقبلية، مكررة، أو OHLC غير منطقي).

معمارية:
  - عند الإقلاع: backfill حقيقي فوري لكل الفريمات التسعة عبر /v1/bars
    (M1/M3/M5/M10/M15/M30/H1/H4/D1 - M3 وM10 معاد تجميعهما من M1 حقيقي)
  - كل 5 ثوان: نبض سعر حي (/v1/prices) يحدّث السعر/Bid/Ask ويحرّك الشمعة
    الأخيرة "الجارية" بصرياً بس (ما تُحفظ نهائياً لقاعدة البيانات إلا بعد تأكيدها)
  - كل دقيقة: إعادة جلب آخر شموع مغلقة من /v1/bars لكل فريم (تصحيح ذاتي - كل
    شمعة "مغلقة" بالنظام مصدرها النهائي هو /v1/bars دائماً، مو التجميع اللحظي)
"""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from goldprice_client import GoldPriceClient, FeedStatus, OHLCVBar
from timeframes import TIMEFRAMES_SECONDS

# فريماتنا الداخلية <-> فريمات عميل goldprice.dev
TIMEFRAME_CLIENT_MAP = {
    "1m": "M1", "3m": "M3", "5m": "M5", "10m": "M10",
    "15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4", "1d": "D1",
}

BACKFILL_WINDOW = {
    "1m": timedelta(hours=6), "3m": timedelta(hours=18), "5m": timedelta(days=2),
    "10m": timedelta(days=4), "15m": timedelta(days=6), "30m": timedelta(days=10),
    "1h": timedelta(days=20), "4h": timedelta(days=60), "1d": timedelta(days=35),
}

MIN_CANDLES_FOR_SUFFICIENT = {
    "1m": 20, "3m": 20, "5m": 20, "10m": 15, "15m": 15,
    "30m": 10, "1h": 10, "4h": 5, "1d": 5,
}

BACKFILL_COUNT = 300
SPOT_POLL_SECONDS = 5
BARS_REFRESH_SECONDS = 60
BARS_REFRESH_RECENT_COUNT = 5


def _bar_to_dict(bar: OHLCVBar) -> Dict:
    return {
        "time": int(bar.timestamp.timestamp()),
        "open": float(bar.open), "high": float(bar.high),
        "low": float(bar.low), "close": float(bar.close),
    }


class GoldLivePriceFeed:
    def __init__(self):
        self.client: Optional[GoldPriceClient] = None
        self.current_price: Optional[float] = None
        self.bid: Optional[float] = None
        self.ask: Optional[float] = None
        self.spread: Optional[float] = None
        self.is_stale: Optional[bool] = None
        self.last_update: Optional[datetime] = None
        self.data_source_status = "STARTING"   # LIVE | STALE | DATA_SOURCE_UNAVAILABLE | PLAN_GATED | RATE_LIMITED | ...
        self.data_source_reason: Optional[str] = None

        self.candles: Dict[str, List[Dict]] = defaultdict(list)
        self.backfill_status: Dict[str, Dict] = {}   # لكل فريم: {ok, reason, count}
        self._on_close_callbacks: List[Callable[[str, Dict], None]] = []
        self._tasks: List[asyncio.Task] = []
        self._stop = False

    def register_on_close(self, callback: Callable[[str, Dict], None]):
        self._on_close_callbacks.append(callback)

    async def start(self, api_key: Optional[str] = None):
        self.client = GoldPriceClient(api_key)
        await self.backfill_all()
        self._stop = False
        self._tasks.append(asyncio.create_task(self._spot_loop()))
        self._tasks.append(asyncio.create_task(self._bars_refresh_loop()))

    async def stop(self):
        self._stop = True
        for t in self._tasks:
            t.cancel()
        if self.client:
            await self.client.aclose()

    async def backfill_all(self):
        now = datetime.now(timezone.utc)
        for tf, client_tf in TIMEFRAME_CLIENT_MAP.items():
            start = now - BACKFILL_WINDOW[tf]
            result = await self.client.get_bars(client_tf, start=start, end=now, count=BACKFILL_COUNT)
            if result.ok and result.data:
                bars = [_bar_to_dict(b) for b in result.data]
                self.candles[tf] = bars
                for c in bars:
                    self._notify_close(tf, c)
                self.backfill_status[tf] = {"ok": True, "count": len(bars), "reason": None}
            else:
                self.backfill_status[tf] = {
                    "ok": False, "count": 0,
                    "reason": f"{result.status.value}: {result.reason}" if result.reason else result.status.value,
                }

    def _notify_close(self, tf: str, candle: Dict):
        for cb in self._on_close_callbacks:
            try:
                cb(tf, candle)
            except Exception:
                pass

    async def _spot_loop(self):
        while not self._stop:
            result = await self.client.get_spot()
            now = datetime.now(timezone.utc)

            if result.data is not None:
                q = result.data
                self.current_price = float(q.price)
                self.bid = float(q.bid) if q.bid is not None else None
                self.ask = float(q.ask) if q.ask is not None else None
                self.spread = float(q.spread) if q.spread is not None else None
                self.is_stale = q.is_stale
                self.last_update = now
                self.data_source_status = "STALE" if result.status == FeedStatus.STALE_DATA else "LIVE"
                self.data_source_reason = result.reason
                self._update_forming_candles(self.current_price, now.timestamp())
            else:
                self.data_source_status = result.status.value
                self.data_source_reason = result.reason

            await asyncio.sleep(SPOT_POLL_SECONDS)

    def _update_forming_candles(self, price: float, ts: float):
        """يحرّك الشمعة الأخيرة (الجارية، غير المغلقة) بصرياً بس - لا تُعتبر
        مصدر حقيقي نهائي؛ التصحيح الرسمي يجي من _bars_refresh_loop كل دقيقة."""
        for tf, tf_seconds in TIMEFRAMES_SECONDS.items():
            bucket_start = int(ts // tf_seconds) * tf_seconds
            candles = self.candles[tf]
            if candles and candles[-1]["time"] == bucket_start:
                c = candles[-1]
                c["high"] = max(c["high"], price)
                c["low"] = min(c["low"], price)
                c["close"] = price
            elif candles and candles[-1]["time"] > bucket_start:
                continue
            else:
                candles.append({"time": bucket_start, "open": price, "high": price, "low": price, "close": price})

    async def _bars_refresh_loop(self):
        while not self._stop:
            await asyncio.sleep(BARS_REFRESH_SECONDS)
            now = datetime.now(timezone.utc)
            for tf, client_tf in TIMEFRAME_CLIENT_MAP.items():
                start = now - BACKFILL_WINDOW[tf]
                result = await self.client.get_bars(
                    client_tf, start=start, end=now, count=BARS_REFRESH_RECENT_COUNT
                )
                if result.ok and result.data:
                    fresh = {b.timestamp.timestamp(): _bar_to_dict(b) for b in result.data}
                    existing = self.candles[tf]
                    existing_times = {c["time"] for c in existing}
                    for ts, c in fresh.items():
                        if int(ts) not in existing_times:
                            self._notify_close(tf, c)
                    # نستبدل ذيل القائمة بالبيانات المؤكدة من المصدر (تصحيح ذاتي)
                    merged = {c["time"]: c for c in existing}
                    for c in fresh.values():
                        merged[c["time"]] = c
                    self.candles[tf] = sorted(merged.values(), key=lambda c: c["time"])[-500:]
                    self.backfill_status[tf] = {"ok": True, "count": len(self.candles[tf]), "reason": None}
                # لو فشل التحديث الدوري، نبقي البيانات الموجودة (ما نمسحها) ونسجل السبب فقط
                elif not result.ok:
                    self.backfill_status.setdefault(tf, {}).update({
                        "last_refresh_error": f"{result.status.value}: {result.reason}"
                    })

    def get_candles(self, timeframe: str) -> List[Dict]:
        return list(self.candles.get(timeframe, []))

    def get_candles_meta(self, timeframe: str) -> Dict:
        candles = list(self.candles.get(timeframe, []))
        min_required = MIN_CANDLES_FOR_SUFFICIENT.get(timeframe, 15)
        status = self.backfill_status.get(timeframe, {})
        return {
            "timeframe": timeframe,
            "candles": candles,
            "count": len(candles),
            "sufficient": len(candles) >= min_required,
            "backfill_ok": status.get("ok"),
            "backfill_reason": status.get("reason"),
        }

    def get_snapshot(self) -> Dict:
        return {
            "price": self.current_price,
            "bid": self.bid,
            "ask": self.ask,
            "spread": self.spread,
            "is_stale": self.is_stale,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "data_source_status": self.data_source_status,
            "data_source_reason": self.data_source_reason,
            "source": "goldprice.dev (XAU-USD-SPOT)",
        }


gold_feed = GoldLivePriceFeed()
