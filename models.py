"""
نماذج قاعدة البيانات
"""
import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, Text, Enum as SQLEnum, ForeignKey
)
from .database import Base


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"


def _gen_public_id() -> str:
    """رقم تعريفي عام قصير لكل مستخدم (يُستخدم بدل الإيميل بأي مكان ظاهر للأدمن بمراسلة عامة)"""
    return uuid.uuid4().hex[:8].upper()


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(16), unique=True, index=True, default=_gen_public_id)
    full_name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)

    # لا يوجد تحقق OTP بناءً على طلب صاحب المنصة - تسجيل وتسجيل دخول مباشر
    is_active = Column(Boolean, default=True)

    # حماية من محاولات الدخول الفاشلة المتكررة (Brute force)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class ContactMessageDB(Base):
    """رسائل المستخدمين للمطور (الأدمن) - تصل بالرقم التعريفي فقط وليس ببيانات المستخدم"""
    __tablename__ = "contact_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_public_id = Column(String(16), index=True)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalysisLogDB(Base):
    """سجل كل تشغيلة تحليل - حتى (لا دخول). هذا هو مصدر بيانات تطوير الاستراتيجية:
    أي بوابة توقف الصفقات أكثر، بأي جلسة، بأي فريم. لا نسجل الصفقات الناجحة بس."""
    __tablename__ = "analysis_log"

    id = Column(Integer, primary_key=True, index=True)
    setup_id = Column(String(64), index=True, nullable=True)   # يمنع تكرار نفس الفرصة كتوصية جديدة
    user_public_id = Column(String(16), index=True, nullable=True)
    timeframe = Column(String(10))

    decision = Column(String(10))         # BUY / SELL / NO_TRADE
    stopped_at_gate = Column(String(64), nullable=True)   # اسم البوابة اللي أوقفت التحليل (لو NO_TRADE)
    stop_reason = Column(Text, nullable=True)

    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit_1 = Column(Float, nullable=True)
    take_profit_2 = Column(Float, nullable=True)
    rr_ratio = Column(Float, nullable=True)
    invalidation_text = Column(Text, nullable=True)

    gates_trace_json = Column(Text, nullable=True)   # JSON كامل لكل بوابة ونتيجتها - للتدقيق الكامل
    session_key = Column(String(20), nullable=True)
    news_lock_active = Column(Boolean, default=False)
    spread_at_signal = Column(Float, nullable=True)

    status = Column(String(20), default="OPEN")  # OPEN / TP1_HIT / TP2_HIT / SL_HIT / CANCELLED / NO_TRADE
    opened_at = Column(DateTime, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime, nullable=True)


class StrategySettingsDB(Base):
    """إعدادات المحرك الرقمية - قابلة للتعديل من لوحة الأدمن، وليست أرقام مدفونة بالكود.
    صف واحد فقط (singleton) بمعرف id=1."""
    __tablename__ = "strategy_settings"

    id = Column(Integer, primary_key=True, default=1)

    equal_level_tolerance_pct = Column(Float, default=0.05)
    liquidity_zone_max_age_candles = Column(Integer, default=50)

    sweep_min_pierce_atr_mult = Column(Float, default=0.5)
    sweep_confirm_max_candles = Column(Integer, default=2)

    displacement_body_range_ratio = Column(Float, default=0.6)
    displacement_body_vs_avg_mult = Column(Float, default=1.5)
    displacement_close_edge_pct = Column(Float, default=0.2)

    fvg_min_gap_pct = Column(Float, default=0.1)
    fvg_fill_pct = Column(Float, default=0.5)

    fib_discount_low = Column(Float, default=0.5)
    fib_discount_high = Column(Float, default=0.618)
    fib_tp2_extension = Column(Float, default=0.27)

    swing_confirmation_lookback = Column(Integer, default=3)   # منع Look-Ahead Bias

    rr_reject_below = Column(Float, default=1.5)
    rr_preferred_above = Column(Float, default=2.0)

    news_lock_before_min = Column(Integer, default=15)
    news_lock_after_min = Column(Integer, default=15)

    max_spread_points = Column(Float, default=0.5)
    spread_stale_max_minutes = Column(Integer, default=480)
    block_on_stale_spread = Column(Boolean, default=False)   # افتراضياً: تحذير بس، مو حظر كامل

    setup_dedup_window_minutes = Column(Integer, default=30)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CandleHistoryDB(Base):
    """تاريخ الشموع الحقيقي المتراكم - يُبنى تدريجياً من التكات الحقيقية بدءاً من لحظة
    تشغيل السيرفر. لا يوجد أي تعبئة اصطناعية أو Backfill وهمي لهذا الجدول أبداً."""
    __tablename__ = "candle_history"

    id = Column(Integer, primary_key=True, index=True)
    timeframe = Column(String(10), index=True)
    candle_time = Column(Integer, index=True)   # unix timestamp لبداية الشمعة
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    source = Column(String(50), default="goldprice.dev")
    stored_at = Column(DateTime, default=datetime.utcnow)


class VisitLogDB(Base):
    """سجل زيارات الموقع - يُستخدم لإحصائية عدد الزوار بلوحة تحكم الأدمن"""
    __tablename__ = "visit_logs"

    id = Column(Integer, primary_key=True, index=True)
    ip_hash = Column(String(128), index=True)   # نخزن هاش الـ IP وليس الـ IP الخام (خصوصية)
    user_id = Column(Integer, nullable=True, index=True)
    path = Column(String(255))
    user_agent = Column(String(255), nullable=True)
    visited_at = Column(DateTime, default=datetime.utcnow, index=True)


class EconomicEventDB(Base):
    __tablename__ = "economic_events"

    id = Column(Integer, primary_key=True, index=True)
    country = Column(String(10), index=True)
    event_title = Column(String(255), index=True)
    impact = Column(String(20))
    event_time = Column(DateTime, index=True)
    actual = Column(String(50), nullable=True)
    estimate = Column(String(50), nullable=True)
    prev = Column(String(50), nullable=True)
    gold_bias = Column(String(20), default="NEUTRAL")
    fetched_at = Column(DateTime, default=datetime.utcnow)


class LoginAuditDB(Base):
    """سجل محاولات الدخول - يساعد الأدمن يشوف أي نشاط مشبوه"""
    __tablename__ = "login_audit"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(150), index=True)
    ip_hash = Column(String(128))
    success = Column(Boolean)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
