"""
Model Decay Rate — velocity of confidence decay over time.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, Integer, Index

from app.services.database import Base


class ModelDecayRate(Base):
    __tablename__ = "model_decay_rates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    model_version = Column(String(64), nullable=False, index=True)
    decay_per_week = Column(Float, nullable=False)
    r_squared = Column(Float, nullable=False)
    current_divergence = Column(Float, nullable=False)
    projected_days_to_uncalibrated = Column(Float, nullable=True)
    alert_level = Column(String(20), nullable=False, default="none")
    record_count = Column(Integer, nullable=False, default=0)
    computed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        Index("ix_model_decay_rate_computed", "computed_at", "model_version"),
    )
