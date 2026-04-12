import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user_id
from app.exchanges.factory import create_exchange
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.schemas.position import PositionResponse
from app.services.database import get_db

router = APIRouter(prefix="/positions", tags=["positions"])


async def _verify_position_ownership(
    position: Position, user_id: uuid.UUID, db: AsyncSession
) -> None:
    """Verifica que la posición pertenezca al usuario autenticado."""
    result = await db.execute(
        select(BotConfig).where(
            BotConfig.id == position.bot_id,
            BotConfig.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")


@router.get("", response_model=list[PositionResponse])
async def list_positions(
    status: str | None = Query(None, description="Filtrar por estado: open, closed"),
    symbol: str | None = Query(None, description="Filtrar por símbolo"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Lista posiciones del usuario con filtros opcionales."""
    query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(BotConfig.user_id == user_id)
        .order_by(Position.opened_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if status:
        query = query.where(Position.status == status)
    if symbol:
        query = query.where(Position.symbol == symbol.upper())

    result = await db.execute(query)
    return result.scalars().all()


class UnifiedPositionResponse(BaseModel):
    """Posición unificada - puede ser de bot, paper o manual (externa)."""
    # Identificación
    id: str | None = None  # UUID para posiciones de bot/paper, None para manuales
    source: str  # "bot", "paper", "manual"
    
    # Datos de la posición
    symbol: str
    side: str
    entry_price: float
    quantity: float
    leverage: int | None = None
    
    # Stop Loss y Take Profits
    current_sl_price: float | None = None
    current_tp_prices: list = []
    
    # P&L
    unrealized_pnl: float
    realized_pnl: float | None = None
    
    # Estado
    status: str = "open"
    opened_at: datetime | None = None
    
    # Info adicional
    exchange: str
    bot_name: str | None = None  # Nombre del bot (si aplica)
    exchange_position_id: str | None = None
    is_external: bool = False
    account_id: str | None = None  # ID de la cuenta de exchange (para cierre manual)
    
    class Config:
        from_attributes = True


@router.get("/unified", response_model=list[UnifiedPositionResponse])
async def list_unified_positions(
    include_manual: bool = Query(True, description="Incluir posiciones manuales del exchange"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista TODAS las posiciones abiertas del usuario en un solo lugar:
    - Posiciones de bots (reales)
    - Posiciones de paper trading
    - Posiciones manuales abiertas directamente en el exchange
    
    Cada posición tiene un campo 'source' que indica su origen:
    - "bot": Abierta por un bot de la plataforma
    - "paper": Simulación de paper trading
    - "manual": Abierta manualmente en el exchange (BingX, etc.)
    """
    from loguru import logger
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    
    logger.info(f"[UNIFIED POSITIONS] User {user_id}, include_manual={include_manual}")
    
    try:
        unified_positions = []
        
        # ═══════════════════════════════════════════════════════════
        # 1. POSICIONES DE BOTS (reales)
        # ═══════════════════════════════════════════════════════════
        result_bots = await db.execute(
            select(Position, BotConfig, ExchangeAccount)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .outerjoin(ExchangeAccount, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(
                BotConfig.user_id == user_id,
                Position.status.in_(["open", "pending_limit"]),
                BotConfig.exchange_account_id.is_not(None),  # Solo reales, no paper
            )
            .order_by(Position.opened_at.desc())
        )
        
        for position, bot, account in result_bots.all():
            # Detectar si es manual app (prefijo [MANUAL]) o bot real
            is_app_manual = bot.bot_name.startswith("[MANUAL]")
            source = "app_manual" if is_app_manual else "bot"
            
            unified_positions.append(UnifiedPositionResponse(
                id=str(position.id),
                source=source,
                symbol=position.symbol,
                side=position.side,
                entry_price=float(position.entry_price),
                quantity=float(position.quantity),
                leverage=position.leverage,
                current_sl_price=float(position.current_sl_price) if position.current_sl_price else None,
                current_tp_prices=position.current_tp_prices or [],
                unrealized_pnl=float(position.unrealized_pnl),
                realized_pnl=float(position.realized_pnl) if position.realized_pnl else None,
                status=position.status,
                opened_at=position.opened_at,
                exchange=account.exchange if account else "unknown",
                bot_name=bot.bot_name,
                exchange_position_id=position.exchange_order_id,
                is_external=False,
                account_id=str(bot.exchange_account_id) if bot.exchange_account_id else None,
            ))
        
        logger.info(f"[UNIFIED POSITIONS] {len(unified_positions)} posiciones de bots")
        
        # ═══════════════════════════════════════════════════════════
        # 2. POSICIONES DE PAPER TRADING
        # ═══════════════════════════════════════════════════════════
        result_paper = await db.execute(
            select(Position, BotConfig, PaperBalance)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(PaperBalance, BotConfig.paper_balance_id == PaperBalance.id)
            .where(
                BotConfig.user_id == user_id,
                Position.status == "open",
                BotConfig.paper_balance_id.is_not(None),
            )
            .order_by(Position.opened_at.desc())
        )
        
        for position, bot, paper_balance in result_paper.all():
            unified_positions.append(UnifiedPositionResponse(
                id=str(position.id),
                source="paper",
                symbol=position.symbol,
                side=position.side,
                entry_price=float(position.entry_price),
                quantity=float(position.quantity),
                leverage=position.leverage,
                current_sl_price=float(position.current_sl_price) if position.current_sl_price else None,
                current_tp_prices=position.current_tp_prices or [],
                unrealized_pnl=float(position.unrealized_pnl),
                realized_pnl=float(position.realized_pnl) if position.realized_pnl else None,
                status=position.status,
                opened_at=position.opened_at,
                exchange="paper",
                bot_name=f"{bot.bot_name} ({paper_balance.label})",
                exchange_position_id=position.exchange_order_id,
                is_external=False,
            ))
        
        logger.info(f"[UNIFIED POSITIONS] Total tras paper: {len(unified_positions)}")
        
        # ═══════════════════════════════════════════════════════════
        # 3. POSICIONES MANUALES (externas del exchange)
        # ═══════════════════════════════════════════════════════════
        if include_manual:
            # Obtener todas las cuentas de exchange del usuario
            accounts_result = await db.execute(
                select(ExchangeAccount)
                .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
            )
            accounts = accounts_result.scalars().all()
            
            for account in accounts:
                exchange = None
                try:
                    exchange = create_exchange(account)
                    live_positions = await exchange.get_open_positions()
                    logger.info(f"[UNIFIED POSITIONS] {account.exchange}: {len(live_positions)} posiciones abiertas desde exchange")
                    for pos in live_positions:
                        logger.info(f"  - {pos.symbol} {pos.side} qty={pos.quantity} id={pos.exchange_position_id}")
                    
                    # Símbolos ya gestionados por bots en esta cuenta
                    db_symbols = {
                        (p.symbol, p.side) for p in unified_positions
                        if p.exchange == account.exchange
                    }
                    
                    # IDs de posiciones ya registradas (para evitar duplicados del exchange)
                    seen_position_ids = {
                        p.exchange_position_id for p in unified_positions
                        if p.exchange_position_id and p.exchange == account.exchange
                    }
                    
                    for pos in live_positions:
                        # Saltar si ya está gestionada por un bot (mismo símbolo+lado)
                        if (pos.symbol, pos.side) in db_symbols:
                            logger.info(f"[UNIFIED POSITIONS] Saltando duplicado: {pos.symbol} {pos.side} ya gestionado por bot")
                            continue
                        # Saltar si ya vimos esta posición del exchange (duplicado de API)
                        if pos.exchange_position_id in seen_position_ids:
                            logger.info(f"[UNIFIED POSITIONS] Saltando duplicado API: {pos.symbol} {pos.side} ID={pos.exchange_position_id}")
                            continue
                        seen_position_ids.add(pos.exchange_position_id)
                        unified_positions.append(UnifiedPositionResponse(
                            id=None,
                            source="manual",
                            symbol=pos.symbol,
                            side=pos.side,
                            entry_price=float(pos.entry_price or 0),
                            quantity=float(pos.quantity or 0),
                            leverage=None,
                            current_sl_price=None,
                            current_tp_prices=[],
                            unrealized_pnl=float(pos.unrealized_pnl or 0),
                            realized_pnl=None,
                            status="open",
                            opened_at=None,
                            exchange=account.exchange,
                            bot_name=None,
                            exchange_position_id=pos.exchange_position_id,
                            is_external=True,
                            account_id=str(account.id),
                        ))

                    # 3b. Órdenes limit abiertas (pendientes de ejecución)
                    open_orders = await exchange.get_open_orders()
                    # IDs de órdenes limit ya registradas en DB (para evitar duplicados)
                    db_limit_order_ids = {
                        p.exchange_position_id for p in unified_positions
                        if p.status == "pending_limit" and p.exchange_position_id
                    }
                    for order in open_orders:
                        if order["id"] in db_limit_order_ids:
                            continue
                        unified_positions.append(UnifiedPositionResponse(
                            id=None,
                            source="manual",
                            symbol=order["symbol"],
                            side=order["side"],
                            entry_price=float(order["price"]),
                            quantity=float(order["quantity"]),
                            leverage=None,
                            unrealized_pnl=0.0,
                            realized_pnl=None,
                            status="pending_limit",
                            opened_at=None,
                            exchange=account.exchange,
                            bot_name=None,
                            exchange_position_id=order["id"],
                            is_external=True,
                            account_id=str(account.id),
                        ))

                except Exception as e:
                    logger.error(f"[UNIFIED POSITIONS] Error consultando {account.label} ({account.exchange}): {type(e).__name__}: {str(e)[:300]}")
                    continue
                finally:
                    if exchange is not None:
                        try:
                            await exchange.close()
                        except Exception:
                            pass
        
        logger.info(f"[UNIFIED POSITIONS] Total final: {len(unified_positions)}")
        
        # Ordenar por símbolo (o podríamos ordenar por opened_at si quisiéramos)
        unified_positions.sort(key=lambda x: x.symbol)
        
        return unified_positions
        
    except Exception as e:
        logger.exception(f"[UNIFIED POSITIONS] ERROR CRÍTICO: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)[:200]}")


@router.get("/open", response_model=list[PositionResponse])
async def list_open_positions(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Shortcut: todas las posiciones abiertas del usuario (solo bots/paper)."""
    result = await db.execute(
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(BotConfig.user_id == user_id, Position.status == "open")
        .order_by(Position.opened_at.desc())
    )
    return result.scalars().all()


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")

    await _verify_position_ownership(position, user_id, db)
    return position


class UpdateSLRequest(BaseModel):
    sl_price: float


@router.patch("/{position_id}/sl", response_model=PositionResponse)
async def update_stop_loss(
    position_id: uuid.UUID,
    data: UpdateSLRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Actualiza el stop loss de una posición abierta."""
    from decimal import Decimal
    from loguru import logger
    
    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")
    
    await _verify_position_ownership(position, user_id, db)
    
    # Obtener el bot y su exchange
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == position.bot_id)
    )
    bot = bot_result.scalar_one()
    
    if bot.exchange_account_id:
        # Exchange real - cargar cuenta directamente
        from app.models.exchange_account import ExchangeAccount
        account_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
        )
        account = account_result.scalar_one()
        exchange = create_exchange(account)
    else:
        # Paper trading - no hay SL real que actualizar
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede actualizar SL en paper trading")
    
    try:
        # Actualizar SL en el exchange (cancelar y recrear)
        if position.exchange_sl_order_id:
            await exchange.modify_stop_loss(
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                old_order_id=position.exchange_sl_order_id,
                new_sl_price=Decimal(str(data.sl_price)),
            )
        else:
            # No hay SL previo, crear uno nuevo
            position.exchange_sl_order_id = await exchange.place_stop_loss(
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                sl_price=Decimal(str(data.sl_price)),
            )
        
        # Actualizar en DB
        position.current_sl_price = Decimal(str(data.sl_price))
        await db.commit()
        await db.refresh(position)
        
        logger.info(f"SL actualizado para posición {position_id}: {data.sl_price}")
        return position
        
    except Exception as e:
        logger.error(f"Error actualizando SL: {e}")
        err_str = str(e)
        # BingX código 109400: órdenes API temporalmente desactivadas por volatilidad
        if "109400" in err_str or "temporarily disabled" in err_str.lower():
            # Guardar precio en DB y marcar como pendiente de envío al exchange
            from datetime import datetime, timezone
            extra = dict(position.extra_config or {})
            extra["sl_pending"] = {
                "price": float(data.sl_price),
                "since": datetime.now(timezone.utc).isoformat(),
            }
            position.extra_config = extra
            position.current_sl_price = Decimal(str(data.sl_price))
            await db.commit()
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "BingX ha desactivado temporalmente las órdenes API por alta volatilidad. "
                "El precio SL se ha guardado y se enviará al exchange automáticamente "
                "en cuanto BingX lo permita (reintentos cada 30s)."
            )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, err_str)
    finally:
        await exchange.close()


@router.get("/external/{account_id}")
async def get_external_positions(
    account_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Obtiene posiciones abiertas directamente desde el exchange (manuales)."""
    from app.models.exchange_account import ExchangeAccount
    from loguru import logger
    
    # Verificar que la cuenta pertenece al usuario
    result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id,
            ExchangeAccount.user_id == user_id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    
    try:
        exchange = create_exchange(account)
        positions = await exchange.get_open_positions()
        await exchange.close()
        
        return {
            "exchange": account.exchange,
            "count": len(positions),
            "positions": [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "entry_price": float(p.entry_price),
                    "quantity": float(p.quantity),
                    "unrealized_pnl": float(p.unrealized_pnl),
                    "exchange_position_id": p.exchange_position_id,
                }
                for p in positions
            ],
        }
    except Exception as e:
        logger.error(f"Error obteniendo posiciones externas: {e}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error del exchange: {str(e)}")


class ExternalCloseRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    exchange_position_id: str | None = None


@router.post("/external/close")
async def close_external_position(
    data: ExternalCloseRequest,
    account_id: uuid.UUID = Query(..., description="ID de la cuenta de exchange"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Cierra una posición manual abierta directamente en el exchange.
    No requiere que la posición exista en nuestra base de datos.
    """
    from decimal import Decimal
    from app.models.exchange_account import ExchangeAccount
    from loguru import logger
    
    # Verificar que la cuenta pertenece al usuario
    result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id,
            ExchangeAccount.user_id == user_id,
            ExchangeAccount.is_active == True,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    
    try:
        exchange = create_exchange(account)
        
        # Cerrar posición en el exchange
        await exchange.close_position(
            symbol=data.symbol,
            side=data.side,
            quantity=Decimal(str(data.quantity)),
        )
        await exchange.close()
        
        logger.info(f"[EXTERNAL CLOSE] Posición cerrada: {data.symbol} {data.side} qty={data.quantity}")
        return {"status": "success", "message": f"Posición {data.symbol} cerrada en {account.exchange}"}
        
    except Exception as e:
        logger.error(f"[EXTERNAL CLOSE] Error: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Error cerrando posición: {str(e)}")


@router.post("/external/partial-close")
async def partial_close_external_position(
    data: ExternalCloseRequest,
    percentage: float = Query(..., ge=0, le=100, description="Porcentaje a cerrar"),
    account_id: uuid.UUID = Query(..., description="ID de la cuenta de exchange"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Cierra un porcentaje de una posición manual del exchange.
    """
    from decimal import Decimal, ROUND_DOWN
    from app.models.exchange_account import ExchangeAccount
    from loguru import logger
    
    # Verificar cuenta
    result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id,
            ExchangeAccount.user_id == user_id,
            ExchangeAccount.is_active == True,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
    
    # Calcular cantidad a cerrar
    close_qty = (Decimal(str(data.quantity)) * Decimal(str(percentage)) / 100).quantize(
        Decimal("0.00001"), rounding=ROUND_DOWN
    )
    
    if close_qty <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cantidad a cerrar demasiado pequeña")
    
    try:
        exchange = create_exchange(account)
        await exchange.close_position(
            symbol=data.symbol,
            side=data.side,
            quantity=close_qty,
            position_id=data.exchange_position_id,
        )
        await exchange.close()
        
        remaining = Decimal(str(data.quantity)) - close_qty
        logger.info(f"[EXTERNAL PARTIAL] {data.symbol} cerrado {percentage}%")
        return {
            "status": "success",
            "closed_percentage": percentage,
            "closed_quantity": float(close_qty),
            "remaining_quantity": float(remaining),
        }
        
    except Exception as e:
        logger.error(f"[EXTERNAL PARTIAL] Error: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Error: {str(e)}")


@router.post("/{position_id}/partial-close")
async def partial_close_position(
    position_id: uuid.UUID,
    percentage: float = Query(..., ge=0, le=100, description="Porcentaje a cerrar (0-100)"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Cierra un porcentaje de la posición."""
    from decimal import Decimal, ROUND_DOWN
    from loguru import logger
    
    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")

    await _verify_position_ownership(position, user_id, db)

    # Obtener información del bot
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == position.bot_id)
    )
    bot = bot_result.scalar_one()
    
    # Calcular cantidad a cerrar
    close_quantity = (position.quantity * Decimal(str(percentage)) / 100).quantize(
        Decimal("0.00001"), rounding=ROUND_DOWN
    )

    if close_quantity <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cantidad a cerrar demasiado pequeña")

    try:
        if bot.exchange_account_id:
            # Exchange real
            from app.models.exchange_account import ExchangeAccount
            account_result = await db.execute(
                select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
            )
            account = account_result.scalar_one_or_none()
            if not account:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta de exchange no encontrada")
            exchange = create_exchange(account)
            
            try:
                # Cerrar posición parcial
                await exchange.close_position(
                    symbol=position.symbol,
                    side=position.side,
                    quantity=close_quantity,
                )
            finally:
                await exchange.close()
        else:
            # Paper trading
            from app.exchanges.paper import PaperExchange
            from app.models.paper_balance import PaperBalance
            
            paper_result = await db.execute(
                select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
            )
            paper_balance = paper_result.scalar_one_or_none()
            if not paper_balance:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta paper no encontrada")
            exchange = PaperExchange(
                account_id=paper_balance.account_id,
                initial_balance=float(paper_balance.initial_balance)
            )
            
            await exchange.close_position(
                symbol=position.symbol,
                side=position.side,
                quantity=close_quantity,
            )

        # Actualizar cantidad en DB
        position.quantity -= close_quantity
        if position.quantity <= 0:
            position.status = "closed"
            position.closed_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(position)

        logger.info(f"Posición {position_id} cerrada parcialmente: {percentage}%")
        return {"status": "success", "closed_percentage": percentage, "remaining_quantity": float(position.quantity)}

    except Exception as e:
        logger.error(f"Error en cierre parcial: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.post("/{position_id}/close")
async def close_position(
    position_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Cierra la posición completa."""
    from loguru import logger
    
    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")

    await _verify_position_ownership(position, user_id, db)

    # Obtener información del bot
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == position.bot_id)
    )
    bot = bot_result.scalar_one()

    try:
        if bot.exchange_account_id:
            # Exchange real - cargar cuenta directamente por ID
            from app.models.exchange_account import ExchangeAccount
            
            logger.info(f"[CLOSE] Cargando exchange account {bot.exchange_account_id} para bot {bot.id}")
            account_result = await db.execute(
                select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
            )
            account = account_result.scalar_one_or_none()
            if not account:
                logger.error(f"[CLOSE] No se encontró cuenta {bot.exchange_account_id}")
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta de exchange no encontrada")
            
            logger.info(f"[CLOSE] Usando cuenta {account.exchange} - {account.label}")
            exchange = create_exchange(account)
            
            try:
                await exchange.close_position(
                    symbol=position.symbol,
                    side=position.side,
                    quantity=position.quantity,
                )
            finally:
                await exchange.close()
        else:
            # Paper trading
            from app.exchanges.paper import PaperExchange
            from app.models.paper_balance import PaperBalance
            
            logger.info(f"[CLOSE] Cargando paper balance {bot.paper_balance_id} para bot {bot.id}")
            paper_result = await db.execute(
                select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
            )
            paper_balance = paper_result.scalar_one_or_none()
            if not paper_balance:
                logger.error(f"[CLOSE] No se encontró paper balance {bot.paper_balance_id}")
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta paper no encontrada")
            
            exchange = PaperExchange(
                account_id=paper_balance.account_id,
                initial_balance=float(paper_balance.initial_balance)
            )
            
            await exchange.close_position(
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
            )

        # Marcar como cerrada
        position.status = "closed"
        position.closed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(position)

        logger.info(f"Posición {position_id} cerrada completamente")
        return {"status": "success", "message": "Posición cerrada"}

    except Exception as e:
        logger.error(f"Error cerrando posición: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.post("/{position_id}/sync-status")
async def sync_position_status(
    position_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Sincroniza el estado de una posición con el exchange.
    Si la posición ya no existe en el exchange (cerrada manualmente),
    la marca como cerrada en la base de datos.
    """
    from loguru import logger
    from app.models.exchange_account import ExchangeAccount
    from app.exchanges.factory import create_exchange
    
    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")

    await _verify_position_ownership(position, user_id, db)
    
    if position.status != "open":
        return {"status": "already_closed", "message": "La posición ya está cerrada"}

    # Obtener información del bot y cuenta
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == position.bot_id)
    )
    bot = bot_result.scalar_one()
    
    if not bot.exchange_account_id:
        # Paper trading - no hay exchange externo que verificar
        return {"status": "paper", "message": "Posición paper - no requiere sincronización"}
    
    try:
        # Cargar cuenta de exchange
        account_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
        )
        account = account_result.scalar_one()
        
        # Consultar posiciones abiertas en el exchange
        exchange = create_exchange(account)
        try:
            live_positions = await exchange.get_open_positions()
            
            # Buscar si la posición sigue abierta en el exchange
            still_open = False
            for lp in live_positions:
                if lp.symbol == position.symbol and lp.side == position.side:
                    # Calcular diferencia de cantidad para detectar cierre parcial
                    qty_diff = abs(float(lp.quantity) - float(position.quantity))
                    if qty_diff < 0.001:  # Misma cantidad (aprox)
                        still_open = True
                        break
            
            if still_open:
                return {"status": "open", "message": "La posición sigue abierta en el exchange"}
            else:
                # Posición ya no existe en exchange, marcar como cerrada
                position.status = "closed"
                position.closed_at = datetime.utcnow()
                await db.commit()
                logger.info(f"[SYNC] Posición {position_id} marcada como cerrada (no encontrada en exchange)")
                return {"status": "closed", "message": "Posición sincronizada: marcada como cerrada"}
                
        finally:
            await exchange.close()
            
    except Exception as e:
        logger.error(f"[SYNC] Error sincronizando posición: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Error sincronizando: {str(e)}")


VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w"}

@router.get("/{position_id}/candles")
async def get_position_candles(
    position_id: uuid.UUID,
    limit: int = Query(200, ge=10, le=500),
    timeframe: str = Query("15m"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Velas OHLCV para el gráfico de una posición.
    Funciona para bots, app_manual y paper trading.
    """
    import ccxt.async_support as ccxt
    from app.models.exchange_account import ExchangeAccount
    
    # Obtener la posición y su bot
    result = await db.execute(
        select(Position, BotConfig)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(Position.id == position_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")
    
    position, bot = row
    
    # Verificar propiedad
    if bot.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")
    
    # Validar timeframe
    tf = timeframe if timeframe in VALID_TIMEFRAMES else (bot.timeframe if bot.timeframe in VALID_TIMEFRAMES else "1h")
    
    # Determinar exchange para obtener precios
    if bot.paper_balance_id:
        # Paper trading - usar Binance como fuente de precios
        exchange_name = "binance"
    else:
        # Exchange real
        account_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")
        
        exchange_name = account.exchange
        if exchange_name == "bitunix":
            exchange_name = "bingx"  # Proxy
    
    # Obtener velas
    client = getattr(ccxt, exchange_name)({"options": {"defaultType": "swap"}})
    try:
        ohlcv = await client.fetch_ohlcv(position.symbol, tf, limit=limit)
        candles = [
            {"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in ohlcv
        ]
        return candles
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error del exchange: {str(e)}")
    finally:
        await client.close()


@router.delete("/{position_id}/cancel-limit")
async def cancel_limit_order(
    position_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Cancela una orden limit pendiente y marca la posición como cerrada."""
    from loguru import logger
    from app.models.exchange_account import ExchangeAccount
    from app.exchanges.factory import create_exchange

    # Verificar que la posición existe y pertenece al usuario
    result = await db.execute(
        select(Position, BotConfig)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            Position.id == position_id,
            Position.status == "pending_limit",
            BotConfig.user_id == user_id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Orden limit pendiente no encontrada")

    position, bot = row

    # Cancelar en el exchange si tenemos orden ID
    if position.exchange_order_id and bot.exchange_account_id:
        acc_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
        )
        account = acc_result.scalar_one_or_none()
        if account:
            exchange = None
            try:
                exchange = create_exchange(account)
                cancelled = await exchange.cancel_order(position.symbol, position.exchange_order_id)
                logger.info(f"[CANCEL LIMIT] Orden {position.exchange_order_id} cancelada en exchange: {cancelled}")
            except Exception as e:
                logger.warning(f"[CANCEL LIMIT] Error cancelando en exchange: {e}")
            finally:
                if exchange:
                    try:
                        await exchange.close()
                    except Exception:
                        pass

    # Marcar posición como cerrada en DB
    from datetime import datetime, timezone
    position.status = "closed"
    position.closed_at = datetime.now(timezone.utc)
    position.realized_pnl = 0
    await db.commit()

    logger.info(f"[CANCEL LIMIT] Posición {position_id} ({position.symbol}) cancelada")
    return {"status": "cancelled", "position_id": str(position_id)}


@router.delete("/external/cancel-limit")
async def cancel_external_limit_order(
    order_id: str = Query(...),
    symbol: str = Query(...),
    account_id: uuid.UUID = Query(...),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Cancela una orden limit externa (sin registro en DB) directamente en el exchange."""
    from loguru import logger
    from app.models.exchange_account import ExchangeAccount
    from app.exchanges.factory import create_exchange

    acc_result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id,
            ExchangeAccount.user_id == user_id,
            ExchangeAccount.is_active == True,
        )
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")

    exchange = None
    try:
        exchange = create_exchange(account)
        cancelled = await exchange.cancel_order(symbol, order_id)
        logger.info(f"[CANCEL EXT LIMIT] Orden {order_id} ({symbol}) cancelada: {cancelled}")
        return {"status": "cancelled", "order_id": order_id}
    except Exception as e:
        logger.error(f"[CANCEL EXT LIMIT] Error: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Error cancelando: {str(e)}")
    finally:
        if exchange:
            try:
                await exchange.close()
            except Exception:
                pass
