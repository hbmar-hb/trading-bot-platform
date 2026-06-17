"""Celery tasks for Dynamic Risk Manager algorithms.

Queues:
  - emergency_reduce  → orders (same priority as TP / kill switch)
  - scale_out         → orders
  - time_exit         → orders
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from celery import shared_task
from loguru import logger
from sqlalchemy import select


def _run_async(coro):
    """Ejecuta corrutina reutilizando el event loop disponible."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ──────────────────────────────────────────────────────────────
# Helpers (mirroring sl_update_tasks patterns)
# ──────────────────────────────────────────────────────────────

async def _load_position_bot_exchange(db, position_id: uuid.UUID):
    from sqlalchemy import select
    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position

    result = await db.execute(
        select(Position, BotConfig)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(Position.id == position_id, Position.status == "open")
    )
    row = result.one_or_none()
    if not row:
        return None, None, None
    position, bot = row

    if bot.is_paper_trading:
        paper_balance = await db.execute(
            select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
        )
        paper_balance = paper_balance.scalar_one()
        exchange = create_paper_exchange(paper_balance)
    else:
        acc_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
        )
        account = acc_result.scalar_one()
        exchange = create_exchange(account)

    return position, bot, exchange


async def _save_bot_log(db, bot_id: uuid.UUID, event_type: str, message: str, extra_data: dict | None = None):
    from app.models.bot_log import BotLog
    log = BotLog(
        bot_id=bot_id,
        event_type=event_type,
        message=message,
        extra_data=extra_data or {},
    )
    db.add(log)
    await db.commit()


# ──────────────────────────────────────────────────────────────
# 1. Emergency Reduce
# ──────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="orders",
    name="app.tasks.dynamic_risk_tasks.execute_emergency_reduce",
)
def execute_emergency_reduce(
    self,
    position_id: str,
    reduce_by_pct: float,
    new_sl_price: float | None,
    reason: str,
) -> dict:
    try:
        _run_async(_execute_emergency_reduce(
            uuid.UUID(position_id),
            Decimal(str(reduce_by_pct)),
            Decimal(str(new_sl_price)) if new_sl_price is not None else None,
            reason,
        ))
        return {"status": "ok", "position_id": position_id, "action": "emergency_reduce"}
    except Exception as exc:
        exc_str = str(exc)
        logger.error(f"Error emergency_reduce {position_id}: {exc_str[:200]}")
        if "101205" in exc_str or "No position to close" in exc_str:
            return {"status": "skipped", "reason": "position_not_on_exchange"}
        raise self.retry(exc=exc, countdown=5 ** (self.request.retries + 1))


