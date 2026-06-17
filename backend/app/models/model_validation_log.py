"""ModelValidationLog — persists Walk-Forward Validation results per retraining.

Each row represents one model retraining attempt, including:
  - Whether it passed or failed the WF gate
  - Aggregated metrics (sharpe, profit_factor, expectancy, win_rate, max_dd)
  - Fold-level results (JSONB)
  - Old vs new model comparison
  - Reason for acceptance/rejection
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class ModelValidationLog(Base):
    __tablename__ = "model_validation_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Training metadata
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(30), nullable=False, default="anti_fake_xgb")
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Dataset info
    samples_used: Mapped[int] = mapped_column(Integer, nullable=False)
    features_used: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # Walk-forward validation results
    wf_passed: Mapped[bool] = mapped_column(nullable=False)
    wf_reason: Mapped[str] = mapped_column(Text, nullable=False)
    wf_folds: Mapped[int] = mapped_column(Integer, nullable=False)

    # Aggregated metrics from WF
    wf_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    wf_profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    wf_expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    wf_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    wf_max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    wf_total_return: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Per-fold results (list of dicts)
    wf_fold_results: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    # Old model comparison (if applicable)
    old_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Model performance on hold-out test set (post-WF)
    test_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_recall: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Artifact path
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Top features at training time
    top_features: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
