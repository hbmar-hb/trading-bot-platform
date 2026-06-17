"""
Receptor de señales de TradingView.

Ruta pública (sin JWT) — autenticada por webhook_secret por bot.
Debe responder en < 3 segundos o TradingView reintenta.
Toda la lógica pesada va al Celery task.
"""
import hashlib
from loguru import logger
import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot_config import BotConfig
from app.models.signal_log import SignalLog
from app.models.trading_signal import TradingSignal
from app.services.database import get_db
from app.tasks.order_tasks import execute_signal
from app.services.notifier import notify_webhook_signal
from app.utils.signal_hasher import generate_signal_hash
from app.utils.crypto import decrypt
from config.settings import settings

router = APIRouter(tags=["webhook"])

VALID_ACTIONS = {"long", "short", "close"}

# TradingView usa "buy"/"sell" por defecto; los mapeamos a nuestro vocabulario.
ACTION_ALIASES = {
    "buy": "long",
    "sell": "short",
    "flat": "close",
}


# ─── Rate limiting con Redis (por IP y por bot) ──────────────

_MAX_IP_PER_MINUTE = 10
_MAX_BOT_PER_MINUTE = 30
_WINDOW_SECONDS = 60


def _rate_limit_key(ip: str, bot_id: str | None = None) -> str:
    scope = f"bot:{bot_id}" if bot_id else f"ip:{ip}"
    return f"rate_limit:webhook:{scope}"


def _check_rate_limit(ip: str, bot_id: str | None = None) -> None:
    """Bloquea si se excede el rate limit. Usa Redis sync para velocidad."""
    from app.services.cache import sync_redis
    import time

    now = int(time.time())
    window_start = now - _WINDOW_SECONDS

    if bot_id:
        key = _rate_limit_key(ip, bot_id)
        limit = _MAX_BOT_PER_MINUTE
    else:
        key = _rate_limit_key(ip)
        limit = _MAX_IP_PER_MINUTE

    pipe = sync_redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, _WINDOW_SECONDS)
    _, count, _, _ = pipe.execute()

    if count >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Rate limit exceeded. Please slow down.",
        )


# ─── Dependencia: IP whitelist TradingView ────────────────────

async def verify_tradingview_ip(request: Request) -> None:
    """
    Verifica que la petición venga de una IP de TradingView.
    Solo activa en producción (ENV != development).
    """
    if settings.env == "development":
        return

    allowed = settings.tradingview_ip_list
    if not allowed:
        return  # sin lista configurada = no filtrar

    client_ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
    if client_ip not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"IP no permitida: {client_ip}",
        )


# ─── Lógica compartida ───────────────────────────────────────