async def _execute_emergency_reduce(
    position_id: uuid.UUID,
    reduce_by_pct: Decimal,
    new_sl_price: Decimal | None,
    reason: str,
) -> None:
    from sqlalchemy import select, update as sa_update
    from app.models.bot_log import BotLog
    from app.models.position import Position as PositionModel
    from app.services.cache import publish_position_update_sync
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
    from app.services.notifier import send_telegram_sync
    from app.tasks.sl_update_tasks import update_stop_loss

    async with AsyncSessionLocal() as db:
        position, bot, exchange = await _load_position_bot_exchange(db, position_id)
        if not position:
            logger.warning(f"Emergency reduce: posición {position_id} no encontrada o ya cerrada")
            return

        # Mark EB triggered BEFORE exchange call
        extra = dict(position.extra_config or {})
        if extra.get("emergency_brake_triggered"):
            logger.info(f"EB ya disparado para {position_id}, ignorando")
            return
        extra["emergency_brake_triggered"] = True
        position.extra_config = extra
        await db.commit()

        close_qty = (position.quantity * reduce_by_pct).quantize(Decimal("0.001"))
        if close_qty <= 0:
            return

        order = None
        fill_price = None
        position_already_closed = False
        try:
            order = await exchange.close_position(position.symbol, position.side, close_qty)
            fill_price = order.fill_price
        except Exception as exc:
            msg = str(exc)
            if "already closed" in msg.lower() or "No position to close" in msg:
                position_already_closed = True
            else:
                raise
        finally:
            await exchange.close()

        if not position_already_closed:
            position.quantity -= close_qty
            pnl = (
                (fill_price - position.entry_price) * close_qty
                if position.side == "long"
                else (position.entry_price - fill_price) * close_qty
            )
            position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl

            if position.quantity <= Decimal("0"):
                position.status = "closed"
                position.closed_at = datetime.now(timezone.utc)
        else:
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.quantity = Decimal("0")
            pnl = Decimal("0")

        await db.commit()

        # Move SL for remainder if applicable
        if new_sl_price and position.status == "open":
            update_stop_loss.delay(
                position_id=str(position.id),
                new_sl_price=float(new_sl_price),
            )

        # Log + notify
        await _save_bot_log(
            db, bot.id, "emergency_reduce",
            f"Emergency brake: reduced {float(reduce_by_pct):.0%} @ {float(fill_price or 0):.4f}. Reason: {reason}",
            {"reduce_by_pct": float(reduce_by_pct), "fill_price": float(fill_price or 0), "reason": reason},
        )
        msg = (
            f"🚨 <b>EMERGENCY BRAKE</b>\n"
            f"Bot: {bot.bot_name}\n"
            f"Par: {position.symbol} | {position.side.upper()}\n"
            f"Reducción: {float(reduce_by_pct):.0%}\n"
            f"Precio: {float(fill_price or 0):.4f} USDT\n"
            f"Motivo: {reason}"
        )
        send_telegram_sync(msg, level="essential")

        if position.status == "closed":
            from app.models.user import User
            from app.tasks.notification_tasks import trade_closed
            user_result = await db.execute(select(User).where(User.id == bot.user_id))
            user = user_result.scalar_one_or_none()
            if user and user.telegram_chat_id and user.notify_on_close:
                original_qty = position.quantity + close_qty
                trade_closed.delay(
                    bot_name=bot.bot_name,
                    symbol=position.symbol,
                    side=position.side,
                    pnl=float(position.realized_pnl),
                    chat_id=user.telegram_chat_id,
                    source="ai_bot" if position.source == "ai_bot" else "bot",
                    entry_price=float(position.entry_price) if position.entry_price else None,
                    exit_price=float(fill_price) if fill_price else None,
                    quantity=float(original_qty) if original_qty > 0 else None,
                    leverage=int(position.leverage) if position.leverage else None,
                    timeframe=bot.timeframe,
                )

        publish_position_update_sync(
            str(bot.user_id),
            {
                "position_id": str(position.id),
                "status": position.status,
                "action": "emergency_reduce",
                "symbol": position.symbol,
                "reduce_by_pct": float(reduce_by_pct),
                "reason": reason,
            }
        )


# ──────────────────────────────────────────────────────────────
# 2. Scale-Out
# ──────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="orders",
    name="app.tasks.dynamic_risk_tasks.execute_scale_out",
)
def execute_scale_out(
    self,
    position_id: str,
    level: float,
    close_pct: float,
    new_sl_price: float | None,
    reason: str,
) -> dict:
    try:
        _run_async(_execute_scale_out(
            uuid.UUID(position_id),
            level,
            Decimal(str(close_pct)),
            Decimal(str(new_sl_price)) if new_sl_price is not None else None,
            reason,
        ))
        return {"status": "ok", "position_id": position_id, "action": "scale_out", "level": level}
    except Exception as exc:
        exc_str = str(exc)
        logger.error(f"Error scale_out {position_id}: {exc_str[:200]}")
        if "101205" in exc_str or "No position to close" in exc_str:
            return {"status": "skipped", "reason": "position_not_on_exchange"}
        raise self.retry(exc=exc, countdown=5 ** (self.request.retries + 1))


