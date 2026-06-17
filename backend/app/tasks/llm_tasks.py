"""Celery tasks for signal diagnosis.

Diagnoses are now generated internally from existing engine fields
(red_flags, green_flags, success_probability, score, components, features).
No external LLM calls are made, so this queue is zero-cost and near-instant.
"""
from __future__ import annotations

import uuid

from celery import shared_task
from loguru import logger

# from config.settings import settings  # no longer needed — diagnosis is internal


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    queue="default",
    name="app.tasks.llm_tasks.generate_signal_diagnosis",
)
def generate_signal_diagnosis(
    self,
    signal_id: str,
    trigger_source: str,
    gate_details: dict | None = None,
) -> dict:
    """Generate and persist internal diagnosis for a signal.

    Args:
        signal_id: UUID string of the AISignal.
        trigger_source: e.g. "anti_fake", "gate_kelly", "gate_portfolio".
        gate_details: Optional gate-specific context dict.
    """
    try:
        from app.services.database import SessionLocal
        from app.models.ai_signal import AISignal
        from app.services.internal_signal_diagnosis import diagnose_signal_internal
        from app.services.signal_diagnosis import save_diagnosis

        with SessionLocal() as db:
            signal = db.query(AISignal).filter(AISignal.id == uuid.UUID(signal_id)).first()
            if not signal:
                logger.warning(f"[DIAGNOSIS] Signal {signal_id} not found, skipping")
                return {"status": "skipped", "reason": "signal_not_found"}

            diagnosis, metadata = diagnose_signal_internal(signal, trigger_source, gate_details)
            save_diagnosis(
                db,
                signal_id=uuid.UUID(signal_id),
                trigger_source=trigger_source,
                diagnosis=diagnosis,
                raw_response=diagnosis.model_dump_json(),
                metadata=metadata,
            )
            return {
                "status": "ok",
                "signal_id": signal_id,
                "trigger_source": trigger_source,
                "model_used": metadata.get("model_used"),
                "latency_ms": metadata.get("latency_ms"),
                "cost_usd": metadata.get("cost_usd"),
            }

    except Exception as exc:
        logger.error(f"[DIAGNOSIS] Failed for {signal_id}: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {"status": "error", "reason": str(exc)[:200]}
