"""Expectancy-Based Optimization — optimize for E instead of WR.

Expectancy formula:
  E = (WinRate × AvgWin) - (LossRate × AvgLoss)

In R-multiple terms:
  E = (WR × AvgWinR) - ((1-WR) × AvgLossR)

Key insight: a system with 40% WR but 3R avg win and 1R avg loss
has E = +0.6R per trade — excellent. A system with 60% WR but
1R avg win and 1.5R avg loss has E = 0 — breakeven.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class ExpectancyResult:
    bucket: str
    total: int
    wins: int
    losses: int
    win_rate: float
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None
    profit_factor: float | None
    r_multiple_avg: float | None


def compute_expectancy_by_bucket(
    signals: list,
    key_fn,
) -> dict[str, ExpectancyResult]:
    """Compute expectancy metrics for each bucket defined by key_fn.

    Args:
        signals: list of signal objects with .outcome, .realistic_pnl_pct or .pnl_pct
        key_fn: function(signal) -> bucket_key

    Returns:
        dict mapping bucket_key -> ExpectancyResult
    """
    from collections import defaultdict

    buckets: dict[str, list] = defaultdict(list)
    for s in signals:
        k = key_fn(s)
        if k:
            buckets[k].append(s)

    results: dict[str, ExpectancyResult] = {}
    for bucket, trades in buckets.items():
        if len(trades) < 3:
            continue

        wins = [t for t in trades if getattr(t, "outcome", None) == "SUCCESS"]
        losses = [t for t in trades if getattr(t, "outcome", None) in ("FAILURE", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")]

        win_rate = len(wins) / len(trades)

        # Use realistic_pnl_pct if available, fallback to pnl_pct
        win_pnls = [
            float(getattr(t, "realistic_pnl_pct", None) or getattr(t, "pnl_pct", 0) or 0)
            for t in wins
        ]
        loss_pnls = [
            float(getattr(t, "realistic_pnl_pct", None) or getattr(t, "pnl_pct", 0) or 0)
            for t in losses
        ]

        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else None
        avg_loss = abs(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else None

        # Expectancy = (WR × AvgWin) - (LR × AvgLoss)
        if avg_win is not None and avg_loss is not None and avg_loss > 0:
            loss_rate = 1.0 - win_rate
            expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
            profit_factor = (win_rate * avg_win) / (loss_rate * avg_loss) if loss_rate > 0 else float("inf")
        else:
            expectancy = None
            profit_factor = None

        # R-multiple average: if we have risk distance info, normalize by risk
        # Fallback: use pnl_pct as proxy for R-multiple (1% ≈ 1R)
        all_pnls = win_pnls + [-abs(x) for x in loss_pnls]
        r_multiple_avg = sum(all_pnls) / len(all_pnls) if all_pnls else None

        results[bucket] = ExpectancyResult(
            bucket=bucket,
            total=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=round(win_rate * 100, 1),
            avg_win=round(avg_win, 4) if avg_win is not None else None,
            avg_loss=round(avg_loss, 4) if avg_loss is not None else None,
            expectancy=round(expectancy, 4) if expectancy is not None else None,
            profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
            r_multiple_avg=round(r_multiple_avg, 4) if r_multiple_avg is not None else None,
        )

    return results


def recommend_config_by_expectancy(
    tier_results: dict[str, ExpectancyResult],
    status_results: dict[str, ExpectancyResult],
    ts_results: dict[str, ExpectancyResult],
) -> dict[str, Any]:
    """Generate config recommendations based on expectancy, not just WR.

    Returns:
        {
            "allowed_tiers": ["STRONG", ...],
            "allowed_statuses": ["CLEAR", ...],
            "tier_expectancy": {...},
            "status_expectancy": {...},
            "best_combination": {"tier": ..., "status": ..., "expectancy": ...},
        }
    """
    # Tiers with positive expectancy and ≥5 trades
    allowed_tiers = []
    for tier, res in sorted(tier_results.items(), key=lambda x: (x[1].expectancy or -999), reverse=True):
        if res.expectancy is not None and res.expectancy > 0 and res.total >= 5:
            allowed_tiers.append(tier)
        elif res.total >= 5:
            # Include if WR >= 40% even if E is slightly negative (thin data)
            if res.win_rate >= 40:
                allowed_tiers.append(tier)

    if not allowed_tiers:
        allowed_tiers = ["STRONG", "MODERATE", "WEAK"]

    # Statuses with positive expectancy
    allowed_statuses = []
    for status, res in sorted(status_results.items(), key=lambda x: (x[1].expectancy or -999), reverse=True):
        if res.expectancy is not None and res.expectancy > 0 and res.total >= 5:
            allowed_statuses.append(status)
        elif res.total >= 5 and res.win_rate >= 40:
            allowed_statuses.append(status)

    if not allowed_statuses:
        allowed_statuses = ["CLEAR", "CAUTION"]

    # Best tier+status combination
    best_ts = None
    best_e = -999.0
    for ts, res in ts_results.items():
        if res.expectancy is not None and res.expectancy > best_e and res.total >= 5:
            best_e = res.expectancy
            best_ts = ts

    best_parsed = None
    if best_ts:
        parts = best_ts.split("|")
        if len(parts) == 2:
            best_parsed = {"tier": parts[0], "status": parts[1], "expectancy": best_e}

    return {
        "allowed_tiers": allowed_tiers,
        "allowed_statuses": allowed_statuses,
        "tier_expectancy": {k: v.expectancy for k, v in tier_results.items()},
        "status_expectancy": {k: v.expectancy for k, v in status_results.items()},
        "best_combination": best_parsed,
    }
