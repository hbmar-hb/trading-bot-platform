import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base


class SignalLog(Base):
    __tablename__ = "signal_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # ─── Señal ───────────────────────────────────────────────
    signal_action: Mapped[str] = mapped_column(String(20), nullable=False)  # long|short|close
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ─── Idempotencia (evita procesar la misma señal dos veces) ──
    # Hash = SHA256(bot_id + action + price + timestamp redondeado a 30s)
    signal_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # ─── Estado de procesamiento ─────────────────────────────
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ─── Timestamp ───────────────────────────────────────────
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # ─── Relaciones ──────────────────────────────────────────
    bot: Mapped["BotConfig"] = relationship(back_populates="signal_logs")

    def __repr__(self) -> str:
        return f"<SignalLog {self.signal_action} bot={self.bot_id} processed={self.processed}>"
