import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def _build_plan(direction):
    candles = zigzag_candles([100, 95, 110, 105, 120], steps=2)
    t0 = candles[-1]["time"]
    if direction == "BUY":
        candles.append({"time": t0+3600, "open": 118, "high": 119, "low": 96, "close": 118.5})  # سحب سيولة
        candles.append({"time": t0+7200, "open": 119, "high": 132, "low": 119, "close": 131})     # زخم
    else:
        candles.append({"time": t0+3600, "open": 96, "high": 124, "low": 95, "close": 96.5})       # سحب سيولة علوي
        candles.append({"time": t0+7200, "open": 95, "high": 95, "low": 82, "close": 83})          # زخم هابط
    df = df_from_candles(candles)
    engine = GateEngine(loose_settings())
    ob = {"top": 97 if direction=="BUY" else 96, "bottom": 96 if direction=="BUY" else 95}
    discount_zone = {"impulse_low": 96 if direction=="BUY" else 83, "impulse_high": 131 if direction=="BUY" else 124}
    plan = engine.build_trade_plan(df, ob, sweep_index=len(candles)-2, discount_zone=discount_zone, direction=direction)
    return plan


def test_buy_entry_never_equals_tp1():
    plan = _build_plan("BUY")
    assert plan["entry"] != plan["tp1"], "🐛 هذا بالضبط الخطأ المطلوب تصحيحه - Entry ما يجوز يساوي TP1"


def test_sell_entry_never_equals_tp1():
    plan = _build_plan("SELL")
    assert plan["entry"] != plan["tp1"]


def test_buy_price_order_sl_lt_entry_lt_tp():
    plan = _build_plan("BUY")
    assert plan["sl"] < plan["entry"] < plan["tp1"], f"ترتيب خاطئ لصفقة شراء: {plan}"


def test_sell_price_order_tp_lt_entry_lt_sl():
    plan = _build_plan("SELL")
    assert plan["tp1"] < plan["entry"] < plan["sl"], f"ترتيب خاطئ لصفقة بيع: {plan}"


def test_buy_and_sell_plans_are_structurally_symmetric():
    """لا شرط مكتوب بطريقة تخلي BUY ممكن وSELL مستحيل - نفس دالة build_trade_plan
    تُنتج خطط صالحة لكلا الاتجاهين من نفس المدخلات النسبية"""
    buy_plan = _build_plan("BUY")
    sell_plan = _build_plan("SELL")
    for plan, direction in [(buy_plan, "BUY"), (sell_plan, "SELL")]:
        assert plan["direction"] == direction
        assert plan["entry"] != plan["sl"]
        assert plan["entry"] != plan["tp1"]
        assert plan["tp1"] != plan["tp2"]
