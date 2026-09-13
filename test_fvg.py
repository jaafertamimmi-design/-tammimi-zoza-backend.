import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def test_real_bullish_fvg_detected():
    """فجوة حقيقية: low الشمعة الثالثة أعلى من high الشمعة الأولى (3-candle gap)"""
    candles = zigzag_candles([100, 95, 105], steps=3)
    t0 = candles[-1]["time"]
    candles.append({"time": t0+3600, "open": 106, "high": 107, "low": 105.5, "close": 106.5})   # c1
    candles.append({"time": t0+7200, "open": 106.5, "high": 108, "low": 106.2, "close": 107.8})  # وسط
    candles.append({"time": t0+10800, "open": 108, "high": 112, "low": 109, "close": 111.5})     # c3 - low(109) > high(107) = فجوة حقيقية
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    fvg = engine.gate_fvg(df, displacement_index=len(candles)-1, direction="BUY")
    assert fvg is not None
    assert fvg["gap_pct"] > 0
    assert engine.rows[-1].status == "PASSED"


def test_no_gap_means_no_fvg():
    """شموع متلاصقة بدون فجوة حقيقية - يُرفض"""
    candles = zigzag_candles([100, 95, 105], steps=3)
    t0 = candles[-1]["time"]
    candles.append({"time": t0+3600, "open": 106, "high": 108, "low": 105, "close": 107})
    candles.append({"time": t0+7200, "open": 107, "high": 109, "low": 106, "close": 108})
    candles.append({"time": t0+10800, "open": 108, "high": 109.5, "low": 106.5, "close": 109})  # low(106.5) < high c1(108) = بدون فجوة
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    fvg = engine.gate_fvg(df, displacement_index=len(candles)-1, direction="BUY")
    assert fvg is None
    assert engine.rows[-1].status == "FAILED"
