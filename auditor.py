"""
مدقق التوصيات - الفلتر الأخير قبل عرض أي توصية للمستخدم.

🐛 تصحيح: RR أقل من الحد الأدنى كان يعطي WARNING بس (يسمح بالتنفيذ) - هذا
خطأ لو النظام يعتبر RR شرط إلزامي (Mandatory Gate). صار الحين REJECTED فعلياً.
كذلك فُعّل max_risk_pct (كان موجود بالتوقيع بس ما يُستخدم أبداً بالمنطق).
"""
from typing import Dict, List, Optional
import pandas as pd


class TradeAuditStatus:
    APPROVED = "PASSED"
    REJECTED = "REJECTED"
    WARNING = "WARNING"


class ChartAndSignalAuditor:
    def __init__(self, min_rr_ratio: float = 1.5, max_risk_pct: float = 3.0):
        self.min_rr_ratio = min_rr_ratio
        self.max_risk_pct = max_risk_pct

    def audit(self, candles: List[Dict], trade_plan: Dict, news_status: Dict, risk_pct: Optional[float] = None) -> Dict:
        audit_logs = []
        is_passed = True
        has_warning = False

        df = pd.DataFrame(candles)
        entry = trade_plan.get("entry", 0)
        sl = trade_plan.get("sl", 0)
        tp1 = trade_plan.get("tp1", 0)
        direction = trade_plan.get("direction", "BUY")

        if entry <= 0 or sl <= 0 or tp1 <= 0:
            audit_logs.append("❌ أسعار الخطة غير منطقية (صفر أو سالبة)")
            is_passed = False

        if entry == tp1:
            audit_logs.append("❌ سعر الدخول يساوي الهدف الأول - هذا خطأ ببناء الخطة (TP يجب يكون هدف مستقل)")
            is_passed = False

        # ترتيب الأسعار الصحيح إلزامي: BUY: SL < Entry < TP | SELL: TP < Entry < SL
        if direction == "BUY" and not (sl < entry < tp1):
            audit_logs.append(f"❌ ترتيب أسعار خاطئ لصفقة شراء: يجب SL({sl}) < Entry({entry}) < TP1({tp1})")
            is_passed = False
        elif direction == "SELL" and not (tp1 < entry < sl):
            audit_logs.append(f"❌ ترتيب أسعار خاطئ لصفقة بيع: يجب TP1({tp1}) < Entry({entry}) < SL({sl})")
            is_passed = False

        risk_pips = abs(entry - sl)
        reward_pips = abs(tp1 - entry)

        if risk_pips == 0:
            audit_logs.append("❌ مسافة الستوب تساوي سعر الدخول")
            is_passed = False
        else:
            rr_ratio = round(reward_pips / risk_pips, 2)
            if rr_ratio < self.min_rr_ratio:
                # بوابة إلزامية - رفض فعلي مو تحذير فقط
                audit_logs.append(f"❌ عائد المخاطرة (1:{rr_ratio}) أقل من الحد الأدنى الإلزامي (1:{self.min_rr_ratio}) - رفض")
                is_passed = False
            else:
                audit_logs.append(f"✅ عائد المخاطرة جيد (1:{rr_ratio})")

        if risk_pct is not None and risk_pct > self.max_risk_pct:
            audit_logs.append(f"❌ نسبة المخاطرة المطلوبة ({risk_pct}%) تتجاوز الحد الأقصى المسموح ({self.max_risk_pct}%) - رفض")
            is_passed = False

        if len(df) >= 20:
            df["sma20"] = df["close"].rolling(20).mean()
            last_close = df["close"].iloc[-1]
            last_sma = df["sma20"].iloc[-1]
            if pd.notna(last_sma):
                if direction == "BUY" and last_close < last_sma:
                    audit_logs.append("⚠️ تعارض: توصية شراء والسعر تحت المتوسط SMA20")
                    has_warning = True
                elif direction == "SELL" and last_close > last_sma:
                    audit_logs.append("⚠️ تعارض: توصية بيع والسعر فوق المتوسط SMA20")
                    has_warning = True
                else:
                    audit_logs.append("✅ الاتجاه متوافق مع المتوسط المتحرك")

        if news_status.get("news_lock_active", False):
            audit_logs.append(f"❌ رفض: {news_status.get('reason_ar', 'خبر عالي الخطورة نشط')}")
            is_passed = False
        else:
            audit_logs.append("✅ لا توجد أخبار حساسة قريبة")

        if len(df) >= 1:
            last_high = df["high"].iloc[-1]
            last_low = df["low"].iloc[-1]
            if direction == "BUY" and sl >= last_low:
                audit_logs.append("⚠️ الستوب قريب جداً من الشمعة الحالية")
                has_warning = True
            elif direction == "SELL" and sl <= last_high:
                audit_logs.append("⚠️ الستوب قريب جداً من الشمعة الحالية")
                has_warning = True

        if not is_passed:
            status = TradeAuditStatus.REJECTED
        elif has_warning:
            status = TradeAuditStatus.WARNING
        else:
            status = TradeAuditStatus.APPROVED

        return {"status": status, "can_execute": is_passed, "audit_logs": audit_logs}
