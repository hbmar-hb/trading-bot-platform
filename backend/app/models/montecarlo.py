"""
Modelos para el módulo Monte Carlo + Backtesting de Estrategias.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base
from app.models.base import TimestampMixin


class MonteCarloStrategy(TimestampMixin, Base):
    """Estrategia de trading personalizada en Python para backtesting."""
    __tablename__ = "montecarlo_strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # {param_name: {default, min, max, type}}
    indicators: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )  # ["ema", "rsi", "atr"]
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MonteCarloBacktest(TimestampMixin, Base):
    """Resultado de un backtest histórico ejecutado sobre una estrategia."""
    __tablename__ = "montecarlo_backtests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("montecarlo_strategies.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    from_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    initial_capital: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=10000.0)
    fee_rate: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, default=0.0006)
    slippage_pct: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, default=0.0)

    trades: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    equity_curve: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed"
    )  # running | completed | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MonteCarloSimulation(TimestampMixin, Base):
    """Resultado de una simulación Monte Carlo sobre un backtest."""
    __tablename__ = "montecarlo_simulations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    backtest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("montecarlo_backtests.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    simulation_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # return_shuffle | bootstrap | param_perturb | equity_path
    n_simulations: Mapped[int] = mapped_column(Integer, nullable=False)

    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    equity_curves: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
