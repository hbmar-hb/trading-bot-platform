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
        retry_in = 5 ** (self.request.retries + 1)
        raise self.retry(exc=exc, countdown=retry_in)
