"""AISignalRejected — tracks signals that were rejected by the bot activator.

Used for survival-bias auditing: every 30 days we check if rejected signals
would have been winners, to detect overly aggressive filters.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class AISignalRejected(Base):
    __tablename__ = "ai_signals_rejected"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Signal identity
    ticker:      Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    timeframe:   Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    direction:   Mapped[str] = mapped_column(String(10), nullable=False)
    score:       Mapped[float] = mapped_column(Float, nullable=False)
    quality_tier:     Mapped[str | None] = mapped_column(String(10), nullable=True)
    anti_fake_status: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Why it was rejected
    rejection_reason: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    # e.g. "stale", "tier", "status", "score", "concurrent",
    #      "stacking", "slippage", "macro", "regime",
    #      "drift", "kelly", "portfolio", "look_ahead"

    # Full feature snapshot at rejection time
    features_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Context
    bot_id:      Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(__import__('datetime').timezone.utc)
    )

    # 30-day audit: would this signal have been a winner?
    audited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    would_have_been_winner: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Outcome of a similar signal within +24h (for audit)
    similar_signal_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    similar_signal_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
