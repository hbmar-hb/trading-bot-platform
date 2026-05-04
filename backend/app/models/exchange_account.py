import uuid
from datetime import datetime
from typing import Literal
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base
from app.models.base import TimestampMixin

ExchangeName = Literal["bingx", "bitunix"]


class ExchangeAccount(TimestampMixin, Base):
    __tablename__ = "exchange_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)   # 'bingx' | 'bitunix'
    label: Mapped[str] = mapped_column(String(100), nullable=False)     # 'Mi cuenta principal'
    api_key_encrypted: Mapped[str] = mapped_column(String(500), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ─── Health check de credenciales ──────────────────────────
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 'healthy', 'error_credentials', 'error_network', 'unknown'
    last_health_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    # Relaciones
    user: Mapped["User"] = relationship(back_populates="exchange_accounts")
    bots: Mapped[list["BotConfig"]] = relationship(back_populates="exchange_account")
    trades: Mapped[list["ExchangeTrade"]] = relationship(
        back_populates="exchange_account", cascade="all, delete-orphan"
    )

    @property
    def is_credentials_valid(self) -> bool:
        """Retorna True si las credenciales fueron verificadas recientemente y son válidas."""
        if not self.last_health_status:
            return False
        return self.last_health_status == "healthy"

    def __repr__(self) -> str:
        return f"<ExchangeAccount {self.exchange} — {self.label}>"
