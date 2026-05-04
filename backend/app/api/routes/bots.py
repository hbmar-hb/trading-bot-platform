import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.core.conflict_validator import has_active_bot_conflict, has_open_position
from app.exchanges.factory import create_exchange
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.models.exchange_account import ExchangeAccount
from app.models.paper_balance import PaperBalance
from app.models.signal_log import SignalLog
from app.schemas.bot import BotCreate, BotLogResponse, BotResponse, BotStatusUpdate, BotUpdate, SignalLogResponse
from app.services.database import get_db

router = APIRouter(prefix="/bots", tags=["bots"])


# ─── Helpers ─────────────────────────────────────────────────

async def _get_bot_or_404(
    bot_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> BotConfig:
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user_id)
    )
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")
    return bot


async def _validate_exchange_account(
    account_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> ExchangeAccount:
    result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id,
            ExchangeAccount.user_id == user_id,
            ExchangeAccount.is_active == True,  # noqa: E712
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Cuenta de exchange no encontrada o inactiva",
        )
    return account


async def _validate_paper_balance(
    balance_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> PaperBalance:
    """Valida que la cuenta paper exista y pertenezca al usuario."""
    result = await db.execute(
        select(PaperBalance).where(
            PaperBalance.id == balance_id,
            PaperBalance.user_id == user_id,
            PaperBalance.is_active == True,
        )
    )
    balance = result.scalar_one_or_none()
    if not balance:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Cuenta paper no encontrada o inactiva",
        )
    return balance


async def _validate_bot_account(data: BotCreate, user_id: uuid.UUID, db: AsyncSession):
    """Valida que el bot tenga una cuenta válida (real o paper)."""
    if data.paper_balance_id:
        return await _validate_paper_balance(data.paper_balance_id, user_id, db)
    elif data.exchange_account_id:
        return await _validate_exchange_account(data.exchange_account_id, user_id, db)
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Debes proporcionar exchange_account_id (trading real) o paper_balance_id (paper trading)"
        )


def _bot_to_db_fields(data: BotCreate) -> dict:
    """Convierte el schema Pydantic a campos serializables para la DB.
    mode='json' convierte Decimal → float para que JSONB los acepte.
    """
    return {
        "take_profits":      [tp.model_dump(mode="json") for tp in data.take_profits],
        "trailing_config":   data.trailing_config.model_dump(mode="json"),
        "breakeven_config":  data.breakeven_config.model_dump(mode="json"),
        "dynamic_sl_config": data.dynamic_sl_config.model_dump(mode="json"),
    }


# ─── CRUD ────────────────────────────────────────────────────

