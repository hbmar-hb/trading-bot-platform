"""
Task Celery para monitorear órdenes límite pendientes y detectar cuándo se ejecutan.

Cuando una orden límite (pending_limit) se ejecuta en el exchange:
  1. Cambia su status a "open"
  2. Coloca el Stop Loss correspondiente
  3. Notifica al usuario por Telegram
"""
import asyncio
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.core import risk_manager
from app.exchanges.factory import create_exchange, create_paper_exchange
from app.models.bot_config import BotConfig
from app.models.paper_balance import PaperBalance
from app.models.position import Position
from app.models.user import User
from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    queue="orders",
    name="app.tasks.limit_order_tasks.check_limit_orders",
)
def check_limit_orders(self) -> dict:
    try:
        _run_async(_check_limit_orders())
        return {"status": "ok", "checked": True}
    except Exception as exc:
        logger.error(f"Error checking limit orders: {exc}")
        raise self.retry(exc=exc, countdown=10)


async def _check_limit_orders() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.status == "pending_limit")
        )
        rows = result.all()
        if not rows:
            return

        for position, bot in rows:
            try:
                await _process_limit_position(db, position, bot)
            except Exception as exc:
                logger.warning(f"Error procesando limit order {position.id}: {exc}")
                continue


async def _process_limit_position(db, position: Position, bot: BotConfig) -> None:
    """Verifica el estado de una orden límite y la activa si se ejecutó."""
    if bot.is_paper_trading:
        # En paper trading las órdenes límite se ejecutan inmediatamente
        await _activate_limit_position(db, position, bot, fill_price=position.entry_price)
        return

    # Exchange real: consultar si la orden sigue abierta
    from app.models.exchange_account import ExchangeAccount
    acc_result = await db.execute(
        select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
    )
    account = acc_result.scalar_one()
    exchange = create_exchange(account)

    try:
        open_orders = await exchange.get_open_orders()
        order_still_open = any(
            str(o.get("id")) == str(position.exchange_order_id)
            for o in open_orders
        )

        if order_still_open:
            return  # La orden sigue pendiente

        # La orden ya no está abierta: verificar si hay posición abierta
        open_positions = await exchange.get_open_positions()
        matching_pos = next(
            (
                p for p in open_positions
                if p.symbol == position.symbol and p.side == position.side
            ),
            None,
        )

        if matching_pos:
            await _activate_limit_position(
                db, position, bot, fill_price=matching_pos.entry_price
            )
        else:
            # Cancelada externamente
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.realized_pnl = 0
            await db.commit()
            logger.info(
                f"Orden límite {position.exchange_order_id} cancelada externamente"
            )
    finally:
        await exchange.close()


async def _activate_limit_position(
    db, position: Position, bot: BotConfig, fill_price
) -> None:
    """Marca una posición límite como abierta, coloca SL y notifica al usuario."""
    from app.tasks.notification_tasks import trade_opened

    # Calcular SL
    sl_price = risk_manager.calculate_sl_price(
        fill_price,
        position.side,
        bot.initial_sl_percentage,
        bot.leverage,
        bot.use_roi_percentage,
    )

    # Colocar SL en exchange
    exchange = None
    if bot.is_paper_trading:
        paper_balance = await db.execute(
            select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
        )
        paper_balance = paper_balance.scalar_one()
        exchange = create_paper_exchange(paper_balance)
    else:
        from app.models.exchange_account import ExchangeAccount
        acc_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
        )
        account = acc_result.scalar_one()
        exchange = create_exchange(account)

    sl_order_id = None
    try:
        sl_order_id = await exchange.place_stop_loss(
            position.symbol, position.side, position.quantity, sl_price
        )
    except Exception as exc:
        logger.warning(
            f"No se pudo colocar SL para posición limit ejecutada {position.id}: {exc}"
        )
    finally:
        if exchange:
            await exchange.close()

    # Actualizar posición
    position.status = "open"
    position.entry_price = fill_price
    position.current_sl_price = sl_price
    position.exchange_sl_order_id = sl_order_id
    await db.commit()

    # Notificar al usuario
    user_result = await db.execute(select(User).where(User.id == bot.user_id))
    user = user_result.scalar_one_or_none()
    if user and user.telegram_chat_id and user.notify_on_open:
        trade_opened.delay(
            bot_name=bot.bot_name,
            symbol=position.symbol,
            side=position.side,
            entry=float(fill_price),
            sl=float(sl_price) if sl_price else 0.0,
            chat_id=user.telegram_chat_id,
            is_limit=False,  # Ahora es una posición abierta real
        )

    logger.info(
        f"Orden límite ejecutada: {position.symbol} {position.side} @ {fill_price}"
    )
