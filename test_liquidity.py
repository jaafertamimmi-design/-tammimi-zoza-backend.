import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def test_liquidity_found_for_buy_direction():
    df = df_from_candles(zigzag_candles([100, 95, 110, 105, 120, 115, 130]))
    engine = GateEngine(loose_settings())
    result = engine.gate_liquidity(df, "BUY")
    assert result is not None
    assert "level" in result
    row = engine.rows[-1]
    assert row.status == "PASSED"
    assert row.key == "liquidity"


def test_liquidity_found_for_sell_direction():
    df = df_from_candles(zigzag_candles([130, 135, 120, 125, 110, 115, 100]))
    engine = GateEngine(loose_settings())
    result = engine.gate_liquidity(df, "SELL")
    assert result is not None
    row = engine.rows[-1]
    assert row.status == "PASSED"


def test_liquidity_waiting_when_zone_too_old():
    """منطقة سيولة قديمة (عمرها تجاوز الحد) يجب تُهمل - نبني بيانات لاحقة
    بشكل صاعد بسيط بدون تذبذب حتى ما تتشكل قيعان سوينغ جديدة تصطنع نتيجة"""
    old_part = zigzag_candles([100, 95, 110, 105, 120])
    filler = [
        {"time": old_part[-1]["time"] + (i + 1) * 3600,
         "open": 120 + i * 0.05, "high": 120.3 + i * 0.05,
         "low": 119.8 + i * 0.05, "close": 120.1 + i * 0.05}
        for i in range(200)
    ]
    df = df_from_candles(old_part + filler)
    engine = GateEngine(loose_settings(liquidity_zone_max_age_candles=5))
    result = engine.gate_liquidity(df, "BUY")
    assert result is None
    assert engine.rows[-1].status == "WAITING"
