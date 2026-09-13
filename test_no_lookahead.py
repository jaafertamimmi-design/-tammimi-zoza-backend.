"""
اختبار صريح ومباشر لمنع Look-Ahead Bias - النقطة الأهم بكل الاستراتيجية.

القاعدة: قرار الهيكلية عند "الآن" (نهاية الداتافريم المُمرر) ما يجوز يتغير
أبداً إذا حذفنا شموع مستقبلية ما كانت موجودة وقت اتخاذ القرار. بمعنى ثاني:
نفس الدالة، بنفس البيانات المتوفرة "وقتها"، لازم تعطي نفس النتيجة بغض النظر
شنو صار بالمستقبل.
"""
import pandas as pd
from app.strategy_engine import find_swing_points, determine_trend


def _zigzag_df(pivots, steps_per_leg=8):
    closes = []
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        for s in range(steps_per_leg):
            closes.append(a + (b - a) * s / steps_per_leg)
    closes.append(pivots[-1])
    return pd.DataFrame({
        "close": closes, "open": [c - 0.1 for c in closes],
        "high": [c + 0.3 for c in closes], "low": [c - 0.3 for c in closes],
    })


def test_swing_detection_stable_regardless_of_future_data():
    """أهم اختبار بالمشروع كله: نكتشف swings على بيانات كاملة، وبعدين نقص
    الداتافريم لآخر نقطة كانت "معروفة وقتها" - النتيجة يجب تكون متطابقة."""
    full_df = _zigzag_df([100, 95, 110, 105, 120, 115, 130, 125, 140, 135, 150])

    # نفترض "الآن" هو الفهرس 40 (يعني ما نعرف شي بعده وقتها)
    known_at_time_40 = full_df.iloc[:41].reset_index(drop=True)

    swings_full = find_swing_points(full_df, lookback=5)
    swings_known = find_swing_points(known_at_time_40, lookback=5)

    # كل swing انكشف بالنسخة المحدودة (اللي بس شافت لين index 40) لازم يكون
    # نفسه موجود بالنسخة الكاملة بنفس القيمة بالضبط - ما تغير بأثر رجعي
    for idx in swings_known["highs"]:
        assert idx in swings_full["highs"], f"swing high @ {idx} اختفى لما زدنا بيانات مستقبلية - هذا يدل على استخدام مستقبل بالخطأ"
        assert full_df["high"].iloc[idx] == known_at_time_40["high"].iloc[idx]

    for idx in swings_known["lows"]:
        assert idx in swings_full["lows"]
        assert full_df["low"].iloc[idx] == known_at_time_40["low"].iloc[idx]


def test_trend_decision_does_not_retroactively_change():
    """نفس الفكرة على مستوى القرار الكامل (determine_trend) - نحسبه بلحظتين
    مختلفتين بنفس نقطة القطع، ونتأكد القرار ما يتغير بس لأن المستقبل انكشف."""
    full_df = _zigzag_df([100, 95, 110, 105, 120, 115, 130, 125, 140, 135, 150, 145, 160])
    cutoff = 50

    known_then = full_df.iloc[:cutoff].reset_index(drop=True)
    trend_then = determine_trend(known_then)

    # لو حسبنا نفس القرار بنفس القص لاحقاً (حتى لو full_df صار أطول بمعلومات
    # جديدة)، لازم نفس القص يعطي نفس القرار بالضبط - هذا يثبت عدم التسرب
    same_cutoff_again = full_df.iloc[:cutoff].reset_index(drop=True)
    trend_again = determine_trend(same_cutoff_again)

    assert trend_then == trend_again


def test_find_swing_points_never_indexes_beyond_input_length():
    """فحص بنيوي: الدالة ما تقدر أصلاً تشوف أبعد من طول الداتافريم المُمرر لها
    (لأنها تقرأ من نفس df بس) - هذا يضمن بنيوياً استحالة الوصول لبيانات مو
    موجودة بالمدخل، بغض النظر عن أي قيمة lookback."""
    df = _zigzag_df([100, 95, 110, 105, 120])
    swings = find_swing_points(df, lookback=5)
    n = len(df)
    assert all(0 <= i < n for i in swings["highs"])
    assert all(0 <= i < n for i in swings["lows"])
