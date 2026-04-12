import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base

# Tipos de evento registrables
EVENT_TYPES = (
    "signal_received",
    "order_opened",
    "order_closed",
    "sl_moved",
    "tp_hit",
    "breakeven_activated",
    "trailing_activated",
    "conflict_rejected",
    "error",
)


class BotLog(Base):
    __tablename__ = "bot_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Datos adicionales del evento (precio, qty, orden ID, etc.)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, name="metadata")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # ─── Relaciones ──────────────────────────────────────────
    bot: Mapped["BotConfig"] = relationship(back_populates="bot_logs")

    def __repr__(self) -> str:
        return f"<BotLog {self.event_type} bot={self.bot_id}>"
