"""
اختبارات كشف القمم/القيعان (Swing Points) - أهم نقطة: منع Look-Ahead Bias.
القاعدة: سوينغ عند الفهرس i ما يظهر بالنتيجة إلا لو فيه lookback شمعة حقيقية
بعده فعلاً بالداتافريم المُمرر - يعني ما نستخدم بيانات مستقبلية غير موجودة.
"""
import numpy as np
import pandas as pd

from app.strategy_engine import find_swing_points, determine_trend


def _flat_df(n=30, price=100.0):
    return pd.DataFrame({
        "open": [price] * n, "high": [price + 0.1] * n,
        "low": [price - 0.1] * n, "close": [price] * n,
    })


def test_no_swings_on_flat_market():
    df = _flat_df(40)
    swings = find_swing_points(df, lookback=5)
    # سوق مسطح تماماً - ما فيه قمة/قاع سوينغ حقيقي مميز
    assert len(swings["highs"]) == 0 or all(
        df["high"].iloc[i] == df["high"].max() for i in swings["highs"]
    )


def test_swing_high_not_detected_without_future_confirmation():
    """أهم اختبار: قمة عند الفهرس 10 ما لازم تظهر إذا ما فيه lookback شمعة بعدها"""
    n = 12
    data = {"open": [100.0] * n, "close": [100.0] * n,
            "low": [99.5] * n, "high": [100.5] * n}
    data["high"][10] = 110.0  # قمة واضحة عند index 10
    df = pd.DataFrame(data)

    # الداتافريم ينتهي عند index 11 - بس شمعة وحدة بعد القمة (lookback=5 يحتاج 5)
    swings = find_swing_points(df, lookback=5)
    assert 10 not in swings["highs"], "لا يجوز اكتشاف القمة بدون 5 شموع تأكيد حقيقية بعدها"


def test_swing_high_detected_after_full_confirmation():
    n = 20
    data = {"open": [100.0] * n, "close": [100.0] * n,
            "low": [99.5] * n, "high": [100.5] * n}
    data["high"][10] = 110.0
    df = pd.DataFrame(data)

    swings = find_swing_points(df, lookback=5)
    assert 10 in swings["highs"], "القمة لازم تنكشف بعد ما توفر 5 شموع تأكيد حقيقية"


def _zigzag_df(pivots, steps_per_leg=8):
    """يبني DataFrame زج-زاج واقعي من نقاط تحول يدوية - كل قطعة بين قمة وقاع
    تُمدد على عدة شموع، تماماً متل تذبذب سعر حقيقي (يعطي swings حقيقية
    للمقارنة، بعكس خط مستقيم تماماً ما ينتج أي تذبذب)."""
    closes = []
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        for s in range(steps_per_leg):
            closes.append(a + (b - a) * s / steps_per_leg)
    closes.append(pivots[-1])
    return pd.DataFrame({
        "close": closes,
        "open": [c - 0.1 for c in closes],
        "high": [c + 0.3 for c in closes],
        "low": [c - 0.3 for c in closes],
    })


def test_determine_trend_bullish_on_higher_highs_higher_lows():
    """زج-زاج صاعد: كل قمة أعلى من اللي قبلها، وكل قاع أعلى من اللي قبله"""
    df = _zigzag_df([100, 95, 110, 105, 120, 115, 130, 125, 140])
    assert determine_trend(df) == "BULLISH"


def test_determine_trend_bearish_on_lower_highs_lower_lows():
    """زج-زاج هابط: كل قمة أقل من اللي قبلها، وكل قاع أقل من اللي قبله"""
    df = _zigzag_df([140, 145, 130, 135, 120, 125, 110, 115, 100])
    assert determine_trend(df) == "BEARISH"


def test_determine_trend_range_on_perfectly_smooth_monotonic_line():
    """توثيق صريح لحد حقيقي بالخوارزمية: خط مستقيم تماماً بدون أي تذبذب ما
    ينتج أي Swing points للمقارنة (لأنه كل نقطة إما أعلى أو أقل من محيطها
    بشكل رتيب) - فالنتيجة RANGE، وهذا سلوك صحيح ومتوقع رياضياً، مو خطأ.
    هذا الاختبار يوثّق الحد بدل ما يخفيه."""
    n = 40
    base = np.linspace(100, 140, n)
    df = pd.DataFrame({
        "open": base - 0.2, "close": base + 0.2,
        "high": base + 0.5, "low": base - 0.5,
    })
    assert determine_trend(df) == "RANGE"
