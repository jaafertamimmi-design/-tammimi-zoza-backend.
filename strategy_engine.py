"""
محرك الاستراتيجية الأساسي - تطبيق حرفي للملاحظات اللي زودنا بيها صاحب المنصة:

  المرحلة 1: تحديد الاتجاه (روؤس قمم متصاعدة = صاعد | روؤس قيعان متنازلة = هابط)
             على فريم 4 ساعات وفريم ساعة، ولازم يكونون متوافقين.
  المرحلة 2: اختراق (Break of Structure) - لازم إغلاق **جسم** الشمعة فوق القمة
             (أو تحت القاع)، بشمعة "زخم" (جسمها نسبة كبيرة من مداها الكلي، مو ذيل طويل).
  المرحلة 3: تصحيح (Pullback) - شموع صغيرة بطيئة متداخلة، ترجع لمنطقة فايبوناتشي
             0.5 - 0.618 من الموجة اللي كسرت الهيكل (منطقة الخصم/الديسكاونت).
  المرحلة 4: تأكيد الدخول - شمعة ابتلاعية (Engulfing) أو Pin Bar عند منطقة الفايبو،
             أو تغيير طابع الهيكل (CHoCH) على فريم أصغر (M15) بعد التصحيح.
  الدخول: عند القمة/القاع المخترق (منطقة الانقلاب/Flip Zone).
  الستوب: تحت/فوق قاع أو قمة التصحيح الأخير + هامش بسيط.
  الهدف 1: القمة/القاع الأساسي (تقفيل 50% + نقل الستوب لنقطة الدخول).
  الهدف 2: امتداد فايبوناتشي -0.27 من الموجة.

هذا نظام قواعد حتمية (Deterministic Rule-Based) - كل قرار ينبني على شرط رياضي واضح
من بيانات الشموع الحقيقية، وليس تخمين أو نموذج "ذكاء اصطناعي" يعمل بصندوق أسود.
"""
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

ALL_TIMEFRAMES = ["4h", "1h", "30m", "15m", "10m", "5m", "3m", "1m"]

SWING_LOOKBACK = 10
MOMENTUM_BODY_RATIO = 0.55
FIB_ZONE_LOW = 0.50
FIB_ZONE_HIGH = 0.618
FIB_EXTENSION_TP2 = -0.27


def _candle_body_ratio(row) -> float:
    rng = row["high"] - row["low"]
    if rng <= 0:
        return 0.0
    return abs(row["close"] - row["open"]) / rng


def find_swing_points(df: pd.DataFrame, lookback: int = SWING_LOOKBACK) -> Dict[str, List[int]]:
    highs_idx, lows_idx = [], []
    n = len(df)
    for i in range(lookback, n - lookback):
        window = df.iloc[i - lookback: i + lookback + 1]
        if df["high"].iloc[i] == window["high"].max():
            highs_idx.append(i)
        if df["low"].iloc[i] == window["low"].min():
            lows_idx.append(i)
    return {"highs": highs_idx, "lows": lows_idx}


def determine_trend(df: pd.DataFrame) -> str:
    swings = find_swing_points(df, lookback=5)
    highs = [df["high"].iloc[i] for i in swings["highs"][-3:]]
    lows = [df["low"].iloc[i] for i in swings["lows"][-3:]]

    if len(highs) >= 2 and len(lows) >= 2:
        higher_highs = highs[-1] > highs[-2]
        higher_lows = lows[-1] > lows[-2]
        lower_highs = highs[-1] < highs[-2]
        lower_lows = lows[-1] < lows[-2]

        if higher_highs and higher_lows:
            return "BULLISH"
        if lower_highs and lower_lows:
            return "BEARISH"
    return "RANGE"


def detect_valid_break(df: pd.DataFrame, swing_level: float, direction: str) -> Optional[int]:
    for i in range(len(df) - 1, max(0, len(df) - 30), -1):
        row = df.iloc[i]
        body_ratio = _candle_body_ratio(row)
        if body_ratio < MOMENTUM_BODY_RATIO:
            continue
        if direction == "BUY" and row["close"] > swing_level and row["open"] < swing_level:
            return i
        if direction == "SELL" and row["close"] < swing_level and row["open"] > swing_level:
            return i
    return None


def is_pullback_healthy(df: pd.DataFrame, break_index: int) -> bool:
    if break_index >= len(df) - 1:
        return False
    break_candle_range = df["high"].iloc[break_index] - df["low"].iloc[break_index]
    after = df.iloc[break_index + 1:]
    if after.empty or break_candle_range <= 0:
        return False
    avg_pullback_range = (after["high"] - after["low"]).mean()
    return avg_pullback_range < break_candle_range * 0.8


