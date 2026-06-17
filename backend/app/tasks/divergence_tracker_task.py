"""
Celery task: Paper vs Real Divergence Tracker.

Corre cada 4 horas y escanea divergencias entre paper y real
para todos los pares activos.
"""
from celery import shared_task

from app.services.database import SessionLocal
from app.services.divergence_tracker import run_divergence_scan
from loguru import logger

logger = logger


@shared_task(name="app.tasks.divergence_tracker_task.run_divergence_scan_task")
def run_divergence_scan_task(days: int = 7) -> dict:
    """Tarea Celery: escanea divergencias paper-vs-real."""
    db = SessionLocal()
    try:
        result = run_divergence_scan(db, days=days)
        logger.info(
            f"[DivergenceScan] Scanned {result['pairs_scanned']} pairs, "
            f"created {result['records_created']} records, "
            f"blocked {len(result['blocked_pairs'])} pairs"
        )
        for b in result["blocked_pairs"]:
            logger.warning(
                f"[DivergenceScan] BLOCKED {b['symbol']} {b['direction']}: {b['reason']}"
            )
        return result
    except Exception as exc:
        logger.error(f"[DivergenceScan] Error: {exc}")
        raise
    finally:
        db.close()
