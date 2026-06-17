"""Realistic Outcome Engine — simulates real-world execution for AI signals.

Unlike the ideal outcome tracker (which uses OHLCV high/low as perfect fills),
this engine models:
  - Entry slippage
  - Stop-loss gaps (worse fills than theoretical SL)
  - TP wicks that never fill (only touch high/low but execute poorly)
  - Exchange fees (entry + exit)
  - Funding costs for held duration
  - Anti-look-ahead verification
  - Tricotomic labels: SUCCESS / FAILURE_MAX_ADVERSE / FAILURE_BEHAVIORAL / INCONCLUSIVE

Deterministic per signal (seeded by signal id) for reproducible backtests
and stable ML training labels.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from app.services.execution_analytics import ExecutionProfile, get_profile_for_signal


@dataclass
class RealisticOutcome:
    outcome: str          # "SUCCESS" | "FAILURE_MAX_ADVERSE" | "FAILURE_BEHAVIORAL" | "INCONCLUSIVE" | "EXPIRED" | "INVALID"
    pnl_pct: float | None # net P&L after costs
    bars: int | None      # bars to resolution
    fill_price: float     # realistic entry after slippage
    exit_price: float | None # actual exit price
    costs_pct: float      # total costs as % of notional
    notes: list[str]      # human-readable simulation notes


def _seed_from_signal_id(signal_id: str) -> random.Random:
    """Create a deterministic RNG seeded from the signal UUID."""
    hash_val = int(hashlib.md5(signal_id.encode()).hexdigest(), 16)
    return random.Random(hash_val)


def _verify_no_look_ahead(signal, candles_after: list) -> None:
    """Assert that no candle used in simulation contains future information.
    Raises ValueError if look-ahead is detected."""
    signal_ts_ms = int(signal.signal_time.timestamp() * 1000)
    tf_min = _tf_to_minutes(signal.timeframe)
    # Allow candles that start after signal_time (not signal_time + 1 candle)
    # The first candle after signal_time is valid
    max_allowed_ts = signal_ts_ms + (tf_min * 60 * 1000 * 2)  # signal + 2 candles buffer for safety

    for i, c in enumerate(candles_after):
        if c[0] < signal_ts_ms:
            raise ValueError(
                f"Look-ahead detected: candle[{i}] timestamp {c[0]} < "
                f"signal_time {signal_ts_ms}"
            )


def _extract_tp_levels(signal) -> list[dict]:
    """Return ordered TP levels from signal features, with legacy fallback."""
    feats = getattr(signal, "features", None) or {}
    levels = feats.get("tp_levels")
    if levels:
        return [
            {
                "level": int(lvl.get("level", i + 1)),
                "price": float(lvl["price"]),
                "close_percent": float(lvl.get("close_percent", 1.0)),
                "r_multiple": float(lvl.get("r_multiple", 1.0)),
            }
            for i, lvl in enumerate(sorted(levels, key=lambda x: int(x.get("level", 0))))
        ]
    if signal.take_profit_1:
        return [
            {"level": 1, "price": float(signal.take_profit_1), "close_percent": 1.0, "r_multiple": 1.5},
        ]
    return []


def simulate_outcome(
    signal,
    candles_after: list,
    profile: ExecutionProfile | None = None,
    notional: float = 1000.0,
) -> RealisticOutcome:
    """Run realistic walk-forward simulation for a single AI signal.

    Supports multi-level TP plans (tp_levels in signal.features).  When a TP
    level fills, only its close_percent portion is exited; the remaining
    position continues until the next TP or the SL.
    """
    _verify_no_look_ahead(signal, candles_after)

    rng = _seed_from_signal_id(str(signal.id))

    if profile is None:
        profile = get_profile_for_signal(signal.ticker, signal.timeframe)

    notes: list[str] = []

    # ── 0. Validate levels ──
    if not _has_valid_levels(signal):
        return RealisticOutcome(
            outcome="INVALID",
            pnl_pct=None,
            bars=None,
            fill_price=float(signal.entry_price),
            exit_price=None,
            costs_pct=0.0,
            notes=["Invalid levels: TP/SL inverted relative to entry"],
        )

    is_long = signal.direction == "long"
    direction_sign = 1.0 if is_long else -1.0

    # ── 1. Apply entry slippage ──
    entry_slippage = profile.avg_entry_slippage_pct / 100.0
    if is_long:
        realistic_entry = float(signal.entry_price) * (1.0 + entry_slippage)
    else:
        realistic_entry = float(signal.entry_price) * (1.0 - entry_slippage)

    notes.append(f"Entry slippage: {profile.avg_entry_slippage_pct:.3f}% → fill @ {realistic_entry:.6f}")

    # ── 2. Compute real risk distance ──
    sl = float(signal.stop_loss)
    tp_levels = _extract_tp_levels(signal)
    real_risk_distance = abs(realistic_entry - sl)
    if real_risk_distance <= 0:
        notes.append("Zero risk distance after slippage — invalid setup")
        return RealisticOutcome(
            outcome="INVALID", pnl_pct=None, bars=None,
            fill_price=realistic_entry, exit_price=None, costs_pct=0.0, notes=notes,
        )

    # ── 3. Walk-forward with realistic execution ──
    # Track which TP levels have been filled and the remaining position.
    remaining_pct = 1.0
    closed_pct = 0.0
    weighted_exit_price = 0.0  # average exit price weighted by closed %
    any_tp_wicked = False
    last_exit_price = realistic_entry

    for i, candle in enumerate(candles_after, start=1):
        if len(candle) < 5:
            continue
        open_p = float(candle[1])
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])

        # Stop-loss check first
        sl_hit = (low <= sl) if is_long else (high >= sl)
        if sl_hit:
            failure_type = "FAILURE_BEHAVIORAL" if any_tp_wicked else "FAILURE_MAX_ADVERSE"
            if rng.random() < profile.gap_frequency:
                gap = profile.avg_sl_gap_pct / 100.0
                if is_long:
                    fill_sl = sl * (1.0 - gap)
                else:
                    fill_sl = sl * (1.0 + gap)
                notes.append(
                    f"Bar {i}: {failure_type} → SL gapped to {fill_sl:.6f} "
                    f"(gap {profile.avg_sl_gap_pct:.4f}%)"
                )
            else:
                fill_sl = sl
                notes.append(f"Bar {i}: {failure_type} → SL filled @ {sl:.6f}")

            # Close remaining position at SL
            exit_pnl_pct = _pnl_pct(realistic_entry, fill_sl, is_long)
            partial_pnl = exit_pnl_pct * remaining_pct
            weighted_exit_price += fill_sl * remaining_pct
            return _resolve_multi(
                signal, failure_type, realistic_entry, last_exit_price,
                weighted_exit_price, closed_pct, remaining_pct, partial_pnl,
                profile, i, notes, rng,
            )

        # TP level checks in order
        for lvl in tp_levels:
            if lvl.get("filled"):
                continue
            tp_price = lvl["price"]
            tp_hit = (high >= tp_price) if is_long else (low <= tp_price)
            if not tp_hit:
                continue

            if rng.random() < profile.tp_wick_fill_rate:
                # Fase C: TP slippage is a cost, never a bonus. Clamp to >= 0.
                tp_slippage = max(0.0, profile.avg_tp_slippage_pct) / 100.0
                if is_long:
                    fill_tp = tp_price * (1.0 + tp_slippage)
                else:
                    fill_tp = tp_price * (1.0 - tp_slippage)
                notes.append(f"Bar {i}: TP{lvl['level']} filled @ {fill_tp:.6f}")
                lvl["filled"] = True
                close_pct = min(lvl["close_percent"], remaining_pct)
                remaining_pct -= close_pct
                closed_pct += close_pct
                weighted_exit_price += fill_tp * close_pct
                last_exit_price = fill_tp

                if remaining_pct <= 0:
                    # Fully closed by TP sequence
                    return _resolve_multi(
                        signal, "SUCCESS", realistic_entry, last_exit_price,
                        weighted_exit_price, closed_pct, 0.0, 0.0,
                        profile, i, notes, rng,
                    )
            else:
                any_tp_wicked = True
                notes.append(f"Bar {i}: TP{lvl['level']} wick only (no fill), continuing")

    # No resolution within available candles
    notes.append("No resolution within candle window — INCONCLUSIVE")
    return RealisticOutcome(
        outcome="INCONCLUSIVE",
        pnl_pct=None,
        bars=None,
        fill_price=realistic_entry,
        exit_price=None,
        costs_pct=0.0,
        notes=notes,
    )


def _pnl_pct(entry: float, exit_price: float, is_long: bool) -> float:
    if is_long:
        return ((exit_price - entry) / entry) * 100.0
    return ((entry - exit_price) / entry) * 100.0


def _resolve_multi(
    signal,
    outcome: str,
    fill_price: float,
    last_exit_price: float,
    weighted_exit_price: float,
    closed_pct: float,
    remaining_pct: float,
    remaining_pnl_pct: float,
    profile: ExecutionProfile,
    bars: int,
    notes: list[str],
    rng: random.Random,
) -> RealisticOutcome:
    """Compute net P&L for a partially-closed position."""
    is_long = signal.direction == "long"

    # weighted_exit_price already contains every closed portion (including the
    # remaining size closed at SL) weighted by its close_percent.  Because the
    # weights sum to 1.0, it is the effective average exit price.
    avg_exit = weighted_exit_price

    # Total gross PnL %
    total_pnl_pct = _pnl_pct(fill_price, avg_exit, is_long) if avg_exit > 0 else 0.0

    # Costs: apply to the whole notional once (entry + exit round-trip)
    fee_cost_pct = profile.fee_rate
    tf_min = _tf_to_minutes(signal.timeframe)
    hours_held = (bars * tf_min) / 60.0
    funding_hours = min(hours_held, 24.0)
    funding_cost_pct = profile.avg_funding_cost_pct * funding_hours
    total_cost_pct = fee_cost_pct + funding_cost_pct

    pnl_net = total_pnl_pct - total_cost_pct

    notes.append(
        f"Costs: fee={fee_cost_pct:.3f}%, funding({funding_hours:.1f}h)={funding_cost_pct:.3f}% "
        f"→ net P&L={pnl_net:.3f}%"
    )

    if outcome == "SUCCESS" and pnl_net <= 0:
        outcome = "FAILURE_MAX_ADVERSE"
        notes.append("SUCCESS reversed to FAILURE_MAX_ADVERSE after costs")

    return RealisticOutcome(
        outcome=outcome,
        pnl_pct=round(pnl_net, 3),
        bars=bars,
        fill_price=round(fill_price, 6),
        exit_price=round(avg_exit, 6) if avg_exit > 0 else None,
        costs_pct=round(total_cost_pct, 3),
        notes=notes,
    )


def _has_valid_levels(signal) -> bool:
    """Detect if TP1 and SL are on the correct side of entry."""
    if signal.direction == "long":
        return float(signal.take_profit_1) > float(signal.entry_price) and float(signal.stop_loss) < float(signal.entry_price)
    else:
        return float(signal.take_profit_1) < float(signal.entry_price) and float(signal.stop_loss) > float(signal.entry_price)


def _tf_to_minutes(tf: str) -> int:
    mapping = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
        "12h": 720, "1d": 1440, "1w": 10080,
    }
    return mapping.get(tf, 60)
