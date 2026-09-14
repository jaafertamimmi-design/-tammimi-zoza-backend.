"""
حاسبة رأس المال والرافعة واللوت المناسب.

🐛 تصحيح خطأ فعلي: النسخة السابقة كانت تعمل `max(0.01, lot_size)` دايماً -
يعني لو اللوت المحسوب فعلياً أقل من 0.01 (حساب صغير أو ستوب بعيد)، كانت
"ترفع" اللوت تلقائياً لـ 0.01 بصمت - وهذا يخلي المخاطرة الفعلية تتجاوز
النسبة اللي المستخدم حددها فعلياً! الصح: نرجع اللوت المحسوب الحقيقي (حتى
لو أقل من الحد الأدنى)، ونعلّم الصفقة "EXECUTION_BLOCKED" بدل ما نخترع رقم.
"""
from typing import Optional, Dict

MIN_LOT_STEP = 0.01


class RiskCalculator:
    def __init__(self, balance: float, leverage: int, risk_per_trade_percent: float = 1.0):
        self.balance = balance
        self.leverage = leverage
        self.risk_percent = risk_per_trade_percent

    def calculate_position_size(self, entry_price: float, stop_loss_price: float, take_profit_price: float) -> Optional[Dict]:
        risk_amount = self.balance * (self.risk_percent / 100.0)
        pip_difference = abs(entry_price - stop_loss_price)

        if pip_difference == 0:
            return None

        # في الذهب (XAUUSD): 1.0 لوت قياسي = 100 أونصة، وكل 1.0 دولار حركة = 100 دولار بالحساب
        raw_lot_size = risk_amount / (pip_difference * 100)
        rounded_lot_size = round(raw_lot_size, 2)

        # لو اللوت المحسوب أقل من أصغر لوت مسموح، ما نرفعه تلقائياً - نعلّم الصفقة محظورة
        execution_blocked = rounded_lot_size < MIN_LOT_STEP
        final_lot_size = rounded_lot_size if not execution_blocked else rounded_lot_size  # نُبقي الرقم الحقيقي (قد يكون 0.0)

        reward_difference = abs(take_profit_price - entry_price)
        risk_reward_ratio = round(reward_difference / pip_difference, 2) if pip_difference else 0

        # الهامش يُحسب على أساس اللوت الفعلي القابل للتنفيذ فقط (لو محظور، الهامش صفر لأنه ما راح ينفذ)
        effective_lot_for_margin = final_lot_size if not execution_blocked else 0
        notional_value = effective_lot_for_margin * 100 * entry_price
        margin_required = round(notional_value / self.leverage, 2) if self.leverage else 0

        return {
            "risk_amount_usd": round(risk_amount, 2),
            "recommended_lot_size": final_lot_size,
            "raw_calculated_lot_size": round(raw_lot_size, 4),
            "execution_blocked": execution_blocked,
            "block_reason": (
                f"الحجم الآمن ({raw_lot_size:.4f} لوت) أقل من أصغر لوت قابل للتنفيذ (0.01) - "
                f"تنفيذ الصفقة بهذا الحجم يعني تجاوز نسبة المخاطرة المحددة ({self.risk_percent}%)"
                if execution_blocked else None
            ),
            "risk_reward_ratio": f"1:{risk_reward_ratio}",
            "required_margin_usd": margin_required,
            "max_leverage_used": f"1:{self.leverage}",
        }
