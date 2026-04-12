# Importar todos los modelos para que Alembic los detecte en autogenerate
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.exchange_account import ExchangeAccount
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.models.signal_log import SignalLog
from app.models.bot_log import BotLog
from app.models.paper_balance import PaperBalance
from app.models.exchange_trade import ExchangeTrade

__all__ = [
    "User",
    "RefreshToken",
    "ExchangeAccount",
    "BotConfig",
    "Position",
    "SignalLog",
    "BotLog",
    "PaperBalance",
    "ExchangeTrade",
]
