import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class AIWatchlistItem(Base):
    __tablename__ = "ai_watchlist"

    id:                 Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:            Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    symbol:             Mapped[str]       = mapped_column(String(30), nullable=False)
    timeframe:          Mapped[str]       = mapped_column(String(10), nullable=False, default="1h")
    # When timeframe="auto", this holds the last resolved best timeframe from the scanner.
    resolved_timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "timeframe", name="uq_ai_watchlist_user_symbol_tf"),
    )


class AILatestScan(Base):
    """One row per (symbol, timeframe) — updated every scan cycle."""
    __tablename__ = "ai_latest_scans"

    symbol:      Mapped[str] = mapped_column(String(30), primary_key=True)
    timeframe:   Mapped[str] = mapped_column(String(10), primary_key=True)
    status:      Mapped[str] = mapped_column(String(20), nullable=False)   # SIGNAL | NO_SIGNAL | ERROR
    context:     Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    signal_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True) # full _to_dict(sig) snapshot
    signal_id:   Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scanned_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
