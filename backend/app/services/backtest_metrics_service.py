"""Backtest metrics service — computes historical simulation outcomes per ticker/tf.

Connects the realistic_outcome engine (backtest) to the ML training pipeline
by providing rolling window metrics as signal features.  These metrics are
computed from *past* signals only — no look-ahead bias.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import func


def _calc_metrics(rows: list) -> dict:
    """Compute win-rate, profit-factor and sample count from a list of DB rows."""
    if not rows:
        return {"backtest_wr_30d": 0.5, "backtest_pf_30d": 1.0, "backtest_n_30d": 0}

    wins = 0
    win_pnl = 0.0
    loss_pnl = 0.0
    for r in rows:
        pnl = r.realistic_pnl_pct
        if pnl is None:
            pnl = r.pnl_pct
        if pnl is None:
            continue
        if pnl > 0:
            wins += 1
            win_pnl += pnl
        else:
            loss_pnl += abs(pnl)

    n = len(rows)
    wr = wins / n if n else 0.5
    pf = win_pnl / loss_pnl if loss_pnl > 0 else (999.0 if win_pnl > 0 else 1.0)

    return {
        "backtest_wr_30d": round(wr, 4),
        "backtest_pf_30d": round(pf, 4),
        "backtest_n_30d": n,
    }


def get_backtest_metrics_sync(db, ticker: str, timeframe: str, lookback_days: int = 30) -> dict:
    """Return rolling backtest metrics for *past* signals of the same ticker/tf.

    Args:
        db: SQLAlchemy sync session.
        ticker: compact ticker, e.g. "BTCUSDT".
        timeframe: e.g. "1h".
        lookback_days: rolling window length.

    Returns:
        Dict with keys backtest_wr_30d, backtest_pf_30d, backtest_n_30d.
        Safe defaults (0.5, 1.0, 0) when no data exists.
    """
    try:
        from app.models.ai_signal import AISignal

        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        rows = (
            db.query(AISignal)
            .filter(
                AISignal.ticker == ticker,
                AISignal.timeframe == timeframe,
                AISignal.resolved_at >= since,
                AISignal.realistic_outcome.in_(["SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL"]),
            )
            .all()
        )
        return _calc_metrics(rows)
    except Exception as exc:
        logger.debug(f"[BacktestMetrics] Failed for {ticker}/{timeframe}: {exc}")
        return {"backtest_wr_30d": 0.5, "backtest_pf_30d": 1.0, "backtest_n_30d": 0}


async def get_backtest_metrics_async(db, ticker: str, timeframe: str, lookback_days: int = 30) -> dict:
    """Async variant for FastAPI / async callers."""
    try:
        from app.models.ai_signal import AISignal
        from sqlalchemy import select

        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        result = await db.execute(
            select(AISignal)
            .where(
                AISignal.ticker == ticker,
                AISignal.timeframe == timeframe,
                AISignal.resolved_at >= since,
                AISignal.realistic_outcome.in_(["SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL"]),
            )
        )
        rows = result.scalars().all()
        return _calc_metrics(rows)
    except Exception as exc:
        logger.debug(f"[BacktestMetrics] Async failed for {ticker}/{timeframe}: {exc}")
        return {"backtest_wr_30d": 0.5, "backtest_pf_30d": 1.0, "backtest_n_30d": 0}
