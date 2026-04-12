"""
Tareas Celery para sincronización periódica de trades del exchange.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from celery import shared_task
from loguru import logger

from app.services.database import AsyncSessionLocal


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
    name="app.tasks.sync_tasks.sync_exchange_trades_task",
    queue="default",
)
def sync_exchange_trades_task(self, account_id: str, user_id: str):
    """
    Sincroniza trades de una cuenta de exchange.
    Reintenta hasta 3 veces con backoff de 5 min si falla.
    """
    logger.info(f"[SYNC] Iniciando sincronización para cuenta {account_id}")
    try:
        result = _run_async(_sync_account(uuid.UUID(account_id), uuid.UUID(user_id)))
        logger.info(f"[SYNC] Cuenta {account_id}: {result}")
        return result
    except Exception as exc:
        logger.error(f"[SYNC] Error cuenta {account_id}: {exc}")
        raise self.retry(exc=exc, countdown=300)


@shared_task(name="app.tasks.sync_tasks.sync_all_accounts_trades_task", queue="default")
def sync_all_accounts_trades_task():
    """
    Sincroniza trades de TODAS las cuentas activas.
    Se ejecuta cada hora via Celery Beat.
    Corre todo en el mismo asyncio.run para evitar problemas de event loop.
    """
    logger.info("[SYNC] Iniciando sincronización de todas las cuentas")
    try:
        result = _run_async(_sync_all_accounts())
        logger.info(f"[SYNC] Completado: {result}")
        return result
    except Exception as exc:
        logger.error(f"[SYNC] Error global: {exc}")
        return {"status": "error", "error": str(exc)}


async def _sync_all_accounts():
    from sqlalchemy import select
    from app.models.exchange_account import ExchangeAccount

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active == True)
        )
        accounts = result.scalars().all()

    logger.info(f"[SYNC] {len(accounts)} cuentas activas")

    results = []
    for account in accounts:
        try:
            r = await _sync_account(account.id, account.user_id)
            results.append({"account_id": str(account.id), **r})
        except Exception as exc:
            logger.error(f"[SYNC] Error cuenta {account.id}: {exc}")
            results.append({"account_id": str(account.id), "status": "error", "error": str(exc)})

    return {"status": "done", "accounts": len(accounts), "results": results}


async def _sync_account(account_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """
    Lógica real de sincronización para una cuenta.
    - No borra trades existentes (append-only, deduplica por exchange_trade_id)
    - Clasifica source=bot si hay posición (abierta o cerrada) que coincide en tiempo
    - Toma últimos 30 días
    """
    from sqlalchemy import select
    from app.exchanges.factory import create_exchange
    from app.models.bot_config import BotConfig
    from app.models.exchange_account import ExchangeAccount
    from app.models.exchange_trade import ExchangeTrade
    from app.models.position import Position

    async with AsyncSessionLocal() as db:
        # Verificar cuenta
        acc_result = await db.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.id == account_id,
                ExchangeAccount.user_id == user_id,
                ExchangeAccount.is_active == True,
            )
        )
        account = acc_result.scalar_one_or_none()
        if not account:
            return {"status": "skipped", "reason": "account_not_found"}

        # Calcular ventana temporal
        since_ts = int((datetime.now(timezone.utc).timestamp() - 30 * 24 * 3600) * 1000)
        since_dt = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc)

        # IDs ya en BD — para deduplicación (no borramos nada)
        existing_result = await db.execute(
            select(ExchangeTrade.exchange_trade_id).where(
                ExchangeTrade.exchange_account_id == account_id,
            )
        )
        existing_ids = {row[0] for row in existing_result.all()}
        logger.info(f"[SYNC] cuenta={account.label} existing={len(existing_ids)}")

        # Posiciones del usuario (abiertas Y cerradas) para clasificar source
        pos_result = await db.execute(
            select(Position)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(BotConfig.user_id == user_id)
        )
        positions = pos_result.scalars().all()

        # Mapear por símbolo para lookup rápido
        positions_by_symbol: dict[str, list] = {}
        for pos in positions:
            positions_by_symbol.setdefault(pos.symbol, []).append(pos)

    # Obtener trades del exchange (fuera de la sesión DB para no bloquear)
    exchange = create_exchange(account)
    try:
        trades_raw = await exchange.get_trade_history(limit=500, since=since_ts)
    finally:
        await exchange.close()

    logger.info(f"[SYNC] cuenta={account.label} raw_trades={len(trades_raw)}")

    if not trades_raw:
        return {"status": "success", "new_trades": 0, "total_from_exchange": 0}

    # Insertar nuevos trades
    new_count = 0
    async with AsyncSessionLocal() as db:
        for trade_data in trades_raw:
            try:
                trade_id = str(trade_data.get("id", ""))
                if not trade_id or trade_id in existing_ids:
                    continue

                trade_ts = trade_data.get("timestamp")
                if trade_ts and trade_ts < since_ts:
                    continue

                symbol = trade_data.get("symbol", "")
                trade_dt = (
                    datetime.fromtimestamp(trade_ts / 1000, tz=timezone.utc)
                    if trade_ts
                    else datetime.now(timezone.utc)
                )

                # Clasificar source
                source = "manual"
                position_id = None
                bot_id = None

                for pos in positions_by_symbol.get(symbol, []):
                    if pos.opened_at and pos.opened_at <= trade_dt:
                        end = pos.closed_at or datetime.now(timezone.utc)
                        if trade_dt <= end:
                            source = "bot"
                            position_id = pos.id
                            bot_id = pos.bot_id
                            break

                new_trade = ExchangeTrade(
                    user_id=user_id,
                    exchange_account_id=account_id,
                    position_id=position_id,
                    bot_id=bot_id,
                    source=source,
                    exchange_trade_id=trade_id,
                    symbol=symbol,
                    side=trade_data.get("side") or "long",
                    quantity=Decimal(str(trade_data.get("quantity") or 0)),
                    entry_price=trade_data.get("price"),
                    exit_price=trade_data.get("price"),
                    realized_pnl=trade_data.get("pnl"),
                    fee=Decimal(str(trade_data.get("fee") or 0)),
                    fee_asset=trade_data.get("fee_asset") or "USDT",
                    closed_at=trade_dt,
                    order_type=trade_data.get("order_type") or "market",
                    status="closed",
                    raw_data=str(trade_data.get("raw", {}))[:1000],
                )
                db.add(new_trade)
                new_count += 1
                existing_ids.add(trade_id)  # evitar duplicado dentro del mismo lote

            except Exception as exc:
                logger.warning(f"[SYNC] Error procesando trade {trade_data.get('id')}: {exc}")

        await db.commit()

    logger.info(f"[SYNC] cuenta={account.label} nuevos={new_count}")
    return {
        "status": "success",
        "new_trades": new_count,
        "total_from_exchange": len(trades_raw),
    }
