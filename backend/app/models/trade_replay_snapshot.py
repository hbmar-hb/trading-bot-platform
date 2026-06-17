"""
Trade Replay Snapshot — versión exacta de cada trade para reproducibilidad.

Guarda features, predictions, weights, thresholds, regime, configs, execution,
y OHLCV de contexto en el momento exacto del trade.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.services.database import Base


class TradeReplaySnapshot(Base):
    """Snapshot inmutable de un trade en el momento de ejecución."""
    __tablename__ = "trade_replay_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Referencias
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ai_signal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_signals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id", ondelete="SET NULL"), nullable=True
    )

    # ── Señal / ML ──────────────────────────────────────────
    features: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    success_probability: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    calibrated_confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    quality_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    anti_fake_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # ── Engine / Confluence ─────────────────────────────────
    confluence_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    regime_confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    htf_bias: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── Bot Config al momento del trade ─────────────────────
    bot_config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    # ── Execution ───────────────────────────────────────────
    execution: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    # execution: {fill_price, slippage_estimate, slippage_actual, order_type,
    #             sor_strategy, sor_reason, quantity, notional, leverage,
    #             entry_price_signal, stop_loss_signal, tp1_signal, tp2_signal,
    #             stop_loss_executed, tp1_executed, tp2_executed,
    #             dynamic_horizon_meta, kelly_meta}

    # ── Gates aplicados ─────────────────────────────────────
    gates_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    # gates: {macro, session_funding, oi_cvd, rolling_beta, divergence, drift, stacking, slippage}

    # ── Market Context ──────────────────────────────────────
    ohlcv_context: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    # últimas N velas [{timestamp, open, high, low, close, volume}, ...]

    funding_rate_at_exec: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    spread_at_exec: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    atr_value_at_exec: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    # ── Model Version ───────────────────────────────────────
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Metadata ────────────────────────────────────────────
    symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<TradeReplaySnapshot {self.symbol} {self.direction} {self.quality_tier}>"
