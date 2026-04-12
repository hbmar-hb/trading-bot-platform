"""
Trading manual — ejecuta operaciones sin depender de señales de TradingView.

Por cada (cuenta, símbolo) se crea un BotConfig oculto de tipo 'manual'
que se reutiliza en cada operación. Esto permite que todo el engine
(posiciones, logs, SL, TP) funcione exactamente igual que con bots automáticos.
"""
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.models.bot_config import BotConfig
from app.models.exchange_account import ExchangeAccount
from app.models.paper_balance import PaperBalance
from app.models.position import Position
from app.models.signal_log import SignalLog
from app.services.database import get_db
from app.tasks.order_tasks import execute_signal
from app.utils.signal_hasher import generate_signal_hash
from datetime import datetime, timezone

router = APIRouter(prefix="/manual-trade", tags=["manual-trade"])

MANUAL_BOT_PREFIX = "[MANUAL]"


# ─── Schemas ─────────────────────────────────────────────────

class ManualTradeRequest(BaseModel):
    exchange_account_id: uuid.UUID | None = None
    paper_balance_id: uuid.UUID | None = None
    symbol: str
    action: Literal["long", "short", "close"]
    leverage: int = 1
    position_sizing_type: Literal["percentage", "fixed"] = "percentage"
    position_value: Decimal = Decimal("10")
    initial_sl_percentage: Decimal = Decimal("2")
    take_profits: list[dict] = []
    trailing_config: dict | None = None
    breakeven_config: dict | None = None
    dynamic_sl_config: dict | None = None
    order_type: Literal["market", "limit"] = "market"
    limit_price: Decimal | None = None


class ManualTradeResponse(BaseModel):
    status: str
    signal_id: str | None = None
    bot_id: str | None = None
    message: str | None = None


# ─── Helpers ─────────────────────────────────────────────────

async def _get_or_create_manual_bot(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: ManualTradeRequest,
) -> BotConfig:
    """
    Busca o crea el BotConfig manual para esta combinación de cuenta+símbolo.
    Actualiza los parámetros (leverage, SL, sizing) en cada llamada.
    """
    # Buscar bot manual existente para esta cuenta+símbolo
    query = (
        select(BotConfig)
        .where(
            BotConfig.user_id == user_id,
            BotConfig.symbol == data.symbol,
            BotConfig.bot_name.like(f"{MANUAL_BOT_PREFIX}%"),
        )
    )
    if data.exchange_account_id:
        query = query.where(BotConfig.exchange_account_id == data.exchange_account_id)
    else:
        query = query.where(BotConfig.paper_balance_id == data.paper_balance_id)

    result = await db.execute(query)
    bot = result.scalar_one_or_none()

    if not bot:
        # Crear nuevo bot manual
        bot = BotConfig(
            user_id=user_id,
            exchange_account_id=data.exchange_account_id,
            paper_balance_id=data.paper_balance_id,
            bot_name=f"{MANUAL_BOT_PREFIX} {data.symbol}",
            symbol=data.symbol,
            timeframe="1h",  # no usado en manual
            position_sizing_type=str(data.position_sizing_type),
            position_value=data.position_value,
            leverage=data.leverage,
            initial_sl_percentage=data.initial_sl_percentage,
            take_profits=[
                {"profit_percent": float(tp["profit_percent"]), "close_percent": float(tp["close_percent"])}
                for tp in data.take_profits
            ],
            status="active",
        )
        # Configuraciones opcionales
        if data.trailing_config:
            bot.trailing_config = data.trailing_config
        if data.breakeven_config:
            bot.breakeven_config = data.breakeven_config
        if data.dynamic_sl_config:
            bot.dynamic_sl_config = data.dynamic_sl_config
        db.add(bot)
    else:
        # Actualizar parámetros (excepto en close — no tiene sentido cambiarlos)
        if data.action != "close":
            bot.leverage = data.leverage
            bot.position_sizing_type = str(data.position_sizing_type)
            bot.position_value = data.position_value
            bot.initial_sl_percentage = data.initial_sl_percentage
            bot.take_profits = [
                {"profit_percent": float(tp["profit_percent"]), "close_percent": float(tp["close_percent"])}
                for tp in data.take_profits
            ]
            if data.trailing_config:
                bot.trailing_config = data.trailing_config
            if data.breakeven_config:
                bot.breakeven_config = data.breakeven_config
            if data.dynamic_sl_config:
                bot.dynamic_sl_config = data.dynamic_sl_config
        bot.status = "active"

    await db.commit()
    await db.refresh(bot)
    return bot


# ─── Endpoints ───────────────────────────────────────────────