async def _process_webhook_signal(
    bot_id: uuid.UUID,
    payload: dict,
    request: Request,
    db: AsyncSession,
) -> dict:
    """Procesa una señal de webhook para un bot concreto.

    Si payload contiene "test": true, solo valida el pipeline sin ejecutar
    trades ni guardar logs. Útil para probar la conectividad.
    """
    is_test = bool(payload.get("test"))
    received_at = datetime.now(timezone.utc)

    # 1. Cargar bot (solo campos necesarios, sin joins)
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")

    # 2. Validar que webhook está habilitado para este bot
    if not getattr(bot, "webhook_enabled", True):
        return {
            "status": "ignored",
            "reason": "Webhook deshabilitado para este bot",
        }

    # 3. Rate limit por bot
    try:
        _check_rate_limit(request.client.host, str(bot_id))
    except HTTPException:
        raise

    # 4. Validar secret (timing-safe comparison)
    try:
        expected_plain = decrypt(bot.webhook_secret)
    except ValueError as exc:
        logger.warning(f"[WEBHOOK] Secret corrupto para bot {bot_id}: {exc}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Secret inválido")
    except Exception as exc:
        logger.error(f"[WEBHOOK] Error inesperado al verificar secret bot {bot_id}: {exc}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al verificar secret")
    received = str(payload.get("secret", ""))
    # Aceptar tanto el secret en texto plano como el valor encriptado legacy,
    # para no romper las alertas de TradingView ya configuradas.
    valid = (
        hmac.compare_digest(received, expected_plain)
        or hmac.compare_digest(received, bot.webhook_secret)
    )
    if not valid:
        logger.warning(f"[WEBHOOK] Secret incorrecto para bot {bot_id} desde {request.client.host}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Secret inválido")

    # 5. Validar acción
    action = str(payload.get("action", "")).strip().lower()
    action = ACTION_ALIASES.get(action, action)
    if action not in VALID_ACTIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Acción inválida: '{action}'. Valores permitidos: {VALID_ACTIONS}",
        )

    # 6. Bot debe estar activo
    if bot.status != "active":
        return {
            "status": "ignored",
            "reason": f"Bot está {bot.status}",
        }

    # Modo test: validar todo el pipeline sin ejecutar trades ni guardar logs
    if is_test:
        logger.info(f"[WEBHOOK TEST] Señal de prueba aceptada para bot {bot_id} ({bot.symbol} {bot.timeframe})")
        return {
            "status": "test_accepted",
            "bot_id": str(bot_id),
            "bot_name": bot.bot_name,
            "symbol": bot.symbol,
            "timeframe": bot.timeframe,
            "action": action,
            "message": "Webhook configurado correctamente. La señal de prueba llegó y pasó todas las validaciones.",
        }

    # 7. Extraer precio (TradingView envía strings para las variables)
    price: float | None = None
    if raw_price := payload.get("price"):
        try:
            price = float(raw_price)
        except (ValueError, TypeError):
            price = None

    # 7b. Extraer valores de indicadores (nuevo)
    indicator_values = payload.get("indicator_values", {})
    # También buscar campos sueltos comunes (retrocompatibilidad)
    if "rsi" in payload:
        indicator_values["rsi"] = float(payload["rsi"]) if payload["rsi"] else None
    if "ema" in payload:
        indicator_values["ema"] = float(payload["ema"]) if payload["ema"] else None
    if "volume" in payload:
        indicator_values["volume"] = float(payload["volume"]) if payload["volume"] else None

    # Anti-replay: rechazar payload idéntico en ventana de 5 minutos
    from app.services.cache import sync_redis
    raw_payload_for_replay = json.dumps({k: v for k, v in payload.items() if k != "source"}, sort_keys=True)
    replay_key = f"webhook:replay:{hashlib.sha256(raw_payload_for_replay.encode()).hexdigest()}"
    if sync_redis.exists(replay_key):
        return {
            "status": "duplicate",
            "reason": "Señal ya recibida recientemente (anti-replay)",
        }
    sync_redis.setex(replay_key, 300, "1")

    # 8. Idempotencia: verificar hash de señal
    signal_hash = generate_signal_hash(bot_id, action, received_at, price)
    existing = await db.execute(
        select(SignalLog).where(SignalLog.signal_hash == signal_hash)
    )
    if existing.scalar_one_or_none():
        return {
            "status": "duplicate",
            "reason": "Señal ya procesada (posible reintento de TradingView)",
        }

    # 9. Registrar señal en DB (SignalLog para auditoría)
    # Añadir source para que engine.py sepa que viene de webhook
    payload_with_source = {**payload, "source": "webhook"}
    signal_log = SignalLog(
        bot_id=bot_id,
        signal_action=action,
        raw_payload=payload_with_source,
        signal_hash=signal_hash,
        received_at=received_at,
        processed=False,
    )
    db.add(signal_log)

    # 8b. Guardar también en TradingSignal (para visualización en gráfico)
    trading_signal = TradingSignal(
        user_id=bot.user_id,
        source='tradingview',
        signal_id=signal_hash,
        symbol=bot.symbol,
        action=action,
        timeframe=bot.timeframe,
        price=price,
        indicator_values=indicator_values,
        status='pending',
        received_at=received_at,
    )
    db.add(trading_signal)

    await db.commit()
    await db.refresh(signal_log)

    # 10. Notificar a Telegram si hay destino configurado
    #    - Prioridad 1: chat_id configurado en el bot.
    #    - Prioridad 2: grupo/topic QUANTUM global (TELEGRAM_QUANTUM_GROUP_CHAT_ID).
    strategy = payload.get("strategy") or payload.get("indicator")
    telegram_target = bot.telegram_chat_id or settings.telegram_quantum_group_chat_id
    if telegram_target:
        logger.info(
            f"[WEBHOOK] Notificando señal {bot.symbol} {action} a Telegram "
            f"(destino: {telegram_target})"
        )
        notify_webhook_signal(
            symbol=bot.symbol,
            action=action,
            price=price,
            strategy=strategy,
            chat_id=bot.telegram_chat_id,
            thread_id=bot.telegram_thread_id,
            alerts_only=getattr(bot, "alerts_only", False),
        )

    # ─── Modo solo alertas: no ejecutar trades ─────────────────
    if getattr(bot, "alerts_only", False):
        return {
            "status": "accepted_alert",
            "signal_id": str(signal_log.id),
            "action": action,
            "reason": "Bot en modo solo alertas — no se ejecuta trade",
        }

    # 9. Encolar tarea Celery con delay de confirmación opcional
    confirmation_minutes = getattr(bot, "signal_confirmation_minutes", 0) or 0
    # CLOSE siempre se ejecuta inmediatamente, sin espera
    countdown_seconds = 0 if action == "close" else int(confirmation_minutes * 60)

    execute_signal.apply_async(
        kwargs={
            "bot_id": str(bot_id),
            "signal_id": str(signal_log.id),
            "action": action,
            "price": price,
        },
        countdown=countdown_seconds,
    )

    return {
        "status": "accepted",
        "signal_id": str(signal_log.id),
        "action": action,
        "confirmation_delay_seconds": countdown_seconds,
    }


# ─── Endpoints ───────────────────────────────────────────────

@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def webhook_global_receiver(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_tradingview_ip),
):
    """
    Webhook global. El bot_id va en el body, no en la URL.
    Body esperado desde TradingView:
    {
        "bot_id":  "<uuid del bot>",
        "secret":  "<webhook_secret del bot>",
        "action":  "long" | "short" | "close",
        "price":   "{{close}}"       ← variable de TradingView (opcional)
    }
    """
    bot_id_raw = payload.get("bot_id")
    if not bot_id_raw:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "bot_id requerido en el body",
        )
    try:
        bot_id = uuid.UUID(str(bot_id_raw))
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"bot_id inválido: {bot_id_raw}",
        )

    return await _process_webhook_signal(bot_id, payload, request, db)


@router.post("/webhook/{bot_id}", status_code=status.HTTP_202_ACCEPTED)
async def webhook_receiver(
    bot_id: uuid.UUID,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_tradingview_ip),
):
    """
    Endpoint legacy. Mantiene compatibilidad con alertas antiguas.
    Body esperado desde TradingView:
    {
        "secret":  "<webhook_secret del bot>",
        "action":  "long" | "short" | "close",
        "price":   "{{close}}"       ← variable de TradingView (opcional)
    }
    """
    return await _process_webhook_signal(bot_id, payload, request, db)
