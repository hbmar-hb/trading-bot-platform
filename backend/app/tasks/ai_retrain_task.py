"""Weekly XGBoost Anti-Fake retraining task.

Triggered by Celery Beat every Sunday at 03:00 UTC.
Also callable manually via POST /ai/model/train.
Skips silently if fewer than 200 resolved signals exist.
"""
from celery import shared_task
from loguru import logger


@shared_task(
    name="app.tasks.ai_retrain_task.retrain_anti_fake",
    queue="default",
)
def retrain_anti_fake() -> dict:
    from ai.dataset_builder import build_dataset_sync
    from ai.trainers.anti_fake_trainer import train, MIN_SAMPLES
    from ai import registry

    X, y = build_dataset_sync()

    if len(X) < MIN_SAMPLES:
        logger.info(
            f"[RETRAIN] Skipping — only {len(X)}/{MIN_SAMPLES} resolved signals"
        )
        return {"status": "insufficient_data", "samples": len(X), "required": MIN_SAMPLES}

    logger.info(f"[RETRAIN] Training on {len(X)} samples…")
    metrics = train(X, y)
    registry.invalidate()  # flush in-memory cache

    logger.info(f"[RETRAIN] Done — AUC={metrics['auc']} ACC={metrics['accuracy']}")
    return {"status": "trained", **metrics}
