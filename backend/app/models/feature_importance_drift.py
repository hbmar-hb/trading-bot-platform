"""
Feature Importance Drift — tracking de degradación de features individuales.

Compara feature importance del modelo actual vs modelo anterior.
Decay rate por feature = (prev - current) / prev.
Alerta si un feature pierde >50% de importancia relativa.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, String, Numeric, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.services.database import Base


class FeatureImportanceDrift(Base):
    """Registro de drift en feature importance entre entrenamientos."""
    __tablename__ = "feature_importance_drift"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Importancia actual (por feature)
    current_importance: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    # Importancia previa
    previous_importance: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    # Decay por feature: {feature_name: decay_pct}
    decay_by_feature: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    # Métricas globales
    max_decay_feature: Mapped[str | None] = mapped_column(String(100), nullable=True)
    max_decay_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    avg_decay_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    total_features_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Alertas
    is_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    alert_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_fi_drift_model", "model_version", "created_at"),
    )
