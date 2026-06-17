"""FASE 3A: Recalibración automática del slippage predictor.

Compara slippage estimado (guardado en TradeReplaySnapshot) vs slippage real
(Position.entry_price vs AISignal.entry_price) de trades cerrados recientemente.

Si el predictor consistentemente sobre-estima o sub-estima, ajusta un factor
de corrección global que se aplica en tiempo real en estimate_slippage().
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import text

from app.services.database import SessionLocal
from app.services.slippage_predictor import set_slippage_correction_factor


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def recalibrate_slippage_predictor(self, lookback_days: int = 3, min_samples: int = 10):
    """Recalculate the global slippage correction factor from recent closed trades.

    Args:
        lookback_days: How many days back to look for closed trades.
        min_samples: Minimum number of trades needed for a reliable recalibration.
    """
    from app.models.trade_replay_snapshot import TradeReplaySnapshot
    from app.models.position import Position
    from app.models.ai_signal import AISignal

    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    with SessionLocal() as db:
        rows = (
            db.query(TradeReplaySnapshot, Position, AISignal)
            .join(Position, TradeReplaySnapshot.position_id == Position.id)
            .join(AISignal, TradeReplaySnapshot.ai_signal_id == AISignal.id)
            .filter(Position.status == "closed")
            .filter(Position.closed_at >= since)
            .filter(TradeReplaySnapshot.execution.isnot(None))
            .all()
        )

        if len(rows) < min_samples:
            logger.info(
                f"[SLIPPAGE-RECAL] Insufficient samples: {len(rows)} < {min_samples}. "
                f"Skipping recalibration."
            )
            return {
                "status": "skipped",
                "reason": "insufficient_samples",
                "samples": len(rows),
                "min_required": min_samples,
            }

        ratios = []
        overestimates = 0
        underestimates = 0

        for snapshot, position, signal in rows:
            exec_data = snapshot.execution or {}
            est_slippage = exec_data.get("slippage_estimate", {}).get("slippage_pct", 0.0)

            signal_entry = float(signal.entry_price) if signal.entry_price else 0.0
            real_entry = float(position.entry_price) if position.entry_price else 0.0

            if signal_entry <= 0 or est_slippage <= 0:
                continue

            actual_slippage = abs(real_entry - signal_entry) / signal_entry * 100.0

            # Ratio: actual / estimated
            # ratio < 1.0 → predictor OVER-estimates
            # ratio > 1.0 → predictor UNDER-estimates
            ratio = actual_slippage / est_slippage if est_slippage > 0 else 1.0
            ratios.append(ratio)

            if ratio < 0.8:
                overestimates += 1
            elif ratio > 1.2:
                underestimates += 1

        if not ratios:
            logger.warning("[SLIPPAGE-RECAL] No valid ratios computed.")
            return {"status": "skipped", "reason": "no_valid_ratios"}

        # Use median instead of mean to be robust to outliers
        sorted_ratios = sorted(ratios)
        median_ratio = sorted_ratios[len(sorted_ratios) // 2]

        # Exponential smoothing: blend 30% new observation with 70% existing
        from app.services.slippage_predictor import get_slippage_correction_factor
        current_factor = get_slippage_correction_factor()
        new_factor = current_factor * 0.7 + median_ratio * 0.3

        set_slippage_correction_factor(new_factor)

        logger.info(
            f"[SLIPPAGE-RECAL] Recalibrated with {len(ratios)} trades. "
            f"median_ratio={median_ratio:.3f} over={overestimates} under={underestimates} "
            f"new_factor={new_factor:.3f} (was {current_factor:.3f})"
        )

        return {
            "status": "recalibrated",
            "samples": len(ratios),
            "median_ratio": round(median_ratio, 4),
            "overestimates": overestimates,
            "underestimates": underestimates,
            "old_factor": round(current_factor, 4),
            "new_factor": round(new_factor, 4),
        }
