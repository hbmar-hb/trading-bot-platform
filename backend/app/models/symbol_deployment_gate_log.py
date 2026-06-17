"""
Per-symbol / per-timeframe deployment gate log.

Tracks health independently for each (symbol, timeframe) pair so that
one bad pair does not poison the entire fleet.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class SymbolDeploymentGateLog(Base):
    __tablename__ = "symbol_deployment_gate_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # HEALTHY | DEGRADED | PAUSED

    sizing_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("1.00")
    )

    sharpe_20: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    expectancy: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index(
            "idx_symgate_symbol_tf_created",
            "symbol",
            "timeframe",
            "created_at",
        ),
    )
