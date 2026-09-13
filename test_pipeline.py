import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _sqlalchemy_stub
_sqlalchemy_stub.install()

from _gate_fixtures import loose_settings, zigzag_candles

VALID_DECISIONS = {"BUY", "SELL", "NO_TRADE"}


def _run_pipeline(monkeypatch_candles, settings_override=None):
    from app import candle_store, settings_store, pipeline_view

    def fake_stored(db, tf, limit=200):
        return monkeypatch_candles.get(tf, [])

    def fake_quality(db, tf, tf_seconds, lookback=200):
        return {"ok": True, "reason_ar": "بيانات كافية للاختبار"}

    candle_store.get_stored_candles = fake_stored
    candle_store.get_data_quality_status = fake_quality
    pipeline_view.load_settings = lambda db: settings_override or loose_settings()

    return pipeline_view.build_pipeline(
        db=None, timeframe="1h", balance=10000, risk_pct=1.0, leverage=100,
        news_status={"news_lock_active": False}, spread=0.3, is_stale=False,
    )


def test_range_market_produces_no_trade():
    """سوق متذبذب بدون اتجاه واضح على H4 - لازم يطلع NO_TRADE"""
    flat = [{"time": i*14400, "open": 2650, "high": 2650.5, "low": 2649.5, "close": 2650.1} for i in range(30)]
    result = _run_pipeline({"4h": flat, "1h": flat, "15m": flat, "5m": flat})
    assert result["final_decision"] == "NO_TRADE"
    assert result["final_decision"] in VALID_DECISIONS


def test_insufficient_data_produces_no_trade():
    result = _run_pipeline({"4h": [], "1h": [], "15m": [], "5m": []})
    assert result["final_decision"] == "NO_TRADE"


def test_decision_is_always_one_of_three_valid_values():
    """بغض النظر عن المدخلات، القرار النهائي دايماً وحدة من ثلاث قيم بس"""
    flat = [{"time": i*14400, "open": 2650, "high": 2650.5, "low": 2649.5, "close": 2650.1} for i in range(30)]
    trending = zigzag_candles([2600, 2590, 2620, 2610, 2650], steps=8, tf_sec=14400)
    for candles_h4 in (flat, trending):
        result = _run_pipeline({"4h": candles_h4, "1h": flat, "15m": flat, "5m": flat})
        assert result["final_decision"] in VALID_DECISIONS


def test_bearish_h4_never_produces_buy_decision():
    """🎯 فحص عدم التحيز: اتجاه هابط واضح على H4 يجب أبداً ما يطلع BUY"""
    bearish_h4 = zigzag_candles([2700, 2710, 2680, 2690, 2650, 2660, 2620], steps=8, tf_sec=14400)
    flat = [{"time": i*3600, "open": 2650, "high": 2650.5, "low": 2649.5, "close": 2650.1} for i in range(30)]
    result = _run_pipeline({"4h": bearish_h4, "1h": flat, "15m": flat, "5m": flat})
    assert result["final_decision"] != "BUY"


def test_bullish_h4_never_produces_sell_decision():
    """🎯 نفس الفحص بالاتجاه المعاكس - عدم تحيز بالاتجاهين"""
    bullish_h4 = zigzag_candles([2600, 2590, 2620, 2610, 2650, 2640, 2680], steps=8, tf_sec=14400)
    flat = [{"time": i*3600, "open": 2650, "high": 2650.5, "low": 2649.5, "close": 2650.1} for i in range(30)]
    result = _run_pipeline({"4h": bullish_h4, "1h": flat, "15m": flat, "5m": flat})
    assert result["final_decision"] != "SELL"


def test_gates_list_always_has_20_entries():
    flat = [{"time": i*14400, "open": 2650, "high": 2650.5, "low": 2649.5, "close": 2650.1} for i in range(30)]
    result = _run_pipeline({"4h": flat, "1h": flat, "15m": flat, "5m": flat})
    assert len(result["gates"]) == 20
