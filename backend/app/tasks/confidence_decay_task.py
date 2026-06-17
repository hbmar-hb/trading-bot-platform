"""
Celery task: Confidence Decay Tracker.

Runs after outcome tracker (every 15 min) or on demand.
Computes rolling confidence decay for the current model version.
"""
from celery import shared_task
from loguru import logger

from app.services.database import SessionLocal
from app.services.confidence_decay_tracker import compute_confidence_decay


@shared_task(name="app.tasks.confidence_decay_task.track_confidence_decay")
def track_confidence_decay(window_size: int = 50) -> dict:
    """Task: compute confidence decay for current model."""
    db = SessionLocal()
    try:
        # Detect current model version from registry meta
        model_version = "unknown"
        try:
            from ai.registry import MODEL_PATH
            meta_path = MODEL_PATH.parent / "retrain_meta.json"
            if meta_path.exists():
                import json
                with open(meta_path) as f:
                    meta = json.load(f)
                model_version = meta.get("model_version")
                if not model_version:
                    # Fallback: build a deterministic version from training timestamp
                    last_trained = meta.get("last_trained_at")
                    if last_trained:
                        from datetime import datetime
                        dt = datetime.fromisoformat(last_trained.replace("Z", "+00:00"))
                        model_version = f"v{dt.strftime('%Y%m%d_%H%M%S')}"
                    else:
                        model_version = "unknown"
        except Exception:
            pass

        record = compute_confidence_decay(db, model_version, window_size=window_size)
        if record:
            logger.info(
                f"[ConfidenceDecay] {model_version} window={record.window_size} "
                f"predicted={float(record.predicted_win_rate or 0):.2%} "
                f"realized={float(record.realized_win_rate or 0):.2%} "
                f"divergence={float(record.divergence_pct or 0):.1f}% "
                f"alert={record.is_alert}"
            )
            return {
                "model_version": model_version,
                "predicted_wr": float(record.predicted_win_rate) if record.predicted_win_rate else None,
                "realized_wr": float(record.realized_win_rate) if record.realized_win_rate else None,
                "divergence_pct": float(record.divergence_pct) if record.divergence_pct else None,
                "is_alert": record.is_alert,
            }
        return {"model_version": model_version, "status": "insufficient_data"}
    except Exception as exc:
        logger.error(f"[ConfidenceDecay] Error: {exc}")
        raise
    finally:
        db.close()
