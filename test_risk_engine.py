from app.risk_engine import RiskCalculator


def test_normal_calculation():
    calc = RiskCalculator(balance=5000, leverage=100, risk_per_trade_percent=1.5)
    result = calc.calculate_position_size(entry_price=2650, stop_loss_price=2642, take_profit_price=2670)
    assert result is not None
    assert result["risk_amount_usd"] == 75.0
    assert result["recommended_lot_size"] == 0.09
    assert result["risk_reward_ratio"] == "1:2.5"


def test_zero_distance_returns_none():
    calc = RiskCalculator(balance=5000, leverage=100, risk_per_trade_percent=1.0)
    result = calc.calculate_position_size(entry_price=2650, stop_loss_price=2650, take_profit_price=2670)
    assert result is None


def test_tiny_account_blocks_execution_instead_of_inflating_lot():
    """حساب صغير جداً - اللوت الآمن الحقيقي أقل من 0.01. يجب أن يرجع الرقم
    الحقيقي (حتى لو صغير) ويعلّم الصفقة execution_blocked=True - ممنوع رفع
    اللوت تلقائياً لأن هذا يعني تجاوز نسبة المخاطرة المحددة فعلياً."""
    calc = RiskCalculator(balance=50, leverage=100, risk_per_trade_percent=1.0)
    result = calc.calculate_position_size(entry_price=2650, stop_loss_price=2600, take_profit_price=2700)
    assert result is not None
    assert result["execution_blocked"] is True
    assert result["block_reason"] is not None
    assert result["raw_calculated_lot_size"] < 0.01


def test_normal_account_is_not_blocked():
    calc = RiskCalculator(balance=5000, leverage=100, risk_per_trade_percent=1.5)
    result = calc.calculate_position_size(entry_price=2650, stop_loss_price=2642, take_profit_price=2670)
    assert result["execution_blocked"] is False
    assert result["block_reason"] is None


def test_sell_direction_rr_calculation():
    calc = RiskCalculator(balance=10000, leverage=50, risk_per_trade_percent=2.0)
    # صفقة بيع: SL أعلى من الدخول، TP أقل
    result = calc.calculate_position_size(entry_price=2650, stop_loss_price=2660, take_profit_price=2620)
    assert result is not None
    assert result["risk_reward_ratio"] == "1:3.0"


def test_high_leverage_reduces_required_margin():
    calc_low_lev = RiskCalculator(balance=5000, leverage=10, risk_per_trade_percent=1.0)
    calc_high_lev = RiskCalculator(balance=5000, leverage=200, risk_per_trade_percent=1.0)
    r1 = calc_low_lev.calculate_position_size(2650, 2640, 2670)
    r2 = calc_high_lev.calculate_position_size(2650, 2640, 2670)
    assert r2["required_margin_usd"] < r1["required_margin_usd"]
