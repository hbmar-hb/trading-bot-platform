"""
Tareas Celery para sincronización periódica de datos.
"""
import asyncio
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger

from app.services.database import AsyncSessionLocal


@shared_task(bind=True, max_retries=3)
def sync_exchange_trades_task(self, account_id: str, user_id: str):
    """
    Sincroniza trades de un exchange periódicamente.
    Se ejecuta cada hora para mantener el historial actualizado.
    """
    logger.info(f"[SYNC] Iniciando sincronización automática para cuenta {account_id}")
    
    async def _do_sync():
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from app.models.exchange_account import ExchangeAccount
            from app.api.routes.exchange_trades import sync_trades
            
            # Verificar que la cuenta existe y está activa
            result = await db.execute(
                select(ExchangeAccount).where(
                    ExchangeAccount.id == account_id,
                    ExchangeAccount.user_id == user_id,
                    ExchangeAccount.is_active == True,
                )
            )
            account = result.scalar_one_or_none()
            
            if not account:
                logger.warning(f"[SYNC] Cuenta {account_id} no encontrada o inactiva")
                return {"status": "skipped", "reason": "account_not_found"}
            
            # Sincronizar últimos 7 días (captura trades recientes)
            try:
                # Llamar directamente a la función de sincronización
                from app.exchanges.factory import create_exchange
                from app.models.bot_config import BotConfig
                from app.models.exchange_trade import ExchangeTrade
                from app.models.position import Position
                import uuid
                from decimal import Decimal
                from datetime import datetime, timezone
                
                # Usar 30 días para sincronización automática
                since_ts = int((datetime.now(timezone.utc).timestamp() - 30 * 24 * 3600) * 1000)
                since_dt = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc)
                
                # Borrar trades antiguos del período para evitar duplicados
                await db.execute(
                    select(ExchangeTrade).where(
                        ExchangeTrade.exchange_account_id == account_id,
                        ExchangeTrade.closed_at >= since_dt,
                    )
                )
                delete_result = await db.execute(
                    select(ExchangeTrade).where(
                        ExchangeTrade.exchange_account_id == account_id,
                        ExchangeTrade.closed_at >= since_dt,
                    )
                )
                trades_to_delete = delete_result.scalars().all()
                for t in trades_to_delete:
                    await db.delete(t)
                await db.commit()
                
                # Obtener trades del exchange
                exchange = create_exchange(account)
                try:
                    trades_raw = await exchange.get_trade_history(limit=500, since=since_ts)
                finally:
                    await exchange.close()
                
                # Cargar posiciones para clasificación
                positions_result = await db.execute(
                    select(Position)
                    .join(BotConfig, Position.bot_id == BotConfig.id)
                    .where(
                        BotConfig.user_id == user_id,
                        Position.status == "open",
                    )
                )
                positions = positions_result.scalars().all()
                
                positions_by_symbol = {}
                for pos in positions:
                    key = (pos.symbol, account.exchange)
                    if key not in positions_by_symbol:
                        positions_by_symbol[key] = []
                    positions_by_symbol[key].append(pos)
                
                # Insertar nuevos trades
                new_count = 0
                for trade_data in trades_raw:
                    try:
                        trade_id = str(trade_data.get("id", ""))
                        if not trade_id:
                            continue
                        
                        symbol = trade_data.get("symbol", "")
                        trade_ts = trade_data.get("timestamp")
                        
                        # Verificar duplicado
                        existing = await db.execute(
                            select(ExchangeTrade).where(
                                ExchangeTrade.exchange_account_id == account_id,
                                ExchangeTrade.exchange_trade_id == trade_id,
                            )
                        )
                        if existing.scalar_one_or_none():
                            continue
                        
                        # Determinar source
                        source = "manual"
                        position_id = None
                        bot_id = None
                        
                        if trade_ts:
                            trade_dt = datetime.fromtimestamp(trade_ts / 1000, tz=timezone.utc)
                            pos_key = (symbol, account.exchange)
                            matching_positions = positions_by_symbol.get(pos_key, [])
                            
                            for pos in matching_positions:
                                if pos.opened_at and pos.opened_at <= trade_dt:
                                    if pos.closed_at is None or trade_dt <= pos.closed_at:
                                        source = "bot"
                                        position_id = pos.id
                                        bot_id = pos.bot_id
                                        break
                        
                        closed_at = datetime.fromtimestamp(
                            trade_ts / 1000, tz=timezone.utc
                        ) if trade_ts else datetime.now(timezone.utc)
                        
                        new_trade = ExchangeTrade(
                            id=uuid.uuid4(),
                            user_id=user_id,
                            exchange_account_id=account_id,
                            position_id=position_id,
                            bot_id=bot_id,
                            source=source,
                            exchange_trade_id=trade_id,
                            symbol=symbol,
                            side=trade_data.get("side", "long"),
                            quantity=trade_data.get("quantity", Decimal("0")),
                            entry_price=trade_data.get("price"),
                            exit_price=trade_data.get("price"),
                            realized_pnl=trade_data.get("pnl"),
                            fee=trade_data.get("fee", Decimal("0")),
                            closed_at=closed_at,
                            status="closed",
                        )
                        
                        db.add(new_trade)
                        new_count += 1
                        
                    except Exception as e:
                        logger.warning(f"[SYNC] Error procesando trade: {e}")
                        continue
                
                await db.commit()
                
                logger.info(f"[SYNC] Completado. {new_count} trades sincronizados")
                return {
                    "status": "success",
                    "account_id": account_id,
                    "new_trades": new_count,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                
            except Exception as e:
                logger.error(f"[SYNC] Error: {e}")
                raise self.retry(exc=e, countdown=300)
    
    # Ejecutar async
    return asyncio.run(_do_sync())


@shared_task
def sync_all_accounts_trades_task():
    """
    Sincroniza trades de TODAS las cuentas activas.
    Se ejecuta automáticamente cada hora.
    """
    logger.info("[SYNC] Iniciando sincronización de todas las cuentas")
    
    async def _sync_all():
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from app.models.exchange_account import ExchangeAccount
            
            result = await db.execute(
                select(ExchangeAccount).where(ExchangeAccount.is_active == True)
            )
            accounts = result.scalars().all()
            
            logger.info(f"[SYNC] Encontradas {len(accounts)} cuentas activas")
            
            results = []
            for account in accounts:
                try:
                    # Encolar tarea individual para cada cuenta
                    task_result = sync_exchange_trades_task.delay(
                        str(account.id),
                        str(account.user_id)
                    )
                    results.append({
                        "account_id": str(account.id),
                        "exchange": account.exchange,
                        "task_id": task_result.id,
                    })
                except Exception as e:
                    logger.error(f"[SYNC] Error encolando cuenta {account.id}: {e}")
            
            return {
                "status": "queued",
                "accounts": len(accounts),
                "tasks": results,
            }
    
    return asyncio.run(_sync_all())
