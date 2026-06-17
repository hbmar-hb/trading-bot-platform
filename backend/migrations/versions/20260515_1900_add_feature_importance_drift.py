"""Add feature_importance_drift table.

Revision ID: 20260515_1900
Revises: 20260515_1800
Create Date: 2026-05-15 19:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260515_1900"
down_revision: Union[str, None] = "20260515_1800"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_importance_drift",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_version", sa.String(64), nullable=False, index=True),
        sa.Column("previous_model_version", sa.String(64), nullable=True),
        sa.Column("current_importance", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("previous_importance", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("decay_by_feature", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("max_decay_feature", sa.String(100), nullable=True),
        sa.Column("max_decay_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("avg_decay_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("total_features_changed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_alert", sa.Boolean, nullable=False, server_default="false", index=True),
        sa.Column("alert_reason", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Index("idx_fi_drift_model", "model_version", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("feature_importance_drift")
