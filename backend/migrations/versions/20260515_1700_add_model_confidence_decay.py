"""Add model_confidence_decay table.

Revision ID: 20260515_1700
Revises: 20260515_1600
Create Date: 2026-05-15 17:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260515_1700"
down_revision: Union[str, None] = "20260515_1600"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_confidence_decay",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_version", sa.String(64), nullable=False, index=True),
        sa.Column("window_size", sa.Integer, nullable=False, server_default="50"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_win_rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("realized_win_rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("divergence_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_alert", sa.Boolean, nullable=False, server_default="false", index=True),
        sa.Column("alert_reason", sa.String(200), nullable=True),
        sa.Column("total_signals", sa.Integer, nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Index("idx_conf_decay_model_end", "model_version", "window_end"),
    )


def downgrade() -> None:
    op.drop_table("model_confidence_decay")
