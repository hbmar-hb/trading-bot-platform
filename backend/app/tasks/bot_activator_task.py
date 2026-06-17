import time

from celery import shared_task
from loguru import logger

from config.settings import settings


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
        # Small delay when LLM diagnosis is enabled so the async diagnosis task
        # (queued alongside this task) has time to write to the DB before the
        # activator reads it in real-time.
        if settings.llm_enabled and settings.openrouter_api_key:
            time.sleep(1.5)
        result = activate(ai_signal_id)
        logger.info(f"[ACTIVATOR TASK] {ai_signal_id}: {result}")
        return result
    except Exception as exc:
        logger.error(f"[ACTIVATOR TASK] Error: {exc}")
        raise self.retry(exc=exc)
