"""P&L Attribution Module — breaks down performance by system component.

Dimensions:
  - quality_tier (STRONG/MODERATE/WEAK)
  - anti_fake_status (CLEAR/CAUTION/BLOCK)
  - market_regime (TRENDING_BULL/TRENDING_BEAR/RANGING/VOLATILE_SPIKE/etc.)
  - direction (long/short)
  - timeframe (15m/1h/4h/1d)
  - symbol
  - bot_id

Metrics per dimension:
  - total_pnl, avg_pnl, win_rate, profit_factor
  - count, wins, losses
"""
from __future__ import annotations

from typing import Any


DIMENSION_FIELDS = {
    "quality_tier": ["extra_config", "quality_tier"],
    "anti_fake_status": ["extra_config", "anti_fake_status"],
    "market_regime": ["extra_config", "market_regime"],
    "direction": ["side"],
    "timeframe": ["extra_config", "timeframe"],
    "symbol": ["symbol"],
    "bot_id": ["bot_id"],
}


def _get_dim_value(pos, dim: str) -> str | None:
    """Extract dimension value from a Position."""
    path = DIMENSION_FIELDS.get(dim)
    if not path:
        return None
    if path[0] == "extra_config":
        val = (pos.extra_config or {}).get(path[1])
        return str(val) if val is not None else "unknown"
    return str(getattr(pos, path[0], "unknown"))


def _compute_metrics(trades: list) -> dict[str, Any]:
    """Compute aggregate metrics for a list of closed trades."""
    if not trades:
        return {
            "count": 0, "wins": 0, "losses": 0,
            "win_rate": None, "profit_factor": None,
            "total_pnl": 0.0, "avg_pnl": 0.0,
        }

    total_pnl = sum(float(t.realized_pnl or 0) for t in trades)
    # Trades with realized_pnl == 0 count as losses (breakeven = not a win)
    wins = [t for t in trades if (t.realized_pnl or 0) > 0]
    losses = [t for t in trades if (t.realized_pnl or 0) <= 0]

    win_pnl = sum(float(t.realized_pnl or 0) for t in wins)
    loss_pnl = abs(sum(float(t.realized_pnl or 0) for t in losses))

    # Cap profit factor to avoid absurd values with micro-PnLs
    raw_pf = win_pnl / loss_pnl if loss_pnl > 0 else (float('inf') if win_pnl > 0 else None)
    if raw_pf is not None and raw_pf > 100:
        profit_factor = 100.0
    elif raw_pf is not None:
        profit_factor = round(raw_pf, 2)
    else:
        profit_factor = None

    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "profit_factor": profit_factor,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(trades), 2) if trades else 0.0,
    }


def compute_attribution(trades: list) -> dict[str, Any]:
    """Compute P&L attribution breakdown from a list of closed Position objects.

    Args:
        trades: list of Position objects with realized_pnl and extra_config

    Returns:
        {
            "total_trades": int,
            "overall": {...metrics...},
            "by_dimension": {
                "quality_tier": {"STRONG": {...}, ...},
                ...
            },
            "insights": [str],
        }
    """
    overall = _compute_metrics(trades)

    by_dimension: dict[str, dict[str, Any]] = {}
    for dim in DIMENSION_FIELDS:
        buckets: dict[str, list] = {}
        for t in trades:
            val = _get_dim_value(t, dim)
            buckets.setdefault(val, []).append(t)
        by_dimension[dim] = {
            val: _compute_metrics(bucket)
            for val, bucket in buckets.items()
        }

    # Auto-generated insights
    insights: list[str] = []

    # Insight 1: best/worst tier
    tier_data = by_dimension.get("quality_tier", {})
    if tier_data:
        sorted_tiers = sorted(
            [(k, v) for k, v in tier_data.items() if v["count"] >= 5],
            key=lambda x: x[1].get("total_pnl", 0),
            reverse=True,
        )
        if sorted_tiers:
            best = sorted_tiers[0]
            insights.append(
                f"Best tier: {best[0]} ({best[1]['count']} trades, "
                f"WR {best[1]['win_rate']}%, PF {best[1]['profit_factor']})"
            )
        if len(sorted_tiers) > 1:
            worst = sorted_tiers[-1]
            insights.append(
                f"Worst tier: {worst[0]} ({worst[1]['count']} trades, "
                f"WR {worst[1]['win_rate']}%, PF {worst[1]['profit_factor']})"
            )

    # Insight 2: regime performance
    regime_data = by_dimension.get("market_regime", {})
    if regime_data:
        candidates = [(k, v) for k, v in regime_data.items() if v["count"] >= 5]
        if candidates:
            best_regime = max(candidates, key=lambda x: x[1].get("total_pnl", 0))
            insights.append(
                f"Best regime: {best_regime[0]} (PF {best_regime[1]['profit_factor']})"
            )

    # Insight 3: direction bias
    dir_data = by_dimension.get("direction", {})
    if dir_data and len(dir_data) == 2:
        long_pf = dir_data.get("long", {}).get("profit_factor")
        short_pf = dir_data.get("short", {}).get("profit_factor")
        if long_pf and short_pf:
            if long_pf > short_pf * 1.5:
                insights.append(f"Long bias detected: long PF={long_pf} vs short PF={short_pf}")
            elif short_pf > long_pf * 1.5:
                insights.append(f"Short bias detected: short PF={short_pf} vs long PF={long_pf}")

    # Insight 4: underperforming filters
    status_data = by_dimension.get("anti_fake_status", {})
    if status_data:
        caution = status_data.get("CAUTION", {})
        clear = status_data.get("CLEAR", {})
        if caution.get("count", 0) >= 5 and clear.get("count", 0) >= 5:
            if caution.get("win_rate", 0) > clear.get("win_rate", 0):
                insights.append(
                    f"CAUTION signals outperforming CLEAR: "
                    f"CAUTION WR={caution['win_rate']}% vs CLEAR WR={clear['win_rate']}%. "
                    f"Consider relaxing anti-fake threshold."
                )

    return {
        "total_trades": overall["count"],
        "overall": overall,
        "by_dimension": by_dimension,
        "insights": insights,
    }
