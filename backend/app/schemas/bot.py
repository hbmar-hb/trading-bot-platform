import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator


# ─── Modelos anidados (config JSON) ──────────────────────────

class TakeProfitLevel(BaseModel):
    profit_percent: Decimal     # % desde entrada para activar (e.g. 2.0 = 2%)
    close_percent: Decimal      # % de la posición a cerrar (e.g. 30.0 = 30%)

    @field_validator("close_percent")
    @classmethod
    def close_pct_valid(cls, v: Decimal) -> Decimal:
        if not Decimal("0") < v <= Decimal("100"):
            raise ValueError("close_percent debe estar entre 0 y 100")
        return v


class TrailingConfig(BaseModel):
    enabled: bool = False
    activation_profit: Decimal = Decimal("0")   # % profit para activar
    callback_rate: Decimal = Decimal("0")        # % retroceso desde el máximo


class BreakevenConfig(BaseModel):
    enabled: bool = False
    activation_profit: Decimal = Decimal("0")   # % profit para activar
    lock_profit: Decimal = Decimal("0")          # % adicional a fijar sobre entrada


class DynamicSLConfig(BaseModel):
    enabled: bool = False
    step_percent: Decimal = Decimal("0")         # mover SL cada X% a favor
    max_steps: int = 0


# ─── Requests ────────────────────────────────────────────────

class BotCreate(BaseModel):
    # Exchange: solo uno de los dos debe ser proporcionado
    exchange_account_id: uuid.UUID | None = None  # Para trading real
    paper_balance_id: uuid.UUID | None = None     # Para paper trading
    
    bot_name: str
    symbol: str
    timeframe: str
    position_sizing_type: Literal["percentage", "fixed"] = "percentage"
    position_value: Decimal
    leverage: int = 1
    initial_sl_percentage: Decimal
    take_profits: list[TakeProfitLevel] = []
    trailing_config: TrailingConfig = TrailingConfig()
    breakeven_config: BreakevenConfig = BreakevenConfig()
    dynamic_sl_config: DynamicSLConfig = DynamicSLConfig()
    signal_confirmation_minutes: int = 0

    @field_validator("exchange_account_id", "paper_balance_id")
    @classmethod
    def validate_account(cls, v: uuid.UUID | None, info) -> uuid.UUID | None:
        # Verificar que al menos uno esté definido
        if info.field_name == "paper_balance_id":
            exchange_id = info.data.get("exchange_account_id")
            paper_id = v
        else:
            exchange_id = v
            paper_id = info.data.get("paper_balance_id")
        
        if not exchange_id and not paper_id:
            raise ValueError(
                "Debes proporcionar exchange_account_id (trading real) "
                "o paper_balance_id (paper trading)"
            )
        if exchange_id and paper_id:
            raise ValueError(
                "No puedes proporcionar ambos exchange_account_id y paper_balance_id. "
                "Elige trading real o paper trading."
            )
        return v

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("leverage")
    @classmethod
    def leverage_valid(cls, v: int) -> int:
        if not 1 <= v <= 125:
            raise ValueError("El apalancamiento debe estar entre 1 y 125")
        return v

    @field_validator("position_value")
    @classmethod
    def position_value_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("El valor de posición debe ser positivo")
        return v

    @field_validator("initial_sl_percentage")
    @classmethod
    def sl_valid(cls, v: Decimal) -> Decimal:
        if not Decimal("0") < v <= Decimal("100"):
            raise ValueError("El SL debe estar entre 0 y 100%")
        return v

    @field_validator("take_profits")
    @classmethod
    def tps_close_sum(cls, v: list[TakeProfitLevel]) -> list[TakeProfitLevel]:
        total = sum(tp.close_percent for tp in v)
        if total > Decimal("100"):
            raise ValueError(
                f"La suma de close_percent de los TPs ({total}%) supera el 100%"
            )
        return v


class BotUpdate(BotCreate):
    """Actualización completa del bot (solo cuando está paused o disabled)."""
    pass


class BotStatusUpdate(BaseModel):
    status: Literal["active", "paused", "disabled"]


# ─── Responses ───────────────────────────────────────────────

class BotLogResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    event_type: str
    message: str
    extra_data: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SignalLogResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    signal_action: str
    raw_payload: dict
    signal_hash: str
    processed: bool
    processed_at: datetime | None = None
    error_message: str | None = None
    received_at: datetime

    model_config = {"from_attributes": True}


class BotResponse(BaseModel):
    id: uuid.UUID
    exchange_account_id: uuid.UUID | None = None
    paper_balance_id: uuid.UUID | None = None
    bot_name: str
    symbol: str
    timeframe: str
    position_sizing_type: str
    position_value: Decimal
    leverage: int
    initial_sl_percentage: Decimal
    take_profits: list
    trailing_config: dict
    breakeven_config: dict
    dynamic_sl_config: dict
    webhook_secret: str
    signal_confirmation_minutes: int
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
    
    @computed_field
    @property
    def is_paper_trading(self) -> bool:
        """True si el bot es de paper trading."""
        return self.paper_balance_id is not None
    
    @computed_field
    @property
    def account_display(self) -> str:
        """Muestra la cuenta asociada."""
        if self.paper_balance_id:
            return "📄 Paper"
        elif self.exchange_account_id:
            return "🏦 Real"
        return "Sin cuenta"
