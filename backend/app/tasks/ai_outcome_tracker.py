"""
Celery Beat task — auto-labels AI signal outcomes.

Runs every 15 minutes:
1. Load all PENDING ai_signals older than 1 candle period
2. Fetch subsequent candles from Binance (public)
3. Check whether TP1 or SL was hit first
4. Update outcome: SUCCESS | FAILURE | EXPIRED (after 50 bars unresolved)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import ccxt.async_support as ccxt
from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal

_TF_SECONDS: dict[str, int] = {
    "1m": 60,   "3m": 180,   "5m": 300,   "15m": 900,
    "30m": 1800, "1h": 3600, "2h": 7200,  "4h": 14400,
    "6h": 21600, "12h": 43200, "1d": 86400,
}

_EXPIRE_BARS = 50  # mark EXPIRED if not resolved within this many bars


def _run(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    name="app.tasks.ai_outcome_tracker.track_outcomes",
    queue="default",
    max_retries=0,
)
def track_outcomes() -> dict:
    try:
        return _run(_track_async())
    except Exception as exc:
        logger.error(f"[AI Tracker] Error: {exc}")
        return {"error": str(exc)}


async def _track_async() -> dict:
    from app.models.ai_signal import AISignal

    now = datetime.now(timezone.utc)
    updated = expired = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AISignal).where(AISignal.outcome == "PENDING")
        )
        pending = result.scalars().all()

    if not pending:
        return {"checked": 0, "updated": 0, "expired": 0}

    exchange = ccxt.binance({"options": {"defaultType": "swap"}})
    try:
        for sig in pending:
            tf_secs = _TF_SECONDS.get(sig.timeframe, 3600)

            # Don't check until at least 1 full candle has closed after signal
            if (now - sig.signal_time).total_seconds() < tf_secs:
                continue

            bars_elapsed = int((now - sig.signal_time).total_seconds() / tf_secs)

            if bars_elapsed > _EXPIRE_BARS:
                await _update_outcome(sig.id, "EXPIRED", None, bars_elapsed)
                expired += 1
                continue

            try:
                since_ms = int(sig.signal_time.timestamp() * 1000)
                ohlcv = await exchange.fetch_ohlcv(
                    sig.ccxt_symbol, sig.timeframe, since=since_ms, limit=_EXPIRE_BARS
                )
            except Exception as exc:
                logger.warning(f"[AI Tracker] {sig.ticker}/{sig.timeframe} fetch error: {exc}")
                continue

            if not ohlcv:
                continue

            # Skip the signal candle itself (index 0 may overlap)
            candles_after = [c for c in ohlcv if c[0] > int(sig.signal_time.timestamp() * 1000)]

            outcome, pnl, bars = _evaluate_outcome(sig, candles_after)
            if outcome:
                await _update_outcome(sig.id, outcome, pnl, bars)
                updated += 1
                logger.info(
                    f"[AI Tracker] {sig.ticker}/{sig.timeframe} {sig.direction.upper()} "
                    f"→ {outcome} | pnl={pnl:.2f}% | bars={bars}"
                )
    finally:
        await exchange.close()

    logger.info(f"[AI Tracker] checked={len(pending)} updated={updated} expired={expired}")
    return {"checked": len(pending), "updated": updated, "expired": expired}


def _evaluate_outcome(sig, candles_after: list) -> tuple[str | None, float | None, int | None]:
    """
    Walk through candles_after and find which level was hit first: TP1 or SL.
    Returns (outcome, pnl_pct, bars_to_resolution) or (None, None, None) if pending.
    """
    is_long = sig.direction == "long"
    entry   = sig.entry_price
    sl      = sig.stop_loss
    tp1     = sig.take_profit_1

    for i, c in enumerate(candles_after, start=1):
        _, high, low, close, *_ = c[1], c[2], c[3], c[4]  # unpack ohlcv

        if is_long:
            tp_hit = high >= tp1
            sl_hit = low  <= sl
        else:
            tp_hit = low  <= tp1
            sl_hit = high >= sl

        if tp_hit and sl_hit:
            # Can't tell from OHLCV alone — use close as tiebreaker
            if is_long:
                outcome = "SUCCESS" if close >= entry else "FAILURE"
            else:
                outcome = "SUCCESS" if close <= entry else "FAILURE"
            ref = tp1 if outcome == "SUCCESS" else sl
        elif tp_hit:
            outcome = "SUCCESS"
            ref = tp1
        elif sl_hit:
            outcome = "FAILURE"
            ref = sl
        else:
            continue

        pnl = (ref - entry) / entry * 100
        if not is_long:
            pnl = (entry - ref) / entry * 100

        return outcome, round(pnl, 3), i

    return None, None, None


async def _update_outcome(signal_id, outcome: str, pnl: float | None, bars: int | None):
    from app.models.ai_signal import AISignal

    async with AsyncSessionLocal() as db:
        sig = await db.get(AISignal, signal_id)
        if sig:
            sig.outcome      = outcome
            sig.pnl_pct      = pnl
            sig.outcome_bars = bars
            sig.resolved_at  = datetime.now(timezone.utc)
            await db.commit()
