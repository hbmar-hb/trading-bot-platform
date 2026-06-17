"""
Feature Importance Drift Tracker.

Compara feature importance entre entrenamientos consecutivos.
Calcula decay rate por feature y emite alertas si hay degradación significativa.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.models.feature_importance_drift import FeatureImportanceDrift

# ── Constants ──────────────────────────────────────────────
ALERT_THRESHOLD_PCT = 50.0  # alert if a feature loses >50% relative importance
GLOBAL_DECAY_ALERT = 30.0   # alert if avg decay across all features >30%


def compute_feature_importance_drift(
    db: Session,
    current_importance: dict[str, float],
    model_version: str,
    previous_model_version: str | None = None,
    previous_importance: dict[str, float] | None = None,
) -> FeatureImportanceDrift | None:
    """
    Compare current feature importance with previous training.
    Returns drift record or None if no previous data.
    """
    if not current_importance:
        return None

    # If no previous importance provided, try to load from DB
    if previous_importance is None:
        prev_row = db.execute(
            select(FeatureImportanceDrift)
            .where(FeatureImportanceDrift.model_version == previous_model_version)
            .order_by(FeatureImportanceDrift.created_at.desc())
            .limit(1)
        ).scalars().first()
        if prev_row and prev_row.current_importance:
            previous_importance = prev_row.current_importance
        else:
            # No previous data — store current as baseline
            record = FeatureImportanceDrift(
                id=uuid.uuid4(),
                model_version=model_version,
                previous_model_version=None,
                current_importance=current_importance,
                previous_importance=None,
                decay_by_feature={},
                max_decay_feature=None,
                max_decay_pct=None,
                avg_decay_pct=None,
                total_features_changed=0,
                is_alert=False,
                alert_reason="Baseline — no previous model to compare",
            )
            db.add(record)
            db.commit()
            return record

    if not previous_importance:
        return None

    # Normalize both to percentages
    total_curr = sum(current_importance.values()) or 1.0
    total_prev = sum(previous_importance.values()) or 1.0

    curr_pct = {k: v / total_curr * 100 for k, v in current_importance.items()}
    prev_pct = {k: v / total_prev * 100 for k, v in previous_importance.items()}

    # Compute decay for each feature present in both
    all_features = set(curr_pct.keys()) | set(prev_pct.keys())
    decay_by_feature = {}
    alerts = []

    for feat in all_features:
        c = curr_pct.get(feat, 0.0)
        p = prev_pct.get(feat, 0.0)
        if p > 0:
            decay = (p - c) / p * 100  # positive = lost importance
        else:
            decay = 0.0 if c == 0 else -100.0  # new feature
        decay_by_feature[feat] = round(decay, 2)

        if decay > ALERT_THRESHOLD_PCT:
            alerts.append(f"{feat} lost {decay:.1f}% importance")

    # Global metrics
    decays = list(decay_by_feature.values())
    max_decay = max(decays) if decays else 0.0
    max_decay_feature = max(decay_by_feature, key=decay_by_feature.get) if decay_by_feature else None
    avg_decay = sum(abs(d) for d in decays) / len(decays) if decays else 0.0
    changed = sum(1 for d in decays if abs(d) > 10)

    is_alert = False
    alert_reason = None
    if alerts:
        is_alert = True
        alert_reason = "; ".join(alerts[:5])
    elif avg_decay > GLOBAL_DECAY_ALERT:
        is_alert = True
        alert_reason = f"Average absolute decay {avg_decay:.1f}% > {GLOBAL_DECAY_ALERT}%"

    record = FeatureImportanceDrift(
        id=uuid.uuid4(),
        model_version=model_version,
        previous_model_version=previous_model_version,
        current_importance=curr_pct,
        previous_importance=prev_pct,
        decay_by_feature=decay_by_feature,
        max_decay_feature=max_decay_feature,
        max_decay_pct=Decimal(str(max_decay)),
        avg_decay_pct=Decimal(str(avg_decay)),
        total_features_changed=changed,
        is_alert=is_alert,
        alert_reason=alert_reason,
    )
    db.add(record)
    db.commit()
    return record


def get_latest_drift(db: Session, model_version: str | None = None) -> dict | None:
    """Returns latest feature importance drift record."""
    from sqlalchemy import desc, select

    q = select(FeatureImportanceDrift).order_by(desc(FeatureImportanceDrift.created_at))
    if model_version:
        q = q.where(FeatureImportanceDrift.model_version == model_version)

    row = db.execute(q.limit(1)).scalars().first()
    if not row:
        return None

    return {
        "model_version": row.model_version,
        "previous_model_version": row.previous_model_version,
        "decay_by_feature": row.decay_by_feature,
        "max_decay_feature": row.max_decay_feature,
        "max_decay_pct": float(row.max_decay_pct) if row.max_decay_pct else None,
        "avg_decay_pct": float(row.avg_decay_pct) if row.avg_decay_pct else None,
        "total_features_changed": row.total_features_changed,
        "is_alert": row.is_alert,
        "alert_reason": row.alert_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def get_drift_history(db: Session, limit: int = 20) -> list[dict]:
    """Returns drift history for trend analysis."""
    from sqlalchemy import desc, select

    rows = db.execute(
        select(FeatureImportanceDrift)
        .order_by(desc(FeatureImportanceDrift.created_at))
        .limit(limit)
    ).scalars().all()

    return [
        {
            "model_version": r.model_version,
            "max_decay_pct": float(r.max_decay_pct) if r.max_decay_pct else None,
            "avg_decay_pct": float(r.avg_decay_pct) if r.avg_decay_pct else None,
            "is_alert": r.is_alert,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