def fibonacci_zone(impulse_low: float, impulse_high: float) -> Dict[str, float]:
    diff = impulse_high - impulse_low
    return {
        "zone_50": impulse_high - diff * FIB_ZONE_LOW,
        "zone_618": impulse_high - diff * FIB_ZONE_HIGH,
        "tp2_extension": impulse_high + diff * abs(FIB_EXTENSION_TP2),
    }


def detect_entry_trigger_candle(df: pd.DataFrame) -> Optional[str]:
    if len(df) < 2:
        return None
    prev, last = df.iloc[-2], df.iloc[-1]

    if last["close"] > last["open"] and prev["close"] < prev["open"]:
        if last["close"] >= prev["open"] and last["open"] <= prev["close"]:
            return "BULLISH_ENGULFING"
    if last["close"] < last["open"] and prev["close"] > prev["open"]:
        if last["close"] <= prev["open"] and last["open"] >= prev["close"]:
            return "BEARISH_ENGULFING"

    rng = last["high"] - last["low"]
    if rng > 0:
        upper_wick = last["high"] - max(last["open"], last["close"])
        lower_wick = min(last["open"], last["close"]) - last["low"]
        if lower_wick > rng * 0.6:
            return "BULLISH_PIN_BAR"
        if upper_wick > rng * 0.6:
            return "BEARISH_PIN_BAR"
    return None


def detect_choch(df_ltf: pd.DataFrame) -> Optional[str]:
    if len(df_ltf) < 20:
        return None
    trend = determine_trend(df_ltf.iloc[-20:])
    prev_trend = determine_trend(df_ltf.iloc[-40:-15]) if len(df_ltf) >= 40 else "RANGE"

    if prev_trend == "BEARISH" and trend == "BULLISH":
        return "CHOCH_BULLISH"
    if prev_trend == "BULLISH" and trend == "BEARISH":
        return "CHOCH_BEARISH"
    return None


class TimeframeStrategyState:
    def __init__(self, timeframe: str):
        self.timeframe = timeframe
        self.phase = "WAITING_STRUCTURE"
        self.direction: Optional[str] = None
        self.broken_level: Optional[float] = None
        self.break_index: Optional[int] = None
        self.fib_zone: Optional[Dict] = None
        self.last_reasons: List[str] = []

    def evaluate(self, df: pd.DataFrame, df_ltf: Optional[pd.DataFrame] = None) -> Dict:
        reasons = []
        if len(df) < SWING_LOOKBACK * 2 + 5:
            return {"phase": "INSUFFICIENT_DATA", "timeframe": self.timeframe, "direction": None,
                    "trade_plan": None, "structure_score": 0, "fib_zone": None,
                    "reasons": ["بيانات غير كافية بعد لهذا الفريم (السيرفر لسه يبني الشموع الحقيقية)"]}

        trend = determine_trend(df)
        swings = find_swing_points(df)

        if trend == "RANGE" or not swings["highs"] or not swings["lows"]:
            self.phase = "WAITING_STRUCTURE"
            reasons.append("السوق بحالة تذبذب (Range) - لا يوجد اتجاه هيكلي واضح بعد")
            return self._result(None, 0, reasons)

        self.direction = "BUY" if trend == "BULLISH" else "SELL"
        key_level_idx = swings["highs"][-1] if self.direction == "BUY" else swings["lows"][-1]
        key_level = df["high"].iloc[key_level_idx] if self.direction == "BUY" else df["low"].iloc[key_level_idx]
        reasons.append(f"اتجاه هيكلي {('صاعد' if self.direction=='BUY' else 'هابط')} محدد على فريم {self.timeframe}")

        sub_df = df.iloc[key_level_idx:].reset_index(drop=True)
        break_idx = detect_valid_break(sub_df, key_level, self.direction)
        if break_idx is None:
            self.phase = "WAITING_STRUCTURE"
            reasons.append("لا يوجد بعد كسر حقيقي (إغلاق جسم + زخم) لآخر قمة/قاع سوينغ")
            return self._result(None, 15, reasons)

        actual_break_idx = key_level_idx + break_idx
        self.phase = "BROKEN"
        self.broken_level = key_level
        self.break_index = actual_break_idx
        reasons.append("✅ تأكد كسر حقيقي بإغلاق الجسم مع شمعة زخم قوية (مو مجرد ذيل/سحب سيولة)")

        impulse_ref = df["low"].iloc[swings["lows"][-1]] if self.direction == "BUY" else df["high"].iloc[swings["highs"][-1]]
        low_bound = min(impulse_ref, key_level)
        high_bound = max(impulse_ref, key_level)
        fib = fibonacci_zone(low_bound, high_bound)
        self.fib_zone = fib

        pullback_ok = is_pullback_healthy(df, actual_break_idx)
        current_price = df["close"].iloc[-1]
        in_discount_zone = (
            fib["zone_618"] <= current_price <= fib["zone_50"] if self.direction == "BUY"
            else fib["zone_50"] <= current_price <= fib["zone_618"]
        )

        if not pullback_ok:
            reasons.append("⚠️ التصحيح الحالي سريع/حاد - يشبه انعكاس اتجاه مو تصحيح صحي، الفكرة معلقة")
            return self._result(None, 25, reasons)

        if not in_discount_zone:
            reasons.append(f"بانتظار وصول السعر لمنطقة الخصم فايبوناتشي (0.50-0.618): {fib['zone_618']:.2f} - {fib['zone_50']:.2f}")
            self.phase = "PULLBACK"
            return self._result(None, 35, reasons)

        reasons.append("✅ السعر داخل منطقة الخصم الذهبية (فايبو 0.50-0.618)")

        trigger = detect_entry_trigger_candle(df)
        choch = detect_choch(df_ltf) if df_ltf is not None else None

        confluence_score = 50
        if trigger:
            confluence_score += 20
            reasons.append(f"✅ تأكيد دخول: {trigger} عند منطقة الفايبو")
        if choch and ((choch == "CHOCH_BULLISH" and self.direction == "BUY") or
                       (choch == "CHOCH_BEARISH" and self.direction == "SELL")):
            confluence_score += 25
            reasons.append("✅ تأكيد إضافي قوي: تغيير طابع الهيكل (CHoCH) على الفريم الأصغر")

        if not trigger and not choch:
            reasons.append("بانتظار شمعة تأكيد (ابتلاعية/Pin Bar) أو CHoCH على فريم أصغر - ما ندخل بدون تأكيد")
            self.phase = "PULLBACK"
            return self._result(None, 40, reasons)

        self.phase = "ENTRY_READY"
        entry = self.broken_level
        pullback_extreme = (
            df["low"].iloc[actual_break_idx:].min() if self.direction == "BUY"
            else df["high"].iloc[actual_break_idx:].max()
        )
        buffer = (df["high"].iloc[-20:].max() - df["low"].iloc[-20:].min()) * 0.05
        sl = pullback_extreme - buffer if self.direction == "BUY" else pullback_extreme + buffer
        tp1 = key_level
        tp2 = fib["tp2_extension"] if self.direction == "BUY" else (2 * low_bound - fib["tp2_extension"] + high_bound - low_bound)

        trade_plan = {
            "direction": self.direction,
            "entry": round(float(entry), 2),
            "sl": round(float(sl), 2),
            "tp1": round(float(tp1), 2),
            "tp2": round(float(tp2), 2),
        }
        return self._result(trade_plan, min(confluence_score, 90), reasons)

    def _result(self, trade_plan: Optional[Dict], score: int, reasons: List[str]) -> Dict:
        self.last_reasons = reasons
        return {
            "timeframe": self.timeframe,
            "phase": self.phase,
            "direction": self.direction,
            "trade_plan": trade_plan,
            "structure_score": score,
            "reasons": reasons,
            "fib_zone": self.fib_zone,
        }


