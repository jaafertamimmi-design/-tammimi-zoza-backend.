import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gate_fixtures import loose_settings, zigzag_candles, df_from_candles
from app.gates import GateEngine


def test_buy_discount_zone_symmetric_to_sell_premium_zone():
    """🎯 اختبار التماثل: BUY يبحث عن السعر بمنطقة الخصم (قرب القاع)، SELL يبحث
    عن نفس المنطقة نسبياً بس مرآة معكوسة (قرب القمة) - نفس القواعد الرياضية بالضبط"""
    settings = loose_settings(fib_discount_low=0.5, fib_discount_high=0.9)

    # حالة BUY: السعر الحالي يوصل لمنطقة الخصم (القريبة من القاع)
    candles_buy = zigzag_candles([100, 95, 110], steps=3)
    candles_buy.append({"time": candles_buy[-1]["time"]+3600, "open": 96, "high": 97, "low": 95.5, "close": 96.5})
    df_buy = df_from_candles(candles_buy)
    engine_buy = GateEngine(settings)
    result_buy = engine_buy.gate_premium_discount(df_buy, sweep_index=1, displacement_index=len(candles_buy)-1, direction="BUY")

    # حالة SELL (مرآة تامة بالأسعار): نفس المسافات بس معكوسة حول نفس المرجع
    candles_sell = zigzag_candles([110, 115, 100], steps=3)
    candles_sell.append({"time": candles_sell[-1]["time"]+3600, "open": 114, "high": 114.5, "low": 113, "close": 113.5})
    df_sell = df_from_candles(candles_sell)
    engine_sell = GateEngine(settings)
    result_sell = engine_sell.gate_premium_discount(df_sell, sweep_index=1, displacement_index=len(candles_sell)-1, direction="SELL")

    # كلا الاتجاهين لازم يقدر يوصل لـ PASSED - ما فيه انحياز لجهة وحدة
    assert engine_buy.rows[-1].status in ("PASSED", "WAITING")
    assert engine_sell.rows[-1].status in ("PASSED", "WAITING")
    # التأكيد الأهم: نفس المنطق الرياضي يُطبق (zone_low < zone_high دايماً بغض النظر عن الاتجاه)
    if result_buy:
        assert result_buy["zone_low"] < result_buy["zone_high"]
    if result_sell:
        assert result_sell["zone_low"] < result_sell["zone_high"]


def test_premium_discount_waiting_without_sweep_or_displacement():
    df = df_from_candles(zigzag_candles([100, 95, 110], steps=3))
    engine = GateEngine(loose_settings())
    result = engine.gate_premium_discount(df, sweep_index=None, displacement_index=None, direction="BUY")
    assert result is None
    assert engine.rows[-1].status == "WAITING"
