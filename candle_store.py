"""
مخزن الشموع الحقيقي - يحفظ كل شمعة حقيقية تُغلق فعلياً بقاعدة البيانات.

هذا هو مصدر "التاريخ" اللي يكبر مع الوقت من بيانات حقيقية فقط، ويُستخدم لـ:
  - Gate 0 (جودة البيانات): كشف التكرار، الفجوات، وعدم الترتيب الزمني
  - محرك الـ Backtesting: بيانات حقيقية بالتسلسل الزمني الصارم، بدون Look-Ahead

⚠️ صريح ومهم: هذا الجدول يبدأ فاضي عند أول تشغيل للسيرفر ويكبر تدريجياً.
ما نحط فيه أي بيانات تاريخية "معبأة" أو مولدة - نلتزم بمبدأ عدم الادعاء
ببيانات ما نملكها فعلياً.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from models import CandleHistoryDB


class DataQualityIssue:
    DUPLICATE = "DUPLICATE_CANDLE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    GAP_DETECTED = "GAP_DETECTED"


def store_finalized_candle(db: Session, timeframe: str, candle: Dict, tf_seconds: int) -> Optional[str]:
    """يحفظ شمعة نهائية حقيقية. يرجع اسم مشكلة جودة لو انكشفت وحدة، أو None لو كل شي سليم."""
    issue = None

    last = (
        db.query(CandleHistoryDB)
        .filter(CandleHistoryDB.timeframe == timeframe)
        .order_by(CandleHistoryDB.candle_time.desc())
        .first()
    )

    if last:
        if candle["time"] == last.candle_time:
            issue = DataQualityIssue.DUPLICATE
        elif candle["time"] < last.candle_time:
            issue = DataQualityIssue.OUT_OF_ORDER
        elif candle["time"] > last.candle_time + tf_seconds:
            # فجوة حقيقية بالتغطية (مثلاً السيرفر انطفى فترة) - نسجلها كملاحظة، ما نمنعها
            issue = DataQualityIssue.GAP_DETECTED

    if issue == DataQualityIssue.DUPLICATE:
        return issue  # ما نخزن نسخة مكررة

    db.add(CandleHistoryDB(
        timeframe=timeframe,
        candle_time=candle["time"],
        open=candle["open"],
        high=candle["high"],
        low=candle["low"],
        close=candle["close"],
    ))
    db.commit()
    return issue


def get_data_quality_status(db: Session, timeframe: str, tf_seconds: int, lookback: int = 200) -> Dict:
    """تقييم جودة البيانات المخزنة لفريم معين - يُستخدم من Gate 0"""
    rows = (
        db.query(CandleHistoryDB)
        .filter(CandleHistoryDB.timeframe == timeframe)
        .order_by(CandleHistoryDB.candle_time.desc())
        .limit(lookback)
        .all()
    )
    rows = list(reversed(rows))

    if len(rows) < 2:
        return {
            "ok": False,
            "stored_candles": len(rows),
            "reason_ar": "لسه ما تجمع تاريخ حقيقي كافي لهذا الفريم (السيرفر لسه بيبني البيانات)",
        }

    gaps = 0
    for i in range(1, len(rows)):
        if rows[i].candle_time - rows[i - 1].candle_time > tf_seconds:
            gaps += 1

    return {
        "ok": True,
        "stored_candles": len(rows),
        "gaps_detected": gaps,
        "oldest": datetime.fromtimestamp(rows[0].candle_time, tz=timezone.utc).isoformat(),
        "newest": datetime.fromtimestamp(rows[-1].candle_time, tz=timezone.utc).isoformat(),
        "reason_ar": f"{len(rows)} شمعة حقيقية مخزنة، {gaps} فجوة انقطاع مكتشفة" if gaps else f"{len(rows)} شمعة حقيقية مخزنة، بدون فجوات",
    }


def get_stored_candles(db: Session, timeframe: str, limit: int = 500) -> List[Dict]:
    rows = (
        db.query(CandleHistoryDB)
        .filter(CandleHistoryDB.timeframe == timeframe)
        .order_by(CandleHistoryDB.candle_time.asc())
        .limit(limit)
        .all()
    )
    return [
        {"time": r.candle_time, "open": r.open, "high": r.high, "low": r.low, "close": r.close}
        for r in rows
    ]
