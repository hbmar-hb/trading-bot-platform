"""
Receptor de señales de TradingView.

Ruta pública (sin JWT) — autenticada por webhook_secret por bot.
Debe responder en < 3 segundos o TradingView reintenta.
Toda la lógica pesada va al Celery task.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot_config import BotConfig
from app.models.signal_log import SignalLog
from app.services.database import get_db
from app.tasks.order_tasks import execute_signal
from app.utils.signal_hasher import generate_signal_hash
from config.settings import settings

router = APIRouter(tags=["webhook"])

VALID_ACTIONS = {"long", "short", "close"}


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


# ─── Endpoint ────────────────────────────────────────────────

@router.post("/webhook/{bot_id}", status_code=status.HTTP_202_ACCEPTED)
async def webhook_receiver(
    bot_id: uuid.UUID,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_tradingview_ip),
):
    """
    Body esperado desde TradingView:
    {
        "secret":  "<webhook_secret del bot>",
        "action":  "long" | "short" | "close",
        "price":   "{{close}}"       ← variable de TradingView (opcional)
    }
    """
    received_at = datetime.now(timezone.utc)

    # 1. Cargar bot (solo campos necesarios, sin joins)
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")

    # 2. Validar secret (timing-safe comparison no necesario aquí — HTTP ya añade latencia)
    if payload.get("secret") != bot.webhook_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Secret inválido")

    # 3. Validar acción
    action = str(payload.get("action", "")).strip().lower()
    if action not in VALID_ACTIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Acción inválida: '{action}'. Valores permitidos: {VALID_ACTIONS}",
        )

    # 4. Bot debe estar activo
    if bot.status != "active":
        return {
            "status": "ignored",
            "reason": f"Bot está {bot.status}",
        }

    # 5. Extraer precio (TradingView envía strings para las variables)
    price: float | None = None
    if raw_price := payload.get("price"):
        try:
            price = float(raw_price)
        except (ValueError, TypeError):
            price = None

    # 6. Idempotencia: verificar hash de señal
    signal_hash = generate_signal_hash(bot_id, action, received_at, price)
    existing = await db.execute(
        select(SignalLog).where(SignalLog.signal_hash == signal_hash)
    )
    if existing.scalar_one_or_none():
        return {
            "status": "duplicate",
            "reason": "Señal ya procesada (posible reintento de TradingView)",
        }

    # 7. Registrar señal en DB
    signal_log = SignalLog(
        bot_id=bot_id,
        signal_action=action,
        raw_payload=payload,
        signal_hash=signal_hash,
        received_at=received_at,
        processed=False,
    )
    db.add(signal_log)
    await db.commit()
    await db.refresh(signal_log)

    # 8. Encolar tarea Celery con delay de confirmación opcional
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
