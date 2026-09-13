import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def test_bos_confirmed_when_close_breaks_level():
    candles = zigzag_candles([100, 95, 110], steps=3)
    candles.append({"time": candles[-1]["time"]+3600, "open": 110, "high": 122, "low": 110, "close": 121})
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    ok = engine.gate_bos_choch(df, displacement_index=len(candles)-1, liquidity={"level": 111}, direction="BUY")
    assert ok is True
    assert engine.rows[-1].status == "PASSED"


def test_bos_fails_when_close_does_not_break_level():
    candles = zigzag_candles([100, 95, 110], steps=3)
    candles.append({"time": candles[-1]["time"]+3600, "open": 108, "high": 111, "low": 107, "close": 109})
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    ok = engine.gate_bos_choch(df, displacement_index=len(candles)-1, liquidity={"level": 115}, direction="BUY")
    assert ok is False
    assert engine.rows[-1].status == "FAILED"
