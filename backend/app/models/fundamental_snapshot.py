"""Fundamental Snapshot — stores CFTC CoT, token unlocks, and macro events."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    ticker: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )  # "cot", "token_unlock", "macro", "manual"

    # Raw data payload (flexible per source)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Computed signal: BLOCK | CAUTION | NEUTRAL | FAVORABLE
    signal: Mapped[str] = mapped_column(String(20), nullable=False, default="NEUTRAL")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # TTL / freshness
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Metadata
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
