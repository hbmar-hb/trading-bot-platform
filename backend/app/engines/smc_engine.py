"""SMC (Smart Money Concepts) context layer.

Complements the ICT engine with:
- Liquidity sweep detection (BSL / SSL)
- Premium / Discount zone position
- Aligned FVG count
- OB distance in ATR multiples

Does NOT duplicate ICT logic — reads ICTResult directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.core.ict_engine import ICTResult


@dataclass
class SMCContext:
    liquidity_sweep: Optional[str]   # 'BSL' | 'SSL' | None
    sweep_level:     Optional[float]
    pd_position:     float            # 0.0 = full discount, 1.0 = full premium
    pd_range:        float            # size of the reference range in price units
    fvg_aligned_count: int            # unfilled FVGs aligned with bias
    ob_distance_atr:   Optional[float]  # distance from price to active OB midpoint in ATR


def analyze_smc(candles: list[dict], ict_result: ICTResult) -> SMCContext:
    """
    Build SMC context from raw candles + ICT result.
    candles: list of {open, high, low, close, volume} dicts (closed candles only).
    """
    df = pd.DataFrame(candles)[["open", "high", "low", "close", "volume"]].astype(float)
    df = df.reset_index(drop=True)

    if len(df) < 14:
        return SMCContext(None, None, 0.5, 0.0, 0, None)

    atr_val = _atr(df, 14)
    last    = df.iloc[-1]

    # ── 1. Liquidity sweep ────────────────────────────────────────────────────
    # BSL sweep: wick breaks above an EQ High, but candle CLOSES back below it
    sweep_type:  Optional[str]   = None
    sweep_level: Optional[float] = None

    for level in ict_result.eq_highs:
        if last["high"] > level and last["close"] < level and last["open"] < level:
            sweep_type  = "BSL"
            sweep_level = level
            break

    if sweep_type is None:
        # SSL sweep: wick breaks below an EQ Low, closes back above
        for level in ict_result.eq_lows:
            if last["low"] < level and last["close"] > level and last["open"] > level:
                sweep_type  = "SSL"
                sweep_level = level
                break

    # ── 2. Premium / Discount ─────────────────────────────────────────────────
    lookback = min(20, len(df))
    hi  = df["high"].iloc[-lookback:].max()
    lo  = df["low"].iloc[-lookback:].min()
    rng = hi - lo
    pd_pos = float((last["close"] - lo) / rng) if rng > 0 else 0.5

    # ── 3. Aligned FVGs (unfilled, same direction as bias) ────────────────────
    direction_kind = "bull" if ict_result.bias == "bull" else "bear"
    aligned_fvgs   = [f for f in ict_result.active_fvgs
                      if f.kind == direction_kind and not f.filled]

    # ── 4. OB distance in ATR multiples ──────────────────────────────────────
    ob_dist: Optional[float] = None
    if ict_result.active_ob and atr_val > 0:
        ob_mid  = (ict_result.active_ob.top + ict_result.active_ob.bottom) / 2
        ob_dist = abs(float(last["close"]) - ob_mid) / atr_val

    return SMCContext(
        liquidity_sweep   = sweep_type,
        sweep_level       = sweep_level,
        pd_position       = pd_pos,
        pd_range          = float(rng),
        fvg_aligned_count = len(aligned_fvgs),
        ob_distance_atr   = ob_dist,
    )


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Public helper — returns last ATR value as float."""
    return _atr(df, period)


def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Return Wilder's ADX value. Returns 25.0 (neutral) when data is insufficient.

    ADX > 25 → trending market; ADX < 25 → ranging / choppy market.
    """
    if len(df) < period * 2 + 1:
        return 25.0

    h, l, c = df["high"], df["low"], df["close"]
    prev_h, prev_l, prev_c = h.shift(1), l.shift(1), c.shift(1)

    # True Range
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)

    # Directional movement (zero out NaN row from shift)
    pdm_raw = np.where((h - prev_h) > (prev_l - l), np.maximum(h - prev_h, 0), 0)
    mdm_raw = np.where((prev_l - l) > (h - prev_h), np.maximum(prev_l - l, 0), 0)
    pdm = pd.Series(pdm_raw, index=df.index, dtype=float)
    mdm = pd.Series(mdm_raw, index=df.index, dtype=float)

    # Wilder smoothing (EWM with alpha = 1/period)
    alpha  = 1.0 / period
    tr_s   = tr.ewm(alpha=alpha, adjust=False).mean()
    pdm_s  = pdm.ewm(alpha=alpha, adjust=False).mean()
    mdm_s  = mdm.ewm(alpha=alpha, adjust=False).mean()

    denom = (pdm_s + mdm_s).replace(0, np.nan)
    dx    = 100 * (pdm_s - mdm_s).abs() / denom
    adx   = dx.ewm(alpha=alpha, adjust=False).mean().dropna()

    return float(adx.iloc[-1]) if not adx.empty else 25.0


# ── Internal ──────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    series = tr.rolling(period).mean()
    valid  = series.dropna()
    return float(valid.iloc[-1]) if not valid.empty else 0.0