class MultiTimeframeEngine:
    """يطبق الاستراتيجية على كل الفريمات المطلوبة، ويشترط توافق H4/H1 كفلتر أساسي
    قبل ما يعتبر أي إشارة على الفريمات الأصغر صالحة."""

    def __init__(self):
        self.states: Dict[str, TimeframeStrategyState] = {
            tf: TimeframeStrategyState(tf) for tf in ALL_TIMEFRAMES
        }

    def run(self, candles_by_tf: Dict[str, List[Dict]]) -> Dict:
        dfs = {}
        for tf in ALL_TIMEFRAMES:
            raw = candles_by_tf.get(tf, [])
            if raw:
                dfs[tf] = pd.DataFrame(raw)

        h4_trend = determine_trend(dfs["4h"]) if "4h" in dfs and len(dfs["4h"]) > SWING_LOOKBACK * 2 else "RANGE"
        h1_trend = determine_trend(dfs["1h"]) if "1h" in dfs and len(dfs["1h"]) > SWING_LOOKBACK * 2 else "RANGE"
        aligned = h4_trend != "RANGE" and h4_trend == h1_trend

        results = {}
        for tf, df in dfs.items():
            df_ltf = dfs.get("15m") if tf != "15m" else None
            tf_result = self.states[tf].evaluate(df, df_ltf)

            if not aligned and tf_result.get("trade_plan"):
                tf_result["trade_plan"] = None
                tf_result["reasons"].append(
                    "⛔ تم تعليق الدخول: فريم الساعة (H1) وفريم 4 الساعات (H4) غير متوافقين حالياً"
                )
                tf_result["structure_score"] = min(tf_result["structure_score"], 30)

            results[tf] = tf_result

        return {
            "h4_trend": h4_trend,
            "h1_trend": h1_trend,
            "h4_h1_aligned": aligned,
            "timeframes": results,
        }
