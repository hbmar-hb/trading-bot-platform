import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator


SUPPORTED_EXCHANGES = ("bingx", "bitunix")


# ─── Requests ────────────────────────────────────────────────

class ExchangeAccountCreate(BaseModel):
    exchange: Literal["bingx", "bitunix"]
    label: str
    api_key: str
    secret: str

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El label no puede estar vacío")
        return v

    @field_validator("api_key", "secret")
    @classmethod
    def credentials_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Las credenciales no pueden estar vacías")
        return v.strip()


class ExchangeAccountUpdate(BaseModel):
    label: str | None = None
    is_active: bool | None = None
    api_key: str | None = None
    secret: str | None = None

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("El label no puede estar vacío")
        return v

    @field_validator("api_key", "secret")
    @classmethod
    def credentials_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Las credenciales no pueden estar vacías")
        return v.strip() if v else v


# ─── Responses ───────────────────────────────────────────────

class ExchangeAccountResponse(BaseModel):
    id: uuid.UUID
    exchange: str
    label: str
    is_active: bool
    created_at: datetime
    # api_key y secret nunca se devuelven
    
    # Health check de credenciales
    last_health_check_at: datetime | None = None
    last_health_status: str | None = None
    last_health_error: str | None = None

    model_config = {"from_attributes": True}
    
    @computed_field
    @property
    def is_credentials_valid(self) -> bool:
        """True si las credenciales fueron verificadas y son válidas."""
        return self.last_health_status == "healthy"


class ExchangeAccountTestResponse(BaseModel):
    exchange: str
    label: str
    status: Literal["healthy", "error"]
    latency_ms: float | None = None
    error: str | None = None
