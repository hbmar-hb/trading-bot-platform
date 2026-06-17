"""
Confidence Decay Tracking — predicted probability vs realized outcome.

Rolling window of N resolved signals per model version.
If |predicted_win_rate - realized_win_rate| / realized_win_rate > 15% → alert.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Integer, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.services.database import Base


class ModelConfidenceDecay(Base):
    """Rolling window confidence calibration check."""
    __tablename__ = "model_confidence_decay"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Predicted: mean(success_probability) = predicted win rate
    predicted_win_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Realized: wins / total
    realized_win_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Divergence
    divergence_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    is_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    alert_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    total_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_conf_decay_model_end", "model_version", "window_end"),
    )
