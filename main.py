"""
تحليل أم سماح - منصة تحليل الذهب اللحظي
نقطة التشغيل الرئيسية (Entry Point)

للتشغيل محلياً: uvicorn main:app --reload --port 8000
"""
import os
import hashlib
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv
# محلياً (على جهازك): نقرأ القيم من ملف .env إذا كان موجود.
# على سيرفر سحابي مثل Railway: القيم تكون محطوطة مباشرة كمتغيرات بيئة
# (Environment Variables) من لوحة التحكم، وما راح يكون فيه ملف .env فعلي
# على السيرفر - وهذا طبيعي وصحيح أمنياً، مو خطأ.
ENV_PATH = Path(__file__).resolve().parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

# نتحقق هسه من المتغيرات الأساسية اللي لازم تكون موجودة بأي طريقة
# (من ملف .env محلياً، أو من إعدادات Variables بالسيرفر السحابي).
_REQUIRED_ENV_VARS = ["JWT_SECRET", "ADMIN_EMAIL"]
_missing = [name for name in _REQUIRED_ENV_VARS if not os.getenv(name)]
if _missing:
    raise RuntimeError(
        "المتغيرات التالية ناقصة ولازم تنحط قبل التشغيل: "
        + ", ".join(_missing)
        + "\nمحلياً: حطها بملف .env جنب main.py."
        + "\nعلى Railway/سيرفر سحابي: حطها بقسم Variables بلوحة التحكم."
    )

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import (
    FastAPI, Depends, HTTPException, status, Request,
    WebSocket, WebSocketDisconnect
)
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import Base, engine, get_db, SessionLocal
from app.models import UserDB, UserRole, VisitLogDB, ContactMessageDB, AnalysisLogDB
from app.schemas import (
    UserRegisterRequest, UserLoginRequest, UserResponse, TokenResponse,
    ContactMessageRequest,
)
from app.security import (
    SecurityEngine, login_rate_limiter, register_rate_limiter, ADMIN_EMAIL,
)
from app.price_feed import gold_feed, TIMEFRAMES_SECONDS
from app import candle_store
from app.news_engine import RealEconomicCalendarEngine
from app.market_sessions import get_market_sessions_status
from app.risk_engine import RiskCalculator
from app import pipeline_view

# ==========================================
# إعداد التطبيق
# ==========================================
Base.metadata.create_all(bind=engine)

ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "http://localhost:3000")
GOLDPRICE_API_KEY = os.getenv("GOLDPRICE_API_KEY") or None  # اختياري - المصدر يشتغل مجاناً بدونه

app = FastAPI(title="تحليل أم سماح - Gold Analysis Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _persist_closed_candle(timeframe: str, candle: Dict):
    """يُستدعى من price_feed كل ما تُغلق شمعة حقيقية - يحفظها بقاعدة البيانات"""
    try:
        db = SessionLocal()
        candle_store.store_finalized_candle(db, timeframe, candle, TIMEFRAMES_SECONDS[timeframe])
        db.close()
    except Exception:
        pass


@app.on_event("startup")
async def startup_event():
    gold_feed.register_on_close(_persist_closed_candle)
    await gold_feed.start(api_key=GOLDPRICE_API_KEY)


@app.on_event("shutdown")
async def shutdown_event():
    await gold_feed.stop()


def hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:32]


@app.middleware("http")
async def log_visits(request: Request, call_next):
    response = await call_next(request)
    try:
        db = SessionLocal()
        client_ip = request.client.host if request.client else "unknown"
        db.add(VisitLogDB(
            ip_hash=hash_ip(client_ip),
            path=str(request.url.path),
            user_agent=request.headers.get("user-agent", "")[:250],
        ))
        db.commit()
        db.close()
    except Exception:
        pass
    return response


# ==========================================
# اعتماد المستخدم الحالي (Auth Dependency)
# ==========================================
def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserDB:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="الرجاء تسجيل الدخول",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise unauthorized
    payload = SecurityEngine.decode_token(token)
    if not payload or not payload.get("sub"):
        raise unauthorized
    user = db.query(UserDB).filter(UserDB.email == payload["sub"]).first()
    if not user or not user.is_active:
        raise unauthorized
    return user


