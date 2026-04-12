"""
Balance para cuentas de Paper Trading.

Las cuentas paper no usan exchange_account real, por lo que necesitan
su propia tabla de balances.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base


def utc_now():
    """Devuelve datetime UTC actual."""
    return datetime.now(timezone.utc)


class PaperBalance(Base):
    """Balance de una cuenta de Paper Trading."""
    
    __tablename__ = "paper_balances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    
    # Referencia al usuario propietario
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    
    # Identificador único de la cuenta paper
    account_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    
    # Nombre descriptivo de la cuenta
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Balances
    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("10000"), nullable=False
    )
    total_equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("10000"), nullable=False
    )
    
    # Balance inicial (para reset)
    initial_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("10000"), nullable=False
    )
    
    # Estado
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    
    # Relaciones
    user: Mapped["User"] = relationship(back_populates="paper_balances")
    bots: Mapped[list["BotConfig"]] = relationship(
        back_populates="paper_balance", cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<PaperBalance {self.label}: {self.available_balance} USDT>"
    
    def reset_balance(self) -> None:
        """Resetea el balance al valor inicial."""
        self.available_balance = self.initial_balance
        self.total_equity = self.initial_balance
