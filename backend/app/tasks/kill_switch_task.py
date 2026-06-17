"""
Kill Switch Task — cierra TODAS las posiciones abiertas de un usuario
en <10 segundos. Cancela órdenes pendientes y cierra a mercado.

Autonomous behaviour:
  - Marks bots with system_paused_by="kill_switch" and auto_resume_after.
  - A companion Celery task (auto_resume_after_kill_switch) will re-activate
    bots after a cooldown + health check, WITHOUT human intervention.

Flujo:
  1. Pausar todos los bots activos del usuario
  2. Obtener todas las posiciones abiertas
  3. Poner locks Redis para que TrailingWorker ignore estas posiciones
  4. Por cada posición:
     - Cancelar SL order
     - Cancelar TP orders (TP1, TP2, ...)
     - Cerrar posición completa a mercado
     - Actualizar DB con realized_pnl
  5. Notificar Telegram/Discord
  6. Limpiar locks
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from celery import shared_task
from loguru import logger
from sqlalchemy import select, update as sa_update, not_

from app.services.cache import publish_position_update_sync, sync_redis


_KILL_SWITCH_COOLDOWN_MINUTES = 30


@shared_task(
    queue="orders",
    name="app.tasks.kill_switch_task.execute_kill_switch",
    max_retries=0,
)
def execute_kill_switch(user_id: str) -> dict:
    return _run_async(_execute_kill_switch(user_id))


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _execute_kill_switch(user_id: str) -> dict:
    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.models.user import User
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
    from app.tasks.notification_tasks import kill_switch_alert

    start_ts = time.time()
    closed_count = 0
    errors: list[str] = []
    closed_pnl = Decimal("0")

    async with AsyncSessionLocal() as db:
        # 1. Pausar TODOS los bots activos del usuario y marcar para auto-resume
        result = await db.execute(
            sa_update(BotConfig)
            .where(BotConfig.user_id == user_id, BotConfig.status == "active")
            .values(status="paused")
        )
        paused_bots = result.rowcount

        # Mark paused bots with kill_switch metadata
        bots_paused = (
            await db.execute(
                select(BotConfig).where(
                    BotConfig.user_id == user_id,
                    BotConfig.status == "paused",
                    not_(BotConfig.bot_name.like("[MANUAL]%")),
                )
            )
        ).scalars().all()

        resume_after = datetime.now(timezone.utc) + timedelta(minutes=_KILL_SWITCH_COOLDOWN_MINUTES)
        from app.services.autonomy_state import mark_paused
        for bot in bots_paused:
            cfg = bot.ai_signal_config or {}
            autonomy = cfg.get("autonomy_state", {})
            mark_paused(autonomy, "kill_switch")
            autonomy["auto_resume_after"] = resume_after.isoformat()
            cfg["autonomy_state"] = autonomy
            bot.ai_signal_config = cfg

        # 2. Obtener TODAS las posiciones abiertas del usuario
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(BotConfig.user_id == user_id, Position.status == "open")
        )
        rows = result.all()

        if not rows:
            await db.commit()
            return {
                "status": "ok",
                "closed": 0,
                "paused_bots": paused_bots,
                "elapsed_sec": 0,
                "errors": [],
                "total_pnl": 0.0,
            }

        # 3. Lock global de kill switch para el usuario (5 min TTL)
        sync_redis.setex(f"kill_switch:active:{user_id}", 300, str(len(rows)))

        # 4. Agrupar por cuenta para reutilizar clientes exchange
        by_account: dict[tuple[str, str], list] = {}
        for position, bot in rows:
            if bot.is_paper_trading:
                key = ("paper", str(bot.paper_balance_id))
            else:
                key = ("real", str(bot.exchange_account_id))
            by_account.setdefault(key, []).append((position, bot))

        # 5. Cerrar posiciones por cuenta
        for (acc_type, acc_id), positions in by_account.items():
            exchange = None
            try:
                # Crear exchange
                if acc_type == "paper":
                    paper = await db.execute(
                        select(PaperBalance).where(PaperBalance.id == acc_id)
                    )
                    paper_balance = paper.scalar_one_or_none()
                    if not paper_balance:
                        errors.append(f"PaperBalance {acc_id} not found")
                        continue
                    from app.exchanges.paper import PaperExchange
                    exchange = PaperExchange(
                        account_id=str(paper_balance.id),
                        initial_balance=paper_balance.initial_balance,
                    )
                else:
                    acc = await db.execute(
                        select(ExchangeAccount).where(ExchangeAccount.id == acc_id)
                    )
                    account = acc.scalar_one_or_none()
                    if not account:
                        errors.append(f"ExchangeAccount {acc_id} not found")
                        continue
                    exchange = create_exchange(account)

                # Cerrar cada posición
                for position, bot in positions:
                    try:
                        # Lock por posición (60s) para que TrailingWorker la ignore
                        sync_redis.setex(
                            f"kill_switch:position:{position.id}", 60, "1"
                        )

                        # Cancelar SL
                        if position.exchange_sl_order_id:
                            try:
                                await exchange.cancel_order(
                                    position.symbol, position.exchange_sl_order_id
                                )
                            except Exception as exc:
                                logger.warning(
                                    f"[KillSwitch] Error cancelando SL "
                                    f"{position.exchange_sl_order_id}: {exc}"
                                )

                        # Cancelar TP orders
                        for tp in position.current_tp_prices or []:
                            tp_order_id = tp.get("order_id")
                            if tp_order_id:
                                try:
                                    await exchange.cancel_order(
                                        position.symbol, str(tp_order_id)
                                    )
                                except Exception as exc:
                                    logger.warning(
                                        f"[KillSwitch] Error cancelando TP "
                                        f"{tp_order_id}: {exc}"
                                    )

                        # Cerrar posición completa a mercado
                        order = await exchange.close_position(
                            position.symbol, position.side, position.quantity
                        )

                        # Calcular PnL
                        pnl = (
                            (order.fill_price - position.entry_price)
                            * position.quantity
                            if position.side == "long"
                            else (position.entry_price - order.fill_price)
                            * position.quantity
                        )
                        closed_pnl += pnl

                        # Actualizar DB
                        position.status = "closed"
                        position.closed_at = datetime.now(timezone.utc)
                        position.realized_pnl = pnl
                        for tp in position.current_tp_prices or []:
                            tp["hit"] = True

                        # Log
                        db.add(
                            BotLog(
                                bot_id=bot.id,
                                event_type="kill_switch_closed",
                                message=(
                                    f"Kill switch: posición cerrada a mercado "
                                    f"@ {order.fill_price}"
                                ),
                                metadata={
                                    "fill_price": float(order.fill_price),
                                    "realized_pnl": float(pnl),
                                    "quantity": float(position.quantity),
                                },
                            )
                        )

                        publish_position_update_sync(
                            user_id,
                            {
                                "position_id": str(position.id),
                                "status": "closed",
                                "action": "kill_switch",
                                "symbol": position.symbol,
                                "realized_pnl": float(pnl),
                            },
                        )

                        closed_count += 1
                        logger.info(
                            f"[KillSwitch] Cerrada {position.symbol} "
                            f"{position.side} @ {order.fill_price} pnl={pnl:.2f}"
                        )

                    except Exception as exc:
                        error_msg = f"{position.symbol}: {str(exc)[:200]}"
                        errors.append(error_msg)
                        logger.error(
                            f"[KillSwitch] Error cerrando posición "
                            f"{position.id}: {exc}"
                        )

            finally:
                if exchange:
                    await exchange.close()

        await db.commit()

    # 6. Limpiar locks
    sync_redis.delete(f"kill_switch:active:{user_id}")
    for position, _ in rows:
        sync_redis.delete(f"kill_switch:position:{position.id}")

    elapsed = round(time.time() - start_ts, 2)

    # 7. Notificar
    async with AsyncSessionLocal() as db_notify:
        user_result = await db_notify.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user and user.telegram_chat_id:
            kill_switch_alert.delay(
                user_name=user.username or user.email or "User",
                closed=closed_count,
                paused=paused_bots,
                pnl=float(closed_pnl),
                elapsed=elapsed,
                chat_id=user.telegram_chat_id,
            )

    logger.info(
        f"[KillSwitch] User {user_id}: cerradas={closed_count} "
        f"bots_pausados={paused_bots} pnl={closed_pnl:.2f} tiempo={elapsed}s"
    )

    return {
        "status": "ok",
        "closed": closed_count,
        "paused_bots": paused_bots,
        "elapsed_sec": elapsed,
        "errors": errors,
        "total_pnl": float(closed_pnl),
    }


@shared_task(
    name="app.tasks.kill_switch_task.auto_resume_after_kill_switch",
    queue="default",
    max_retries=0,
)
def auto_resume_after_kill_switch() -> dict:
    """
    Periodic task that auto-resumes bots paused by kill_switch after cooldown.
    Runs every 10 minutes via Celery Beat.
    """
    return _run_async(_auto_resume_async())


async def _auto_resume_async() -> dict:
    from app.models.bot_config import BotConfig
    from app.models.position import Position
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
    from app.core.conflict_validator import has_active_bot_conflict

    resumed = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        bots = (
            await db.execute(
                select(BotConfig).where(
                    BotConfig.status == "paused",
                    not_(BotConfig.bot_name.like("[MANUAL]%")),
                )
            )
        ).scalars().all()

        now = datetime.now(timezone.utc)

        for bot in bots:
            cfg = bot.ai_signal_config or {}
            autonomy = cfg.get("autonomy_state", {})
            paused_by = autonomy.get("paused_by")
            if not paused_by:
                continue

            # ── Kill Switch & Emergency Stop: require cooldown ──
            if paused_by in ("kill_switch", "emergency_stop"):
                resume_after_str = autonomy.get("auto_resume_after")
                if not resume_after_str:
                    continue
                try:
                    resume_after = datetime.fromisoformat(resume_after_str)
                    if resume_after.tzinfo is None:
                        resume_after = resume_after.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if now < resume_after:
                    skipped += 1
                    continue
                # Kill switch: ensure no open positions left
                if paused_by == "kill_switch":
                    open_count = (
                        await db.execute(
                            select(Position).where(
                                Position.bot_id == bot.id,
                                Position.status == "open",
                            )
                        )
                    ).scalars().all()
                    if open_count:
                        logger.warning(
                            f"[AUTO_RESUME] Bot {bot.bot_name} still has "
                            f"{len(open_count)} open positions after kill_switch, skipping"
                        )
                        skipped += 1
                        continue

            # ── Optimizer conflict: warn and resume anyway ──
            if paused_by == "optimizer_conflict":
                conflict = await has_active_bot_conflict(
                    db, bot.symbol, bot.exchange_account_id, exclude_bot_id=bot.id, timeframe=bot.timeframe
                )
                if conflict:
                    logger.warning(
                        f"[AUTO_RESUME] Advertencia: {bot.bot_name} se reanuda aunque existe "
                        f"{conflict.bot_name} activo para {bot.symbol}/{bot.timeframe}"
                    )

            # ── Optimizer error: retry after 15 min ──
            if paused_by == "optimizer_error":
                paused_at_str = autonomy.get("paused_at")
                if paused_at_str:
                    try:
                        paused_at = datetime.fromisoformat(paused_at_str)
                        if paused_at.tzinfo is None:
                            paused_at = paused_at.replace(tzinfo=timezone.utc)
                        if now < paused_at + timedelta(minutes=15):
                            skipped += 1
                            continue
                    except Exception:
                        pass

            # ── Verify no other blocks are active ──
            cfg = bot.ai_signal_config or {}
            if cfg.get("execution_blocked") and cfg.get("execution_blocked_reason") != paused_by:
                logger.info(
                    f"[AUTO_RESUME] Bot {bot.bot_name} has other block "
                    f"({cfg.get('execution_blocked_reason')}), skipping"
                )
                skipped += 1
                continue

            # ── Auto-resume ──
            from app.services.autonomy_state import clear_pause
            if not clear_pause(autonomy, paused_by):
                skipped += 1
                continue
            bot.status = "active"
            autonomy.pop("auto_resume_after", None)
            autonomy.pop("drawdown_paused_at", None)
            cfg["autonomy_state"] = autonomy
            bot.ai_signal_config = cfg
            resumed += 1
            logger.info(
                f"[AUTO_RESUME] Auto-resumed bot {bot.bot_name} "
                f"(was paused_by={paused_by})"
            )

        if resumed:
            await db.commit()

    return {"resumed_bots": resumed, "skipped_bots": skipped}
