"""
محرك الأخبار الاقتصادية الحقيقي (Finnhub) - يجلب تقويم اقتصادي حقيقي فعلي
مع تصحيح الأخطاء اللي كانت بالكود الأصلي:
  1. event_time الآن تُقرأ من رد الـ API فعلياً (مو datetime.now() الخاطئة)
  2. gold_bias الآن تُحسب بمقارنة القيمة الفعلية (actual) بالتوقع (estimate) فعلياً
  3. حظر تداول مؤقت تلقائي حول الأخبار عالية الخطورة (30 دقيقة قبل/بعد)
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from .models import EconomicEventDB

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"

HIGH_IMPACT_KEYWORDS = ["CPI", "FOMC", "NFP", "Interest Rate", "Non-Farm", "Fed"]
GOLD_RELEVANT_COUNTRIES = {"US", "EU", "CN", "DE"}

# نافذة حظر التداول حول الأخبار الحساسة (دقائق)
NEWS_LOCK_WINDOW_MINUTES = 30


def _classify_impact(event_name: str, raw_impact: Optional[int]) -> str:
    if raw_impact is not None and raw_impact >= 3:
        return "HIGH"
    if any(k.lower() in event_name.lower() for k in HIGH_IMPACT_KEYWORDS):
        return "HIGH"
    if raw_impact == 2:
        return "MEDIUM"
    return "LOW"


def _compute_gold_bias(actual: Optional[float], estimate: Optional[float], event_name: str) -> str:
    """
    مقارنة رياضية حقيقية بين الفعلي والمتوقع - ليست تخمين عشوائي.
    القاعدة الاقتصادية العامة: بيانات تضخم/فائدة/توظيف أقوى من المتوقع = دولار أقوى = ذهب أضعف، والعكس صحيح.
    """
    if actual is None or estimate is None:
        return "NEUTRAL"
    try:
        actual = float(actual)
        estimate = float(estimate)
    except (TypeError, ValueError):
        return "NEUTRAL"

    if actual == estimate:
        return "NEUTRAL"

    stronger_than_expected = actual > estimate
    # بيانات "خفض فائدة" منطقها معكوس - نتعامل معها كحالة خاصة
    if "rate" in event_name.lower() and ("cut" in event_name.lower() or "خفض" in event_name):
        stronger_than_expected = not stronger_than_expected

    return "BEARISH_GOLD" if stronger_than_expected else "BULLISH_GOLD"


class RealEconomicCalendarEngine:
    @staticmethod
    def is_configured() -> bool:
        return bool(FINNHUB_API_KEY)

    @staticmethod
    def fetch_and_sync(db: Session) -> Dict:
        if not FINNHUB_API_KEY:
            return {"status": "NOT_CONFIGURED", "message": "FINNHUB_API_KEY غير موجود بملف .env"}

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")

        try:
            resp = requests.get(
                FINNHUB_CALENDAR_URL,
                params={"from": today, "to": next_week, "token": FINNHUB_API_KEY},
                timeout=10,
            )
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

        if resp.status_code != 200:
            return {"status": "FAILED", "reason": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        payload = resp.json().get("economicCalendar", [])
        synced = 0

        for item in payload:
            country = item.get("country", "")
            if country not in GOLD_RELEVANT_COUNTRIES:
                continue

            event_name = item.get("event", "Unknown Event")
            raw_time = item.get("time")  # مثال: "2026-09-15 12:30:00"
            try:
                event_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S") if raw_time else datetime.now(timezone.utc)
            except ValueError:
                event_time = datetime.now(timezone.utc)

            impact_level = _classify_impact(event_name, item.get("impact"))
            gold_bias = _compute_gold_bias(item.get("actual"), item.get("estimate"), event_name)

            existing = db.query(EconomicEventDB).filter(
                EconomicEventDB.event_title == event_name,
                EconomicEventDB.country == country,
                EconomicEventDB.event_time == event_time,
            ).first()

            if existing:
                existing.actual = str(item.get("actual", ""))
                existing.estimate = str(item.get("estimate", ""))
                existing.prev = str(item.get("prev", ""))
                existing.gold_bias = gold_bias
                existing.impact = impact_level
            else:
                db.add(EconomicEventDB(
                    country=country,
                    event_title=event_name,
                    impact=impact_level,
                    event_time=event_time,
                    actual=str(item.get("actual", "")),
                    estimate=str(item.get("estimate", "")),
                    prev=str(item.get("prev", "")),
                    gold_bias=gold_bias,
                ))
            synced += 1

        db.commit()
        return {"status": "SUCCESS", "events_synced": synced}

    @staticmethod
    def get_news_risk_status(db: Session) -> Dict:
        """يفحص إذا فيه خبر عالي الخطورة قريب من الوقت الحالي (نافذة حظر التداول)"""
        now = datetime.now(timezone.utc)
        window = timedelta(minutes=NEWS_LOCK_WINDOW_MINUTES)

        upcoming_high_impact = db.query(EconomicEventDB).filter(
            EconomicEventDB.impact == "HIGH",
            EconomicEventDB.event_time >= now - window,
            EconomicEventDB.event_time <= now + window,
        ).all()

        if upcoming_high_impact:
            ev = upcoming_high_impact[0]
            return {
                "news_lock_active": True,
                "reason_ar": f"خبر عالي الخطورة قريب: {ev.event_title} ({ev.event_time.strftime('%H:%M UTC')})",
                "gold_bias": ev.gold_bias,
            }

        return {"news_lock_active": False, "reason_ar": "لا توجد أخبار عالية الخطورة بالنافذة الحالية", "gold_bias": "NEUTRAL"}

    @staticmethod
    def get_recent_events(db: Session, limit: int = 20) -> List[Dict]:
        events = db.query(EconomicEventDB).order_by(EconomicEventDB.event_time.desc()).limit(limit).all()
        return [
            {
                "country": e.country,
                "title": e.event_title,
                "impact": e.impact,
                "time": e.event_time.isoformat(),
                "actual": e.actual,
                "estimate": e.estimate,
                "prev": e.prev,
                "gold_bias": e.gold_bias,
            }
            for e in events
        ]
