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


def simulate_outcome(
    signal,
    candles_after: list,
    profile: ExecutionProfile | None = None,
    notional: float = 1000.0,
) -> RealisticOutcome:
    """Run realistic walk-forward simulation for a single AI signal.

    Args:
        signal: AISignal instance (or duck-typed object with required attrs)
        candles_after: list of OHLCV candles after signal_time (same format as tracker)
        profile: ExecutionProfile to use. If None, fetched from analytics service.
        notional: assumed position notional in USDT for cost calculation.

    Returns:
        RealisticOutcome with net P&L and resolution details.
    """
    # Anti-look-ahead verification
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
    # Slippage always makes entry worse
    if is_long:
        realistic_entry = float(signal.entry_price) * (1.0 + entry_slippage)
    else:
        realistic_entry = float(signal.entry_price) * (1.0 - entry_slippage)

    notes.append(f"Entry slippage: {profile.avg_entry_slippage_pct:.3f}% → fill @ {realistic_entry:.6f}")

    # ── 2. Compute real risk distance ──
    sl = float(signal.stop_loss)
    tp1 = float(signal.take_profit_1)
    real_risk_distance = abs(realistic_entry - sl)
    if real_risk_distance <= 0:
        notes.append("Zero risk distance after slippage — invalid setup")
        return RealisticOutcome(
            outcome="INVALID", pnl_pct=None, bars=None,
            fill_price=realistic_entry, exit_price=None, costs_pct=0.0, notes=notes,
        )

    # ── 3. Walk-forward with realistic execution ──
    tp_wicked = False  # Tracks if TP was touched but not filled (wick)

    for i, candle in enumerate(candles_after, start=1):
        # candle format: [timestamp, open, high, low, close, volume, ...]
        if len(candle) < 5:
            continue
        open_p = float(candle[1])
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])

        candle_range = high - low if high != low else 1e-9

        # Determine if TP and/or SL were touched in this candle
        if is_long:
            tp_hit = high >= tp1
            sl_hit = low <= sl
        else:
            tp_hit = low <= tp1
            sl_hit = high >= sl

        if tp_hit and sl_hit:
            # Both touched — realistic probabilistic tie-breaker
            tp_sl_spread = abs(tp1 - sl)
            volatility_factor = min(1.0, candle_range / max(tp_sl_spread, 1e-9))

            if is_long:
                dist_to_tp = abs(high - tp1)
                dist_to_sl = abs(low - sl)
            else:
                dist_to_tp = abs(tp1 - low)
                dist_to_sl = abs(sl - high)

            total_dist = dist_to_tp + dist_to_sl + 1e-9
            tp_prob = 1.0 - (dist_to_tp / total_dist)
            tp_prob = tp_prob * (1.0 - volatility_factor * 0.3) + 0.5 * volatility_factor * 0.3

            outcome = "SUCCESS" if rng.random() < tp_prob else "FAILURE_MAX_ADVERSE"
            ref = tp1 if outcome == "SUCCESS" else sl
            notes.append(
                f"Bar {i}: both TP and SL touched (vol_factor={volatility_factor:.2f}, "
                f"tp_prob={tp_prob:.2f}) → {outcome}"
            )
            return _resolve(signal, outcome, ref, i, realistic_entry, profile, notional, notes, rng)

        elif tp_hit:
            # TP touched — but was it a wick or a real fill?
            if rng.random() < profile.tp_wick_fill_rate:
                # TP filled with slippage
                tp_slippage = profile.avg_tp_slippage_pct / 100.0
                if is_long:
                    fill_tp = tp1 * (1.0 + tp_slippage)
                else:
                    fill_tp = tp1 * (1.0 - tp_slippage)
                notes.append(f"Bar {i}: TP filled @ {fill_tp:.6f} (slippage {profile.avg_tp_slippage_pct:.4f}%)")
                return _resolve(signal, "SUCCESS", fill_tp, i, realistic_entry, profile, notional, notes, rng)
            else:
                # Wick only — mark and continue
                tp_wicked = True
                notes.append(f"Bar {i}: TP wick only (no fill), continuing")
                continue

        elif sl_hit:
            # SL touched — did it gap?
            failure_type = "FAILURE_BEHAVIORAL" if tp_wicked else "FAILURE_MAX_ADVERSE"
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
                return _resolve(signal, failure_type, fill_sl, i, realistic_entry, profile, notional, notes, rng)
            else:
                notes.append(f"Bar {i}: {failure_type} → SL filled @ {sl:.6f}")
                return _resolve(signal, failure_type, sl, i, realistic_entry, profile, notional, notes, rng)

        else:
            continue

    # No resolution within available candles (not yet expired by time)
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


def _resolve(
    signal,
    outcome: str,
    exit_price: float,
    bars: int,
    fill_price: float,
    profile: ExecutionProfile,
    notional: float,
    notes: list[str],
    rng: random.Random,
) -> RealisticOutcome:
    """Compute net P&L after applying all costs."""
    is_long = signal.direction == "long"
    entry = fill_price

    # Gross P&L in price terms
    if is_long:
        price_pnl = exit_price - entry
    else:
        price_pnl = entry - exit_price

    # Convert to % of notional
    pnl_pct_raw = (price_pnl / entry) * 100.0

    # ── Costs ──
    # Fee: entry + exit (round trip)
    fee_cost_pct = profile.fee_rate * 100.0 * 2.0  # entry + exit

    # Funding: approximate based on bars held
    tf_min = _tf_to_minutes(signal.timeframe)
    hours_held = (bars * tf_min) / 60.0
    funding_hours = min(hours_held, 24.0)
    funding_cost_pct = profile.avg_funding_cost_pct * funding_hours

    total_cost_pct = fee_cost_pct + funding_cost_pct
    pnl_net = pnl_pct_raw - total_cost_pct

    notes.append(
        f"Costs: fee={fee_cost_pct:.3f}%, funding({funding_hours:.1f}h)={funding_cost_pct:.3f}% "
        f"→ net P&L={pnl_net:.3f}%"
    )

    # Final outcome check: even if TP "touched", after costs it might be a loss
    if outcome == "SUCCESS" and pnl_net <= 0:
        outcome = "FAILURE_MAX_ADVERSE"
        notes.append("SUCCESS reversed to FAILURE_MAX_ADVERSE after costs")

    return RealisticOutcome(
        outcome=outcome,
        pnl_pct=round(pnl_net, 3),
        bars=bars,
        fill_price=round(fill_price, 6),
        exit_price=round(exit_price, 6),
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
