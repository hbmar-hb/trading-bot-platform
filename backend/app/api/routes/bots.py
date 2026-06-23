import re
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_authorized_user, get_current_user_id
from app.core.conflict_validator import has_active_bot_conflict, has_open_position
from app.exchanges.factory import create_exchange
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.models.exchange_account import ExchangeAccount
from app.models.ai_scan import AIWatchlistItem
from app.models.paper_balance import PaperBalance
from app.models.signal_log import SignalLog
from app.schemas.bot import BotCreate, BotLogResponse, BotResponse, BotStatusUpdate, BotUpdate, SignalLogResponse
from app.services.database import get_db
from app.api.routes.webhook import _process_webhook_signal

router = APIRouter(prefix="/bots", tags=["bots"], dependencies=[Depends(get_current_authorized_user)])


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
    """Valida que el bot tenga una cuenta válida (real o paper).
    
    Los bots de solo alertas no requieren cuenta.
    """
    if data.alerts_only:
        return
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
        webhook_enabled=data.webhook_enabled,
        indicator_enabled=data.indicator_enabled,
        ai_signal_mode=data.ai_signal_mode,
        ai_optimal_config_enabled=data.ai_optimal_config_enabled,
        auto_timeframe=data.auto_timeframe,
        ai_signal_config=data.ai_signal_config,
        trigger_indicator=data.trigger_indicator,
        trigger_timeframe=data.trigger_timeframe,
        trigger_min_grade=data.trigger_min_grade,
        trigger_timing=data.trigger_timing,
        trigger_interval_minutes=data.trigger_interval_minutes,
        min_confirm_candles=data.min_confirm_candles,
        ict_config=data.ict_config,
        conflict_config=data.conflict_config,
        alerts_only=data.alerts_only,
        status="paused",    # seguro: requiere activación explícita
        **_bot_to_db_fields(data),
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    # Sync: add to AI watchlist if bot is in AI mode (skip alert-only bots)
    if bot.ai_signal_mode and not bot.alerts_only:
        normalized = re.sub(r'/([^:]+):[^:]+$', r'\1', bot.symbol).replace('/', '')
        db.add(AIWatchlistItem(user_id=user_id, symbol=normalized, timeframe=bot.timeframe))
        await db.commit()

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

    # Capture old values for watchlist sync
    old_symbol = bot.symbol
    old_timeframe = bot.timeframe
    old_ai_mode = bot.ai_signal_mode

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
    bot.ai_signal_mode   = data.ai_signal_mode
    bot.ai_optimal_config_enabled = data.ai_optimal_config_enabled
    bot.auto_timeframe     = data.auto_timeframe
    bot.webhook_enabled    = data.webhook_enabled
    bot.indicator_enabled  = data.indicator_enabled
    bot.trigger_indicator  = data.trigger_indicator
    bot.trigger_timeframe  = data.trigger_timeframe
    bot.trigger_min_grade  = data.trigger_min_grade
    bot.trigger_timing     = data.trigger_timing
    bot.trigger_interval_minutes = data.trigger_interval_minutes
    bot.min_confirm_candles = data.min_confirm_candles
    bot.ict_config         = data.ict_config
    bot.conflict_config    = data.conflict_config
    bot.alerts_only        = data.alerts_only
    # Deep-merge ai_signal_config so runtime state (circuit_breaker_state) is preserved
    merged_config = dict(bot.ai_signal_config or {})
    if data.ai_signal_config:
        for k, v in data.ai_signal_config.items():
            if isinstance(v, dict) and isinstance(merged_config.get(k), dict):
                merged_config[k] = {**merged_config[k], **v}
            else:
                merged_config[k] = v
    bot.ai_signal_config = merged_config
    for field, value in _bot_to_db_fields(data).items():
        setattr(bot, field, value)

    await db.commit()
    await db.refresh(bot)

    # Sync AI watchlist on symbol/timeframe/ai_mode changes (skip alert-only bots)
    if (old_ai_mode or data.ai_signal_mode) and not data.alerts_only:
        old_normalized = re.sub(r'/([^:]+):[^:]+$', r'\1', old_symbol).replace('/', '')
        new_normalized = re.sub(r'/([^:]+):[^:]+$', r'\1', data.symbol).replace('/', '')

        if old_ai_mode and not data.ai_signal_mode:
            # AI mode disabled: remove old entry
            await db.execute(
                delete(AIWatchlistItem).where(
                    AIWatchlistItem.user_id == user_id,
                    AIWatchlistItem.symbol == old_normalized,
                    AIWatchlistItem.timeframe == old_timeframe,
                )
            )
            await db.commit()
        elif not old_ai_mode and data.ai_signal_mode:
            # AI mode enabled: add new entry
            db.add(AIWatchlistItem(user_id=user_id, symbol=new_normalized, timeframe=data.timeframe))
            await db.commit()
        elif old_ai_mode and data.ai_signal_mode:
            # AI mode still on: check if symbol/timeframe changed
            if old_normalized != new_normalized or old_timeframe != data.timeframe:
                await db.execute(
                    delete(AIWatchlistItem).where(
                        AIWatchlistItem.user_id == user_id,
                        AIWatchlistItem.symbol == old_normalized,
                        AIWatchlistItem.timeframe == old_timeframe,
                    )
                )
                db.add(AIWatchlistItem(user_id=user_id, symbol=new_normalized, timeframe=data.timeframe))
                await db.commit()

    return bot


