"""
منسّق خط الأنابيب الكامل (20 بوابة حقيقية) - يشغّل GateEngine بالتسلسل الصارم.

القاعدة الحديدية: أي بوابة WAITING/FAILED توقف السلسلة فوراً؛ البوابات اللي
بعدها تُعلَّم NOT_AVAILABLE (ما تحسبناها أصلاً لأنه ما وصلنا إلها بعد بالتسلسل -
مو لأنها غير مبنية). القرار البوابات NOT_AVAILABLE تختلف دلالياً عن WAITING:
NOT_AVAILABLE = "ما وصلنا لهذي المرحلة بعد"، WAITING = "وصلنا وننتظر شرطها".

يعمل على شموع مغلقة فقط من candle_store (أبداً الشمعة الجارية غير المغلقة).
"""
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from gates import GateEngine
import candle_store
from timeframes import TIMEFRAMES_SECONDS
from settings_store import load_settings

PIPELINE_VERSION = "gates-v1.0.0"

GATE_NAMES = [
    (0, "data_quality", "جودة البيانات"), (1, "h4_bias", "H4 BIAS"), (2, "h1_structure", "H1 STRUCTURE"),
    (3, "liquidity", "LIQUIDITY"), (4, "liquidity_sweep", "LIQUIDITY SWEEP"), (5, "displacement", "DISPLACEMENT"),
    (6, "bos_choch", "BOS / CHoCH"), (7, "fvg", "FVG"), (8, "order_block", "ORDER BLOCK"),
    (9, "freshness", "FRESHNESS"), (10, "premium_discount", "PREMIUM / DISCOUNT"),
    (11, "m15_setup", "15M SETUP"), (12, "m5_confirmation", "5M CONFIRMATION"),
    (13, "structural_sl", "STRUCTURAL SL"), (14, "liquidity_tp", "LIQUIDITY TP"), (15, "rr_check", "RR CHECK"),
    (16, "news_lock", "NEWS LOCK"), (17, "spread_check", "SPREAD CHECK"), (18, "risk_engine", "RISK ENGINE"),
    (19, "auditor", "AUDITOR"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _not_available_from(from_id: int) -> list:
    return [
        {"gate_id": gid, "key": key, "name_ar": name, "status": "NOT_AVAILABLE",
         "reason_ar": "لم تُحسب - السلسلة توقفت ببوابة سابقة", "details": {},
         "timestamp": _now_iso(), "source": "goldprice.dev", "strategy_version": PIPELINE_VERSION}
        for gid, key, name in GATE_NAMES if gid >= from_id
    ]


def build_pipeline(
    db: Session, timeframe: str,
    balance: float = 10000.0, risk_pct: float = 1.0, leverage: int = 100,
    news_status: Optional[Dict] = None, spread: Optional[float] = None, is_stale: Optional[bool] = None,
) -> Dict:
    settings = load_settings(db)
    engine = GateEngine(settings)
    news_status = news_status or {"news_lock_active": False, "reason_ar": ""}

    def stop(next_gate_id: int, final_reason: str) -> Dict:
        gates = engine.to_list() + _not_available_from(next_gate_id)
        return {
            "pipeline_version": PIPELINE_VERSION, "timeframe": timeframe, "gates": gates,
            "final_decision": "NO_TRADE", "final_reason_ar": final_reason, "generated_at": _now_iso(),
        }

    # Gate 0
    tf_seconds = TIMEFRAMES_SECONDS.get(timeframe, 3600)
    quality = candle_store.get_data_quality_status(db, timeframe, tf_seconds)
    if not engine.gate_data_quality(quality):
        return stop(1, "جودة البيانات غير كافية بعد لهذا الفريم")

    h4_candles = candle_store.get_stored_candles(db, "4h", limit=200)
    h1_candles = candle_store.get_stored_candles(db, "1h", limit=200)
    work_candles = candle_store.get_stored_candles(db, timeframe, limit=200)
    m15_candles = candle_store.get_stored_candles(db, "15m", limit=200)
    m5_candles = candle_store.get_stored_candles(db, "5m", limit=200)

    h4_df = pd.DataFrame(h4_candles) if h4_candles else None
    h1_df = pd.DataFrame(h1_candles) if h1_candles else None
    work_df = pd.DataFrame(work_candles) if work_candles else None
    m15_df = pd.DataFrame(m15_candles) if m15_candles else None
    m5_df = pd.DataFrame(m5_candles) if m5_candles else None

    # Gate 1: H4 Bias
    direction = engine.gate_h4_bias(h4_df)
    if direction is None:
        return stop(2, "لا يوجد انحياز H4 واضح بعد")

    # Gate 2: H1 Structure
    if not engine.gate_h1_structure(h1_df, direction):
        return stop(3, "هيكلية H1 لا تثبت انحياز H4")

    if work_df is None or len(work_df) < 25:
        engine._row(3, "liquidity", "LIQUIDITY", "WAITING", "بيانات الفريم المختار غير كافية بعد")
        return stop(4, "بيانات الفريم المختار غير كافية بعد")

    # Gate 3: Liquidity (على الفريم المختار)
    liquidity = engine.gate_liquidity(work_df, direction)
    if not liquidity:
        return stop(4, "لا توجد منطقة سيولة صالحة بعد")

    # Gate 4: Sweep
    sweep_index = engine.gate_sweep(work_df, liquidity, direction)
    if sweep_index is None:
        return stop(5, "لم يتحقق سحب سيولة (Sweep) حقيقي بعد")

    # Gate 5: Displacement
    displacement_index = engine.gate_displacement(work_df, sweep_index, direction)
    if displacement_index is None:
        return stop(6, "لم تتحقق شمعة زخم (Displacement) بعد")

    # Gate 6: BOS/CHoCH
    if not engine.gate_bos_choch(work_df, displacement_index, liquidity, direction):
        return stop(7, "لم يتأكد كسر الهيكل بعد")

    # Gate 7: FVG
    fvg = engine.gate_fvg(work_df, displacement_index, direction)
    if not fvg:
        return stop(8, "لا توجد فجوة سعرية (FVG) صالحة")

    # Gate 8: Order Block
    ob = engine.gate_order_block(work_df, displacement_index, direction)
    if not ob:
        return stop(9, "لا يوجد Order Block صالح")

    # Gate 9: Freshness
    if not engine.gate_freshness(work_df, ob, displacement_index, direction):
        return stop(10, "المنطقة لم تعد طازجة")

    # Gate 10: Premium/Discount
    discount_zone = engine.gate_premium_discount(work_df, sweep_index, displacement_index, direction)
    if not discount_zone:
        return stop(11, "السعر لم يصل بعد لمنطقة الخصم/العلاوة")

    # Gate 11: 15M Setup
    if not engine.gate_m15_setup(m15_df, direction):
        return stop(12, "إعداد M15 غير مكتمل بعد")

    # Gate 12: 5M Confirmation
    confirmation = engine.gate_m5_confirmation(m5_df, m15_df, direction)
    if not confirmation:
        return stop(13, "بانتظار تأكيد دخول على M5")

    # بناء خطة الصفقة (Entry/SL/TP1/TP2 - كلها مستقلة عن بعضها)
    trade_plan = engine.build_trade_plan(work_df, ob, sweep_index, discount_zone, direction)

    # Gate 13: Structural SL
    if not engine.gate_structural_sl(trade_plan, direction):
        return stop(14, "الستوب لوز غير منطقي هيكلياً")

    # Gate 14: Liquidity TP
    if not engine.gate_liquidity_tp(trade_plan, direction):
        return stop(15, "الهدف الأول غير صالح")

    # Gate 15: RR
    rr = engine.gate_rr(trade_plan)
    if rr is None:
        return stop(16, "عائد المخاطرة أقل من الحد الأدنى الإلزامي")

    # Gate 16: News Lock
    if not engine.gate_news_lock(news_status):
        return stop(17, "قفل الأخبار مفعّل")

    # Gate 17: Spread
    engine.gate_spread(spread, is_stale)  # لا يوقف السلسلة إذا NOT_AVAILABLE، بس يوقفها لو تجاوز الحد فعلياً
    last_spread_row = engine.rows[-1]
    if last_spread_row.status == "FAILED":
        return stop(18, "السبريد الحالي أعلى من الحد المسموح")

    # Gate 18: Risk Engine
    risk_result = engine.gate_risk(trade_plan, balance, leverage, risk_pct)
    if not risk_result or risk_result.get("execution_blocked"):
        return stop(19, "الحجم الآمن ضمن نسبة المخاطرة أقل من الحد الأدنى القابل للتنفيذ")

    # Gate 19: Auditor (شبكة أمان مستقلة أخيرة)
    candles_for_audit = work_candles[-30:] if len(work_candles) >= 30 else work_candles
    if not engine.gate_auditor(candles_for_audit, trade_plan, news_status, risk_pct):
        gates = engine.to_list()
        return {
            "pipeline_version": PIPELINE_VERSION, "timeframe": timeframe, "gates": gates,
            "final_decision": "NO_TRADE", "final_reason_ar": "رفض المدقق النهائي (Auditor) الصفقة",
            "generated_at": _now_iso(),
        }

    # ✅ كل البوابات العشرين نجحت فعلياً
    invalidation_text = (
        f"الصفقة تصير باطلة إذا أغلق السعر {'تحت' if direction=='BUY' else 'فوق'} "
        f"{trade_plan['sl']} أو انعكس انحياز H4 الأساسي."
    )
    return {
        "pipeline_version": PIPELINE_VERSION, "timeframe": timeframe, "gates": engine.to_list(),
        "final_decision": direction, "final_reason_ar": "كل البوابات العشرون نجحت - توصية كاملة",
        "trade_plan": trade_plan, "risk": risk_result, "invalidation_text": invalidation_text,
        "generated_at": _now_iso(),
    }
