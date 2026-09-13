import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def test_real_sweep_detected_buy():
    """اختراق حقيقي تحت القاع ثم إغلاق رجوعي فوقه - Sweep صالح"""
    candles = zigzag_candles([100, 95, 110, 105, 120])
    liquidity_level = min(c["low"] for c in candles[-15:])
    candles.append({"time": candles[-1]["time"]+3600, "open": 119, "high": 120,
                     "low": liquidity_level - 2, "close": 120})  # فتيل يخترق ويرجع يغلق فوق
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    liquidity = {"level": liquidity_level, "index": 0}
    idx = engine.gate_sweep(df, liquidity, "BUY")
    assert idx is not None
    assert engine.rows[-1].status == "PASSED"


def test_simple_breakout_without_return_is_not_a_sweep():
    """اختراق بدون رجوع إغلاق (Breakout عادي) - ما يُعتبر Sweep"""
    candles = zigzag_candles([100, 95, 110, 105, 120])
    liquidity_level = min(c["low"] for c in candles[-15:])
    # يكسر تحت ويضل تحت (بدون رجوع) - breakout مو sweep
    for i in range(5):
        candles.append({"time": candles[-1]["time"]+3600, "open": liquidity_level-1-i,
                         "high": liquidity_level-0.5-i, "low": liquidity_level-2-i, "close": liquidity_level-1.5-i})
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings(sweep_confirm_max_candles=1))
    liquidity = {"level": liquidity_level, "index": 0}
    idx = engine.gate_sweep(df, liquidity, "BUY")
    assert idx is None
    assert engine.rows[-1].status == "WAITING"


def test_sweep_waiting_when_no_liquidity():
    df = df_from_candles(zigzag_candles([100, 95, 110]))
    engine = GateEngine(loose_settings())
    idx = engine.gate_sweep(df, None, "BUY")
    assert idx is None
    assert engine.rows[-1].status == "WAITING"
