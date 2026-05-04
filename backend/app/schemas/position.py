import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PositionResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    exchange: str
    symbol: str
    side: str
    entry_price: Decimal
    quantity: Decimal
    leverage: int | None
    current_sl_price: Decimal | None
    current_tp_prices: list
    extra_config: dict | None
    unrealized_pnl: Decimal
    realized_pnl: Decimal | None
    status: str
    exchange_order_id: str | None
    opened_at: datetime
    closed_at: datetime | None

    model_config = {"from_attributes": True}


class PositionListParams(BaseModel):
    status: str | None = None    # 'open' | 'closed' | None (todos)
    bot_id: uuid.UUID | None = None
    limit: int = 50
    offset: int = 0
