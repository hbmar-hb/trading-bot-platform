"""
Celery Beat task — audits rejected signals for survival-bias detection.

Runs every 6 hours:
1. Find all AISignalRejected rows with audited_at IS NULL
2. For each, find the closest AISignal with same ticker/timeframe/direction
   within ±24h that has a resolved outcome (SUCCESS / FAILURE)
3. Populate:
   - would_have_been_winner (bool)
   - similar_signal_outcome (str)
   - similar_signal_pnl_pct (float)
   - audited_at (datetime)

This allows the dashboard to flag filters that reject >60% would-be winners.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import select, func

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.models.ai_signal import AISignal
from app.models.ai_signal_rejected import AISignalRejected


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def audit_rejected_signals(self, batch_size: int = 200):
    """Celery task wrapper — runs the async audit logic."""
    try:
        asyncio.run(_audit_rejected_signals_async(batch_size))
    except Exception as exc:
        logger.error(f"[REJECTED_AUDIT] Task failed: {exc}")
        raise self.retry(exc=exc)


async def _audit_rejected_signals_async(batch_size: int = 200):
    async with AsyncSessionLocal() as db:
        # Fetch un-audited rejected signals (oldest first)
        stmt = (
            select(AISignalRejected)
            .where(AISignalRejected.audited_at.is_(None))
            .order_by(AISignalRejected.rejected_at.asc())
            .limit(batch_size)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            logger.info("[REJECTED_AUDIT] No pending rejected signals to audit.")
            return

        logger.info(f"[REJECTED_AUDIT] Auditing {len(rows)} rejected signals...")

        audited_count = 0
        matched_count = 0

        for rejected in rows:
            # Find closest resolved AISignal within ±24h with same ticker/tf/direction
            window_start = rejected.signal_time - timedelta(hours=24)
            window_end = rejected.signal_time + timedelta(hours=24)

            similar_stmt = (
                select(AISignal)
                .where(
                    AISignal.ticker == rejected.ticker,
                    AISignal.timeframe == rejected.timeframe,
                    AISignal.direction == rejected.direction,
                    AISignal.outcome.in_(["SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "EXPIRED"]),
                    AISignal.signal_time >= window_start,
                    AISignal.signal_time <= window_end,
                )
                .order_by(
                    func.abs(
                        func.extract("epoch", AISignal.signal_time)
                        - func.extract("epoch", rejected.signal_time)
                    ).asc()
                )
                .limit(1)
            )

            similar_result = await db.execute(similar_stmt)
            similar = similar_result.scalar_one_or_none()

            rejected.audited_at = datetime.now(timezone.utc)
            audited_count += 1

            if similar:
                rejected.would_have_been_winner = similar.outcome == "SUCCESS"
                rejected.similar_signal_outcome = similar.outcome
                rejected.similar_signal_pnl_pct = similar.pnl_pct
                matched_count += 1
            else:
                # No similar signal found within window — leave null
                pass

        await db.commit()
        logger.info(
            f"[REJECTED_AUDIT] Completed: {audited_count} audited, "
            f"{matched_count} matched with similar signal."
        )
