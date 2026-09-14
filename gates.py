"""
محرك الـ 20 بوابة الحقيقي - كل بوابة حساب رقمي فعلي على بيانات OHLC حقيقية،
بدون Look-Ahead Bias (نفس ضمانات find_swing_points: سوينغ ما يُكتشف إلا بعد
تأكيده بشموع حقيقية لاحقة).

🐛 تصحيحات مهمة مقارنة بالمسودة السابقة (strategy_engine.TimeframeStrategyState
غير المستخدمة، والتي فيها هذي الأخطاء بالضبط):
  1. Entry != TP1 دائماً - TP1 هدف سيولة معاكسة مستقل، مو نفس مستوى الدخول
  2. فايبوناتشي Premium/Discount متماثل تماماً بين BUY وSELL (مرآة صحيحة)
  3. البوابات كلها تشتغل على شموع مغلقة فقط من candle_store (مو الشمعة
     الجارية غير المغلقة من price_feed المباشر)
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from strategy_engine import (
    find_swing_points, determine_trend, detect_entry_trigger_candle, detect_choch,
    _candle_body_ratio,
)
from settings_store import StrategySettings
from risk_engine import RiskCalculator
from auditor import ChartAndSignalAuditor, TradeAuditStatus

STRATEGY_VERSION = "gates-v1.0.0"


@dataclass
class GateRow:
    gate_id: int
    key: str
    name_ar: str
    status: str  # PASSED | FAILED | WAITING | NOT_AVAILABLE
    reason_ar: str
    details: Dict = field(default_factory=dict)
    timestamp: str = ""
    source: str = "goldprice.dev"
    strategy_version: str = STRATEGY_VERSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < 2:
        return 0.0
    period = min(period, len(df))
    return float((df["high"] - df["low"]).tail(period).mean())


class GateEngine:
    """يشغّل الـ 20 بوابة بالتسلسل على فريم واحد (المطلوب من المستخدم)، مستعيناً
    بـ H4/H1 من فريماتهم الخاصة للانحياز والهيكلية العليا."""

    def __init__(self, settings: StrategySettings):
        self.s = settings
        self.rows: List[GateRow] = []
        self.ctx: Dict = {}

    def _row(self, gate_id, key, name_ar, status, reason_ar, details=None):
        r = GateRow(gate_id, key, name_ar, status, reason_ar, details or {}, _now())
        self.rows.append(r)
        return r

    # ---------------- Gate 0 ----------------
    def gate_data_quality(self, quality: Dict):
        ok = quality.get("ok", False)
        self._row(0, "data_quality", "جودة البيانات",
                   "PASSED" if ok else "WAITING", quality.get("reason_ar", ""), quality)
        return ok

    # ---------------- Gate 1: H4 Bias ----------------
    def gate_h4_bias(self, h4_df: pd.DataFrame) -> Optional[str]:
        if h4_df is None or len(h4_df) < 25:
            self._row(1, "h4_bias", "H4 BIAS", "WAITING", "بيانات H4 غير كافية بعد")
            return None
        trend = determine_trend(h4_df)
        if trend == "RANGE":
            self._row(1, "h4_bias", "H4 BIAS", "WAITING", "لا يوجد اتجاه واضح على H4 حالياً (تذبذب)")
            return None
        direction = "BUY" if trend == "BULLISH" else "SELL"
        self._row(1, "h4_bias", "H4 BIAS", "PASSED",
                   f"انحياز {'صاعد' if direction=='BUY' else 'هابط'} محدد من هيكلية H4",
                   {"trend": trend, "direction": direction})
        return direction

    # ---------------- Gate 2: H1 Structure ----------------
    def gate_h1_structure(self, h1_df: pd.DataFrame, h4_direction: Optional[str]) -> bool:
        if h4_direction is None:
            self._row(2, "h1_structure", "H1 STRUCTURE", "WAITING", "بانتظار انحياز H4 أولاً")
            return False
        if h1_df is None or len(h1_df) < 25:
            self._row(2, "h1_structure", "H1 STRUCTURE", "WAITING", "بيانات H1 غير كافية بعد")
            return False
        trend = determine_trend(h1_df)
        h1_dir = "BUY" if trend == "BULLISH" else ("SELL" if trend == "BEARISH" else None)
        if h1_dir is None:
            self._row(2, "h1_structure", "H1 STRUCTURE", "WAITING", "H1 بحالة تذبذب - بانتظار وضوح الهيكلية")
            return False
        if h1_dir != h4_direction:
            self._row(2, "h1_structure", "H1 STRUCTURE", "FAILED",
                       f"H1 ({trend}) يعاكس انحياز H4 - لا يثبته", {"h4": h4_direction, "h1": h1_dir})
            return False
        self._row(2, "h1_structure", "H1 STRUCTURE", "PASSED", "H1 يثبت نفس انحياز H4", {"trend": trend})
        return True

    # ---------------- Gate 3: Liquidity ----------------
    def gate_liquidity(self, df: pd.DataFrame, direction: str) -> Optional[Dict]:
        swings = find_swing_points(df, lookback=self.s.swing_confirmation_lookback)
        idxs = swings["highs"] if direction == "SELL" else swings["lows"]
        col = "high" if direction == "SELL" else "low"
        n = len(df)
        max_age = self.s.liquidity_zone_max_age_candles

        candidates = [i for i in idxs if n - i <= max_age]
        if not candidates:
            self._row(3, "liquidity", "LIQUIDITY", "WAITING", "لا توجد مناطق سيولة قريبة العمر بعد")
            return None

        level = float(df[col].iloc[candidates[-1]])
        tol = self.s.equal_level_tolerance_pct / 100.0
        equal_touches = sum(1 for i in candidates if level and abs(df[col].iloc[i] - level) / level <= tol)

        self._row(3, "liquidity", "LIQUIDITY", "PASSED",
                   f"مستوى سيولة {'علوي' if direction=='SELL' else 'سفلي'} عند {level:.2f} ({equal_touches} لمسة)",
                   {"level": level, "index": candidates[-1], "equal_touches": equal_touches})
        return {"level": level, "index": candidates[-1]}

    # ---------------- Gate 4: Liquidity Sweep ----------------
    def gate_sweep(self, df: pd.DataFrame, liquidity: Optional[Dict], direction: str) -> Optional[int]:
        if not liquidity:
            self._row(4, "liquidity_sweep", "LIQUIDITY SWEEP", "WAITING", "بانتظار تحديد مستوى سيولة أولاً")
            return None

        level = liquidity["level"]
        atr = _atr(df)
        min_pierce = atr * self.s.sweep_min_pierce_atr_mult
        window = self.s.sweep_confirm_max_candles
        recent = df.tail(20).reset_index(drop=True)

        for i in range(len(recent)):
            row = recent.iloc[i]
            pierced = (row["low"] < level - min_pierce) if direction == "BUY" else (row["high"] > level + min_pierce)
            if not pierced:
                continue
            for j in range(i, min(i + window + 1, len(recent))):
                closed_back = (recent.iloc[j]["close"] > level) if direction == "BUY" else (recent.iloc[j]["close"] < level)
                if closed_back:
                    self._row(4, "liquidity_sweep", "LIQUIDITY SWEEP", "PASSED",
                               f"اختراق حقيقي (≥{self.s.sweep_min_pierce_atr_mult}×ATR) ثم إغلاق رجوعي خلال {j-i} شمعة",
                               {"pierce_index": i, "confirm_index": j, "level": level})
                    return j

        self._row(4, "liquidity_sweep", "LIQUIDITY SWEEP", "WAITING",
                   "ما صار اختراق حقيقي يرجع يغلق داخل المنطقة بعد - ينتظر Sweep صالح")
        return None

    # ---------------- Gate 5: Displacement ----------------
    def gate_displacement(self, df: pd.DataFrame, sweep_index: Optional[int], direction: str) -> Optional[int]:
        if sweep_index is None:
            self._row(5, "displacement", "DISPLACEMENT", "WAITING", "بانتظار Sweep صالح أولاً")
            return None

        recent = df.tail(20).reset_index(drop=True)
        avg_body = (recent["close"] - recent["open"]).abs().mean() or 0.0001

        for i in range(sweep_index, min(sweep_index + 6, len(recent))):
            row = recent.iloc[i]
            body = abs(row["close"] - row["open"])
            rng = row["high"] - row["low"]
            if rng <= 0:
                continue
            body_ratio = body / rng
            body_vs_avg = body / avg_body
            edge_dist = (row["high"] - row["close"]) / rng if direction == "BUY" else (row["close"] - row["low"]) / rng
            dir_ok = (row["close"] > row["open"]) if direction == "BUY" else (row["close"] < row["open"])

            if (dir_ok and body_ratio >= self.s.displacement_body_range_ratio
                    and body_vs_avg >= self.s.displacement_body_vs_avg_mult
                    and edge_dist <= self.s.displacement_close_edge_pct):
                self._row(5, "displacement", "DISPLACEMENT", "PASSED",
                           f"شمعة زخم حقيقية: Body/Range={body_ratio:.2f}, Body/متوسط={body_vs_avg:.2f}×",
                           {"index": i, "body_ratio": round(body_ratio, 3)})
                return i

        self._row(5, "displacement", "DISPLACEMENT", "WAITING", "لا توجد شمعة تحقق شروط الزخم الرقمية بعد")
        return None

    # ---------------- Gate 6: BOS/CHoCH ----------------
    def gate_bos_choch(self, df: pd.DataFrame, displacement_index: Optional[int], liquidity: Optional[Dict], direction: str) -> bool:
        if displacement_index is None or not liquidity:
            self._row(6, "bos_choch", "BOS / CHoCH", "WAITING", "بانتظار شمعة زخم صالحة أولاً")
            return False
        recent = df.tail(20).reset_index(drop=True)
        row = recent.iloc[displacement_index]
        level = liquidity["level"]
        broke = (row["close"] > level) if direction == "BUY" else (row["close"] < level)
        if not broke:
            self._row(6, "bos_choch", "BOS / CHoCH", "FAILED", "شمعة الزخم ما أغلقت فعلياً خارج مستوى الهيكل")
            return False
        self._row(6, "bos_choch", "BOS / CHoCH", "PASSED", "إغلاق جسم مؤكد خارج المستوى - كسر هيكل حقيقي")
        return True

    # ---------------- Gate 7: FVG + Order Block (منفصلين لكن محسوبين معاً) ----------------
    def gate_fvg(self, df: pd.DataFrame, displacement_index: Optional[int], direction: str) -> Optional[Dict]:
        if displacement_index is None or displacement_index < 2:
            self._row(7, "fvg", "FVG", "WAITING", "بانتظار شمعة زخم صالحة لتشكيل فجوة")
            return None
        recent = df.tail(20).reset_index(drop=True)
        c1 = recent.iloc[displacement_index - 2]
        c3 = recent.iloc[displacement_index]
        price_ref = c3["close"]

        gap = (c3["low"] - c1["high"]) if direction == "BUY" else (c1["low"] - c3["high"])
        gap_pct = (gap / price_ref) * 100 if price_ref else 0

        if gap <= 0 or gap_pct < self.s.fvg_min_gap_pct:
            self._row(7, "fvg", "FVG", "FAILED", f"الفجوة {gap_pct:.3f}% أصغر من الحد الأدنى - لا يوجد FVG صالح")
            return None

        fvg = {"top": float(c3["low"]) if direction == "BUY" else float(c1["low"]),
               "bottom": float(c1["high"]) if direction == "BUY" else float(c3["high"]),
               "gap_pct": round(gap_pct, 4)}
        self._row(7, "fvg", "FVG", "PASSED", f"فجوة سعرية حقيقية {gap_pct:.3f}% ناتجة عن الزخم", fvg)
        return fvg

    def gate_order_block(self, df: pd.DataFrame, displacement_index: Optional[int], direction: str) -> Optional[Dict]:
        if displacement_index is None or displacement_index < 1:
            self._row(8, "order_block", "ORDER BLOCK", "WAITING", "بانتظار شمعة زخم صالحة")
            return None
        recent = df.tail(20).reset_index(drop=True)
        ob_index = displacement_index - 1
        ob_row = recent.iloc[ob_index]
        is_opposite = (ob_row["close"] < ob_row["open"]) if direction == "BUY" else (ob_row["close"] > ob_row["open"])
        if not is_opposite:
            self._row(8, "order_block", "ORDER BLOCK", "FAILED", "آخر شمعة قبل الزخم ليست معاكسة اللون - لا يوجد OB صالح")
            return None
        ob = {"top": float(max(ob_row["open"], ob_row["close"])), "bottom": float(min(ob_row["open"], ob_row["close"])), "index": ob_index}
        self._row(8, "order_block", "ORDER BLOCK", "PASSED", "Order Block صالح خلف شمعة الزخم", ob)
        return ob

    # ---------------- Gate 9: Freshness ----------------
    def gate_freshness(self, df: pd.DataFrame, ob: Optional[Dict], displacement_index: Optional[int], direction: str) -> bool:
        if not ob or displacement_index is None:
            self._row(9, "freshness", "FRESHNESS", "WAITING", "بانتظار Order Block صالح")
            return False
        recent = df.tail(20).reset_index(drop=True)
        after = recent.iloc[displacement_index + 1:]
        if after.empty:
            self._row(9, "freshness", "FRESHNESS", "PASSED", "لسه ما مر وقت كافٍ لاختبار المنطقة - طازجة")
            return True
        closed_through = ((after["close"] < ob["bottom"]).any() if direction == "BUY" else (after["close"] > ob["top"]).any())
        if closed_through:
            self._row(9, "freshness", "FRESHNESS", "FAILED", "صار إغلاق كامل خلال المنطقة - أصبحت Invalid")
            return False
        self._row(9, "freshness", "FRESHNESS", "PASSED", "المنطقة لسه طازجة (ما انلمست بإغلاق كامل)")
        return True

    # ---------------- Gate 10: Premium/Discount ----------------
    def gate_premium_discount(self, df: pd.DataFrame, sweep_index: Optional[int], displacement_index: Optional[int], direction: str) -> Optional[Dict]:
        if sweep_index is None or displacement_index is None:
            self._row(10, "premium_discount", "PREMIUM / DISCOUNT", "WAITING", "بانتظار موجة Sweep+Displacement مكتملة")
            return None

        recent = df.tail(20).reset_index(drop=True)
        # الموجة الدافعة: من نقطة السحب لغاية قمة/قاع شمعة الزخم - متماثلة تماماً بين BUY/SELL
        if direction == "BUY":
            impulse_low = float(recent.iloc[sweep_index]["low"])
            impulse_high = float(recent.iloc[displacement_index]["high"])
        else:
            impulse_high = float(recent.iloc[sweep_index]["high"])
            impulse_low = float(recent.iloc[displacement_index]["low"])

        diff = impulse_high - impulse_low
        if diff <= 0:
            self._row(10, "premium_discount", "PREMIUM / DISCOUNT", "WAITING", "موجة غير صالحة لحساب المنطقة")
            return None

        zone_low = impulse_high - diff * self.s.fib_discount_low
        zone_high = impulse_high - diff * self.s.fib_discount_high
        # للـ SELL: نفس النسب لكن من الطرف الثاني (مرآة صحيحة - العلاوة تكون قرب القمة)
        if direction == "SELL":
            zone_low, zone_high = impulse_low + diff * self.s.fib_discount_low, impulse_low + diff * self.s.fib_discount_high

        current_price = float(df["close"].iloc[-1])
        lo, hi = min(zone_low, zone_high), max(zone_low, zone_high)
        in_zone = lo <= current_price <= hi

        zone_name = "الخصم" if direction == "BUY" else "العلاوة"
        if not in_zone:
            self._row(10, "premium_discount", "PREMIUM / DISCOUNT", "WAITING",
                       f"السعر {current_price:.2f} خارج منطقة {zone_name} ({lo:.2f}-{hi:.2f})")
            return None

        result = {"zone_low": lo, "zone_high": hi, "impulse_low": impulse_low, "impulse_high": impulse_high}
        self._row(10, "premium_discount", "PREMIUM / DISCOUNT", "PASSED",
                   f"السعر داخل منطقة {zone_name} الذهبية ({lo:.2f}-{hi:.2f})", result)
        return result

    # ---------------- Gate 11: 15M Setup ----------------
    def gate_m15_setup(self, m15_df: pd.DataFrame, direction: str) -> bool:
        if m15_df is None or len(m15_df) < 30:
            self._row(11, "m15_setup", "15M SETUP", "WAITING", "بيانات M15 غير كافية بعد")
            return False
        trend = determine_trend(m15_df.iloc[-20:])
        m15_dir = "BUY" if trend == "BULLISH" else ("SELL" if trend == "BEARISH" else "RANGE")
        if m15_dir == "RANGE" or m15_dir != direction:
            self._row(11, "m15_setup", "15M SETUP", "WAITING", "M15 بمرحلة تصحيح مؤقت أو تذبذب - ينتظر إعداد واضح")
            return False
        self._row(11, "m15_setup", "15M SETUP", "PASSED", "M15 يبني إعداد متوافق مع الاتجاه")
        return True

    # ---------------- Gate 12: 5M Confirmation ----------------
    def gate_m5_confirmation(self, m5_df: pd.DataFrame, m15_df: pd.DataFrame, direction: str) -> Optional[str]:
        if m5_df is None or len(m5_df) < 10:
            self._row(12, "m5_confirmation", "5M CONFIRMATION", "WAITING", "بيانات M5 غير كافية بعد")
            return None
        trigger = detect_entry_trigger_candle(m5_df)
        choch = detect_choch(m15_df) if m15_df is not None and len(m15_df) >= 40 else None
        trigger_ok = trigger and (("BULLISH" in trigger and direction == "BUY") or ("BEARISH" in trigger and direction == "SELL"))
        choch_ok = choch and (("BULLISH" in choch and direction == "BUY") or ("BEARISH" in choch and direction == "SELL"))
        if not trigger_ok and not choch_ok:
            self._row(12, "m5_confirmation", "5M CONFIRMATION", "WAITING", "بانتظار شمعة تأكيد (Engulfing/Pin Bar) أو CHoCH")
            return None
        confirmation = trigger if trigger_ok else "CHoCH"
        self._row(12, "m5_confirmation", "5M CONFIRMATION", "PASSED", f"تأكيد دخول: {confirmation}", {"confirmation": confirmation})
        return confirmation

    # ---------------- Trade plan (Entry/SL/TP - منفصلين تماماً) ----------------
    def build_trade_plan(self, df: pd.DataFrame, ob: Dict, sweep_index: int, discount_zone: Dict, direction: str) -> Dict:
        entry = ob["top"] if direction == "BUY" else ob["bottom"]

        recent = df.tail(20).reset_index(drop=True)
        extreme = float(recent.iloc[sweep_index]["low"]) if direction == "BUY" else float(recent.iloc[sweep_index]["high"])
        buffer = _atr(df) * 0.15
        sl = extreme - buffer if direction == "BUY" else extreme + buffer

        # TP1 هدف سيولة معاكسة حقيقي ومستقل - أبداً ما يساوي نقطة الدخول
        swings = find_swing_points(df, lookback=self.s.swing_confirmation_lookback)
        opposite_idxs = swings["highs"] if direction == "BUY" else swings["lows"]
        col = "high" if direction == "BUY" else "low"

        tp1 = None
        for i in reversed(opposite_idxs):
            candidate = float(df[col].iloc[i])
            if direction == "BUY" and candidate > entry:
                tp1 = candidate; break
            if direction == "SELL" and candidate < entry:
                tp1 = candidate; break

        if tp1 is None:
            # ما فيه سيولة معاكسة مؤكدة بعد - نستخدم أقصى نقطة بالموجة الدافعة كبديل معقول (لسه مستقل عن Entry)
            tp1 = discount_zone["impulse_high"] if direction == "BUY" else discount_zone["impulse_low"]
            if tp1 == entry:  # حماية أخيرة - ما يصير أبداً TP1=Entry
                diff = abs(discount_zone["impulse_high"] - discount_zone["impulse_low"])
                tp1 = entry + diff * 0.5 if direction == "BUY" else entry - diff * 0.5

        diff = discount_zone["impulse_high"] - discount_zone["impulse_low"]
        tp2 = tp1 + diff * self.s.fib_tp2_extension if direction == "BUY" else tp1 - diff * self.s.fib_tp2_extension

        return {
            "direction": direction,
            "entry": round(entry, 2), "sl": round(sl, 2),
            "tp1": round(tp1, 2), "tp2": round(tp2, 2),
        }

    # ---------------- Gate 13: Structural SL ----------------
    def gate_structural_sl(self, trade_plan: Dict, direction: str) -> bool:
        sl, entry = trade_plan["sl"], trade_plan["entry"]
        valid = (sl < entry) if direction == "BUY" else (sl > entry)
        if not valid or sl == entry:
            self._row(13, "structural_sl", "STRUCTURAL SL", "FAILED", "الستوب لوز غير منطقي بالنسبة لاتجاه الصفقة")
            return False
        self._row(13, "structural_sl", "STRUCTURAL SL", "PASSED",
                   f"SL={sl} مبني خلف نقطة إبطال الفكرة (نقطة السحب)، مو رقم تقريبي")
        return True

    # ---------------- Gate 14: Liquidity TP ----------------
    def gate_liquidity_tp(self, trade_plan: Dict, direction: str) -> bool:
        tp1, entry = trade_plan["tp1"], trade_plan["entry"]
        if tp1 == entry:
            self._row(14, "liquidity_tp", "LIQUIDITY TP", "FAILED", "TP1 يساوي الدخول - هدف غير مستقل")
            return False
        valid = (tp1 > entry) if direction == "BUY" else (tp1 < entry)
        if not valid:
            self._row(14, "liquidity_tp", "LIQUIDITY TP", "FAILED", "TP1 بالاتجاه المعاكس الخاطئ")
            return False
        self._row(14, "liquidity_tp", "LIQUIDITY TP", "PASSED", f"TP1={tp1} هدف سيولة معاكسة مستقل عن الدخول")
        return True

    # ---------------- Gate 15: RR ----------------
    def gate_rr(self, trade_plan: Dict) -> Optional[float]:
        risk = abs(trade_plan["entry"] - trade_plan["sl"])
        reward = abs(trade_plan["tp1"] - trade_plan["entry"])
        if risk == 0:
            self._row(15, "rr_check", "RR CHECK", "FAILED", "مسافة الستوب صفر")
            return None
        rr = round(reward / risk, 2)
        if rr < self.s.rr_reject_below:
            self._row(15, "rr_check", "RR CHECK", "FAILED", f"RR={rr} أقل من الحد الأدنى الإلزامي ({self.s.rr_reject_below})", {"rr": rr})
            return None
        tier = "مفضّلة" if rr >= self.s.rr_preferred_above else "مقبولة"
        self._row(15, "rr_check", "RR CHECK", "PASSED", f"RR={rr} ({tier})", {"rr": rr})
        return rr

    # ---------------- Gate 16: News Lock ----------------
    def gate_news_lock(self, news_status: Dict) -> bool:
        if news_status.get("news_lock_active"):
            self._row(16, "news_lock", "NEWS LOCK", "FAILED", news_status.get("reason_ar", "خبر عالي الخطورة قريب"))
            return False
        self._row(16, "news_lock", "NEWS LOCK", "PASSED", "لا توجد أخبار عالية الخطورة بالنافذة الزمنية")
        return True

    # ---------------- Gate 17: Spread ----------------
    def gate_spread(self, spread: Optional[float], is_stale: Optional[bool]) -> bool:
        if spread is None:
            self._row(17, "spread_check", "SPREAD CHECK", "NOT_AVAILABLE", "بيانات السبريد غير متوفرة من المصدر حالياً")
            return True  # لا نحظر بسبب نقص بيانات، بس نعلن الحالة بصراحة
        if is_stale:
            self._row(17, "spread_check", "SPREAD CHECK", "WAITING", f"آخر قراءة سبريد ({spread:.2f}) قديمة (Stale)")
            return True
        if spread > self.s.max_spread_points:
            self._row(17, "spread_check", "SPREAD CHECK", "FAILED", f"السبريد الحالي ({spread:.2f}) أعلى من الحد المسموح ({self.s.max_spread_points})")
            return False
        self._row(17, "spread_check", "SPREAD CHECK", "PASSED", f"السبريد ({spread:.2f}) ضمن الحد المسموح")
        return True

    # ---------------- Gate 18: Risk Engine ----------------
    def gate_risk(self, trade_plan: Dict, balance: float, leverage: int, risk_pct: float) -> Optional[Dict]:
        calc = RiskCalculator(balance, leverage, risk_pct)
        result = calc.calculate_position_size(trade_plan["entry"], trade_plan["sl"], trade_plan["tp1"])
        if not result:
            self._row(18, "risk_engine", "RISK ENGINE", "FAILED", "تعذر حساب حجم الصفقة")
            return None
        if result["execution_blocked"]:
            self._row(18, "risk_engine", "RISK ENGINE", "FAILED", result["block_reason"], result)
            return result
        self._row(18, "risk_engine", "RISK ENGINE", "PASSED",
                   f"لوت {result['recommended_lot_size']} - مخاطرة ${result['risk_amount_usd']}", result)
        return result

    # ---------------- Gate 19: Auditor ----------------
    def gate_auditor(self, candles: List[Dict], trade_plan: Dict, news_status: Dict, risk_pct: float) -> bool:
        auditor = ChartAndSignalAuditor()
        result = auditor.audit(candles, trade_plan, news_status, risk_pct=risk_pct)
        status = "PASSED" if result["can_execute"] else "FAILED"
        self._row(19, "auditor", "AUDITOR", status, "؛ ".join(result["audit_logs"]), result)
        return result["can_execute"]

    def to_list(self) -> List[Dict]:
        return [asdict(r) for r in self.rows]
