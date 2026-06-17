"""
Model Decay Rate Tracker — computes velocity of confidence decay.

Uses linear regression on confidence decay records over time to compute
decay rate (divergence per week). Projects days until model becomes
uncalibrated (divergence > 50%).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.models.model_confidence_decay import ModelConfidenceDecay
from app.models.model_decay_rate import ModelDecayRate

# ── Constants ──────────────────────────────────────────────
MIN_RECORDS_FOR_REGRESSION = 3
ALERT_DECAY_PER_WEEK_PCT = 15.0
CRITICAL_DECAY_PER_WEEK_PCT = 30.0
UNCALIBRATED_THRESHOLD_PCT = 50.0


@dataclass(frozen=True)
class DecayRateResult:
    decay_per_week: float
    r_squared: float
    current_divergence: float
    projected_days_to_uncalibrated: float | None
    alert_level: str  # "none" | "warning" | "critical"
    record_count: int


def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """Return (slope, r_squared) for simple linear regression."""
    n = len(x)
    if n < 2:
        return 0.0, 0.0
    
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    ss_xx = sum((xi - mean_x) ** 2 for xi in x)
    ss_yy = sum((yi - mean_y) ** 2 for yi in y)
    
    if ss_xx == 0:
        return 0.0, 0.0
    
    slope = ss_xy / ss_xx
    
    if ss_yy == 0:
        r_squared = 1.0 if abs(slope) < 1e-9 else 0.0
    else:
        r_squared = (ss_xy ** 2) / (ss_xx * ss_yy)
    
    return slope, r_squared


def compute_decay_rate(
    db: Session,
    model_version: str | None = None,
    min_records: int = MIN_RECORDS_FOR_REGRESSION,
) -> DecayRateResult | None:
    """
    Compute decay rate from confidence decay history.
    
    If model_version is None, uses the most recent model version.
    Returns None if not enough records.
    """
    query = select(ModelConfidenceDecay).order_by(desc(ModelConfidenceDecay.computed_at))
    
    if model_version:
        query = query.where(ModelConfidenceDecay.model_version == model_version)
    
    records = db.execute(query.limit(50)).scalars().all()
    
    if len(records) < min_records:
        return None
    
    # Sort by time ascending
    records = sorted(records, key=lambda r: r.computed_at or datetime.min.replace(tzinfo=timezone.utc))
    
    # Use days since first record as x, divergence_pct as y
    base_time = records[0].computed_at
    if base_time is None:
        return None
    
    x = []
    y = []
    for rec in records:
        if rec.computed_at is None or rec.divergence_pct is None:
            continue
        days = (rec.computed_at - base_time).total_seconds() / 86400.0
        x.append(days)
        y.append(float(rec.divergence_pct))
    
    if len(x) < min_records:
        return None
    
    slope, r_squared = _linear_regression(x, y)
    
    # Convert slope from %/day to %/week
    decay_per_week = slope * 7.0
    
    current_divergence = y[-1] if y else 0.0
    
    # Project days until uncalibrated (divergence > 50%)
    projected_days = None
    if decay_per_week > 0 and current_divergence < UNCALIBRATED_THRESHOLD_PCT:
        remaining_pct = UNCALIBRATED_THRESHOLD_PCT - current_divergence
        projected_days = (remaining_pct / decay_per_week) * 7.0
    
    # Alert level
    if decay_per_week >= CRITICAL_DECAY_PER_WEEK_PCT:
        alert_level = "critical"
    elif decay_per_week >= ALERT_DECAY_PER_WEEK_PCT:
        alert_level = "warning"
    else:
        alert_level = "none"
    
    return DecayRateResult(
        decay_per_week=round(decay_per_week, 4),
        r_squared=round(r_squared, 4),
        current_divergence=round(current_divergence, 4),
        projected_days_to_uncalibrated=round(projected_days, 2) if projected_days else None,
        alert_level=alert_level,
        record_count=len(x),
    )


def persist_decay_rate(
    db: Session,
    result: DecayRateResult,
    model_version: str | None = None,
) -> ModelDecayRate:
    """Persist decay rate result to DB."""
    record = ModelDecayRate(
        model_version=model_version or "current",
        decay_per_week=result.decay_per_week,
        r_squared=result.r_squared,
        current_divergence=result.current_divergence,
        projected_days_to_uncalibrated=result.projected_days_to_uncalibrated,
        alert_level=result.alert_level,
        record_count=result.record_count,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_decay_rate(
    db: Session,
    model_version: str | None = None,
) -> DecayRateResult | None:
    """Get the latest persisted decay rate result."""
    query = select(ModelDecayRate).order_by(desc(ModelDecayRate.computed_at))
    if model_version:
        query = query.where(ModelDecayRate.model_version == model_version)
    
    record = db.execute(query.limit(1)).scalar_one_or_none()
    if not record:
        return None
    
    return DecayRateResult(
        decay_per_week=record.decay_per_week,
        r_squared=record.r_squared,
        current_divergence=record.current_divergence,
        projected_days_to_uncalibrated=record.projected_days_to_uncalibrated,
        alert_level=record.alert_level,
        record_count=record.record_count,
    )
