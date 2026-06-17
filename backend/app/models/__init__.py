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
from app.models.ai_signal_rejected import AISignalRejected
from app.models.chat import ChatRoom, ChatMessage

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
    "ChatRoom",
    "ChatMessage",
]
from app.models.model_validation_log import ModelValidationLog
from app.models.paper_real_divergence import PaperRealDivergence
from app.models.model_confidence_decay import ModelConfidenceDecay
from app.models.trade_replay_snapshot import TradeReplaySnapshot
from app.models.deployment_gate_log import DeploymentGateLog
from app.models.symbol_deployment_gate_log import SymbolDeploymentGateLog
from app.models.feature_importance_drift import FeatureImportanceDrift
from app.models.scanner_regime_config import ScannerRegimeConfig
from app.models.fundamental_snapshot import FundamentalSnapshot
from app.models.montecarlo import MonteCarloStrategy, MonteCarloBacktest, MonteCarloSimulation
