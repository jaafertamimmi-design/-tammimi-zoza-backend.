"""
محمّل إعدادات الاستراتيجية - كل الأرقام اللي كانت بالنسخة السابقة مدفونة بالكود
صارت الحين مخزنة بقاعدة البيانات وقابلة للتعديل من لوحة الأدمن بدون لمس الكود.
"""
from dataclasses import dataclass
from sqlalchemy.orm import Session

from .models import StrategySettingsDB


@dataclass
class StrategySettings:
    equal_level_tolerance_pct: float
    liquidity_zone_max_age_candles: int
    sweep_min_pierce_atr_mult: float
    sweep_confirm_max_candles: int
    displacement_body_range_ratio: float
    displacement_body_vs_avg_mult: float
    displacement_close_edge_pct: float
    fvg_min_gap_pct: float
    fvg_fill_pct: float
    fib_discount_low: float
    fib_discount_high: float
    fib_tp2_extension: float
    swing_confirmation_lookback: int
    rr_reject_below: float
    rr_preferred_above: float
    news_lock_before_min: int
    news_lock_after_min: int
    max_spread_points: float
    spread_stale_max_minutes: int
    block_on_stale_spread: bool
    setup_dedup_window_minutes: int


def get_or_create_settings_row(db: Session) -> StrategySettingsDB:
    row = db.query(StrategySettingsDB).filter(StrategySettingsDB.id == 1).first()
    if not row:
        row = StrategySettingsDB(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def load_settings(db: Session) -> StrategySettings:
    row = get_or_create_settings_row(db)
    return StrategySettings(
        equal_level_tolerance_pct=row.equal_level_tolerance_pct,
        liquidity_zone_max_age_candles=row.liquidity_zone_max_age_candles,
        sweep_min_pierce_atr_mult=row.sweep_min_pierce_atr_mult,
        sweep_confirm_max_candles=row.sweep_confirm_max_candles,
        displacement_body_range_ratio=row.displacement_body_range_ratio,
        displacement_body_vs_avg_mult=row.displacement_body_vs_avg_mult,
        displacement_close_edge_pct=row.displacement_close_edge_pct,
        fvg_min_gap_pct=row.fvg_min_gap_pct,
        fvg_fill_pct=row.fvg_fill_pct,
        fib_discount_low=row.fib_discount_low,
        fib_discount_high=row.fib_discount_high,
        fib_tp2_extension=row.fib_tp2_extension,
        swing_confirmation_lookback=row.swing_confirmation_lookback,
        rr_reject_below=row.rr_reject_below,
        rr_preferred_above=row.rr_preferred_above,
        news_lock_before_min=row.news_lock_before_min,
        news_lock_after_min=row.news_lock_after_min,
        max_spread_points=row.max_spread_points,
        spread_stale_max_minutes=row.spread_stale_max_minutes,
        block_on_stale_spread=row.block_on_stale_spread,
        setup_dedup_window_minutes=row.setup_dedup_window_minutes,
    )
