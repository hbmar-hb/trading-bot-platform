import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal
from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base

PositionSide = Literal["long", "short"]
PositionStatus = Literal["open", "closing", "closed"]


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id", ondelete="CASCADE"), nullable=False
    )

    # ─── Datos de la posición ────────────────────────────────
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)   # long | short

    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int | None] = mapped_column(nullable=True)

    # ─── Stop Loss y Take Profit ─────────────────────────────
    current_sl_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    # current_tp_prices: [{level: 1, price: 35000.0, close_percent: 30, hit: false}, ...]
    current_tp_prices: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    
    # ─── Configuración extra (trailing, breakeven, dynamic sl, etc.) ───
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    # ─── P&L ─────────────────────────────────────────────────
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    # ─── ID de orden en el exchange ─────────────────────────
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exchange_sl_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exchange_position_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ─── Estado ──────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)

    # ─── Timestamps ──────────────────────────────────────────
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ─── Relaciones ──────────────────────────────────────────
    bot: Mapped["BotConfig"] = relationship(back_populates="positions")
    exchange_trades: Mapped[list["ExchangeTrade"]] = relationship(
        back_populates="position", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Position {self.symbol} {self.side} [{self.status}]>"