@router.get("", response_model=list[BotResponse])
async def list_bots(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BotConfig)
        .where(
            BotConfig.user_id == user_id,
            ~BotConfig.bot_name.like("[MANUAL]%"),
        )
        .order_by(BotConfig.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=BotResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    data: BotCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # Validar la cuenta (real o paper)
    await _validate_bot_account(data, user_id, db)

    bot = BotConfig(
        user_id=user_id,
        exchange_account_id=data.exchange_account_id,
        paper_balance_id=data.paper_balance_id,
        bot_name=data.bot_name,
        symbol=data.symbol,
        timeframe=data.timeframe,
        position_sizing_type=data.position_sizing_type,
        position_value=data.position_value,
        leverage=data.leverage,
        initial_sl_percentage=data.initial_sl_percentage,
        signal_confirmation_minutes=data.signal_confirmation_minutes,
        status="paused",    # siempre empieza pausado
        **_bot_to_db_fields(data),
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return bot


@router.get("/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _get_bot_or_404(bot_id, user_id, db)


@router.put("/{bot_id}", response_model=BotResponse)
async def update_bot(
    bot_id: uuid.UUID,
    data: BotUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_bot_or_404(bot_id, user_id, db)

    if bot.status == "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Pausa el bot antes de modificarlo",
        )

    # Validar nueva cuenta (real o paper)
    await _validate_bot_account(data, user_id, db)

    bot.exchange_account_id = data.exchange_account_id
    bot.paper_balance_id = data.paper_balance_id
    bot.bot_name = data.bot_name
    bot.symbol = data.symbol
    bot.timeframe = data.timeframe
    bot.position_sizing_type = data.position_sizing_type
    bot.position_value = data.position_value
    bot.leverage = data.leverage
    bot.initial_sl_percentage = data.initial_sl_percentage
    bot.signal_confirmation_minutes = data.signal_confirmation_minutes
    for field, value in _bot_to_db_fields(data).items():
        setattr(bot, field, value)

    await db.commit()
    await db.refresh(bot)
    return bot


@router.patch("/{bot_id}/status", response_model=BotResponse)
async def update_bot_status(
    bot_id: uuid.UUID,
    data: BotStatusUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_bot_or_404(bot_id, user_id, db)

    if data.status == "active":
        # Verificar que no haya conflicto antes de activar
        conflict = await has_active_bot_conflict(
            db, bot.symbol, bot.exchange_account_id, exclude_bot_id=bot.id
        )
        if conflict:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Ya existe un bot activo para {bot.symbol} en esta cuenta "
                f"({conflict.bot_name}). Paúsalo primero.",
            )

    bot.status = data.status
    await db.commit()
    await db.refresh(bot)
    return bot


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_bot_or_404(bot_id, user_id, db)

    if bot.status == "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Pausa el bot antes de eliminarlo",
        )

    open_pos = await has_open_position(db, bot.symbol, bot.exchange_account_id)
    if open_pos and open_pos.bot_id == bot.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El bot tiene una posición abierta. Ciérrala antes de eliminar el bot.",
        )

    await db.delete(bot)
    await db.commit()


@router.get("/{bot_id}/logs", response_model=list[BotLogResponse])
async def get_bot_logs(
    bot_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_bot_or_404(bot_id, user_id, db)
    result = await db.execute(
        select(BotLog)
        .where(BotLog.bot_id == bot_id)
        .order_by(BotLog.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w"}

@router.get("/{bot_id}/candles")
async def get_bot_candles(
    bot_id: uuid.UUID,
    limit: int = Query(200, ge=10, le=500),
    timeframe: str = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Velas OHLCV del símbolo del bot en su timeframe configurado.
    Usa cliente público (sin credenciales) — OHLCV es dato público.
    Funciona tanto para bots de paper trading como para bots reales.
    """
    import ccxt.async_support as ccxt

    bot = await _get_bot_or_404(bot_id, user_id, db)

    # Timeframe: parámetro de query > configuración del bot
    tf = timeframe if timeframe in VALID_TIMEFRAMES else bot.timeframe
    if tf not in VALID_TIMEFRAMES:
        tf = "1h"  # fallback seguro

    # Determinar qué exchange usar para obtener velas
    if bot.is_paper_trading:
        # Para paper trading, usar Binance como fuente de precios (más estable)
        exchange_name = "binance"
    else:
        # Para trading real, usar el exchange de la cuenta
        acc_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
        )
        account = acc_result.scalar_one_or_none()
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta de exchange no encontrada")
        
        exchange_name = account.exchange
        if exchange_name == "bitunix":
            # Bitunix no tiene soporte CCXT nativo; usamos BingX como proxy de precio
            exchange_name = "bingx"

    client = getattr(ccxt, exchange_name)({"options": {"defaultType": "swap"}})
    try:
        ohlcv = await client.fetch_ohlcv(bot.symbol, tf, limit=limit)
        candles = [
            {"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in ohlcv
        ]
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error obteniendo velas: {exc}")
    finally:
        await client.close()

    return candles


@router.get("/{bot_id}/signals", response_model=list[SignalLogResponse])
async def get_bot_signals(
    bot_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_bot_or_404(bot_id, user_id, db)
    result = await db.execute(
        select(SignalLog)
        .where(SignalLog.bot_id == bot_id)
        .order_by(SignalLog.received_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
