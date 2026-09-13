from app.auditor import ChartAndSignalAuditor, TradeAuditStatus


def _mock_candles(n=25, base=2650.0):
    return [{"open": base + i * 0.1, "high": base + 1 + i * 0.1,
             "low": base - 1 + i * 0.1, "close": base + 0.5 + i * 0.1} for i in range(n)]


def test_valid_buy_passes():
    auditor = ChartAndSignalAuditor()
    candles = _mock_candles()
    plan = {"direction": "BUY", "entry": candles[-1]["close"], "sl": candles[-1]["close"] - 8, "tp1": candles[-1]["close"] + 16}
    result = auditor.audit(candles, plan, {"news_lock_active": False})
    assert result["can_execute"] is True


def test_low_rr_is_mandatory_rejection_not_warning():
    """🐛 تصحيح: RR أقل من الحد الأدنى لازم يرفض التنفيذ فعلياً، مو يعطي تحذير بس"""
    auditor = ChartAndSignalAuditor(min_rr_ratio=1.5)
    candles = _mock_candles()
    plan = {"direction": "BUY", "entry": candles[-1]["close"], "sl": candles[-1]["close"] - 10, "tp1": candles[-1]["close"] + 5}
    result = auditor.audit(candles, plan, {"news_lock_active": False})
    assert result["status"] == TradeAuditStatus.REJECTED
    assert result["can_execute"] is False


def test_news_lock_rejects_trade():
    auditor = ChartAndSignalAuditor()
    candles = _mock_candles()
    plan = {"direction": "BUY", "entry": candles[-1]["close"], "sl": candles[-1]["close"] - 8, "tp1": candles[-1]["close"] + 16}
    result = auditor.audit(candles, plan, {"news_lock_active": True, "reason_ar": "خبر قوي قريب"})
    assert result["can_execute"] is False
    assert result["status"] == TradeAuditStatus.REJECTED


def test_invalid_zero_prices_rejected():
    auditor = ChartAndSignalAuditor()
    candles = _mock_candles()
    plan = {"direction": "BUY", "entry": 0, "sl": 0, "tp1": 0}
    result = auditor.audit(candles, plan, {"news_lock_active": False})
    assert result["can_execute"] is False


def test_entry_equals_tp1_rejected():
    """🐛 تصحيح: Entry == TP1 كان ممكن يمر بدون فحص - الحين يُرفض صراحة"""
    auditor = ChartAndSignalAuditor()
    candles = _mock_candles()
    entry = candles[-1]["close"]
    plan = {"direction": "BUY", "entry": entry, "sl": entry - 8, "tp1": entry}
    result = auditor.audit(candles, plan, {"news_lock_active": False})
    assert result["can_execute"] is False


def test_buy_wrong_price_order_rejected():
    """BUY لازم SL < Entry < TP1 - لو الترتيب معكوس يُرفض"""
    auditor = ChartAndSignalAuditor()
    candles = _mock_candles()
    entry = candles[-1]["close"]
    plan = {"direction": "BUY", "entry": entry, "sl": entry + 8, "tp1": entry - 16}  # معكوس بالكامل
    result = auditor.audit(candles, plan, {"news_lock_active": False})
    assert result["can_execute"] is False


def test_sell_correct_price_order_passes():
    """SELL لازم TP1 < Entry < SL"""
    auditor = ChartAndSignalAuditor()
    candles = _mock_candles()
    entry = candles[-1]["close"]
    plan = {"direction": "SELL", "entry": entry, "sl": entry + 8, "tp1": entry - 16}
    result = auditor.audit(candles, plan, {"news_lock_active": False})
    assert result["can_execute"] is True


def test_sell_wrong_price_order_rejected():
    auditor = ChartAndSignalAuditor()
    candles = _mock_candles()
    entry = candles[-1]["close"]
    plan = {"direction": "SELL", "entry": entry, "sl": entry - 8, "tp1": entry + 16}  # ترتيب شراء بالغلط لصفقة بيع
    result = auditor.audit(candles, plan, {"news_lock_active": False})
    assert result["can_execute"] is False


def test_max_risk_pct_enforced():
    """🐛 تصحيح: max_risk_pct كان موجود بالتوقيع بدون أي استخدام فعلي - الحين مفعّل"""
    auditor = ChartAndSignalAuditor(max_risk_pct=2.0)
    candles = _mock_candles()
    entry = candles[-1]["close"]
    plan = {"direction": "BUY", "entry": entry, "sl": entry - 8, "tp1": entry + 16}
    result = auditor.audit(candles, plan, {"news_lock_active": False}, risk_pct=5.0)
    assert result["can_execute"] is False


def test_risk_pct_within_limit_passes():
    auditor = ChartAndSignalAuditor(max_risk_pct=2.0)
    candles = _mock_candles()
    entry = candles[-1]["close"]
    plan = {"direction": "BUY", "entry": entry, "sl": entry - 8, "tp1": entry + 16}
    result = auditor.audit(candles, plan, {"news_lock_active": False}, risk_pct=1.0)
    assert result["can_execute"] is True
