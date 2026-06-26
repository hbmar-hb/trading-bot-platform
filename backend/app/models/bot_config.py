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
from app.utils.crypto import encrypt

BotStatus = Literal["active", "paused", "disabled"]

def _encrypt_webhook_secret() -> str:
    """Genera y encripta un nuevo webhook secret."""
    return encrypt(secrets.token_hex(32))
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
    auto_timeframe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # When auto_timeframe=True, the bot queries historical performance
    # and uses the best timeframe for this ticker instead of the fixed one.

    # ─── Configuración de capital ────────────────────────────
    position_sizing_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="percentage"
    )
    position_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False
    )                                   # % del equity o cantidad fija en USDT
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # ─── Usar %ROI en lugar de % de movimiento de precio ─────
    # Cuando está activo, los porcentajes de SL/TP/Trailing/BE/Dynamic
    # se interpretan como %ROI (afectados por leverage)
    use_roi_percentage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
        String(500), nullable=False, default=lambda: _encrypt_webhook_secret()
    )

    # ─── Telegram Notifications ──────────────────────────────
    # Chat ID para notificaciones de este bot (grupo/canal de Telegram)
    telegram_chat_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None
    )
    # Topic ID para grupos con topics/forums (opcional)
    telegram_thread_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )

    # ─── Modo solo alertas ───────────────────────────────────
    # Si True, el bot solo recibe webhooks y notifica a Telegram.
    # No ejecuta trades ni requiere cuenta de exchange/paper.
    alerts_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
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
        Boolean, nullable=False, default=True
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

    # ─── AI Signal Mode ──────────────────────────────────────
    # Cuando True, el bot auto-ejecuta señales del AI Confluence Scanner
    # (filtro configurable: por defecto quality_tier=STRONG + anti_fake_status=CLEAR)
    ai_signal_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Cuando True, aplica automáticamente la config óptima por ticker
    # calculada desde estadísticas históricas de señales AI
    ai_optimal_config_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    ai_signal_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        default=lambda: {
            "min_score": 60,
            "require_clear": True,
            "max_concurrent": 1,
            "allowed_tiers": ["STRONG"],
            "allowed_statuses": ["CLEAR"],
            "sizing_multipliers": {
                "STRONG": 1.0,
                "MODERATE": 1.0,
                "WEAK": 1.0,
                "CLEAR": 1.0,
                "CAUTION": 1.0,
            },
            "circuit_breaker_thresholds": {
                "STRONG": {"consecutive_sl": 3},
                "MODERATE": {"consecutive_sl": 2},
                "WEAK": {"consecutive_sl": 1},
            },
            "circuit_breaker_state": {},
            "portfolio_limits": {
                "max_total_exposure_pct": 50.0,
                "max_symbol_exposure_pct": 30.0,
                "max_directional_exposure_pct": 40.0,
                "alt_correlation_threshold": 3,
            },
            "timeframe_fallback_enabled": False,
            # Multi-timeframe IA control: null/empty means accept any timeframe.
            "ai_timeframes": None,
            "ai_timeframe_preference": "auto",
            "min_confluence_score": 60,
            "htf_alignment_required": True,
            # V2.1 Confluence Engine — configurable gates per bot
            "confluence": {
                "require_htf_alignment": True,
                "require_liquidity_sweep": {
                    "enabled": True,
                    "lookback_candles": 20,
                    "htf_alternative": True,
                    "timeframes": ["15m", "1h"],
                },
                "pd_gate_strictness": 0.70,
                "asia_gate_enabled": True,
                "killzone_gate_mode": "asia_only",
                "cdc_map": {
                    "15m": "5m", "30m": "5m",
                    "1h": "15m", "2h": "15m",
                    "4h": "1h", "6h": "1h", "8h": "1h", "12h": "4h",
                    "1d": "4h", "3d": "1d", "1w": "1d",
                },
            },
        }
    )

    # ─── Dynamic Risk Manager Config ─────────────────────────
    # Overrides defaults in app/services/dynamic_risk_manager.py
    # emergency_brake thresholds, scale_out levels, time_decay schedule,
    # exposure_caps and slippage_multipliers per symbol.
    dynamic_risk_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # ─── ICT Scan (legacy) ───────────────────────────────────
    # Activa el motor Python ICT en lugar de esperar webhooks externos
    ict_scan_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Configuración del motor ICT (ver ict_engine.py para valores por defecto)
    # {pivot_len, atr_mult, atr_len, entry_mode, candles_limit}
    ict_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        default=lambda: {
            "pivot_len": 5,
            "atr_mult": 1.5,
            "atr_len": 14,
            "entry_mode": "ob_or_fvg",
            "candles_limit": 200,
        }
    )

    # ─── Fuentes de señal activas ───────────────────────────
    # Ahora un bot puede tener múltiples fuentes simultáneamente
    webhook_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    indicator_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # ─── Conflict Resolution Config ─────────────────────────
    # Configuración simplificada de gestión de conflictos
    conflict_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        default=lambda: {
            "same_direction": "reject",
            "opposite_direction": {
                "ia": "close_and_open",
                "webhook": "close_and_open",
                "indicator": "close_and_open",
            },
            "auto_evaluate_profit": True,
        }
    )

    # ─── Alert Trigger ───────────────────────────────────────
    # Indicador que activa el bot: "ict" | None (desactivado)
    trigger_indicator: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None
    )
    # Timeframe del scan (si None, usa bot.timeframe)
    trigger_timeframe: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default=None
    )
    # Grade mínimo de señal para disparar: "A+" | "A" | "A-"
    trigger_min_grade: Mapped[str] = mapped_column(
        String(5), nullable=False, default="A"
    )
    # Cuándo evaluar: "candle_close" | "intracandle"
    trigger_timing: Mapped[str] = mapped_column(
        String(20), nullable=False, default="candle_close"
    )
    # Intervalo en minutos para modo intracandle
    trigger_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    # Velas de confirmación antes de disparar (anti-falsas)
    min_confirm_candles: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    # ─── Fundamental Gate ────────────────────────────────────
    fundamental_gate_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    fundamental_sensitivity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal"
    )  # "strict" | "normal" | "relaxed"

    # ─── Monte Carlo Validation ──────────────────────────────
    montecarlo_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None
    )  # {enabled, min_score, n_trades_lookback, simulation_type}

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
