"""
محرك القرار النهائي - يجمع كل شي مع بعض (شموع + هيكلية + أخبار + جلسات + تدقيق)
ويطلع القرار (شراء/بيع/انتظار) ونسبة ثقة - مو نسبة "مضمونة 100%"، هذا مستحيل تقنياً
ولا توجد منصة تداول حقيقية بالعالم تقدر تضمنه.

نسبة الثقة محسوبة من تراكم عوامل حقيقية موزونة:
  - قوة الهيكلية والتأكيدات الفنية (من strategy_engine) : الوزن الأكبر
  - حالة الأخبار (حظر/آمن) : تخفض الثقة أو ترفضها كلياً
  - جلسة السوق المفتوحة حالياً (سيولة عالية/منخفضة) : تعديل بسيط
  - نتيجة التدقيق النهائي (auditor) : فيتو - لو REJECTED ما تطلع توصية إطلاقاً
"""
from typing import Dict, Optional

from .auditor import ChartAndSignalAuditor, TradeAuditStatus
from .risk_engine import RiskCalculator

MAX_CONFIDENCE_CAP = 92  # لا نعطي أبداً 100% - هذا تعهد مستحيل بأي سوق مالي حقيقي

DISCLAIMER_AR = (
    "⚠️ هذا تحليل آلي مبني على قواعد فنية وإخبارية ثابتة، وليس نصيحة استثمارية أو ضماناً "
    "لتحقيق ربح. الأسواق المالية تحمل مخاطر حقيقية، والقرار النهائي والمسؤولية الكاملة "
    "تقع على المتداول."
)
DISCLAIMER_EN = (
    "⚠️ This is an automated technical/fundamental analysis, not financial advice or a "
    "profit guarantee. Financial markets carry real risk; the final decision and "
    "responsibility rest with the trader."
)


class DecisionEngine:
    def __init__(self):
        self.auditor = ChartAndSignalAuditor()

    def build_final_decision(
        self,
        tf_result: Dict,
        candles: list,
        news_status: Dict,
        session_status: Dict,
        user_balance: float,
        user_leverage: int,
        user_risk_pct: float,
    ) -> Dict:
        trade_plan = tf_result.get("trade_plan")
        base_score = tf_result.get("structure_score", 0)

        if not trade_plan:
            return {
                "decision": "WAIT",
                "confidence_percent": 0,
                "timeframe": tf_result.get("timeframe"),
                "phase": tf_result.get("phase"),
                "reasons": tf_result.get("reasons", []),
                "trade_plan": None,
                "risk": None,
                "audit": None,
                "disclaimer_ar": DISCLAIMER_AR,
                "disclaimer_en": DISCLAIMER_EN,
            }

        audit_result = self.auditor.audit(candles, trade_plan, news_status)

        if not audit_result["can_execute"]:
            return {
                "decision": "REJECTED_BY_AUDIT",
                "confidence_percent": 0,
                "timeframe": tf_result.get("timeframe"),
                "phase": tf_result.get("phase"),
                "reasons": tf_result.get("reasons", []) + audit_result["audit_logs"],
                "trade_plan": None,
                "risk": None,
                "audit": audit_result,
                "disclaimer_ar": DISCLAIMER_AR,
                "disclaimer_en": DISCLAIMER_EN,
            }

        score = base_score

        if audit_result["status"] == TradeAuditStatus.WARNING:
            score -= 10

        if session_status.get("high_liquidity_window"):
            score += 5
        elif session_status.get("open_sessions_count", 0) == 0:
            score -= 10

        news_bias = news_status.get("gold_bias", "NEUTRAL")
        if news_bias == "BULLISH_GOLD" and trade_plan["direction"] == "BUY":
            score += 5
        elif news_bias == "BEARISH_GOLD" and trade_plan["direction"] == "SELL":
            score += 5
        elif news_bias in ("BULLISH_GOLD", "BEARISH_GOLD"):
            score -= 5  # الأخبار تعاكس اتجاه التوصية الفنية

        confidence = max(5, min(score, MAX_CONFIDENCE_CAP))

        risk_calc = RiskCalculator(user_balance, user_leverage, user_risk_pct)
        risk_result = risk_calc.calculate_position_size(
            trade_plan["entry"], trade_plan["sl"], trade_plan["tp1"]
        )

        return {
            "decision": trade_plan["direction"],
            "confidence_percent": confidence,
            "timeframe": tf_result.get("timeframe"),
            "phase": tf_result.get("phase"),
            "reasons": tf_result.get("reasons", []) + audit_result["audit_logs"],
            "trade_plan": trade_plan,
            "risk": risk_result,
            "audit": audit_result,
            "disclaimer_ar": DISCLAIMER_AR,
            "disclaimer_en": DISCLAIMER_EN,
        }
