import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_authorized_user, get_current_user_id
from app.exchanges.factory import create_exchange
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.schemas.position import PositionResponse
from app.services.cache import async_redis, publish_position_update
from app.services.database import get_db

router = APIRouter(prefix="/positions", tags=["positions"], dependencies=[Depends(get_current_authorized_user)])


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
    source: str  # "bot_int" | "bot_ext" | "ai_bot" | "app_manual" | "paper" | "manual"
    
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
    bot_name: str | None = None
    exchange_position_id: str | None = None
    is_external: bool = False
    account_id: str | None = None
    extra_config: dict | None = None
    # Configuración de riesgo del bot (solo para posiciones con bot)
    trailing_config: dict | None = None
    breakeven_config: dict | None = None
    dynamic_sl_config: dict | None = None
    use_roi_percentage: bool | None = None
    
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
    - "bot_int": Abierta por bot con señal interna (indicador)
    - "bot_ext": Abierta por bot con señal externa (webhook)
    - "ai_bot": Abierta por bot IA
    - "app_manual": Abierta manualmente desde la app
    - "paper": Paper trading
    - "manual": Abierta directamente en el exchange
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
        
        # Precios actuales de Redis para calcular PnL en tiempo real
        bot_rows = result_bots.all()
        bot_symbols = list({r[0].symbol for r in bot_rows})
        if bot_symbols:
            price_keys = [f"price:{s}" for s in bot_symbols]
            price_vals = await async_redis.mget(*price_keys)
            price_map = {s: float(v) for s, v in zip(bot_symbols, price_vals) if v is not None}
        else:
            price_map = {}
        
        for position, bot, account in bot_rows:
            # Usar source guardado en la posición (nuevo: bot_int / bot_ext / ai_bot / app_manual)
            # Fallback para datos antiguos que aún tengan source="bot"
            if bot.bot_name.startswith("[MANUAL]"):
                source = "app_manual"
            elif position.source and position.source not in ("bot", "manual"):
                source = position.source
            elif position.source == "bot":
                # Datos antiguos sin distinción int/ext
                source = "bot"
            elif getattr(bot, "ai_signal_mode", False):
                # Fallback legacy: bot con ai_signal_mode pero posición sin source ai_bot
                source = "ai_bot"
            else:
                # Default
                source = "bot_ext"
            
            # Calcular PnL en tiempo real con precio actual de Redis
            current_price = price_map.get(position.symbol)
            if current_price:
                entry = float(position.entry_price)
                qty = float(position.quantity)
                if position.side == "long":
                    live_pnl = (current_price - entry) * qty
                else:
                    live_pnl = (entry - current_price) * qty
            else:
                live_pnl = float(position.unrealized_pnl)
            
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
                unrealized_pnl=live_pnl,
                realized_pnl=float(position.realized_pnl) if position.realized_pnl else None,
                status=position.status,
                opened_at=position.opened_at,
                exchange=account.exchange if account else "unknown",
                bot_name=bot.bot_name,
                exchange_position_id=position.exchange_order_id,
                is_external=False,
                account_id=str(bot.exchange_account_id) if bot.exchange_account_id else None,
                extra_config=position.extra_config,
                trailing_config=bot.trailing_config or None,
                breakeven_config=bot.breakeven_config or None,
                dynamic_sl_config=bot.dynamic_sl_config or None,
                use_roi_percentage=bot.use_roi_percentage,
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
        
        paper_rows = result_paper.all()
        paper_symbols = list({r[0].symbol for r in paper_rows})
        for s in paper_symbols:
            if s not in price_map:
                val = await async_redis.get(f"price:{s}")
                if val:
                    price_map[s] = float(val)
        
        for position, bot, paper_balance in paper_rows:
            current_price = price_map.get(position.symbol)
            if current_price:
                entry = float(position.entry_price)
                qty = float(position.quantity)
                if position.side == "long":
                    live_pnl = (current_price - entry) * qty
                else:
                    live_pnl = (entry - current_price) * qty
            else:
                live_pnl = float(position.unrealized_pnl)
            
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
                unrealized_pnl=live_pnl,
                realized_pnl=float(position.realized_pnl) if position.realized_pnl else None,
                status=position.status,
                opened_at=position.opened_at,
                exchange="paper",
                bot_name=f"{bot.bot_name} ({paper_balance.label})",
                exchange_position_id=position.exchange_order_id,
                is_external=False,
                trailing_config=bot.trailing_config or None,
                breakeven_config=bot.breakeven_config or None,
                dynamic_sl_config=bot.dynamic_sl_config or None,
                use_roi_percentage=bot.use_roi_percentage,
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
                            source="orphan",
                            symbol=pos.symbol,
                            side=pos.side,
                            entry_price=float(pos.entry_price or 0),
                            quantity=float(pos.quantity or 0),
                            leverage=pos.leverage,
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
        
        # Deduplicar posiciones del mismo bot en el mismo par+lado
        # (protección contra duplicados históricos, ej. bug de paper trading)
        deduped = {}
        duplicates_found = 0
        for p in unified_positions:
            # Solo deduplicar posiciones con bot (tienen bot_name)
            key = None
            if p.bot_name and p.source != "manual":
                key = (p.symbol, p.bot_name, p.side)
            if key:
                existing = deduped.get(key)
                if existing:
                    # Quedarse con la más reciente; si no hay opened_at, mantener la actual
                    if p.opened_at and existing.opened_at:
                        if p.opened_at > existing.opened_at:
                            deduped[key] = p
                            duplicates_found += 1
                    else:
                        # Sin fecha: preferir la que tenga leverage (más completa)
                        if p.leverage and not existing.leverage:
                            deduped[key] = p
                            duplicates_found += 1
                else:
                    deduped[key] = p
            else:
                # Posiciones manuales/external: usar índice único para no perder ninguna
                deduped[id(p)] = p
        
        if duplicates_found:
            logger.warning(f"[UNIFIED POSITIONS] {duplicates_found} posiciones duplicadas omitidas (misma bot+par+lado)")
        
        unified_positions = list(deduped.values())
        logger.info(f"[UNIFIED POSITIONS] Total final tras dedup: {len(unified_positions)}")
        
        # Guardar en Redis los símbolos de posiciones manuales externas
        # para que el price_monitor también los vigile.
        manual_symbols = [
            {"exchange": p.exchange, "symbol": p.symbol}
            for p in unified_positions
            if p.source == "manual" and p.status == "open"
        ]
        try:
            if manual_symbols:
                await async_redis.setex("manual_position_symbols", 60, json.dumps(manual_symbols))
            else:
                await async_redis.delete("manual_position_symbols")
        except Exception as e:
            logger.warning(f"[UNIFIED POSITIONS] Error guardando manual symbols en Redis: {e}")
        
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
    from app.models.bot_config import BotConfig

    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")

    await _verify_position_ownership(position, user_id, db)

    # Cargar config de riesgo del bot para mostrar en el frontend
    bot = None
    if position.bot_id:
        bot_result = await db.execute(select(BotConfig).where(BotConfig.id == position.bot_id))
        bot = bot_result.scalar_one_or_none()

    response = PositionResponse.model_validate(position)
    if bot:
        response.trailing_config = bot.trailing_config or None
        response.breakeven_config = bot.breakeven_config or None
        response.dynamic_sl_config = bot.dynamic_sl_config or None
        response.use_roi_percentage = bot.use_roi_percentage
    return response


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
    
    if bot.is_paper_trading:
        # Paper trading — solo actualizar DB, no hay exchange
        position.current_sl_price = Decimal(str(data.sl_price))
        await db.commit()
        await db.refresh(position)
        await publish_position_update(
            str(user_id),
            {"position_id": str(position_id), "status": position.status, "current_sl_price": float(position.current_sl_price)}
        )
        logger.info(f"[PAPER] SL actualizado para posición {position_id}: {data.sl_price}")
        return position

    # Exchange real
    from app.models.exchange_account import ExchangeAccount
    account_result = await db.execute(
        select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
    )
    account = account_result.scalar_one()
    exchange = create_exchange(account)

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
        await publish_position_update(
            str(user_id),
            {"position_id": str(position_id), "status": position.status, "current_sl_price": float(position.current_sl_price)}
        )

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
            await publish_position_update(
                str(user_id),
                {"position_id": str(position_id), "status": position.status, "current_sl_price": float(position.current_sl_price), "sl_pending": True}
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "BingX ha desactivado temporalmente las órdenes API por alta volatilidad. "
                "El precio SL se ha guardado y se enviará al exchange automáticamente "
                "en cuanto BingX lo permita (reintentos cada 30s)."
            )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, err_str)
    finally:
        await exchange.close()


