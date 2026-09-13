"""أدوات مساعدة مشتركة لبناء بيانات OHLC اختبارية دقيقة لكل بوابة على حدة."""
import pandas as pd
from app.settings_store import StrategySettings


def loose_settings(**overrides) -> StrategySettings:
    """إعدادات متساهلة (لتسهيل اختبار كل بوابة لحالها بدون قيود صارمة غير ذات صلة)"""
    base = dict(
        equal_level_tolerance_pct=0.1, liquidity_zone_max_age_candles=100,
        sweep_min_pierce_atr_mult=0.1, sweep_confirm_max_candles=3,
        displacement_body_range_ratio=0.3, displacement_body_vs_avg_mult=0.8, displacement_close_edge_pct=0.5,
        fvg_min_gap_pct=0.001, fvg_fill_pct=0.5,
        fib_discount_low=0.5, fib_discount_high=0.9, fib_tp2_extension=0.27,
        swing_confirmation_lookback=3, rr_reject_below=0.01, rr_preferred_above=2.0,
        news_lock_before_min=15, news_lock_after_min=15, max_spread_points=5.0,
        spread_stale_max_minutes=480, block_on_stale_spread=False, setup_dedup_window_minutes=30,
    )
    base.update(overrides)
    return StrategySettings(**base)


def df_from_candles(candles):
    return pd.DataFrame(candles)


def zigzag_candles(pivots, steps=10, start_t=0, tf_sec=3600):
    closes = []
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        for s in range(steps):
            closes.append(a + (b - a) * s / steps)
    closes.append(pivots[-1])
    return [{"time": start_t + i * tf_sec, "open": c - 0.15, "high": c + 0.4, "low": c - 0.4, "close": c + 0.15}
            for i, c in enumerate(closes)]
