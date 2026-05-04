"""
Trades importados desde el exchange (BingX, Bitunix, etc).
Permite sincronizar historial y distinguir entre trades del bot vs manuales.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base


class ExchangeTrade(Base):
    """
    Trade real ejecutado en el exchange.
    
    Se sincroniza periódicamente desde la API del exchange.
    source='bot' → ejecutado por nuestro bot
    source='manual' → ejecutado manualmente por el usuario en el exchange
    """
    __tablename__ = "exchange_trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Referencias
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    
    # Si es un trade del bot, referencia a la posición
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id", ondelete="SET NULL"), nullable=True
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id", ondelete="SET NULL"), nullable=True
    )
    
    # Origen del trade
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")  # 'bot' | 'manual'
    
    # Datos del trade desde el exchange
    exchange_trade_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # 'long' | 'short'
    
    # Cantidades y precios
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    
    # PnL
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True, default=Decimal("0"))
    
    # Fees desglozadas (si están disponibles)
    fee_asset: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # Timestamps del exchange
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    
    # Metadata
    order_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 'market', 'limit', etc
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="closed")  # 'open', 'closed'
    raw_data: Mapped[dict | None] = mapped_column(Text, nullable=True)  # JSON completo del exchange
    
    # Control de sincronización
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        nullable=False
    )
    
    # Relaciones
    user: Mapped["User"] = relationship(back_populates="exchange_trades")
    exchange_account: Mapped["ExchangeAccount"] = relationship(back_populates="trades")
    position: Mapped["Position | None"] = relationship(back_populates="exchange_trades")
    bot: Mapped["BotConfig | None"] = relationship(back_populates="exchange_trades")
    
    def __repr__(self) -> str:
        return f"<ExchangeTrade {self.symbol} {self.side} {self.source} PnL:{self.realized_pnl}>"
