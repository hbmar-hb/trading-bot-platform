"""AISignalShadowEvaluation — tracks what would have happened under filter profiles.

Used during the 48h infrastructure/ML validation test to capture false
positives/negatives without executing real or paper trades.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class AISignalShadowEvaluation(Base):
    __tablename__ = "ai_signal_shadow_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Link to the original signal
    ai_signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Bot context (nullable so we can record bot-less evaluations if needed)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bot_configs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Signal identity — duplicated for fast queries without join
    ticker: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    quality_tier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    anti_fake_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    success_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Filter profile under test
    profile: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    profile_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Evaluation outcome
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_at: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    block_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Would the execution gates (slippage/cost/min-notional) have allowed it?
    would_execute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Optional simulated sizing if it had executed
    simulated_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulated_leverage: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Snapshot of signal features + regime at evaluation time
    features_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Resolution — copied from ai_signals when outcome tracker resolves the signal
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
