"""
Celery task — recalibrate adaptive confluence weights from historical outcomes.
Runs daily at 03:00 UTC (after the weekly retrain window).
"""
from __future__ import annotations

from celery import shared_task
from loguru import logger

from app.services.database import SessionLocal
from app.services.adaptive_weight_optimizer import recalibrate_with_contraejemplos


@shared_task(
    name="app.tasks.adaptive_weight_task.recalibrate_adaptive_weights",
    queue="default",
    max_retries=2,
    default_retry_delay=60,
)
def recalibrate_adaptive_weights(max_samples: int = 5000) -> dict:
    """Recalibrate weights (aggregated + contraejemplos) and return summary."""
    logger.info("[AdaptiveWeightTask] Starting weight recalibration with CDFC…")
    with SessionLocal() as db:
        result = recalibrate_with_contraejemplos(db, max_samples=max_samples)
    logger.info("[AdaptiveWeightTask] Recalibration with CDFC complete.")
    return result
