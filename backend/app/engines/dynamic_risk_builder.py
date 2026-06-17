"""Dynamic SL/TP builder — computes confluence-aware entry levels.

The goal is to guarantee a realistic minimum R-ratio for every signal while
using the actual ICT+SMC structure (OB, FVG, EQ, swing points) for
invalidation and take-profit placement.  Higher confluence scores get tighter
stops and wider profit targets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger

# Default risk/reward guardrails.  These can be overridden per-bot via
# ai_signal_config or by passing explicit parameters.
_DEFAULT_MIN_R = 1.2
_DEFAULT_TP2_R = 1.8
_DEFAULT_TP3_R = 2.5
_DEFAULT_MAX_SL_PCT = 0.02
_DEFAULT_MIN_SL_PCT = 0.003

# ATR buffer added below structural invalidation levels.
# Higher score = more confidence = smaller buffer.
_SCORE_BUFFER_MULT = {
    (75, 100): 0.5,
    (60, 75): 1.0,
    (0, 60): 1.5,
}

# TP close splits by confluence score.
_CLOSE_SPLITS = {
    (75, 100): [0.35, 0.35, 0.30],
    (55, 75): [0.50, 0.30, 0.20],
    (0, 55): [0.65, 0.25, 0.10],
}


@dataclass
class TPLevel:
    level: int
    price: float
    close_percent: float
    r_multiple: float
    kind: str


@dataclass
class DynamicRiskPlan:
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: Optional[float]
    tp_levels: List[TPLevel] = field(default_factory=list)
    risk_reward: float = 0.0
    sl_basis: str = ""
    tp1_basis: str = ""
    risk_distance: float = 0.0
    risk_pct: float = 0.0


def _buffer_mult(score: float) -> float:
    for (lo, hi), mult in _SCORE_BUFFER_MULT.items():
        if lo <= score <= hi:
            return mult
    return 1.0


def _close_splits(score: float) -> List[float]:
    for (lo, hi), splits in _CLOSE_SPLITS.items():
        if lo <= score <= hi:
            return splits
    return [0.65, 0.25, 0.10]


def _format_basis(kind: str, fallback: str) -> str:
    return kind if kind else fallback


def build_levels(
    entry_mid: float,
    direction: str,
    score: float,
    quality_tier: Optional[str],
    ict,
    atr_value: float,
    timeframe: str = "15m",
    min_r: float = _DEFAULT_MIN_R,
    tp2_r: float = _DEFAULT_TP2_R,
    tp3_r: float = _DEFAULT_TP3_R,
    max_sl_pct: float = _DEFAULT_MAX_SL_PCT,
    min_sl_pct: float = _DEFAULT_MIN_SL_PCT,
) -> DynamicRiskPlan:
    """Build a confluence-aware SL/TP plan.

    Args:
        entry_mid: reference entry price.
        direction: 'long' or 'short'.
        score: confluence score (0-100).
        quality_tier: STRONG/MODERATE/WEAK.
        ict: ICTResult from app.core.ict_engine (active_ob, active_fvgs, etc.).
        atr_value: current ATR value.
        timeframe: used only for logging / future time-based rules.
        min_r: minimum acceptable R for TP1 (default 1.2).
        tp2_r: minimum R for TP2 (default 1.8).
        tp3_r: minimum R for TP3 (default 2.5).
        max_sl_pct: maximum allowed SL distance from entry.
        min_sl_pct: minimum allowed SL distance from entry.

    Returns:
        DynamicRiskPlan with SL, TP1/2/3, risk/reward and metadata.
    """
    if entry_mid <= 0:
        raise ValueError("entry_mid must be positive")

    is_long = direction == "long"
    buffer_mult = _buffer_mult(score)

    # ── 1. Structural stop-loss candidates ───────────────────────────────────
    sl_candidates: List[tuple[float, str]] = []

    if is_long:
        # Active bullish OB below entry
        if ict.active_ob and ict.active_ob.kind == "bull" and ict.active_ob.bottom < entry_mid:
            sl_candidates.append((ict.active_ob.bottom, "active_ob"))
        # Bullish FVGs below entry
        for fvg in ict.active_fvgs:
            if fvg.kind == "bull" and not fvg.filled and fvg.bottom < entry_mid:
                sl_candidates.append((fvg.bottom, "fvg_bull"))
        # Last swing low
        if ict.last_swing_low and ict.last_swing_low.price < entry_mid:
            sl_candidates.append((ict.last_swing_low.price, "swing_low"))
        # EQ lows
        for lvl in ict.eq_lows:
            if lvl < entry_mid:
                sl_candidates.append((lvl, "eq_low"))
        # Support levels behind price
        for lvl in ict.support_levels:
            if lvl.price < entry_mid:
                sl_candidates.append((lvl.price, lvl.kind))
    else:
        # Active bearish OB above entry
        if ict.active_ob and ict.active_ob.kind == "bear" and ict.active_ob.top > entry_mid:
            sl_candidates.append((ict.active_ob.top, "active_ob"))
        # Bearish FVGs above entry
        for fvg in ict.active_fvgs:
            if fvg.kind == "bear" and not fvg.filled and fvg.top > entry_mid:
                sl_candidates.append((fvg.top, "fvg_bear"))
        # Last swing high
        if ict.last_swing_high and ict.last_swing_high.price > entry_mid:
            sl_candidates.append((ict.last_swing_high.price, "swing_high"))
        # EQ highs
        for lvl in ict.eq_highs:
            if lvl > entry_mid:
                sl_candidates.append((lvl, "eq_high"))
        # Resistance levels behind price
        for lvl in ict.support_levels:
            # support_levels in ICTResult are structural lows below entry for both sides
            if lvl.price < entry_mid:
                sl_candidates.append((lvl.price, lvl.kind))

    # ── 2. ATR-based invalidation buffer ─────────────────────────────────────
    # If we have structural candidates, put the SL slightly beyond the closest
    # one. If not, fall back to a pure ATR-based SL.
    atr_buffer = atr_value * buffer_mult if atr_value > 0 else entry_mid * 0.005

    if is_long:
        if sl_candidates:
            raw_sl = max(p for p, _ in sl_candidates)
            sl = raw_sl - atr_buffer
            sl_basis = max(_format_basis(k, "structure") for p, k in sl_candidates if p == raw_sl)
        else:
            sl = entry_mid - atr_buffer
            sl_basis = "atr_fallback"
    else:
        if sl_candidates:
            raw_sl = min(p for p, _ in sl_candidates)
            sl = raw_sl + atr_buffer
            sl_basis = max(_format_basis(k, "structure") for p, k in sl_candidates if p == raw_sl)
        else:
            sl = entry_mid + atr_buffer
            sl_basis = "atr_fallback"

    # ── 3. Clamp SL to allowed risk range ────────────────────────────────────
    risk_distance = abs(entry_mid - sl)
    risk_pct = risk_distance / entry_mid if entry_mid > 0 else 0.0

    if risk_pct > max_sl_pct:
        if is_long:
            sl = entry_mid * (1.0 - max_sl_pct)
        else:
            sl = entry_mid * (1.0 + max_sl_pct)
        sl_basis = f"{sl_basis}_clamped_max"
        risk_distance = abs(entry_mid - sl)
        risk_pct = risk_distance / entry_mid
    elif risk_pct < min_sl_pct:
        if is_long:
            sl = entry_mid * (1.0 - min_sl_pct)
        else:
            sl = entry_mid * (1.0 + min_sl_pct)
        sl_basis = f"{sl_basis}_clamped_min"
        risk_distance = abs(entry_mid - sl)
        risk_pct = risk_distance / entry_mid

    # ── 4. Take-profit levels from forward structure ─────────────────────────
    # Forward levels are already sorted by (strength DESC, distance ASC).  We
    # re-sort by distance and pick the first one that satisfies min R.
    forward = sorted(
        [lvl for lvl in ict.forward_levels if lvl.distance_pct > 0],
        key=lambda x: x.distance_pct,
    )

    def _r_for(price: float) -> float:
        return (abs(price - entry_mid) / risk_distance) if risk_distance > 0 else 0.0

    tp1_price: Optional[float] = None
    tp1_basis = "fallback_minR"
    for lvl in forward:
        r = _r_for(lvl.price)
        if r >= min_r:
            tp1_price = lvl.price
            tp1_basis = _format_basis(lvl.kind, "forward")
            break

    if tp1_price is None:
        tp1_price = entry_mid + risk_distance * min_r if is_long else entry_mid - risk_distance * min_r

    # TP2 / TP3: next structural levels satisfying higher R targets
    tp2_price: Optional[float] = None
    tp2_basis = "fallback"
    tp3_price: Optional[float] = None
    tp3_basis = "fallback"

    used_for_tp1 = {tp1_price}
    for lvl in forward:
        if lvl.price in used_for_tp1:
            continue
        r = _r_for(lvl.price)
        if tp2_price is None and r >= tp2_r:
            tp2_price = lvl.price
            tp2_basis = _format_basis(lvl.kind, "forward")
            used_for_tp1.add(lvl.price)
            continue
        if tp2_price is not None and tp3_price is None and r >= tp3_r:
            tp3_price = lvl.price
            tp3_basis = _format_basis(lvl.kind, "forward")
            used_for_tp1.add(lvl.price)
            break

    if tp2_price is None:
        tp2_price = entry_mid + risk_distance * tp2_r if is_long else entry_mid - risk_distance * tp2_r
    if tp3_price is None:
        tp3_price = entry_mid + risk_distance * tp3_r if is_long else entry_mid - risk_distance * tp3_r

    # Ensure ordering: TP1 < TP2 < TP3 for long, reverse for short
    if is_long:
        if tp2_price <= tp1_price:
            tp2_price = tp1_price + risk_distance * 0.5
            tp2_basis = "fallback_order"
        if tp3_price <= tp2_price:
            tp3_price = tp2_price + risk_distance * 0.5
            tp3_basis = "fallback_order"
    else:
        if tp2_price >= tp1_price:
            tp2_price = tp1_price - risk_distance * 0.5
            tp2_basis = "fallback_order"
        if tp3_price >= tp2_price:
            tp3_price = tp2_price - risk_distance * 0.5
            tp3_basis = "fallback_order"

    # ── 5. Build TP levels with adaptive close splits ────────────────────────
    splits = _close_splits(score)
    tp_prices = [tp1_price, tp2_price, tp3_price]
    tp_basis = [tp1_basis, tp2_basis, tp3_basis]
    tp_levels: List[TPLevel] = []
    for i, (price, basis) in enumerate(zip(tp_prices, tp_basis)):
        r = _r_for(price)
        tp_levels.append(TPLevel(
            level=i + 1,
            price=price,
            close_percent=splits[i],
            r_multiple=round(r, 3),
            kind=basis,
        ))

    rr = _r_for(tp1_price)

    logger.debug(
        f"[DYNAMIC_RISK] {direction} entry={entry_mid:.6f} score={score:.1f} "
        f"SL={sl:.6f} ({sl_basis}) R={rr:.2f} "
        f"TPs={[tp.price for tp in tp_levels]}"
    )

    return DynamicRiskPlan(
        stop_loss=sl,
        take_profit_1=tp1_price,
        take_profit_2=tp2_price,
        take_profit_3=tp3_price,
        tp_levels=tp_levels,
        risk_reward=round(rr, 3),
        sl_basis=sl_basis,
        tp1_basis=tp1_basis,
        risk_distance=risk_distance,
        risk_pct=round(risk_pct, 6),
    )