class UpdateTPRequest(BaseModel):
    tp_levels: list[dict]   # [{level, price, close_percent, hit}]


@router.patch("/{position_id}/tp", response_model=PositionResponse)
async def update_take_profits(
    position_id: uuid.UUID,
    data: UpdateTPRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Actualiza los niveles de TP de una posición abierta."""
    from loguru import logger

    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")

    await _verify_position_ownership(position, user_id, db)

    # TPs son internos (el engine los monitoriza y ejecuta cierre parcial)
    # — válido para paper y real por igual
    position.current_tp_prices = data.tp_levels
    await db.commit()
    await db.refresh(position)
    await publish_position_update(
        str(user_id),
        {"position_id": str(position_id), "status": position.status, "current_tp_prices": data.tp_levels}
    )
    logger.info(f"TPs actualizados para posición {position_id}: {len(data.tp_levels)} niveles")
    return position


class UpdateStrategyRequest(BaseModel):
    take_profits: list[dict] | None = None          # reemplaza todos los TPs del bot
    trailing_config: dict | None = None
    breakeven_config: dict | None = None
    dynamic_sl_config: dict | None = None


@router.patch("/{position_id}/strategy")
async def update_position_strategy(
    position_id: uuid.UUID,
    data: UpdateStrategyRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Actualiza la estrategia activa (TPs, trailing, breakeven, dynamic SL) en caliente."""
    from loguru import logger
    from app.core.risk_manager import calculate_tp_price as _calc_tp
    from decimal import Decimal

    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada")

    await _verify_position_ownership(position, user_id, db)

    bot_result = await db.execute(select(BotConfig).where(BotConfig.id == position.bot_id))
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")

    # Actualizar config en el bot (el engine lo lee en el siguiente ciclo)
    if data.trailing_config is not None:
        bot.trailing_config = data.trailing_config
    if data.breakeven_config is not None:
        bot.breakeven_config = data.breakeven_config
    if data.dynamic_sl_config is not None:
        bot.dynamic_sl_config = data.dynamic_sl_config

    # Si se envían TPs nuevos, recalcular precios y actualizar la posición
    if data.take_profits is not None:
        bot.take_profits = data.take_profits
        entry = Decimal(str(position.entry_price))
        side = position.side
        tp_records = []
        for i, tp_cfg in enumerate(data.take_profits):
            tp_price = _calc_tp(
                entry, side,
                Decimal(str(tp_cfg["profit_percent"])),
                bot.leverage,
                bot.use_roi_percentage,
            )
            tp_records.append({
                "level": i + 1,
                "price": float(tp_price),
                "close_percent": tp_cfg["close_percent"],
                "hit": False,
            })
        position.current_tp_prices = tp_records

    await db.commit()
    logger.info(f"Estrategia actualizada para posición {position_id}")
    await publish_position_update(
        str(user_id),
        {"position_id": str(position_id), "status": position.status, "strategy_updated": True}
    )
    return {"status": "ok", "position_id": str(position_id)}


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

    order = None
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
                order = await exchange.close_position(
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
            
            order = await exchange.close_position(
                symbol=position.symbol,
                side=position.side,
                quantity=close_quantity,
            )

        fill_price = order.fill_price if order else position.entry_price
        if not fill_price or fill_price <= 0:
            logger.warning(
                f"[PARTIAL CLOSE] fill_price inválido ({fill_price}) para {position.symbol}, "
                f"usando entry_price como fallback"
            )
            fill_price = position.entry_price
        partial_pnl = (
            (fill_price - position.entry_price) * close_quantity
            if position.side == "long"
            else (position.entry_price - fill_price) * close_quantity
        )

        # Actualizar cantidad en DB
        position.quantity -= close_quantity
        if position.quantity <= 0:
            position.status = "closed"
            position.closed_at = datetime.utcnow()
            position.realized_pnl = partial_pnl
        
        await db.commit()
        await db.refresh(position)
        await publish_position_update(
            str(user_id),
            {"position_id": str(position_id), "status": position.status, "quantity": float(position.quantity), "action": "partial_close"}
        )

        # Notificación Telegram al usuario si está configurada
        from app.models.user import User
        from app.tasks.notification_tasks import trade_partial
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user and user.telegram_chat_id and user.notify_on_partial:
            trade_partial.delay(
                bot_name=bot.bot_name,
                symbol=position.symbol,
                side=position.side,
                tp_level=0,
                close_percent=float(percentage),
                fill_price=float(fill_price),
                partial_pnl=float(partial_pnl),
                chat_id=user.telegram_chat_id,
            )

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

    order = None
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
                order = await exchange.close_position(
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
            
            order = await exchange.close_position(
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
            )

        fill_price = order.fill_price if order else position.entry_price
        realized_pnl = (
            (fill_price - position.entry_price) * position.quantity
            if position.side == "long"
            else (position.entry_price - fill_price) * position.quantity
        )

        position.status = "closed"
        position.closed_at = datetime.utcnow()
        position.realized_pnl = realized_pnl
        await db.commit()
        await db.refresh(position)
        await publish_position_update(
            str(user_id),
            {"position_id": str(position_id), "status": "closed", "action": "close"}
        )

        # Notificación Telegram al usuario si está configurada
        from app.models.user import User
        from app.tasks.notification_tasks import trade_closed
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user and user.telegram_chat_id and user.notify_on_close:
            trade_closed.delay(
                bot_name=bot.bot_name,
                symbol=position.symbol,
                side=position.side,
                pnl=float(realized_pnl),
                chat_id=user.telegram_chat_id,
                source="ai_bot" if position.source == "ai_bot" else "bot",
                entry_price=float(position.entry_price) if position.entry_price else None,
                exit_price=float(fill_price) if fill_price else None,
                quantity=float(position.quantity) if position.quantity else None,
                leverage=int(position.leverage) if position.leverage else None,
                timeframe=bot.timeframe,
            )

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
                await publish_position_update(
                    str(user_id),
                    {"position_id": str(position_id), "status": "closed", "action": "sync_close"}
                )
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
    await publish_position_update(
        str(user_id),
        {"position_id": str(position_id), "status": "closed", "action": "cancel_limit"}
    )

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
