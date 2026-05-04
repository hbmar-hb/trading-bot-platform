import uuid

from celery import shared_task
from loguru import logger


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
        logger.error(f"Error en execute_signal task (intento {self.request.retries + 1}): {exc}")

        # Si es el último reintento, notificar al usuario por Telegram
        if self.request.retries >= self.max_retries:
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
                                error=f"La señal no pudo ejecutarse tras varios intentos: {str(exc)[:200]}",
                                chat_id=user.telegram_chat_id,
                            )
            except Exception as notify_err:
                logger.warning(f"No se pudo enviar notificación de error al usuario: {notify_err}")

        retry_in = 5 ** (self.request.retries + 1)
        raise self.retry(exc=exc, countdown=retry_in)
