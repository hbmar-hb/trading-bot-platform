"""Periodic shadow-mode monitor task (Fase D)."""
from __future__ import annotations

from celery import shared_task
from loguru import logger

from app.services.shadow_monitor_service import run_shadow_monitor_check


@shared_task(
    bind=True,
    max_retries=2,
    name="app.tasks.shadow_monitor_task.run_shadow_monitor",
    queue="default",
)
def run_shadow_monitor(self) -> dict:
    """Run the shadow-mode health check and keep history in Redis."""
    try:
        report = run_shadow_monitor_check(save_history=True)
        if not report["healthy"]:
            logger.warning(
                f"[ShadowMonitorTask] Unhealthy: candidate_none={report['candidate']['none_recent']} "
                f"live_none={report['live']['none_recent']}"
            )
        return report
    except Exception as exc:
        logger.error(f"[ShadowMonitorTask] Failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)
