"""
Auto-timeframe resolver — picks the best timeframe for a ticker based on
historical signal performance using a COMPOSITE score:
  - Win Rate (30%)
  - Profit Factor (25%)
  - Sharpe-like ratio (25%)
  - Max Drawdown penalty (20%)

Used by:
  - AI scanner when watchlist entry has timeframe="auto"
  - Bot activator when bot.auto_timeframe=True
  - Frontend via /ai/optimal-config endpoint
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from loguru import logger

from app.core.constants import VALID_TIMEFRAMES


# Minimum signals required in a timeframe before it can be considered "best"
_MIN_SIGNALS_PER_TF = 5
# Default timeframe when insufficient data across all timeframes
_DEFAULT_TF = "1h"


def resolve_best_timeframe_sync(ticker: str, db) -> str:
    """
    Synchronous resolver used by Celery tasks.
    Returns the timeframe with the best COMPOSITE score for this ticker,
    considering WR, Profit Factor, Sharpe-like ratio, and Max Drawdown.

    Paper trades from the SAME timeframe are included with reduced weight
    so that long-term paper testing contributes to timeframe selection.
    """
    from app.models.ai_signal import AISignal
    from app.models.position import Position
    from app.models.bot_config import BotConfig
    from sqlalchemy import func

    ticker_upper = ticker.upper().strip()
    since = datetime.now(timezone.utc) - timedelta(days=30)

    # Fetch ALL positions (real + paper) for this ticker with their signal data
    rows = (
        db.query(
            Position.realized_pnl,
            Position.entry_price,
            Position.quantity,
            Position.leverage,
            AISignal.timeframe,
            AISignal.outcome,
            BotConfig.paper_balance_id.is_(None).label("is_real"),
        )
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .join(
            AISignal,
            AISignal.id == func.cast(Position.extra_config["ai_signal_id"].astext, AISignal.id.type),
        )
        .filter(
            Position.symbol == ticker_upper,
            Position.status == "closed",
            Position.closed_at >= since,
            Position.source == "ai_bot",
            Position.realized_pnl.isnot(None),
        )
        .all()
    )

    if not rows:
        logger.info(f"[AUTO_TF] No historical data for {ticker_upper}, defaulting to {_DEFAULT_TF}")
        return _DEFAULT_TF

    # Aggregate stats per timeframe with WEIGHTS: real=1.0, paper=0.5
    tf_stats: dict[str, dict] = {}
    for realized_pnl, entry_price, quantity, leverage, tf, outcome, is_real in rows:
        tf = tf or "unknown"
        weight = 1.0 if is_real else 0.5
        # Calculate P&L % manually — Position model has no realized_pnl_pct column
        notional = float(entry_price) * float(quantity)
        if leverage and leverage > 0:
            notional = notional / float(leverage)
        pnl = float(realized_pnl)
        pnl_pct = (pnl / notional * 100) if notional > 0 else 0.0

        if tf not in tf_stats:
            tf_stats[tf] = {
                "weighted_total": 0.0, "weighted_wins": 0.0,
                "pnls": [], "weighted_pnls": [],
            }
        tf_stats[tf]["weighted_total"] += weight
        if pnl > 0:
            tf_stats[tf]["weighted_wins"] += weight
        tf_stats[tf]["pnls"].append(pnl_pct)
        tf_stats[tf]["weighted_pnls"].append((pnl_pct, weight))

    best_tf = _DEFAULT_TF
    best_score = -1.0
    for tf, st in tf_stats.items():
        if st["weighted_total"] < _MIN_SIGNALS_PER_TF:
            continue

        # 1. Win Rate
        wr = st["weighted_wins"] / st["weighted_total"] * 100

        # 2. Profit Factor
        wins = [pnl * w for pnl, w in st["weighted_pnls"] if pnl > 0]
        losses = [abs(pnl * w) for pnl, w in st["weighted_pnls"] if pnl <= 0]
        pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (999.0 if wins else 0.0)

        # 3. Sharpe-like: mean return / std dev (annualized roughly)
        pnls = st["pnls"]
        mean_ret = sum(pnls) / len(pnls) if pnls else 0
        std_ret = (sum((p - mean_ret) ** 2 for p in pnls) / len(pnls)) ** 0.5 if pnls else 1
        sharpe = mean_ret / std_ret if std_ret > 0 else 0

        # 4. Max Drawdown from equity curve
        cumulative = []
        running = 0.0
        for p in pnls:
            running += p
            cumulative.append(running)
        peak = cumulative[0] if cumulative else 0
        max_dd = 0.0
        for c in cumulative:
            if c > peak:
                peak = c
            dd = (peak - c) / abs(peak) * 100 if peak != 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Composite score: higher is better
        # WR 0-100, PF 0-10 (capped), Sharpe -5 to +5, MaxDD 0-100 (penalty)
        score = (
            wr * 0.30 +                    # Win Rate weight
            min(pf, 10) * 10 * 0.25 +      # Profit Factor weight (capped at 10)
            max(0, sharpe) * 20 * 0.25 +   # Sharpe weight (only positive)
            max(0, 100 - max_dd) * 0.20    # Drawdown penalty weight
        )

        if score > best_score:
            best_score = score
            best_tf = tf

        logger.debug(
            f"[AUTO_TF] {ticker_upper}/{tf}: WR={wr:.1f}% PF={pf:.2f} "
            f"Sharpe={sharpe:.2f} MDD={max_dd:.1f}% Score={score:.1f}"
        )

    # Ensure the resolved TF is still valid
    if best_tf not in VALID_TIMEFRAMES:
        logger.warning(f"[AUTO_TF] Resolved {best_tf} not in valid TFs, falling back to {_DEFAULT_TF}")
        best_tf = _DEFAULT_TF

    logger.info(
        f"[AUTO_TF] {ticker_upper} → {best_tf} (composite_score={best_score:.1f})"
    )
    return best_tf


async def resolve_best_timeframe_async(ticker: str, db) -> str:
    """Async wrapper for FastAPI endpoints."""
    return resolve_best_timeframe_sync(ticker, db)