@router.post("/execute", response_model=ManualTradeResponse)
async def execute_manual_trade(
    data: ManualTradeRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Ejecuta una operación manual (long/short/close)."""

    # Validar cuenta
    if not data.exchange_account_id and not data.paper_balance_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Debes seleccionar una cuenta")

    if data.exchange_account_id:
        acc = await db.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.id == data.exchange_account_id,
                ExchangeAccount.user_id == user_id,
                ExchangeAccount.is_active == True,
            )
        )
        if not acc.scalar_one_or_none():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta de exchange no encontrada")
    else:
        pb = await db.execute(
            select(PaperBalance).where(
                PaperBalance.id == data.paper_balance_id,
                PaperBalance.user_id == user_id,
            )
        )
        if not pb.scalar_one_or_none():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta paper no encontrada")

    # Obtener o crear bot manual
    bot = await _get_or_create_manual_bot(db, user_id, data)

    # Registrar señal
    received_at = datetime.now(timezone.utc)
    signal_hash = generate_signal_hash(bot.id, data.action, received_at, None)

    # Guardar datos de orden limit si aplica
    raw_payload = {
        "action": data.action, 
        "source": "manual",
        "order_type": data.order_type,
    }
    if data.order_type == "limit" and data.limit_price:
        raw_payload["limit_price"] = float(data.limit_price)

    signal_log = SignalLog(
        bot_id=bot.id,
        signal_action=data.action,
        raw_payload=raw_payload,
        signal_hash=signal_hash,
        received_at=received_at,
        processed=False,
    )
    db.add(signal_log)
    await db.commit()
    await db.refresh(signal_log)

    # Encolar tarea Celery
    # Pasar el precio limit para que el engine lo use
    from loguru import logger
    logger.info(f"[MANUAL_TRADE] Received: order_type={data.order_type}, limit_price={data.limit_price}")
    limit_price = float(data.limit_price) if data.order_type == "limit" and data.limit_price else None
    logger.info(f"[MANUAL_TRADE] Sending to Celery: price={limit_price}")
    execute_signal.delay(
        bot_id=str(bot.id),
        signal_id=str(signal_log.id),
        action=data.action,
        price=limit_price,
    )

    return ManualTradeResponse(
        status="accepted",
        signal_id=str(signal_log.id),
        bot_id=str(bot.id),
        message=f"Señal {data.action.upper()} enviada para {data.symbol}",
    )


@router.get("/position")
async def get_manual_position(
    symbol: str,
    exchange_account_id: uuid.UUID | None = None,
    paper_balance_id: uuid.UUID | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve la posición abierta del bot manual para esta cuenta+símbolo (si existe)."""
    query = (
        select(BotConfig)
        .where(
            BotConfig.user_id == user_id,
            BotConfig.symbol == symbol,
            BotConfig.bot_name.like(f"{MANUAL_BOT_PREFIX}%"),
        )
    )
    if exchange_account_id:
        query = query.where(BotConfig.exchange_account_id == exchange_account_id)
    elif paper_balance_id:
        query = query.where(BotConfig.paper_balance_id == paper_balance_id)

    result = await db.execute(query)
    bot = result.scalar_one_or_none()

    if not bot:
        return {"position": None}

    pos_result = await db.execute(
        select(Position).where(
            Position.bot_id == bot.id,
            Position.status.in_(["open", "pending_limit"]),
        ).order_by(Position.opened_at.desc())
    )
    position = pos_result.scalars().first()

    if not position:
        return {"position": None}

    return {
        "position": {
            "id": str(position.id),
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": float(position.entry_price),
            "quantity": float(position.quantity),
            "leverage": position.leverage,
            "current_sl_price": float(position.current_sl_price) if position.current_sl_price else None,
            "unrealized_pnl": float(position.unrealized_pnl) if position.unrealized_pnl else 0,
            "opened_at": position.opened_at.isoformat(),
            "status": position.status,
        }
    }


@router.get("/accounts")
async def get_manual_trade_accounts(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve cuentas reales y paper disponibles para trading manual."""
    real = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.user_id == user_id,
            ExchangeAccount.is_active == True,
        )
    )
    paper = await db.execute(
        select(PaperBalance).where(
            PaperBalance.user_id == user_id,
            PaperBalance.is_active == True,
        )
    )

    real_accounts = [
        {"id": str(a.id), "label": a.label, "exchange": a.exchange, "type": "real"}
        for a in real.scalars().all()
    ]
    paper_accounts = [
        {"id": str(p.id), "label": p.label, "exchange": "paper", "type": "paper"}
        for p in paper.scalars().all()
    ]

    return {"accounts": real_accounts + paper_accounts}


@router.get("/external-positions")
async def get_external_positions(
    exchange_account_id: uuid.UUID | None = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Devuelve posiciones abiertas en el exchange que NO tienen registro en la plataforma.
    Si se pasa exchange_account_id, consulta solo esa cuenta.
    Si no, consulta todas las cuentas reales activas del usuario.
    """
    from app.exchanges.factory import create_exchange
    from loguru import logger

    # Obtener cuentas a consultar
    acc_query = select(ExchangeAccount).where(
        ExchangeAccount.user_id == user_id,
        ExchangeAccount.is_active == True,
    )
    if exchange_account_id:
        acc_query = acc_query.where(ExchangeAccount.id == exchange_account_id)

    acc_result = await db.execute(acc_query)
    accounts = acc_result.scalars().all()

    if not accounts:
        return {"external_positions": []}

    # Posiciones gestionadas en DB para las cuentas relevantes
    account_ids = [a.id for a in accounts]
    db_pos_result = await db.execute(
        select(Position, BotConfig)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.exchange_account_id.in_(account_ids),
            Position.status.in_(["open", "closing"]),
        )
    )
    managed: dict[uuid.UUID, set] = {}
    for pos, bot in db_pos_result.all():
        managed.setdefault(bot.exchange_account_id, set()).add((pos.symbol, pos.side))

    # Consultar posiciones abiertas en cada cuenta
    external = []
    for account in accounts:
        try:
            exchange = create_exchange(account)
            try:
                open_positions = await exchange.get_open_positions()
            finally:
                await exchange.close()

            account_managed = managed.get(account.id, set())
            for p in open_positions:
                if (p.symbol, p.side) not in account_managed:
                    external.append({
                        "symbol": p.symbol,
                        "side": p.side,
                        "entry_price": float(p.entry_price),
                        "quantity": float(p.quantity),
                        "unrealized_pnl": float(p.unrealized_pnl),
                        "exchange_position_id": p.exchange_position_id,
                        "exchange_account_id": str(account.id),
                        "account_label": account.label,
                        "exchange": account.exchange,
                    })
        except Exception as exc:
            logger.warning(f"external-positions: error en cuenta {account.id}: {exc}")

    return {"external_positions": external}


class AdoptPositionRequest(BaseModel):
    exchange_account_id: uuid.UUID
    symbol: str
    side: str                             # "long" | "short"
    sl_percentage: Decimal = Decimal("2")
    take_profits: list[dict] = []
    trailing_config: dict | None = None
    breakeven_config: dict | None = None
    dynamic_sl_config: dict | None = None


@router.post("/adopt")
async def adopt_position(
    data: AdoptPositionRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Adopta una posición externa (abierta en BingX nativo) y la pone bajo gestión
    de la plataforma: crea un BotConfig [MANUAL], un registro de Position,
    y coloca la orden de Stop Loss en el exchange.
    """
    # Validar cuenta
    acc_result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == data.exchange_account_id,
            ExchangeAccount.user_id == user_id,
            ExchangeAccount.is_active == True,
        )
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta no encontrada")

    # Verificar que la posición no está ya gestionada
    existing = await db.execute(
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.exchange_account_id == data.exchange_account_id,
            Position.symbol == data.symbol,
            Position.side == data.side,
            Position.status.in_(["open", "closing"]),
        )
    )
    if existing.scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta posición ya está gestionada")

    # Obtener datos reales del exchange
    from app.exchanges.factory import create_exchange
    exchange = create_exchange(account)
    try:
        open_positions = await exchange.get_open_positions()
        bingx_pos = next(
            (p for p in open_positions if p.symbol == data.symbol and p.side == data.side),
            None,
        )
        if not bingx_pos:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Posición no encontrada en el exchange")

        entry_price = bingx_pos.entry_price
        quantity    = bingx_pos.quantity
        exchange_position_id = bingx_pos.exchange_position_id

        # Calcular precio de SL y colocarlo en el exchange
        sl_multiplier = (1 - data.sl_percentage / 100) if data.side == "long" else (1 + data.sl_percentage / 100)
        sl_price = entry_price * sl_multiplier

        sl_order_id = None
        sl_pending = False
        try:
            sl_order_id = await exchange.place_stop_loss(data.symbol, data.side, quantity, sl_price)
        except Exception as sl_err:
            from loguru import logger
            logger.warning(f"adopt: no se pudo colocar SL en exchange: {sl_err}")
            sl_pending = True   # se marcará en extra_config de la Position
    finally:
        await exchange.close()

    # Buscar o crear BotConfig [MANUAL]
    bot_result = await db.execute(
        select(BotConfig).where(
            BotConfig.user_id == user_id,
            BotConfig.exchange_account_id == data.exchange_account_id,
            BotConfig.symbol == data.symbol,
            BotConfig.bot_name.like(f"{MANUAL_BOT_PREFIX}%"),
        )
    )
    bot = bot_result.scalar_one_or_none()

    if not bot:
        bot = BotConfig(
            user_id=user_id,
            exchange_account_id=data.exchange_account_id,
            bot_name=f"{MANUAL_BOT_PREFIX} {data.symbol}",
            symbol=data.symbol,
            timeframe="1h",
            position_sizing_type="percentage",
            position_value=Decimal("10"),
            leverage=1,
            initial_sl_percentage=data.sl_percentage,
            take_profits=[
                {"profit_percent": float(tp["profit_percent"]), "close_percent": float(tp["close_percent"])}
                for tp in data.take_profits
            ],
            status="active",
        )
        if data.trailing_config:
            bot.trailing_config = data.trailing_config
        if data.breakeven_config:
            bot.breakeven_config = data.breakeven_config
        if data.dynamic_sl_config:
            bot.dynamic_sl_config = data.dynamic_sl_config
        db.add(bot)
        await db.flush()
    else:
        bot.initial_sl_percentage = data.sl_percentage
        bot.take_profits = [
            {"profit_percent": float(tp["profit_percent"]), "close_percent": float(tp["close_percent"])}
            for tp in data.take_profits
        ]
        if data.trailing_config:
            bot.trailing_config = data.trailing_config
        if data.breakeven_config:
            bot.breakeven_config = data.breakeven_config
        if data.dynamic_sl_config:
            bot.dynamic_sl_config = data.dynamic_sl_config
        bot.status = "active"

    # Crear el registro de Position
    tp_prices = []
    for i, tp in enumerate(data.take_profits, 1):
        tp_pct   = Decimal(str(tp["profit_percent"]))
        if data.side == "long":
            tp_price = entry_price * (1 + tp_pct / 100)
        else:
            tp_price = entry_price * (1 - tp_pct / 100)
        tp_prices.append({
            "level": i,
            "price": float(tp_price),
            "close_percent": float(tp["close_percent"]),
            "hit": False,
        })

    extra: dict = {}
    if sl_pending:
        extra["sl_pending"] = {
            "price": float(sl_price),
            "since": datetime.now(timezone.utc).isoformat(),
        }

    position = Position(
        bot_id=bot.id,
        exchange=account.exchange,
        symbol=data.symbol,
        side=data.side,
        entry_price=entry_price,
        quantity=quantity,
        leverage=1,
        current_sl_price=sl_price,
        current_tp_prices=tp_prices,
        exchange_position_id=exchange_position_id,
        exchange_sl_order_id=sl_order_id,
        extra_config=extra or None,
        status="open",
        opened_at=datetime.now(timezone.utc),
        unrealized_pnl=bingx_pos.unrealized_pnl,
    )
    db.add(position)
    await db.commit()

    return {
        "status": "adopted",
        "sl_pending_exchange": sl_pending,
        "position_id": str(position.id),
        "bot_id": str(bot.id),
        "sl_price": float(sl_price),
        "message": f"Posición {data.side.upper()} {data.symbol} adoptada y bajo gestión",
    }


@router.get("/candles")
async def get_candles(
    symbol: str,
    timeframe: str = Query("15m", description="1m, 5m, 15m, 1h, 4h, 1d"),
    limit: int = Query(100, ge=10, le=500),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Obtiene velas históricas para cualquier símbolo (usado en trading manual)."""
    import asyncio
    import ccxt.async_support as ccxt
    from app.workers.price_monitor import _to_ccxt_symbol

    # Reject obviously incomplete symbols before hitting the exchange
    if len(symbol) < 5 or ('/' not in symbol and ':' not in symbol and len(symbol) < 6):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Símbolo incompleto o inválido")

    client = ccxt.bingx({
        "options": {"defaultType": "swap"},
        "timeout": 10000,  # 10s máximo
    })
    try:
        ccxt_symbol = _to_ccxt_symbol(symbol.upper(), "bingx")
        ohlcv = await asyncio.wait_for(
            client.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit),
            timeout=12.0,
        )
        return [
            {"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in ohlcv
            if c[0] is not None and c[1] is not None
        ]
    except asyncio.TimeoutError:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Timeout obteniendo velas")
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Error obteniendo velas: {str(e)}")
    finally:
        await client.close()
