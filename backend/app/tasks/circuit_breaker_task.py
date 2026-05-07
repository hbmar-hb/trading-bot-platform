"""Circuit breaker — auto-pauses AI bots after 3 consecutive losses.

Runs every 15 minutes. For each active AI-signal bot:
  - Fetches the last 3 closed positions (ordered by closed_at DESC)
  - If all 3 have realized_pnl < 0, pauses the bot and sends an alert
  - Records the event in ai_signal_config for audit purposes
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select, desc

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal

_CONSECUTIVE_LOSSES_THRESHOLD = 3


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.circuit_breaker_task.check_circuit_breakers",
    queue="default",
)
def check_circuit_breakers(self) -> dict:
    try:
        return asyncio.run(_check_async())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=120)


async def _check_async() -> dict:
    from app.models.bot_config import BotConfig
    from app.models.position import Position
    from app.services.notifier import notify_circuit_breaker

    async with AsyncSessionLocal() as db:
        bots = (
            await db.execute(
                select(BotConfig).where(
                    BotConfig.ai_signal_mode.is_(True),
                    BotConfig.status == "active",
                )
            )
        ).scalars().all()

        paused = 0
        for bot in bots:
            positions = (
                await db.execute(
                    select(Position)
                    .where(
                        Position.bot_id == bot.id,
                        Position.status == "closed",
                    )
                    .order_by(desc(Position.closed_at))
                    .limit(_CONSECUTIVE_LOSSES_THRESHOLD)
                )
            ).scalars().all()

            if len(positions) < _CONSECUTIVE_LOSSES_THRESHOLD:
                continue

            all_losses = all(
                p.realized_pnl is not None and p.realized_pnl < 0
                for p in positions
            )
            if not all_losses:
                continue

            bot.status = "paused"
            cfg = dict(bot.ai_signal_config or {})
            cfg["circuit_breaker_at"]     = datetime.now(timezone.utc).isoformat()
            cfg["circuit_breaker_losses"] = _CONSECUTIVE_LOSSES_THRESHOLD
            bot.ai_signal_config = cfg
            paused += 1

            logger.warning(
                f"[CIRCUIT BREAKER] Bot '{bot.bot_name}' ({bot.symbol}) "
                f"paused after {_CONSECUTIVE_LOSSES_THRESHOLD} consecutive losses"
            )
            try:
                notify_circuit_breaker(bot.bot_name, bot.symbol, _CONSECUTIVE_LOSSES_THRESHOLD)
            except Exception as notify_exc:
                logger.warning(f"[CIRCUIT BREAKER] Notification failed: {notify_exc}")

        if paused:
            await db.commit()

    return {"checked": len(bots), "paused": paused}
