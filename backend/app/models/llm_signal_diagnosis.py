"""LLM Signal Diagnosis — stores AI-generated explanations for rejected signals."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.database import Base


class LLMSignalDiagnosis(Base):
    __tablename__ = "llm_signal_diagnoses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ai_signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    trigger_source: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # e.g. "anti_fake", "gate_kelly", "gate_portfolio"

    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    model_used: Mapped[str] = mapped_column(String(50), nullable=False)

    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
