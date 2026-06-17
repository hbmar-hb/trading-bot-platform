"""
Deployment Gate Log — máquina de estados unificada de salud del sistema.

Estados:
- HEALTHY   (100% sizing) — todas las métricas en verde
- DEGRADED  (25-50% sizing) — alguna métrica en amarillo
- PAUSED    (0% sizing) — métrica crítica o múltiples amarillas

Métricas de entrada:
- Sharpe rolling 20
- Profit Factor
- Max Drawdown
- Drift PSI
- Walk-Forward validation
- Confidence Decay divergence
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, String, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.services.database import Base


class DeploymentGateLog(Base):
    """Registro de estado de deployment gate."""
    __tablename__ = "deployment_gate_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Estado
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # HEALTHY | DEGRADED | PAUSED
    sizing_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1.00"))

    # Métricas de entrada
    sharpe_20: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    drift_psi_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    wf_passed: Mapped[bool | None] = mapped_column(nullable=True)
    confidence_decay_divergence: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Razones
    reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # Detalle completo
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("idx_deployment_gate_state_created", "state", "created_at"),
    )
