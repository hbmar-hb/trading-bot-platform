import uuid
import secrets
from decimal import Decimal
from typing import Literal
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.database import Base
from app.models.base import TimestampMixin

BotStatus = Literal["active", "paused", "disabled"]
PositionSizingType = Literal["percentage", "fixed"]


class BotConfig(TimestampMixin, Base):
    __tablename__ = "bot_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    
    # ─── Exchange (real o paper) ─────────────────────────────
    # Opción 1: Cuenta real de exchange (BingX, Bitunix)
    exchange_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchange_accounts.id"), nullable=True
    )
    # Opción 2: Cuenta paper (simulación)
    paper_balance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_balances.id"), nullable=True
    )

    # ─── Identificación ─────────────────────────────────────
    bot_name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)  # '1h', '4h', '1d'

    # ─── Configuración de capital ────────────────────────────
    position_sizing_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="percentage"
    )
    position_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False
    )                                   # % del equity o cantidad fija en USDT
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # ─── Stop Loss inicial ───────────────────────────────────
    initial_sl_percentage: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)

    # ─── Configuración avanzada (JSONB) ──────────────────────
    # take_profits: [{profit_percent: 2.0, close_percent: 30.0}, ...]
    take_profits: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # trailing_config: {enabled: bool, activation_profit: float, callback_rate: float}
    trailing_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # breakeven_config: {enabled: bool, activation_profit: float, lock_profit: float}
    breakeven_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # dynamic_sl_config: {enabled: bool, step_percent: float, max_steps: int}
    dynamic_sl_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ─── Webhook ─────────────────────────────────────────────
    webhook_secret: Mapped[str] = mapped_column(
        String(64), nullable=False, default=lambda: secrets.token_hex(32)
    )

    # ─── Confirmación de señal ───────────────────────────────
    # Minutos a esperar antes de ejecutar (0 = inmediato)
    signal_confirmation_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # ─── Estado ──────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="paused"
    )   # active | paused | disabled

    # ─── Optimizer tracking ──────────────────────────────────
    # Guarda cuándo y con cuántos trades se aplicaron las últimas sugerencias
    optimizer_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    optimizer_trades_at_apply: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )
    # Qué parámetros se aplicaron (para mostrar en gris)
    optimizer_applied_params: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )

    # ─── Auto-Optimización ───────────────────────────────────
    # Toggle de auto-optimización
    auto_optimize_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Configuración personalizable del algoritmo
    auto_optimize_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, 
        default=lambda: {
            "confidence_threshold": 5,       # Trades mínimos para confianza media
            "high_confidence_threshold": 20, # Trades para confianza alta
            "max_sl_change_pct": 30,         # Máximo cambio SL (%)
            "max_leverage_change": 2,        # Máximo cambio apalancamiento
            "max_tp_change_pct": 20,         # Máximo cambio TP (%)
            "reeval_after_trades": 5,        # Re-evaluar cada N trades nuevos
        }
    )
    # Tracking de ejecución
    auto_optimize_last_eval_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_optimize_trades_at_eval: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )
    # Historial de cambios automáticos
    auto_optimize_history: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )

    # ─── Relaciones ──────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="bots")
    exchange_account: Mapped["ExchangeAccount | None"] = relationship(back_populates="bots")
    paper_balance: Mapped["PaperBalance | None"] = relationship(back_populates="bots")
    positions: Mapped[list["Position"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    signal_logs: Mapped[list["SignalLog"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    bot_logs: Mapped[list["BotLog"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    exchange_trades: Mapped[list["ExchangeTrade"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )

    @property
    def is_paper_trading(self) -> bool:
        """True si el bot opera en modo simulación (paper trading)."""
        return self.paper_balance_id is not None
    
    @property
    def account_display(self) -> str:
        """Retorna el nombre de la cuenta asociada (real o paper)."""
        if self.paper_balance:
            return f"📄 {self.paper_balance.label}"
        elif self.exchange_account:
            return f"🏦 {self.exchange_account.label}"
        return "Sin cuenta"

    def __repr__(self) -> str:
        mode = "📄 PAPER" if self.is_paper_trading else "🏦 LIVE"
        return f"<BotConfig {self.bot_name} — {self.symbol} [{self.status}] {mode}>"
