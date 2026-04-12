"""
Celery tasks para actualización de Stop Loss y ejecución de Take Profits.

Separadas de order_tasks para poder priorizar colas:
  sl_updates > notifications > default
"""
import asyncio
import uuid
from decimal import Decimal

from celery import shared_task
from loguru import logger


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=2,
    queue="sl_updates",
    name="app.tasks.sl_update_tasks.update_stop_loss",
)
def update_stop_loss(
    self,
    position_id: str,
    new_sl_price: float,
) -> dict:
    """
    Modifica el Stop Loss de una posición abierta en el exchange.

    Flujo:
      1. Cargar posición + bot + exchange_account de DB (sync)
      2. Llamar al exchange para cancelar SL viejo y colocar nuevo (async)
      3. Actualizar DB y logar evento
    """
    try:
        asyncio.run(_execute_sl_update(uuid.UUID(position_id), Decimal(str(new_sl_price))))
        return {"status": "ok", "position_id": position_id, "new_sl": new_sl_price}

    except Exception as exc:
        logger.error(f"Error actualizando SL posición {position_id}: {exc}")
        retry_in = 2 ** (self.request.retries + 1)   # 2, 4, 8, 16, 32 s
        raise self.retry(exc=exc, countdown=retry_in)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="orders",
    name="app.tasks.sl_update_tasks.execute_take_profit",
)
def execute_take_profit(
    self,
    position_id: str,
    tp_level: int,
    tp_price: float,
    close_percent: float,
) -> dict:
    """
    Cierra un % de la posición cuando se alcanza un TP.
    Marca el TP como hit en la DB para no ejecutarlo dos veces.
    """
    try:
        asyncio.run(_execute_tp(
            uuid.UUID(position_id),
            tp_level,
            Decimal(str(tp_price)),
            Decimal(str(close_percent)),
        ))
        return {"status": "ok", "position_id": position_id, "tp_level": tp_level}
    except Exception as exc:
        logger.error(f"Error ejecutando TP{tp_level} posición {position_id}: {exc}")
        raise self.retry(exc=exc, countdown=5 ** (self.request.retries + 1))


async def _execute_tp(
    position_id: uuid.UUID,
    tp_level: int,
    tp_price: Decimal,
    close_percent: Decimal,
) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.services.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.id == position_id, Position.status == "open")
        )
        row = result.one_or_none()
        if not row:
            logger.warning(f"Posición {position_id} no encontrada o ya cerrada")
            return

        position, bot = row

        # Verificar que este TP no esté ya marcado como hit (doble ejecución)
        tps = list(position.current_tp_prices or [])
        tp_entry = next((t for t in tps if t.get("level") == tp_level), None)
        if not tp_entry or tp_entry.get("hit"):
            logger.info(f"TP{tp_level} ya ejecutado para posición {position_id}, ignorando")
            return

        # Marcar como hit ANTES de llamar al exchange (evita doble ejecución)
        tp_entry["hit"] = True
        position.current_tp_prices = tps

        # Calcular cantidad a cerrar
        close_qty = (position.quantity * close_percent / Decimal("100")).quantize(Decimal("0.001"))

        # Crear exchange apropiado (paper o real)
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

        try:
            order = await exchange.close_position(position.symbol, position.side, close_qty)
        finally:
            await exchange.close()

        fill_price = order.fill_price

        # Actualizar cantidad restante
        position.quantity -= close_qty

        # Si se cerró el 100% o ya no queda cantidad, cerrar posición completa
        all_tps_hit = all(t.get("hit") for t in tps)
        if close_percent >= Decimal("100") or position.quantity <= Decimal("0") or all_tps_hit:
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.realized_pnl = (
                (fill_price - position.entry_price) * close_qty
                if position.side == "long"
                else (position.entry_price - fill_price) * close_qty
            )

        pnl = (
            (fill_price - position.entry_price) * close_qty
            if position.side == "long"
            else (position.entry_price - fill_price) * close_qty
        )

        db.add(BotLog(
            bot_id=bot.id,
            event_type="tp_hit",
            message=(
                f"TP{tp_level} alcanzado: cerrado {close_percent}% "
                f"a {fill_price} | PnL parcial={pnl:.2f} USDT"
            ),
            metadata={
                "tp_level":      tp_level,
                "tp_price":      float(tp_price),
                "fill_price":    float(fill_price),
                "close_percent": float(close_percent),
                "close_qty":     float(close_qty),
                "partial_pnl":   float(pnl),
            },
        ))

        await db.commit()
        logger.info(
            f"TP{tp_level} ejecutado: {position.symbol} {position.side} "
            f"cierre={close_percent}% qty={close_qty} @ {fill_price} pnl={pnl:.2f}"
        )


async def _execute_sl_update(position_id: uuid.UUID, new_sl_price: Decimal) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.services.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        # Cargar posición con bot y cuenta
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.id == position_id, Position.status == "open")
        )
        row = result.one_or_none()
        if not row:
            logger.warning(f"Posición {position_id} no encontrada o ya cerrada")
            return

        position, bot = row

        # Crear exchange apropiado (paper o real)
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
        try:
            new_order_id = await exchange.modify_stop_loss(
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                old_order_id=position.exchange_sl_order_id or "",
                new_sl_price=new_sl_price,
            )
        finally:
            await exchange.close()

        # Actualizar posición
        old_sl = position.current_sl_price
        position.current_sl_price = new_sl_price
        position.exchange_sl_order_id = new_order_id

        # Log
        db.add(BotLog(
            bot_id=bot.id,
            event_type="sl_moved",
            message=(
                f"SL actualizado: {old_sl:.4f} → {new_sl_price:.4f} "
                f"({position.side} {position.symbol})"
            ),
            metadata={
                "old_sl":    float(old_sl) if old_sl else None,
                "new_sl":    float(new_sl_price),
                "order_id":  new_order_id,
            },
        ))

        await db.commit()
        logger.info(
            f"SL actualizado: {position.symbol} {old_sl} → {new_sl_price}"
        )