async def _execute_scale_out(
    position_id: uuid.UUID,
    level: float,
    close_pct: Decimal,
    new_sl_price: Decimal | None,
    reason: str,
) -> None:
    from app.models.bot_log import BotLog
    from app.models.position import Position as PositionModel
    from app.services.cache import publish_position_update_sync
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
    from app.services.notifier import send_telegram_sync
    from app.tasks.sl_update_tasks import update_stop_loss

    async with AsyncSessionLocal() as db:
        position, bot, exchange = await _load_position_bot_exchange(db, position_id)
        if not position:
            logger.warning(f"Scale-out: posición {position_id} no encontrada o ya cerrada")
            return

        extra = dict(position.extra_config or {})
        hit_levels = set(extra.get("scale_out_levels_hit", []))
        if level in hit_levels:
            logger.info(f"Scale-out nivel {level} ya ejecutado para {position_id}, ignorando")
            return
        hit_levels.add(level)
        extra["scale_out_levels_hit"] = sorted(list(hit_levels))
        position.extra_config = extra
        await db.commit()

        close_qty = (position.quantity * close_pct).quantize(Decimal("0.001"))
        if close_qty <= 0:
            return

        order = None
        fill_price = None
        position_already_closed = False
        try:
            order = await exchange.close_position(position.symbol, position.side, close_qty)
            fill_price = order.fill_price
        except Exception as exc:
            msg = str(exc)
            if "already closed" in msg.lower() or "No position to close" in msg:
                position_already_closed = True
            else:
                raise
        finally:
            await exchange.close()

        if not position_already_closed:
            position.quantity -= close_qty
            pnl = (
                (fill_price - position.entry_price) * close_qty
                if position.side == "long"
                else (position.entry_price - fill_price) * close_qty
            )
            position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl

            if position.quantity <= Decimal("0"):
                position.status = "closed"
                position.closed_at = datetime.now(timezone.utc)
        else:
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.quantity = Decimal("0")
            pnl = Decimal("0")

        await db.commit()

        # Update SL if provided and position still open
        if new_sl_price and position.status == "open":
            update_stop_loss.delay(
                position_id=str(position.id),
                new_sl_price=float(new_sl_price),
            )

        await _save_bot_log(
            db, bot.id, "scale_out",
            f"Scale-out nivel {level}: cerrado {float(close_pct):.0%} @ {float(fill_price or 0):.4f}",
            {"level": level, "close_pct": float(close_pct), "fill_price": float(fill_price or 0), "reason": reason},
        )
        msg = (
            f"📐 <b>SCALE-OUT +{level:.0%}</b>\n"
            f"Bot: {bot.bot_name}\n"
            f"Par: {position.symbol} | {position.side.upper()}\n"
            f"Cierre: {float(close_pct):.0%} @ {float(fill_price or 0):.4f} USDT\n"
            f"PnL parcial: {float(pnl):+.2f} USDT"
        )
        send_telegram_sync(msg, level="essential")

        if position.status == "closed":
            from app.models.user import User
            from app.tasks.notification_tasks import trade_closed
            user_result = await db.execute(select(User).where(User.id == bot.user_id))
            user = user_result.scalar_one_or_none()
            if user and user.telegram_chat_id and user.notify_on_close:
                original_qty = position.quantity + close_qty
                trade_closed.delay(
                    bot_name=bot.bot_name,
                    symbol=position.symbol,
                    side=position.side,
                    pnl=float(position.realized_pnl),
                    chat_id=user.telegram_chat_id,
                    source="ai_bot" if position.source == "ai_bot" else "bot",
                    entry_price=float(position.entry_price) if position.entry_price else None,
                    exit_price=float(fill_price) if fill_price else None,
                    quantity=float(original_qty) if original_qty > 0 else None,
                    leverage=int(position.leverage) if position.leverage else None,
                    timeframe=bot.timeframe,
                )

        publish_position_update_sync(
            str(bot.user_id),
            {
                "position_id": str(position.id),
                "status": position.status,
                "action": "scale_out",
                "symbol": position.symbol,
                "level": level,
                "close_pct": float(close_pct),
            }
        )


