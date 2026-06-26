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
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str | None = None

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/0"

    @property
    def celery_broker_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/1"

    @property
    def celery_result_backend(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/2"

    # ─── Auth (JWT) ─────────────────────────────────────────
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    jwt_issuer: str = "trading-bot-api"
    jwt_audience: str = "trading-bot-frontend"

    # ─── Encriptación API keys en DB ────────────────────────
    # Generar: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str

    # ─── Exchanges — URLs base ──────────────────────────────
    bingx_base_url: str = "https://open-api.bingx.com"
    bitunix_base_url: str = "https://fapi.bitunix.com"

    # ─── Notificaciones ─────────────────────────────────────
    # Legacy token: se mantiene como fallback para compatibilidad.
    telegram_bot_token: str = ""
    # Token del bot que envía notificaciones de IA y trades reales.
    telegram_trading_bot_token: str = ""
    # Token del bot que envía notificaciones de bots solo alertas (Telegram-only).
    telegram_quantum_bot_token: str = ""
    telegram_chat_id: str = ""
    # Username del bot de Telegram (sin @) usado para generar enlaces de vinculación.
    telegram_bot_username: str = ""
    # Grupo/topic de Telegram donde el bot QUANTUM envía las señales recibidas por webhook.
    telegram_quantum_group_chat_id: str = ""
    telegram_quantum_thread_id: int = 0
    discord_webhook_url: str = ""
    giphy_api_key: str = ""
    # "essential" = solo trades, circuit breaker, kill switch  |  "verbose" = todo
    telegram_notify_level: str = "essential"

    @property
    def trading_bot_token(self) -> str:
        return self.telegram_trading_bot_token or self.telegram_bot_token

    @property
    def quantum_bot_token(self) -> str:
        return self.telegram_quantum_bot_token or self.telegram_bot_token

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

    # ─── LLM / Moonshot AI (Kimi) ───────────────────────────
    # Compatible OpenAI API. Get key: https://platform.moonshot.cn/
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://api.moonshot.ai/v1"
    llm_default_model: str = "moonshot-v1-8k"
    llm_fallback_model: str = "moonshot-v1-8k"
    llm_timeout_seconds: int = 30
    llm_max_tokens: int = 500
    llm_enabled: bool = True

    # ─── Shadow mode ─────────────────────────────────────────
    # When enabled, bot_activator records what would have happened under
    # several filter profiles without executing trades. Used for ML/gate
    # validation during paper-trading tests.
    ai_shadow_mode_enabled: bool = False

    # ─── Local LLM (Ollama / vLLM / etc.) ────────────────────
    # Used for optional live scanner tips and assistant. The model runs on the
    # user's local machine; the backend calls the exposed OpenAI-compatible endpoint.
    local_llm_url: str = ""          # e.g. http://localhost:11434/v1 or a tunnel URL
    local_llm_model: str = "mistral:7b"              # fast model for interactive tips
    local_llm_model_assistant: str = "mistral:7b"    # model for assistant/RAG responses
    local_llm_model_heavy: str = "mixtral:8x7b"      # slow model for background tasks
    local_llm_enabled: bool = False
    local_llm_allow_remote_fallback: bool = False      # if false, local LLM failures return unavailable instead of using remote paid LLM
    assistant_use_local_llm: bool = True               # if false, assistant uses OpenRouter/Moonshot

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }


    # URLs
    frontend_url: str = "http://localhost"
    api_base_url: str = "http://localhost:8100"

    # Security
    require_email_verification: bool = False

    # Comma-separated list of usernames that have developer/super-admin access.
    # Developers bypass assistant knowledge restrictions and can query all docs.
    developer_usernames: str = "Marci526"

    @property
    def developer_username_set(self) -> set[str]:
        return {u.strip() for u in self.developer_usernames.split(",") if u.strip()}

    # GIFs (Giphy)
    giphy_api_key: str = ""

    # Email (Resend API o SMTP fallback)
    email_provider: str = "resend"
    resend_api_key: str = ""
    email_from: str = ""
    email_from_name: str = "Trading Bot Platform"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True


settings = Settings()