@router.post("/{bot_id}/test-webhook")
async def test_bot_webhook(
    bot_id: uuid.UUID,
    request: Request,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Envía una señal de prueba al webhook del bot sin ejecutar trades."""
    bot = await _get_bot_or_404(bot_id, user_id, db)

    if not getattr(bot, "webhook_enabled", True):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "El webhook no está habilitado para este bot",
        )

    from app.utils.crypto import decrypt
    try:
        secret = decrypt(bot.webhook_secret)
    except Exception:
        secret = bot.webhook_secret

    test_payload = {
        "secret": secret,
        "action": "long",
        "price": 12345.67,
        "test": True,
    }

    return await _process_webhook_signal(bot_id, test_payload, request, db)


@router.patch("/{bot_id}/status", response_model=BotResponse)
async def update_bot_status(
    bot_id: uuid.UUID,
    data: BotStatusUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_bot_or_404(bot_id, user_id, db)

    if data.status == "active":
        # Verificar posible conflicto antes de activar (mismo símbolo + timeframe + cuenta)
        conflict = await has_active_bot_conflict(
            db, bot.symbol, bot.exchange_account_id, exclude_bot_id=bot.id, timeframe=bot.timeframe
        )
        if conflict:
            # Se emite un aviso en lugar de bloquear, permitiendo múltiples temporalidades
            logger.warning(
                f"[BOT ACTIVATE] Advertencia: {bot.bot_name} se activa aunque ya existe "
                f"{conflict.bot_name} activo para {bot.symbol}/{bot.timeframe} en la misma cuenta."
            )

        # AI bots require the symbol to be in the scanner watchlist
        if bot.ai_signal_mode:
            import re
            from app.models.ai_scan import AIWatchlistItem
            # Normalize: "BTC/USDT:USDT" → "BTCUSDT", "XRP/USDT:USDT" → "XRPUSDT"
            normalized = re.sub(r'/([^:]+):[^:]+$', r'\1', bot.symbol).replace('/', '')
            wl_result = await db.execute(
                select(AIWatchlistItem).where(AIWatchlistItem.symbol == normalized).limit(1)
            )
            if not wl_result.scalar_one_or_none():
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"El símbolo {bot.symbol} no está en el scanner IA. "
                    f"Añádelo primero en la página IA Engine.",
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

    # Sync: remove from AI watchlist if bot was in AI mode
    if bot.ai_signal_mode:
        normalized = re.sub(r'/([^:]+):[^:]+$', r'\1', bot.symbol).replace('/', '')
        await db.execute(
            delete(AIWatchlistItem).where(
                AIWatchlistItem.user_id == user_id,
                AIWatchlistItem.symbol == normalized,
                AIWatchlistItem.timeframe == bot.timeframe,
            )
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


from app.core.constants import VALID_TIMEFRAMES_SET, validate_timeframe

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
    tf = timeframe if timeframe in VALID_TIMEFRAMES_SET else bot.timeframe
    if tf not in VALID_TIMEFRAMES_SET:
        tf = "1h"  # fallback seguro

    # Determinar qué exchange usar para obtener velas
    # Velas OHLCV son datos públicos; si el bot no tiene cuenta asignada
    # (p. ej. modo solo alertas), usamos Binance como fuente por defecto.
    if bot.is_paper_trading:
        # Para paper trading, usar Binance como fuente de precios (más estable)
        exchange_name = "binance"
    elif bot.exchange_account_id:
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
        # bingx y bitget usan CCXT directamente
    else:
        # Bots sin cuenta asignada (alerts_only u otros) usan fuente pública
        exchange_name = "binance"

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


@router.post("/emergency-stop", status_code=status.HTTP_200_OK)
async def emergency_stop_all_bots(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Kill-switch global: pausa TODOS los bots activos del usuario inmediatamente."""
    from sqlalchemy import update
    from app.models.bot_config import BotConfig

    bots = (
        await db.execute(
            select(BotConfig)
            .where(BotConfig.user_id == user_id, BotConfig.status == "active")
        )
    ).scalars().all()

    for bot in bots:
        bot.status = "paused"
        cfg = bot.ai_signal_config or {}
        autonomy = cfg.get("autonomy_state", {})
        autonomy["paused_by"] = "emergency_stop"
        autonomy["paused_at"] = datetime.now(timezone.utc).isoformat()
        autonomy["auto_resume_after"] = (
            datetime.now(timezone.utc) + timedelta(hours=2)
        ).isoformat()
        cfg["autonomy_state"] = autonomy
        bot.ai_signal_config = cfg

    await db.commit()
    paused = len(bots)

    return {
        "message": f"Emergency stop executed — {paused} bot(s) paused",
        "paused_bots": paused,
    }