# ──────────────────────────────────────────────────────────────
# 3. Time Exit
# ──────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="orders",
    name="app.tasks.dynamic_risk_tasks.execute_time_exit",
)
def execute_time_exit(
    self,
    position_id: str,
    reason: str,
) -> dict:
    try:
        _run_async(_execute_time_exit(
            uuid.UUID(position_id),
            reason,
        ))
        return {"status": "ok", "position_id": position_id, "action": "time_exit"}
    except Exception as exc:
        exc_str = str(exc)
        logger.error(f"Error time_exit {position_id}: {exc_str[:200]}")
        if "101205" in exc_str or "No position to close" in exc_str:
            return {"status": "skipped", "reason": "position_not_on_exchange"}
        raise self.retry(exc=exc, countdown=5 ** (self.request.retries + 1))


async def _execute_time_exit(
    position_id: uuid.UUID,
    reason: str,
) -> None:
    from app.models.bot_log import BotLog
    from app.services.cache import publish_position_update_sync
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
    from app.services.notifier import send_telegram_sync

    async with AsyncSessionLocal() as db:
        position, bot, exchange = await _load_position_bot_exchange(db, position_id)
        if not position:
            logger.warning(f"Time exit: posición {position_id} no encontrada o ya cerrada")
            return

        extra = dict(position.extra_config or {})
        if extra.get("time_decay_exited"):
            return
        extra["time_decay_exited"] = True
        position.extra_config = extra
        await db.commit()

        qty = position.quantity
        order = None
        fill_price = None
        position_already_closed = False
        try:
            order = await exchange.close_position(position.symbol, position.side, qty)
            fill_price = order.fill_price
        except Exception as exc:
            msg = str(exc)
            if "already closed" in msg.lower() or "No position to close" in msg:
                position_already_closed = True
            else:
                raise
        finally:
            await exchange.close()

        if not position_already_closed:
            pnl = (
                (fill_price - position.entry_price) * qty
                if position.side == "long"
                else (position.entry_price - fill_price) * qty
            )
            position.realized_pnl = (position.realized_pnl or Decimal("0")) + pnl
        else:
            pnl = Decimal("0")

        position.status = "closed"
        position.closed_at = datetime.now(timezone.utc)
        position.quantity = Decimal("0")
        await db.commit()

        await _save_bot_log(
            db, bot.id, "time_exit",
            f"Time decay exit @ {float(fill_price or 0):.4f}. Reason: {reason}",
            {"fill_price": float(fill_price or 0), "reason": reason},
        )
        msg = (
            f"⏰ <b>TIME DECAY EXIT</b>\n"
            f"Bot: {bot.bot_name}\n"
            f"Par: {position.symbol} | {position.side.upper()}\n"
            f"Precio cierre: {float(fill_price or 0):.4f} USDT\n"
            f"PnL: {float(pnl):+.2f} USDT\n"
            f"Motivo: {reason}"
        )
        send_telegram_sync(msg, level="essential")

        from app.models.user import User
        from app.tasks.notification_tasks import trade_closed
        user_result = await db.execute(select(User).where(User.id == bot.user_id))
        user = user_result.scalar_one_or_none()
        if user and user.telegram_chat_id and user.notify_on_close:
            trade_closed.delay(
                bot_name=bot.bot_name,
                symbol=position.symbol,
                side=position.side,
                pnl=float(position.realized_pnl),
                chat_id=user.telegram_chat_id,
                source="ai_bot" if position.source == "ai_bot" else "bot",
                entry_price=float(position.entry_price) if position.entry_price else None,
                exit_price=float(fill_price) if fill_price else None,
                quantity=float(qty) if qty else None,
                leverage=int(position.leverage) if position.leverage else None,
                timeframe=bot.timeframe,
            )

        publish_position_update_sync(
            str(bot.user_id),
            {
                "position_id": str(position.id),
                "status": "closed",
                "action": "time_exit",
                "symbol": position.symbol,
                "reason": reason,
            }
        )
