import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def test_strong_bullish_candle_detected_as_displacement():
    candles = zigzag_candles([100, 95, 110], steps=3)
    candles.append({"time": candles[-1]["time"]+3600, "open": 110, "high": 122, "low": 110, "close": 121})
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    idx = engine.gate_displacement(df, sweep_index=len(candles)-2, direction="BUY")
    assert idx is not None
    assert engine.rows[-1].status == "PASSED"


def test_weak_doji_candle_not_displacement():
    candles = zigzag_candles([100, 95, 110], steps=3)
    # شمعة دوجي ضعيفة (جسم صغير جداً نسبة للمدى) - ما تصلح Displacement
    candles.append({"time": candles[-1]["time"]+3600, "open": 110, "high": 112, "low": 108, "close": 110.1})
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings(displacement_body_range_ratio=0.6, displacement_body_vs_avg_mult=2.0))
    idx = engine.gate_displacement(df, sweep_index=len(candles)-2, direction="BUY")
    assert idx is None
    assert engine.rows[-1].status == "WAITING"


def test_wrong_direction_candle_not_displacement_for_buy():
    """شمعة هابطة قوية ما تصلح Displacement لصفقة شراء"""
    candles = zigzag_candles([100, 95, 110], steps=3)
    candles.append({"time": candles[-1]["time"]+3600, "open": 121, "high": 122, "low": 110, "close": 110.5})
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    idx = engine.gate_displacement(df, sweep_index=len(candles)-2, direction="BUY")
    assert idx is None
