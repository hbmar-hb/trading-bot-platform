"""Drawdown Guard — pausa bots si una cuenta pierde más del X% en un día.

Autonomous behaviour:
  1. Pauses bots when daily drawdown exceeds limit.
  2. AUTO-RESUMES bots when drawdown recovers below limit AND
     rolling win-rate (last 10 closed trades) >= 40%.

Runs every 5 minutes via Celery Beat.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import select, func, not_

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.services.autonomy_state import mark_paused, clear_pause

_DEFAULT_DAILY_DRAWDOWN_LIMIT_PCT = 5.0
_AUTO_RESUME_MIN_WR = 0.40
_AUTO_RESUME_MIN_TRADES = 5


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
    name="app.tasks.drawdown_guard.check_daily_drawdown",
    queue="default",
)
def check_daily_drawdown(self) -> dict:
    try:
        return _run_async(_check_async())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


async def _check_async() -> dict:
    from app.models.bot_config import BotConfig
    from app.models.exchange_account import ExchangeAccount
    from app.models.position import Position
    from app.exchanges.factory import create_exchange

    async with AsyncSessionLocal() as db:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # ── PAUSE PHASE: check accounts in drawdown ──
        accounts = (
            await db.execute(
                select(ExchangeAccount).where(
                    ExchangeAccount.is_active == True,
                )
            )
        ).scalars().all()

        paused = 0
        resumed = 0

        for account in accounts:
            # Bots activos de esta cuenta
            bots = (
                await db.execute(
                    select(BotConfig).where(
                        BotConfig.exchange_account_id == account.id,
                        BotConfig.status == "active",
                        not_(BotConfig.bot_name.like("[MANUAL]%")),
                    )
                )
            ).scalars().all()

            if not bots:
                continue

            bot_ids = [b.id for b in bots]
            closed_today = (
                await db.execute(
                    select(Position).where(
                        Position.bot_id.in_(bot_ids),
                        Position.status == "closed",
                        Position.closed_at >= today_start,
                    )
                )
            ).scalars().all()
            realized_pnl = float(sum(p.realized_pnl or 0 for p in closed_today))

            open_positions = (
                await db.execute(
                    select(Position).where(
                        Position.bot_id.in_(bot_ids),
                        Position.status == "open",
                    )
                )
            ).scalars().all()
            unrealized_pnl = float(sum(p.unrealized_pnl or 0 for p in open_positions))

            total_pnl = realized_pnl + unrealized_pnl
            if total_pnl >= 0:
                continue  # No drawdown

            try:
                exchange = create_exchange(account)
                balance = await exchange.get_equity()
                await exchange.close()
                equity = float(balance.total_equity)
            except Exception as exc:
                logger.warning(f"[DRAWDOWN GUARD] Failed to get equity for {account.label}: {exc}")
                continue

            if equity <= 0:
                continue

            drawdown_pct = abs(total_pnl) / equity * 100
            limit = _DEFAULT_DAILY_DRAWDOWN_LIMIT_PCT

            if drawdown_pct > limit:
                for bot in bots:
                    cfg = bot.ai_signal_config or {}
                    autonomy = cfg.get("autonomy_state", {})
                    if mark_paused(autonomy, "drawdown"):
                        cfg["execution_blocked"] = True
                        cfg["execution_blocked_reason"] = "drawdown"
                        cfg["autonomy_state"] = autonomy
                        bot.ai_signal_config = cfg
                        paused += 1
                if paused:
                    logger.critical(
                        f"[DRAWDOWN GUARD] Account {account.label} drawdown "
                        f"{drawdown_pct:.2f}% > limit {limit}% — "
                        f"BLOCKED {paused} bot(s)"
                    )
                try:
                    from app.services.notifier import notify_circuit_breaker
                    notify_circuit_breaker(
                        account.label, "ALL",
                        f"Daily drawdown {drawdown_pct:.1f}% > {limit}% — {len(bots)} bots blocked"
                    )
                except Exception:
                    pass

        # ── RESUME PHASE: check bots blocked by drawdown ──
        all_account_bots = (
            await db.execute(
                select(BotConfig).where(
                    BotConfig.exchange_account_id.in_([a.id for a in accounts]),
                    not_(BotConfig.bot_name.like("[MANUAL]%")),
                )
            )
        ).scalars().all()

        for bot in all_account_bots:
            cfg = bot.ai_signal_config or {}
            if cfg.get("execution_blocked_reason") != "drawdown":
                continue

            # Re-evaluate account drawdown for this bot
            account = next((a for a in accounts if a.id == bot.exchange_account_id), None)
            if not account:
                continue

            all_bot_ids = [b.id for b in all_account_bots if b.exchange_account_id == account.id]

            closed_today = (
                await db.execute(
                    select(Position).where(
                        Position.bot_id.in_(all_bot_ids),
                        Position.status == "closed",
                        Position.closed_at >= today_start,
                    )
                )
            ).scalars().all()
            realized_pnl = float(sum(p.realized_pnl or 0 for p in closed_today))
            open_positions = (
                await db.execute(
                    select(Position).where(
                        Position.bot_id.in_(all_bot_ids),
                        Position.status == "open",
                    )
                )
            ).scalars().all()
            unrealized_pnl = float(sum(p.unrealized_pnl or 0 for p in open_positions))
            total_pnl = realized_pnl + unrealized_pnl

            if total_pnl >= 0:
                drawdown_pct = 0.0
            else:
                try:
                    exchange = create_exchange(account)
                    balance = await exchange.get_equity()
                    await exchange.close()
                    equity = float(balance.total_equity)
                    drawdown_pct = abs(total_pnl) / equity * 100 if equity > 0 else 0.0
                except Exception:
                    continue

            if drawdown_pct > limit:
                continue  # Still in drawdown, keep blocked

            # Check rolling win-rate for this bot specifically
            recent_closed = (
                await db.execute(
                    select(Position).where(
                        Position.bot_id == bot.id,
                        Position.status == "closed",
                    ).order_by(Position.closed_at.desc()).limit(10)
                )
            ).scalars().all()

            if len(recent_closed) >= _AUTO_RESUME_MIN_TRADES:
                wins = sum(1 for p in recent_closed if (p.realized_pnl or 0) > 0)
                wr = wins / len(recent_closed)
                if wr < _AUTO_RESUME_MIN_WR:
                    logger.info(
                        f"[DRAWDOWN GUARD] Bot {bot.bot_name} drawdown recovered "
                        f"but WR {wr:.1%} < {_AUTO_RESUME_MIN_WR:.0%}, keeping blocked"
                    )
                    continue

            # All clear — unblock ONLY if drawdown was the pauser
            autonomy = cfg.get("autonomy_state", {})
            if clear_pause(autonomy, "drawdown"):
                cfg.pop("execution_blocked", None)
                cfg.pop("execution_blocked_reason", None)
                cfg["autonomy_state"] = autonomy
                bot.ai_signal_config = cfg
                resumed += 1
            logger.info(
                f"[DRAWDOWN GUARD] Auto-unblocked bot {bot.bot_name} — "
                f"drawdown recovered to {drawdown_pct:.2f}%"
            )

        if paused or resumed:
            await db.commit()

    return {"checked_accounts": len(accounts), "paused_bots": paused, "resumed_bots": resumed}
