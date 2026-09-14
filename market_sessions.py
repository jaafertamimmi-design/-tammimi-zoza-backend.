"""
جلسات التداول العالمية - محسوبة بتوقيت UTC مباشرة (بدون أي بيانات وهمية)
مصدر الأوقات: أوقات التداول القياسية المعتمدة عالمياً للفوركس (تقريبية بسبب التوقيت الصيفي/الشتوي
لكل بلد - وهذا واقع أي منصة تداول، مو نقص بالكود).
"""
from datetime import datetime, timezone
from typing import Dict, List

# (اسم الجلسة، ساعة البدء UTC، ساعة الانتهاء UTC)
SESSIONS = [
    {"key": "SYDNEY", "name_ar": "سيدني", "name_en": "Sydney", "start": 22, "end": 7},
    {"key": "TOKYO", "name_ar": "طوكيو", "name_en": "Tokyo", "start": 0, "end": 9},
    {"key": "LONDON", "name_ar": "لندن", "name_en": "London", "start": 8, "end": 17},
    {"key": "NEWYORK", "name_ar": "نيويورك", "name_en": "New York", "start": 13, "end": 22},
]


def _is_open(hour_now: float, start: int, end: int) -> bool:
    if start < end:
        return start <= hour_now < end
    # جلسة تعبر منتصف الليل (مثل سيدني: 22 -> 7)
    return hour_now >= start or hour_now < end


def get_market_sessions_status() -> Dict:
    now = datetime.now(timezone.utc)
    hour_now = now.hour + now.minute / 60.0

    sessions_status: List[Dict] = []
    open_count = 0
    for s in SESSIONS:
        is_open = _is_open(hour_now, s["start"], s["end"])
        if is_open:
            open_count += 1
        sessions_status.append({
            "key": s["key"],
            "name_ar": s["name_ar"],
            "name_en": s["name_en"],
            "is_open": is_open,
            "utc_start": s["start"],
            "utc_end": s["end"],
        })

    # تداخل لندن + نيويورك = أعلى سيولة باليوم (مهم لتقييم قوة أي كسر هيكلي)
    london_ny_overlap = (
        next(s for s in sessions_status if s["key"] == "LONDON")["is_open"]
        and next(s for s in sessions_status if s["key"] == "NEWYORK")["is_open"]
    )

    return {
        "utc_time": now.strftime("%H:%M:%S"),
        "sessions": sessions_status,
        "open_sessions_count": open_count,
        "high_liquidity_window": london_ny_overlap,
        "liquidity_note_ar": (
            "تداخل جلستي لندن ونيويورك - أعلى سيولة وأقوى الحركات اليوم"
            if london_ny_overlap else
            "لا يوجد تداخل حالياً - احتمالية حركات وهمية (Fakeouts) أعلى"
        ),
    }
