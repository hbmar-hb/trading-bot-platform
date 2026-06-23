import uuid
from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base
from app.models.base import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Rol: rol1 | moderator | admin | developer
    role: Mapped[str] = mapped_column(String(20), default="rol1", nullable=False)

    # Email verificado
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Forzar cambio de contraseña en el próximo login
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 2FA (TOTP)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Telegram notifications
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    telegram_username: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
    telegram_link_code: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None, unique=True)
    notify_on_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_partial: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_close: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Chat personalization
    chat_bg_color: Mapped[str | None] = mapped_column(String(20), nullable=True, default='#1f2937')
    chat_bg_shape: Mapped[str | None] = mapped_column(String(20), nullable=True, default='none')
    chat_font_family: Mapped[str | None] = mapped_column(String(50), nullable=True, default='Inter')
    chat_font_size: Mapped[int | None] = mapped_column(nullable=True, default=14)
    chat_font_color: Mapped[str | None] = mapped_column(String(20), nullable=True, default='#e2e8f0')

    # Relaciones
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    exchange_accounts: Mapped[list["ExchangeAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    bots: Mapped[list["BotConfig"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    paper_balances: Mapped[list["PaperBalance"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    exchange_trades: Mapped[list["ExchangeTrade"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    assistant_interactions: Mapped[list["AssistantInteraction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"
