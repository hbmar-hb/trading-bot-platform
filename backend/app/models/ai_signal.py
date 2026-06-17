import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class AISignal(Base):
    __tablename__ = "ai_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    ticker:      Mapped[str]   = mapped_column(String(30), nullable=False, index=True)
    ccxt_symbol: Mapped[str]   = mapped_column(String(40), nullable=False)
    timeframe:   Mapped[str]   = mapped_column(String(10), nullable=False)
    direction:   Mapped[str]   = mapped_column(String(10), nullable=False)  # long | short
    score:       Mapped[float] = mapped_column(Float,      nullable=False)
    confidence:  Mapped[str]   = mapped_column(String(10), nullable=False)  # HIGH | MEDIUM | LOW

    entry_price:     Mapped[float] = mapped_column(Float, nullable=False)
    entry_zone_low:  Mapped[float] = mapped_column(Float, nullable=False)
    entry_zone_high: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss:       Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_1:   Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_2:   Mapped[float] = mapped_column(Float, nullable=False)

    features:    Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    components:  Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    warnings:    Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Quality assessment — filled by signal_quality_engine (Fase 1.5)
    quality_score:    Mapped[float | None] = mapped_column(Float,      nullable=True)
    quality_tier:     Mapped[str | None]   = mapped_column(String(10), nullable=True)
    anti_fake_status: Mapped[str | None]   = mapped_column(String(10), nullable=True)
    success_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    red_flags:   Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    green_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Outcome — filled by the outcome tracker Celery task
    outcome:      Mapped[str]        = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    pnl_pct:      Mapped[float|None] = mapped_column(Float,   nullable=True)
    outcome_bars: Mapped[int|None]   = mapped_column(Integer, nullable=True)
    resolved_at:  Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Realistic outcome — filled by the realistic outcome engine
    realistic_outcome: Mapped[str|None] = mapped_column(String(20), nullable=True, index=True)
    realistic_pnl_pct: Mapped[float|None] = mapped_column(Float, nullable=True)

    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                   default=lambda: datetime.now(__import__('datetime').timezone.utc))
