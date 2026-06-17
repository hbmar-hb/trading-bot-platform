"""
Paper vs Real Trading Divergence Tracker.

Compara fills de paper trading contra fills reales para el mismo
símbolo/dirección en ventanas de tiempo deslizantes.

Regla: si divergencia acumulada > 15% en 100-200 trades → bloqueo
para pasar a real en ese símbolo.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func, Index, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class PaperRealDivergence(Base):
    """
    Métrica de divergencia paper-vs-real por ventana deslizante.
    """
    __tablename__ = "paper_real_divergence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Ventana
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # long | short
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Conteos
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    real_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Precios medios
    paper_avg_entry: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    real_avg_entry: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    entry_divergence_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )

    paper_avg_exit: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    real_avg_exit: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    exit_divergence_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )

    # P&L medios
    paper_avg_pnl_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    real_avg_pnl_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    pnl_divergence_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )

    # Divergencia combinada (ponderada)
    weighted_divergence_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )

    # Estado
    is_critical: Mapped[bool] = mapped_column(
        nullable=False, default=False, index=True
    )
    block_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    # Metadatos
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "idx_paper_real_divergence_symbol_window",
            "symbol",
            "direction",
            "window_end",
        ),
    )
