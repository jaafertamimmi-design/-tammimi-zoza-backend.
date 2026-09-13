import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def test_bearish_candle_before_bullish_displacement_is_valid_ob():
    candles = zigzag_candles([100, 95, 105], steps=3)
    t0 = candles[-1]["time"]
    candles.append({"time": t0+3600, "open": 107, "high": 107.5, "low": 105, "close": 105.5})  # شمعة هابطة (OB صالح لشراء)
    candles.append({"time": t0+7200, "open": 105.5, "high": 118, "low": 105.5, "close": 117})   # زخم صاعد
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    ob = engine.gate_order_block(df, displacement_index=len(candles)-1, direction="BUY")
    assert ob is not None
    assert engine.rows[-1].status == "PASSED"


def test_bullish_candle_before_bullish_displacement_is_invalid_ob():
    """آخر شمعة قبل الزخم صاعدة (نفس لون الزخم) - ما تصلح OB لشراء"""
    candles = zigzag_candles([100, 95, 105], steps=3)
    t0 = candles[-1]["time"]
    candles.append({"time": t0+3600, "open": 105, "high": 107, "low": 104.8, "close": 106.8})  # صاعدة أيضاً
    candles.append({"time": t0+7200, "open": 106.8, "high": 118, "low": 106.8, "close": 117})
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    ob = engine.gate_order_block(df, displacement_index=len(candles)-1, direction="BUY")
    assert ob is None
    assert engine.rows[-1].status == "FAILED"
