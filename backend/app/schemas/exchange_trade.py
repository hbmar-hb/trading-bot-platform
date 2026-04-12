"""Schemas para trades importados desde el exchange."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ExchangeTradeBase(BaseModel):
    symbol: str
    side: str  # 'long' | 'short'
    quantity: Decimal
    source: str  # 'bot' | 'manual'


class ExchangeTradeResponse(BaseModel):
    id: uuid.UUID
    exchange_account_id: uuid.UUID
    position_id: uuid.UUID | None
    bot_id: uuid.UUID | None
    source: str  # 'bot' | 'manual'
    
    exchange_trade_id: str
    symbol: str
    side: str
    
    quantity: Decimal
    entry_price: Decimal | None
    exit_price: Decimal | None
    
    realized_pnl: Decimal | None
    fee: Decimal | None
    
    opened_at: datetime | None
    closed_at: datetime | None
    
    order_type: str | None
    status: str
    
    synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ExchangeTradeSyncResult(BaseModel):
    """Resultado de sincronización de trades."""
    total_synced: int
    new_trades: int
    updated_trades: int
    errors: list[str] | None = None


class ExchangeTradeFilter(BaseModel):
    """Filtros para consultar trades."""
    account_id: uuid.UUID | None = None
    bot_id: uuid.UUID | None = None
    source: str | None = None  # 'bot', 'manual', or None for all
    symbol: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
