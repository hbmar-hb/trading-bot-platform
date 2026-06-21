"""Assistant interaction history for analytics and future fine-tuning."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampMixin
from app.services.database import Base


class AssistantInteraction(TimestampMixin, Base):
    """A single assistant turn (question + answer) persisted for learning."""

    __tablename__ = "assistant_interactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # User message and final assistant reply.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    # Which knowledge scope was used: 'phase1' for regular users, 'developer'
    # for super-admins, 'engine' for /explain metrics queries.
    source_scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Model metadata.
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    was_streamed: Mapped[bool] = mapped_column(default=False, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Explicit user feedback (1 = helpful, -1 = not helpful, None = no feedback).
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional structured metadata: full messages list, retrieved chunks,
    # request history, etc. Keep it compact by default.
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    user: Mapped["User"] = relationship("User", back_populates="assistant_interactions")
