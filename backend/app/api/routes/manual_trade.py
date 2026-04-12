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
