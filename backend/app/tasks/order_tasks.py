import re
import time
import uuid

from celery import shared_task
from loguru import logger

# BingX 100410: endpoint temporalmente bloqueado por rate-limit
# El mensaje incluye el timestamp de desbloqueo: "unblocked after <ms>"
_BINGX_RATE_LIMIT_CODE = "100410"
_MAX_RATE_LIMIT_WAIT_S = 300  # si el ban dura > 5 min, no esperamos


def _bingx_rate_limit_wait(exc_str: str) -> int | None:
    """Devuelve los segundos a esperar según el timestamp de desbloqueo de BingX, o None."""
    if _BINGX_RATE_LIMIT_CODE not in exc_str:
        return None
    try:
        m = re.search(r'after\s+(\d{13})', exc_str)  # timestamp en ms (13 dígitos)
        if not m:
            return None
        unblock_ms = int(m.group(1))
        wait_s = max(1, (unblock_ms - int(time.time() * 1000)) // 1000 + 2)
        return wait_s
    except Exception:
        return None


def _notify_error(bot_id: str, message: str) -> None:
    try:
        from app.models.bot_config import BotConfig
        from app.models.user import User
        from app.services.database import SessionLocal
        from app.tasks.notification_tasks import error_alert

        with SessionLocal() as db:
            bot = db.query(BotConfig).filter(BotConfig.id == uuid.UUID(bot_id)).first()
            if bot:
                user = db.query(User).filter(User.id == bot.user_id).first()
                if user and user.telegram_chat_id:
                    error_alert.delay(
                        bot_name=bot.bot_name,
                        error=message,
                        chat_id=user.telegram_chat_id,
                    )
    except Exception as notify_err:
        logger.warning(f"No se pudo enviar notificación de error: {notify_err}")


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="orders",
    name="app.tasks.order_tasks.execute_signal",
)
def execute_signal(
    self,
    bot_id: str,
    signal_id: str,
    action: str,
    price: float | None = None,
) -> dict:
    from app.core.engine import execute_signal as engine_execute

    try:
        engine_execute(bot_id, signal_id, action, price)
        return {"status": "ok", "signal_id": signal_id}

    except Exception as exc:
        exc_str = str(exc)
        attempt = self.request.retries + 1
        logger.error(f"Error en execute_signal task (intento {attempt}): {exc_str[:300]}")

        # ── BingX rate-limit 100410 ───────────────────────────────────────────
        wait_s = _bingx_rate_limit_wait(exc_str)
        if wait_s is not None:
            if wait_s <= _MAX_RATE_LIMIT_WAIT_S and self.request.retries < self.max_retries:
                logger.warning(f"[ORDER] BingX rate-limit — reintentando en {wait_s}s")
                raise self.retry(exc=exc, countdown=wait_s)
            else:
                # Ban demasiado largo o sin reintentos restantes — notificar y salir
                mins = wait_s // 60
                secs = wait_s % 60
                wait_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                _notify_error(
                    bot_id,
                    f"BingX bloqueó el endpoint temporalmente (rate-limit). "
                    f"Se desbloqueará en ~{wait_str}. Vuelve a intentarlo entonces."
                )
                return {"status": "rate_limited", "wait_seconds": wait_s}

        # ── Error genérico: backoff exponencial ───────────────────────────────
        if self.request.retries >= self.max_retries:
            _notify_error(
                bot_id,
                f"La señal no pudo ejecutarse tras varios intentos: {exc_str[:200]}",
            )

        retry_in = 5 ** (self.request.retries + 1)
        raise self.retry(exc=exc, countdown=retry_in)
