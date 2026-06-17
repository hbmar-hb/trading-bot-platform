"""Slippage Predictor — estimates pre-execution slippage to avoid bad fills.

Uses available market data + execution analytics profile.
If estimated slippage > 50% of risk distance → abort or reduce sizing.

Hierarchy: L3 Execution — prevents trades where execution costs eat the edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger

from app.services.execution_analytics import get_profile_for_signal


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3A: Recalibración automática del slippage predictor
# ═══════════════════════════════════════════════════════════════════════════════

_SLIPPAGE_CORRECTION_KEY = "slippage_predictor:correction_factor"
_SLIPPAGE_CORRECTION_DEFAULT = 1.0


def get_slippage_correction_factor() -> float:
    """Return the global correction factor from Redis.
    
    If the predictor consistently over-estimates slippage by 2×,
    the correction factor will be ~0.5, bringing estimates closer to reality.
    """
    try:
        from app.services.cache import sync_redis
        raw = sync_redis.get(_SLIPPAGE_CORRECTION_KEY)
        if raw:
            factor = float(raw)
            # Sanity bounds: never go below 0.2 or above 3.0
            return max(0.2, min(3.0, factor))
    except Exception as e:
        logger.debug(f"[SLIPPAGE] Could not read correction factor: {e}")
    return _SLIPPAGE_CORRECTION_DEFAULT


def set_slippage_correction_factor(factor: float) -> None:
    """Persist correction factor to Redis with 24h TTL."""
    try:
        from app.services.cache import sync_redis
        bounded = max(0.2, min(3.0, factor))
        sync_redis.set(_SLIPPAGE_CORRECTION_KEY, str(bounded), ex=86400)
        logger.info(f"[SLIPPAGE] Correction factor updated to {bounded:.3f}")
    except Exception as e:
        logger.warning(f"[SLIPPAGE] Could not save correction factor: {e}")


@dataclass(frozen=True)
class SlippageEstimate:
    slippage_pct: float
    risk_distance_pct: float
    slippage_vs_risk_ratio: float
    action: str  # "proceed" | "reduce_70" | "abort"
    reason: str


# Thresholds
_ABORT_RATIO = 0.65   # slippage > 65% of risk distance → abort
_REDUCE_RATIO = 0.40  # slippage > 40% of risk distance → reduce 70%


def _time_since_funding_ms(symbol: str) -> float:
    """Return hours since last funding settlement."""
    try:
        from app.services.macro_context import fetch_funding_rate
        funding = fetch_funding_rate(symbol)
        funding_time_str = funding.get("funding_time")
        if funding_time_str:
            ft = datetime.fromisoformat(funding_time_str)
            if ft.tzinfo is None:
                ft = ft.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - ft).total_seconds() / 3600.0
    except Exception:
        pass
    return 0.0


def estimate_slippage(
    symbol: str,
    direction: str,
    notional: float,
    entry_price: float,
    stop_loss: float,
    atr_value: float | None = None,
    volume_1h: float | None = None,
    volume_avg_20h: float | None = None,
    user_cfg: dict | None = None,
) -> SlippageEstimate:
    """Estimate expected slippage for a trade.

    Args:
        symbol: CCXT symbol (e.g. "BTC/USDT:USDT")
        direction: "long" or "short"
        notional: intended position notional in USDT
        entry_price: signal entry price
        stop_loss: signal stop loss
        atr_value: current ATR (optional)
        volume_1h: last 1h volume (optional)
        volume_avg_20h: average volume last 20h (optional)

    Returns:
        SlippageEstimate with action recommendation.
    """
    # Base slippage from execution analytics profile
    profile = get_profile_for_signal(symbol, "1h")  # use 1h as generic fallback
    base_slippage = profile.avg_entry_slippage_pct

    # Risk distance in %
    risk_distance = abs(entry_price - stop_loss)
    risk_distance_pct = (risk_distance / entry_price) * 100.0 if entry_price > 0 else 1.0

    # ATR adjustment: higher ATR → higher slippage
    atr_factor = 1.0
    if atr_value and entry_price > 0:
        atr_pct = (atr_value / entry_price) * 100.0
        # If ATR > 1% of price, slippage increases
        atr_factor = 1.0 + max(0, (atr_pct - 0.5)) * 0.5

    # Volume adjustment: low relative volume → higher slippage
    volume_factor = 1.0
    if volume_1h and volume_avg_20h and volume_avg_20h > 0:
        rel_vol = volume_1h / volume_avg_20h
        if rel_vol < 0.5:
            volume_factor = 1.5
        elif rel_vol < 1.0:
            volume_factor = 1.2
        elif rel_vol > 2.0:
            volume_factor = 0.8

    # Time since funding adjustment: high volatility 0-2h post-funding
    funding_factor = 1.0
    try:
        hours_since = _time_since_funding_ms(symbol)
        if hours_since < 2.0:
            funding_factor = 1.3
        elif hours_since < 4.0:
            funding_factor = 1.1
    except Exception:
        pass

    # Notional size adjustment: larger positions → higher slippage
    size_factor = 1.0
    if notional > 10000:
        size_factor = 1.2
    elif notional > 5000:
        size_factor = 1.1

    # FASE 3A: Apply learned correction factor from historical execution quality
    correction_factor = get_slippage_correction_factor()

    estimated_slippage = (
        base_slippage * atr_factor * volume_factor * funding_factor * size_factor * correction_factor
    )

    ratio = estimated_slippage / risk_distance_pct if risk_distance_pct > 0 else 0.0

    mult = float(user_cfg.get("slippage_abort_ratio_multiplier", 1.0)) if user_cfg else 1.0
    abort_th = _ABORT_RATIO * mult
    reduce_th = _REDUCE_RATIO * mult

    if ratio > abort_th:
        action = "abort"
        reason = (
            f"slippage {estimated_slippage:.3f}% > {abort_th:.0%} of risk "
            f"{risk_distance_pct:.3f}% (ratio={ratio:.2f}, mult={mult:.2f})"
        )
    elif ratio > reduce_th:
        action = "reduce_70"
        reason = (
            f"slippage {estimated_slippage:.3f}% > {reduce_th:.0%} of risk "
            f"{risk_distance_pct:.3f}% (ratio={ratio:.2f}, mult={mult:.2f})"
        )
    else:
        action = "proceed"
        reason = f"slippage {estimated_slippage:.3f}% vs risk {risk_distance_pct:.3f}% (ratio={ratio:.2f})"

    logger.debug(
        f"[SLIPPAGE] {symbol} {direction}: est={estimated_slippage:.3f}% "
        f"base={base_slippage:.3f} atr={atr_factor:.2f} vol={volume_factor:.2f} "
        f"funding={funding_factor:.2f} size={size_factor:.2f} → {action}"
    )

    return SlippageEstimate(
        slippage_pct=round(estimated_slippage, 4),
        risk_distance_pct=round(risk_distance_pct, 4),
        slippage_vs_risk_ratio=round(ratio, 4),
        action=action,
        reason=reason,
    )
