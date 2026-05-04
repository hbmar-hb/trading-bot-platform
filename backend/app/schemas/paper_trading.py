"""
Schemas para Paper Trading.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator


class PaperBalanceCreate(BaseModel):
    """Datos para crear una cuenta paper."""
    label: str
    initial_balance: Decimal = Decimal("10000")
    
    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El label no puede estar vacío")
        return v
    
    @field_validator("initial_balance")
    @classmethod
    def balance_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("El balance inicial debe ser positivo")
        return v


class PaperBalanceUpdate(BaseModel):
    """Datos para actualizar una cuenta paper."""
    label: str | None = None


class PaperBalanceResponse(BaseModel):
    """Respuesta con datos de una cuenta paper."""
    id: uuid.UUID
    account_id: str
    label: str
    initial_balance: float
    available_balance: float
    total_equity: float
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class PaperTradeResult(BaseModel):
    """Resultado de una operación paper."""
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    fee: Decimal
    timestamp: datetime
