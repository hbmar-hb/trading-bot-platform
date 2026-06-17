"""Watchlist coverage check — alerts when active AI bots are not receiving signals
because their symbol/timeframe is missing from the AI watchlist.

Runs every 15 minutes. For each active bot with ai_signal_mode=True:
  1. Check if the bot's symbol/timeframe exists in AIWatchlistItem
  2. Check when the bot last received an AI signal (AISignal) or opened a position
  3. Log warning if no signals for > 1 hour
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import select, desc

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.services.notifier import notify_watchlist_coverage_alert

# Thresholds
_NO_SIGNAL_ALERT_MINUTES = 60
_MIN_BOT_ACTIVE_MINUTES = 15  # Don't alert on bots that were just activated


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.watchlist_coverage_task.check_watchlist_coverage",
    queue="default",
)
def check_watchlist_coverage(self) -> dict:
    try:
        return _run_async(_check_async())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=120)


async def _check_async() -> dict:
    from app.models.bot_config import BotConfig
    from app.models.ai_scan import AIWatchlistItem
    from app.models.ai_signal import AISignal
    from app.models.position import Position

    async with AsyncSessionLocal() as db:
        # Get all active AI bots
        bots_result = await db.execute(
            select(BotConfig).where(
                BotConfig.ai_signal_mode.is_(True),
                BotConfig.status == "active",
            )
        )
        bots = bots_result.scalars().all()

        # Get all watchlist items
        wl_result = await db.execute(
            select(AIWatchlistItem.symbol, AIWatchlistItem.timeframe).distinct()
        )
        watchlist_pairs = {(r.symbol.upper(), r.timeframe) for r in wl_result.all()}

        alerted = 0
        alerted_bots = []
        for bot in bots:
            # Normalize symbol for comparison (same logic as api/routes/bots.py)
            bot_symbol = re.sub(r'/([^:]+):[^:]+$', r'\1', bot.symbol).replace('/', '').upper()
            if ".P" in bot_symbol:
                bot_symbol = bot_symbol.replace(".P", "")
            # Also try raw symbol
            bot_symbol_raw = bot.symbol.upper()

            bot_tf = bot.timeframe or "1h"

            # Check if symbol is in watchlist (try both normalized and raw)
            in_watchlist = (
                (bot_symbol, bot_tf) in watchlist_pairs or
                (bot_symbol_raw, bot_tf) in watchlist_pairs
            )

            # Find last AI signal for this bot's symbol/timeframe
            last_signal_result = await db.execute(
                select(AISignal.created_at)
                .where(
                    AISignal.ticker == bot_symbol,
                    AISignal.timeframe == bot_tf,
                )
                .order_by(desc(AISignal.created_at))
                .limit(1)
            )
            last_signal_row = last_signal_result.first()
            last_signal_at = last_signal_row[0] if last_signal_row else None

            # Find last position opened by this bot
            last_pos_result = await db.execute(
                select(Position.opened_at)
                .where(
                    Position.bot_id == bot.id,
                    Position.source == "ai_bot",
                )
                .order_by(desc(Position.opened_at))
                .limit(1)
            )
            last_pos_row = last_pos_result.first()
            last_pos_at = last_pos_row[0] if last_pos_row else None

            # Determine the most recent activity
            last_activity = last_signal_at or last_pos_at
            if last_signal_at and last_pos_at:
                last_activity = max(last_signal_at, last_pos_at)

            now = datetime.now(timezone.utc)
            if last_activity and last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            minutes_since_signal = (
                (now - last_activity).total_seconds() / 60
                if last_activity else float("inf")
            )

            # Skip bots that were just activated
            if bot.updated_at:
                bot_updated = bot.updated_at
                if bot_updated.tzinfo is None:
                    bot_updated = bot_updated.replace(tzinfo=timezone.utc)
                minutes_since_active = (now - bot_updated).total_seconds() / 60
                if minutes_since_active < _MIN_BOT_ACTIVE_MINUTES:
                    continue

            # Alert conditions
            if not in_watchlist:
                logger.warning(
                    f"[WATCHLIST CHECK] {bot.bot_name} ({bot.symbol} {bot_tf}) "
                    f"is active but NOT in AI watchlist — no signals will be generated"
                )
                alerted += 1
                alerted_bots.append({
                    "bot_name": bot.bot_name,
                    "symbol": bot.symbol,
                    "timeframe": bot_tf,
                    "reason": "not_in_watchlist",
                })
            elif minutes_since_signal > _NO_SIGNAL_ALERT_MINUTES:
                logger.warning(
                    f"[WATCHLIST CHECK] {bot.bot_name} ({bot.symbol} {bot_tf}) "
                    f"no AI signal or position for {int(minutes_since_signal)}min "
                    f"(threshold: {_NO_SIGNAL_ALERT_MINUTES}min)"
                )
                alerted += 1
                alerted_bots.append({
                    "bot_name": bot.bot_name,
                    "symbol": bot.symbol,
                    "timeframe": bot_tf,
                    "reason": "no_signal",
                    "minutes_since": int(minutes_since_signal),
                })
            else:
                logger.debug(
                    f"[WATCHLIST CHECK] {bot.bot_name} ({bot.symbol} {bot_tf}) OK — "
                    f"last activity {int(minutes_since_signal)}min ago"
                )

        # Send consolidated notification if any bots are alerted
        if alerted_bots:
            try:
                notify_watchlist_coverage_alert(alerted_bots)
            except Exception as exc:
                logger.warning(f"Failed to send watchlist coverage notification: {exc}")

    return {"checked": len(bots), "alerted": alerted, "watchlist_items": len(watchlist_pairs)}
