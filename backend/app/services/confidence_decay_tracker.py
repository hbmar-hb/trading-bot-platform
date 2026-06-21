"""
Confidence Decay Tracker — predicted probability vs realized outcome.

For each model version, computes a rolling window of N resolved signals.
Compares mean predicted win rate (success_probability) with actual win rate.
If divergence > 15%, raises an alert.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

# Fecha de corte: solo usamos señales generadas por el motor actual.
CLEAN_CUTOFF = datetime(2026, 6, 10, tzinfo=timezone.utc)
from typing import TYPE_CHECKING

from sqlalchemy import desc, select, func

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.models.model_confidence_decay import ModelConfidenceDecay
from app.models.ai_signal import AISignal

# ── Constants ──────────────────────────────────────────────
DEFAULT_WINDOW_SIZE = 50
ALERT_THRESHOLD_PCT = Decimal("15.0")
MIN_SIGNALS_FOR_ALERT = 30


def compute_confidence_decay(
    db: Session,
    model_version: str,
    window_size: int = DEFAULT_WINDOW_SIZE,
) -> ModelConfidenceDecay | None:
    """
    Computes rolling confidence decay for a model version.
    Returns the decay record or None if not enough signals.
    """
    # Fetch last N resolved signals for this model version
    # model_version is not stored directly on AISignal, so we use the model
    # from the signal's features or fall back to current model.
    # For now, we track ALL resolved signals regardless of model_version
    # because success_probability is calibrated by the current model.
    # Only count signals that were executed as REAL positions
    from app.models.position import Position
    from app.models.bot_config import BotConfig
    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import UUID as PGUUID

    real_signal_ids = (
        db.query(func.cast(Position.extra_config["ai_signal_id"].astext, PGUUID).label("ai_signal_id"))
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .filter(BotConfig.paper_balance_id.is_(None))
        .filter(Position.extra_config["ai_signal_id"].isnot(None))
        .subquery()
    )

    signals = db.execute(
        select(AISignal)
        .where(
            AISignal.id.in_(select(real_signal_ids.c.ai_signal_id)),
            AISignal.outcome.in_([
                "SUCCESS", "FAILURE", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL"
            ]),
            AISignal.success_probability.isnot(None),
            AISignal.created_at >= CLEAN_CUTOFF,
        )
        .order_by(desc(AISignal.created_at))
        .limit(window_size)
    ).scalars().all()

    if len(signals) < MIN_SIGNALS_FOR_ALERT:
        return None

    # Sort by created_at ascending for window boundaries
    signals = sorted(signals, key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc))
    window_signals = signals[-window_size:]

    total = len(window_signals)
    wins = sum(1 for s in window_signals if s.outcome == "SUCCESS")
    losses = total - wins

    realized_wr = Decimal(wins) / Decimal(total) if total > 0 else Decimal("0")

    # Predicted win rate = mean(success_probability)
    # success_probability is P(SUCCESS=1)
    pred_probs = [Decimal(str(s.success_probability)) for s in window_signals if s.success_probability is not None]
    predicted_wr = sum(pred_probs) / Decimal(len(pred_probs)) if pred_probs else Decimal("0")

    # Divergence: |predicted - realized| / realized * 100
    divergence = None
    if realized_wr > 0:
        divergence = abs(predicted_wr - realized_wr) / realized_wr * Decimal("100")

    is_alert = False
    alert_reason = None
    if divergence is not None and total >= MIN_SIGNALS_FOR_ALERT:
        if divergence >= ALERT_THRESHOLD_PCT:
            is_alert = True
            alert_reason = (
                f"Divergence {float(divergence):.1f}% >= {ALERT_THRESHOLD_PCT}% "
                f"(predicted={float(predicted_wr):.1%}, realized={float(realized_wr):.1%})"
            )

    record = ModelConfidenceDecay(
        id=uuid.uuid4(),
        model_version=model_version,
        window_size=window_size,
        window_start=window_signals[0].created_at if window_signals[0].created_at else datetime.now(timezone.utc),
        window_end=window_signals[-1].created_at if window_signals[-1].created_at else datetime.now(timezone.utc),
        predicted_win_rate=predicted_wr,
        realized_win_rate=realized_wr,
        divergence_pct=divergence,
        is_alert=is_alert,
        alert_reason=alert_reason,
        total_signals=total,
        wins=wins,
        losses=losses,
    )
    db.add(record)
    db.commit()
    return record


def get_latest_decay(db: Session, model_version: str) -> dict | None:
    """Returns the latest decay record for a model version."""
    row = db.execute(
        select(ModelConfidenceDecay)
        .where(ModelConfidenceDecay.model_version == model_version)
        .order_by(desc(ModelConfidenceDecay.window_end))
        .limit(1)
    ).scalars().first()

    if not row:
        return None

    return {
        "model_version": row.model_version,
        "window_size": row.window_size,
        "window_start": row.window_start.isoformat() if row.window_start else None,
        "window_end": row.window_end.isoformat() if row.window_end else None,
        "predicted_win_rate": float(row.predicted_win_rate) if row.predicted_win_rate else None,
        "realized_win_rate": float(row.realized_win_rate) if row.realized_win_rate else None,
        "divergence_pct": float(row.divergence_pct) if row.divergence_pct else None,
        "is_alert": row.is_alert,
        "alert_reason": row.alert_reason,
        "total_signals": row.total_signals,
        "wins": row.wins,
        "losses": row.losses,
    }


def get_decay_history(
    db: Session,
    model_version: str,
    limit: int = 20,
) -> list[dict]:
    """Returns last N decay records for trend analysis."""
    rows = db.execute(
        select(ModelConfidenceDecay)
        .where(ModelConfidenceDecay.model_version == model_version)
        .order_by(desc(ModelConfidenceDecay.window_end))
        .limit(limit)
    ).scalars().all()

    return [
        {
            "window_end": r.window_end.isoformat() if r.window_end else None,
            "predicted_win_rate": float(r.predicted_win_rate) if r.predicted_win_rate else None,
            "realized_win_rate": float(r.realized_win_rate) if r.realized_win_rate else None,
            "divergence_pct": float(r.divergence_pct) if r.divergence_pct else None,
            "is_alert": r.is_alert,
            "total_signals": r.total_signals,
        }
        for r in rows
    ]
