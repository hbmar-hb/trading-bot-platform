"""Schemas para Trading Signals"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from pydantic import BaseModel


class TradingSignalBase(BaseModel):
    symbol: str
    action: str  # 'long', 'short', 'close'
    timeframe: Optional[str] = None
    price: Optional[Decimal] = None
    indicator_values: Dict[str, Any] = {}


class TradingSignalCreate(TradingSignalBase):
    source: str = 'tradingview'
    signal_id: Optional[str] = None


class TradingSignalResponse(TradingSignalBase):
    id: uuid.UUID
    user_id: uuid.UUID
    source: str
    signal_id: Optional[str]
    status: str
    error_message: Optional[str]
    position_id: Optional[uuid.UUID]
    received_at: datetime
    processed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class TradingSignalList(BaseModel):
    total: int
    signals: list[TradingSignalResponse]