def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Optional[UserDB]:
    if not token:
        return None
    payload = SecurityEngine.decode_token(token)
    if not payload or not payload.get("sub"):
        return None
    return db.query(UserDB).filter(UserDB.email == payload["sub"]).first()


def get_current_admin(user: UserDB = Depends(get_current_user)) -> UserDB:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="هذا القسم مخصص للمطور فقط")
    return user


def get_ws_user(token: str, db: Session) -> Optional[UserDB]:
    payload = SecurityEngine.decode_token(token)
    if not payload or not payload.get("sub"):
        return None
    return db.query(UserDB).filter(UserDB.email == payload["sub"]).first()


# ==========================================
# مسارات التسجيل وتسجيل الدخول
# ==========================================
@app.post("/api/v1/auth/register", response_model=UserResponse, status_code=201)
def register(payload: UserRegisterRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    if not register_rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="محاولات تسجيل كثيرة، حاول بعد دقائق")

    existing = db.query(UserDB).filter(UserDB.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="البريد الإلكتروني مسجل مسبقاً")

    role = UserRole.ADMIN if payload.email.strip().lower() == ADMIN_EMAIL else UserRole.USER

    user = UserDB(
        full_name=payload.full_name,
        email=payload.email.lower(),
        hashed_password=SecurityEngine.get_password_hash(payload.password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(payload: UserLoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    limiter_key = f"{payload.email.lower()}:{client_ip}"
    if not login_rate_limiter.is_allowed(limiter_key):
        wait_s = login_rate_limiter.seconds_until_allowed(limiter_key)
        raise HTTPException(status_code=429, detail=f"محاولات كثيرة، حاول بعد {wait_s} ثانية")

    user = db.query(UserDB).filter(UserDB.email == payload.email.lower()).first()

    now = datetime.utcnow()
    if user and user.locked_until and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds())
        raise HTTPException(status_code=423, detail=f"الحساب مقفل مؤقتاً، حاول بعد {remaining} ثانية")

    if not user or not SecurityEngine.verify_password(payload.password, user.hashed_password):
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_login_attempts = 0
            db.commit()
        raise HTTPException(status_code=401, detail="البريد الإلكتروني أو كلمة المرور غير صحيحة")

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    token = SecurityEngine.create_access_token(data={"sub": user.email, "role": user.role.value})
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/api/v1/users/me", response_model=UserResponse)
def read_me(user: UserDB = Depends(get_current_user)):
    return user


# ==========================================
# رسائل التواصل مع المطور (تظهر برقم تعريفي فقط)
# ==========================================
@app.post("/api/v1/contact")
def send_contact_message(
    payload: ContactMessageRequest,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.add(ContactMessageDB(sender_public_id=user.public_id, message=payload.message))
    db.commit()
    return {"message": "تم إرسال رسالتك للمطور بنجاح"}


# ==========================================
# مسارات الأدمن (تحتاج إيميل المطور فقط)
# ==========================================
@app.get("/api/v1/admin/users")
def admin_list_users(admin: UserDB = Depends(get_current_admin), db: Session = Depends(get_db)):
    users = db.query(UserDB).filter(UserDB.role == UserRole.USER).order_by(UserDB.created_at.desc()).all()
    return {
        "total_users": len(users),
        "users": [
            {"public_id": u.public_id, "email": u.email, "full_name": u.full_name,
             "created_at": u.created_at.isoformat()}
            for u in users
        ],
    }


@app.get("/api/v1/admin/messages")
def admin_list_messages(admin: UserDB = Depends(get_current_admin), db: Session = Depends(get_db)):
    messages = db.query(ContactMessageDB).order_by(ContactMessageDB.created_at.desc()).limit(200).all()
    return {
        "messages": [
            {"id": m.id, "sender_public_id": m.sender_public_id, "message": m.message,
             "is_read": m.is_read, "created_at": m.created_at.isoformat()}
            for m in messages
        ]
    }


@app.get("/api/v1/admin/stats")
def admin_stats(admin: UserDB = Depends(get_current_admin), db: Session = Depends(get_db)):
    total_users = db.query(UserDB).filter(UserDB.role == UserRole.USER).count()
    total_visits = db.query(VisitLogDB).count()
    total_analysis_runs = db.query(AnalysisLogDB).count()
    no_trade_count = db.query(AnalysisLogDB).filter(AnalysisLogDB.decision == "NO_TRADE").count()

    return {
        "total_registered_users": total_users,
        "total_site_visits": total_visits,
        "analysis_runs": {
            "total": total_analysis_runs,
            "no_trade": no_trade_count,
        },
    }


@app.post("/api/v1/admin/sync-news")
def admin_sync_news(admin: UserDB = Depends(get_current_admin), db: Session = Depends(get_db)):
    result = RealEconomicCalendarEngine.fetch_and_sync(db)
    return result


# ==========================================
# صحة النظام
# ==========================================
@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    snapshot = gold_feed.get_snapshot()
    return {
        "api": "OK",
        "database": "OK" if db_ok else "ERROR",
        "data_source": {
            "name": "goldprice.dev",
            "status": snapshot["data_source_status"],
            "reason": snapshot.get("data_source_reason"),
            "last_update": snapshot.get("last_update"),
        },
    }


# ==========================================
# بيانات عامة (سعر، جلسات، أخبار) - بدون تسجيل دخول، للعرض العام
# ==========================================
@app.get("/api/v1/market/price")
def market_price():
    return gold_feed.get_snapshot()


@app.get("/api/v1/market/sessions")
def market_sessions():
    return get_market_sessions_status()


@app.get("/api/v1/market/news")
def market_news(db: Session = Depends(get_db)):
    return {
        "configured": RealEconomicCalendarEngine.is_configured(),
        "risk_status": RealEconomicCalendarEngine.get_news_risk_status(db),
        "recent_events": RealEconomicCalendarEngine.get_recent_events(db),
    }


@app.get("/api/v1/market/candles/{timeframe}")
def market_candles(timeframe: str):
    if timeframe not in TIMEFRAMES_SECONDS:
        raise HTTPException(status_code=400, detail=f"فريم غير مدعوم. الفريمات المتاحة: {list(TIMEFRAMES_SECONDS.keys())}")
    return gold_feed.get_candles_meta(timeframe)


@app.get("/api/v1/market/summary")
def market_summary():
    snapshot = gold_feed.get_snapshot()
    daily = gold_feed.get_candles_meta("1d")
    daily_candles = daily["candles"]

    today_candle = daily_candles[-1] if daily_candles else None
    prev_candle = daily_candles[-2] if len(daily_candles) >= 2 else None

    return {
        **snapshot,
        "daily_high": today_candle["high"] if today_candle else None,
        "daily_low": today_candle["low"] if today_candle else None,
        "previous_close": prev_candle["close"] if prev_candle else None,
        "market_sessions": get_market_sessions_status(),
    }


# ==========================================
# خط أنابيب التحليل (20 بوابة - حقيقي جزئياً + NOT_AVAILABLE بوضوح)
# ==========================================
@app.get("/api/v1/analysis/pipeline")
def analysis_pipeline(
    timeframe: str = "1h", balance: float = 10000.0, risk_pct: float = 1.0, leverage: int = 100,
    db: Session = Depends(get_db),
):
    if timeframe not in TIMEFRAMES_SECONDS:
        raise HTTPException(status_code=400, detail="فريم غير مدعوم")

    news_status = RealEconomicCalendarEngine.get_news_risk_status(db)
    snapshot = gold_feed.get_snapshot()

    result = pipeline_view.build_pipeline(
        db, timeframe, balance=balance, risk_pct=risk_pct, leverage=leverage,
        news_status=news_status, spread=snapshot.get("spread"), is_stale=snapshot.get("is_stale"),
    )

    _log_analysis_result_throttled(db, timeframe, result)
    return result


def _log_analysis_result_throttled(db: Session, timeframe: str, result: Dict):
    """يسجل نتيجة التحليل بقاعدة البيانات، لكن يتجنب التكرار الفارغ: يتخطى
    التسجيل لو نفس القرار ونفس السبب انسجلوا لهذا الفريم خلال آخر 60 ثانية
    (حسب طلب: لا نسجل AnalysisLog جديد بكل refresh بدون سبب فعلي)."""
    last = (
        db.query(AnalysisLogDB)
        .filter(AnalysisLogDB.timeframe == timeframe)
        .order_by(AnalysisLogDB.opened_at.desc())
        .first()
    )
    now = datetime.utcnow()
    if last and (now - last.opened_at).total_seconds() < 60 and last.decision == result["final_decision"] and last.stop_reason == result["final_reason_ar"]:
        return  # لا شي جديد يستحق التسجيل

    trade_plan = result.get("trade_plan")
    rr_value = None
    for g in result["gates"]:
        if g["key"] == "rr_check" and g.get("details", {}).get("rr") is not None:
            rr_value = g["details"]["rr"]

    db.add(AnalysisLogDB(
        timeframe=timeframe,
        decision=result["final_decision"],
        stop_reason=result["final_reason_ar"],
        gates_trace_json=json.dumps(result["gates"], ensure_ascii=False),
        entry_price=trade_plan["entry"] if trade_plan else None,
        stop_loss=trade_plan["sl"] if trade_plan else None,
        take_profit_1=trade_plan["tp1"] if trade_plan else None,
        take_profit_2=trade_plan["tp2"] if trade_plan else None,
        rr_ratio=rr_value,
        invalidation_text=result.get("invalidation_text"),
        status="OPEN" if trade_plan else "NO_TRADE",
    ))
    db.commit()


@app.get("/api/v1/analysis/recent-signals")
def recent_signals(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(AnalysisLogDB).order_by(AnalysisLogDB.opened_at.desc()).limit(limit).all()
    return {
        "signals": [
            {
                "id": r.id, "timeframe": r.timeframe, "decision": r.decision,
                "reason": r.stop_reason, "entry": r.entry_price, "sl": r.stop_loss,
                "tp1": r.take_profit_1, "tp2": r.take_profit_2,
                "opened_at": r.opened_at.isoformat(),
            }
            for r in rows
        ]
    }


# ==========================================
# حاسبة المخاطرة (REST) - تستخدم risk_engine.py نفسه، صفر تكرار منطق
# ==========================================
class RiskCalculateRequest(BaseModel):
    balance: float = Field(..., gt=0)
    risk_pct: float = Field(..., gt=0, le=100)
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    leverage: int = Field(..., gt=0)
    take_profit: Optional[float] = None


@app.post("/api/v1/risk/calculate")
def risk_calculate(payload: RiskCalculateRequest):
    if payload.entry == payload.stop_loss:
        raise HTTPException(status_code=400, detail="سعر الدخول لا يمكن أن يساوي الستوب لوز")

    calc = RiskCalculator(payload.balance, payload.leverage, payload.risk_pct)
    tp_for_calc = payload.take_profit if payload.take_profit is not None else payload.entry
    result = calc.calculate_position_size(payload.entry, payload.stop_loss, tp_for_calc)

    if not result:
        raise HTTPException(status_code=400, detail="تعذر حساب حجم الصفقة بهذي المدخلات")

    executable = not result["execution_blocked"]
    potential_loss = result["risk_amount_usd"]
    potential_profit_tp1 = None
    rr = None
    if payload.take_profit is not None:
        risk_dist = abs(payload.entry - payload.stop_loss)
        reward_dist = abs(payload.take_profit - payload.entry)
        rr = round(reward_dist / risk_dist, 2) if risk_dist else None
        potential_profit_tp1 = round(result["recommended_lot_size"] * 100 * reward_dist, 2)

    return {
        **result,
        "executable": executable,
        "potential_loss_usd": potential_loss,
        "potential_profit_tp1_usd": potential_profit_tp1,
        "rr": rr,
        "warning": result.get("block_reason"),
    }


# ==========================================
# WebSocket: بث حي (سعر + خط أنابيب التحليل) - مستقل لكل مستخدم
# ==========================================
class UserSession:
    def __init__(self, user: UserDB):
        self.user = user
        self.selected_timeframe = "1h"
        self.balance = 10000.0
        self.risk_pct = 1.0
        self.leverage = 100


# ذاكرة تخزين مؤقت مشتركة لنتيجة كل فريم - تمنع كل مستخدم متصل من إعادة حساب
# نفس الـ 20 بوابة من الصفر كل 5 ثوان لو فيه مستخدمين ثانيين على نفس الفريم
# (يبقى دقيق: أي مستخدم مخاطرة/رصيد مختلف يحصل حساب Risk Engine خاص به دايماً،
# بس الجزء المشترك من البوابات 0-17 يُعاد استخدامه إذا كان طرياً بحدود 3 ثوان)
_pipeline_cache: Dict[str, Dict] = {}
_PIPELINE_CACHE_TTL_SECONDS = 3


def _get_cached_or_build_pipeline(db: Session, timeframe: str, balance: float, risk_pct: float, leverage: int) -> Dict:
    cache_key = timeframe  # ملاحظة: الكاش على مستوى الفريم فقط؛ اختلاف balance/risk بين المستخدمين
    now_ts = datetime.utcnow().timestamp()  # يعاد حسابه الحين إذا مر وقت الصلاحية، وإلا نعيد استخدام النتيجة المخزنة
    cached = _pipeline_cache.get(cache_key)
    if cached and (now_ts - cached["ts"]) < _PIPELINE_CACHE_TTL_SECONDS:
        return cached["result"]

    news_status = RealEconomicCalendarEngine.get_news_risk_status(db)
    snapshot = gold_feed.get_snapshot()
    result = pipeline_view.build_pipeline(
        db, timeframe, balance=balance, risk_pct=risk_pct, leverage=leverage,
        news_status=news_status, spread=snapshot.get("spread"), is_stale=snapshot.get("is_stale"),
    )
    _pipeline_cache[cache_key] = {"ts": now_ts, "result": result}
    return result


@app.websocket("/ws/analysis")
async def websocket_analysis(websocket: WebSocket):
    await websocket.accept()

    try:
        auth_msg = await asyncio.wait_for(websocket.receive_text(), timeout=15)
        auth_payload = json.loads(auth_msg)
        token = auth_payload.get("token", "")
    except Exception:
        await websocket.close(code=4001)
        return

    db = SessionLocal()
    user = get_ws_user(token, db)
    if not user:
        await websocket.send_json({"type": "AUTH_ERROR", "message": "جلسة غير صالحة، سجل الدخول من جديد"})
        await websocket.close(code=4001)
        db.close()
        return

    session = UserSession(user)
    await websocket.send_json({
        "type": "AUTH_OK",
        "user": {"public_id": user.public_id, "full_name": user.full_name, "role": user.role.value},
    })

    async def push_update():
        pipeline_result = _get_cached_or_build_pipeline(
            db, session.selected_timeframe, session.balance, session.risk_pct, session.leverage
        )
        session_status = get_market_sessions_status()

        await websocket.send_json({
            "type": "ANALYSIS_UPDATE",
            "price": gold_feed.get_snapshot(),
            "pipeline": pipeline_result,
            "market_sessions": session_status,
        })

    async def price_push_loop():
        while True:
            await asyncio.sleep(5)
            try:
                await push_update()
            except WebSocketDisconnect:
                break
            except Exception as e:
                try:
                    await websocket.send_json({"type": "ERROR", "message": str(e)})
                except Exception:
                    break

    push_task = asyncio.create_task(price_push_loop())

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "SET_PREFERENCES":
                tf = msg.get("timeframe")
                if tf in TIMEFRAMES_SECONDS:
                    session.selected_timeframe = tf
                await push_update()

            elif msg_type == "PING":
                await websocket.send_json({"type": "PONG"})

    except WebSocketDisconnect:
        pass
    finally:
        push_task.cancel()
        db.close()


@app.get("/")
def root():
    return {"status": "تحليل أم سماح - المنصة تعمل", "docs": "/docs"}
