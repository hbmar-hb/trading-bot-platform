from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):

    # ─── App ───────────────────────────────────────────────
    env: str = "development"
    debug: bool = True

    # ─── Base de datos ─────────────────────────────────────
    database_url: str           # async  (asyncpg)   — FastAPI
    database_url_sync: str      # sync   (psycopg2)  — Celery / Alembic

    # ─── Redis ─────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"             # cache general
    celery_broker_url: str = "redis://redis:6379/1"     # broker Celery
    celery_result_backend: str = "redis://redis:6379/2" # resultados Celery

    # ─── Auth (JWT) ─────────────────────────────────────────
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ─── Encriptación API keys en DB ────────────────────────
    # Generar: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str

    # ─── Exchanges — URLs base ──────────────────────────────
    bingx_base_url: str = "https://open-api.bingx.com"
    bitunix_base_url: str = "https://fapi.bitunix.com"

    # ─── Notificaciones ─────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    # ─── TradingView ────────────────────────────────────────
    # IPs oficiales separadas por coma en .env
    tradingview_allowed_ips: str = "52.89.214.238,34.212.75.30,54.70.159.135"

    @field_validator("tradingview_allowed_ips", mode="before")
    @classmethod
    def parse_allowed_ips(cls, v: str) -> str:
        # Guardamos como string; el método as_list() lo convierte cuando se necesita
        return v

    @property
    def tradingview_ip_list(self) -> List[str]:
        return [ip.strip() for ip in self.tradingview_allowed_ips.split(",") if ip.strip()]

    # ─── Celery Beat ────────────────────────────────────────
    cleanup_logs_days: int = 30

    # ─── Registro de usuarios ───────────────────────────────
    allow_registration: bool = False

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()
