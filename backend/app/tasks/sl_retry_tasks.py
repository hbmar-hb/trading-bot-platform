"""
Reintento automático de órdenes SL pendientes.

Cuando BingX bloquea las órdenes API por volatilidad (código 109400),
el precio SL se guarda en DB con extra_config["sl_pending"].
Esta tarea se ejecuta cada 30s y reintenta colocar las órdenes pendientes.
"""
import asyncio
from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger


@shared_task(
    name="app.tasks.sl_retry_tasks.retry_pending_sl_orders",
    queue="sl_updates",
)
def retry_pending_sl_orders() -> dict:
    """Reintenta colocar en el exchange los SL que fallaron por 109400."""
    return asyncio.run(_retry_all())


async def _retry_all() -> dict:
    from decimal import Decimal
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import JSONB

    from app.exchanges.factory import create_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.position import Position
    from app.services.database import AsyncSessionLocal

    MAX_PENDING_MINUTES = 15  # Advertencia si lleva más de 15 min pendiente

    processed = 0
    succeeded = 0
    still_blocked = 0

    async with AsyncSessionLocal() as db:
        # Buscar posiciones abiertas con sl_pending en extra_config
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(
                Position.status == "open",
                Position.extra_config["sl_pending"].astext.is_not(None),
                BotConfig.exchange_account_id.is_not(None),  # solo real, no paper
            )
        )
        rows = result.all()

    for position, bot in rows:
        extra = dict(position.extra_config or {})
        pending = extra.get("sl_pending")
        if not pending:
            continue

        processed += 1
        sl_price = Decimal(str(pending["price"]))
        since = pending.get("since")

        # Advertencia si lleva demasiado tiempo pendiente
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
                elapsed = datetime.now(timezone.utc) - since_dt
                if elapsed > timedelta(minutes=MAX_PENDING_MINUTES):
                    logger.warning(
                        f"SL pendiente lleva {elapsed.seconds // 60}min sin colocarse: "
                        f"pos={position.id} {position.symbol} {position.side} "
                        f"sl={sl_price}"
                    )
            except Exception:
                pass

        # Intentar colocar el SL en el exchange
        async with AsyncSessionLocal() as db_write:
            try:
                acc_result = await db_write.execute(
                    select(ExchangeAccount).where(
                        ExchangeAccount.id == bot.exchange_account_id
                    )
                )
                account = acc_result.scalar_one()
                exchange = create_exchange(account)

                try:
                    # Cancelar SL anterior si existe, luego colocar nuevo
                    if position.exchange_sl_order_id:
                        new_order_id = await exchange.modify_stop_loss(
                            symbol=position.symbol,
                            side=position.side,
                            quantity=position.quantity,
                            old_order_id=position.exchange_sl_order_id,
                            new_sl_price=sl_price,
                        )
                    else:
                        new_order_id = await exchange.place_stop_loss(
                            symbol=position.symbol,
                            side=position.side,
                            quantity=position.quantity,
                            sl_price=sl_price,
                        )
                finally:
                    await exchange.close()

                # Éxito: limpiar pending y actualizar order_id
                pos_result = await db_write.execute(
                    select(Position).where(Position.id == position.id)
                )
                pos = pos_result.scalar_one()
                extra_upd = dict(pos.extra_config or {})
                extra_upd.pop("sl_pending", None)
                pos.extra_config = extra_upd
                pos.exchange_sl_order_id = new_order_id

                db_write.add(BotLog(
                    bot_id=bot.id,
                    event_type="sl_placed",
                    message=(
                        f"SL colocado (reintento automático): "
                        f"{position.side} {position.symbol} @ {sl_price}"
                    ),
                    metadata={
                        "sl_price": float(sl_price),
                        "order_id": new_order_id,
                        "pending_since": since,
                    },
                ))

                await db_write.commit()
                succeeded += 1
                logger.info(
                    f"SL pendiente colocado: {position.symbol} {position.side} "
                    f"@ {sl_price} (order={new_order_id})"
                )

            except Exception as exc:
                err = str(exc)
                if "109400" in err or "temporarily disabled" in err.lower():
                    still_blocked += 1
                    logger.debug(
                        f"SL sigue bloqueado por BingX: {position.symbol} {position.side}"
                    )
                else:
                    logger.error(
                        f"Error inesperado reintentando SL pos={position.id}: {exc}"
                    )

    if processed:
        logger.info(
            f"retry_pending_sl: procesadas={processed} "
            f"ok={succeeded} bloqueadas={still_blocked}"
        )

    return {"processed": processed, "succeeded": succeeded, "still_blocked": still_blocked}
