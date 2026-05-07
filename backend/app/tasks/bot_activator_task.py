from celery import shared_task
from loguru import logger


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    queue="orders",
    name="app.tasks.bot_activator_task.activate_signal",
)
def activate_signal(self, ai_signal_id: str) -> dict:
    from app.engines.bot_activator import activate
    try:
        result = activate(ai_signal_id)
        logger.info(f"[ACTIVATOR TASK] {ai_signal_id}: {result}")
        return result
    except Exception as exc:
        logger.error(f"[ACTIVATOR TASK] Error: {exc}")
        raise self.retry(exc=exc)
