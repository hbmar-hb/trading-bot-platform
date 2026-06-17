#!/usr/bin/env python3
"""Backfill candidate shadow predictions for recently resolved signals.

Useful after fixing the signal_id="None" bug so the 48h window can be
populated immediately with real ids.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.ai_signal import AISignal
from app.services.database import SessionLocal
from ai.services.candidate_shadow_mode import record_candidate_shadow
from ai.services import candidate_model
from ai import registry as anti_fake_registry


def backfill(hours: int = 72) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with SessionLocal() as db:
        signals = (
            db.query(AISignal)
            .filter(AISignal.created_at >= since)
            .filter(AISignal.realistic_outcome.isnot(None))
            .filter(AISignal.success_probability.isnot(None))
            .all()
        )

    if not candidate_model.model_ready():
        return {"status": "candidate_model_not_ready", "filled": 0}

    filled = 0
    for sig in signals:
        try:
            live_prob = float(sig.success_probability)
            candidate_prob = candidate_model.predict_success_probability(sig.features or {})
            if candidate_prob is None:
                continue
            record_candidate_shadow(
                signal_id=str(sig.id),
                live_prob=live_prob,
                candidate_prob=candidate_prob,
            )
            filled += 1
        except Exception as exc:
            print(f"skip {sig.id}: {exc}")

    return {"filled": filled, "total_signals": len(signals)}


if __name__ == "__main__":
    result = backfill()
    print(result)
