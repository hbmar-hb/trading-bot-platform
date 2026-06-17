"""Add symbol_deployment_gate_logs table.

Revision ID: 20260526_1236
Revises: 20260521_2300
Create Date: 2026-05-26 12:36:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260526_1236"
down_revision: Union[str, None] = "20260521_2300"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "symbol_deployment_gate_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(50), nullable=False, index=True),
        sa.Column("timeframe", sa.String(10), nullable=False, index=True),
        sa.Column("state", sa.String(20), nullable=False, index=True),
        sa.Column("sizing_multiplier", sa.Numeric(5, 2), nullable=False, server_default="1.00"),
        sa.Column("sharpe_20", sa.Numeric(10, 4), nullable=True),
        sa.Column("profit_factor", sa.Numeric(10, 4), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("expectancy", sa.Numeric(10, 4), nullable=True),
        sa.Column("trade_count", sa.Integer, nullable=True),
        sa.Column("reasons", postgresql.JSONB, nullable=True, server_default="[]"),
        sa.Column("extra_data", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Index("idx_symgate_symbol_tf_created", "symbol", "timeframe", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("symbol_deployment_gate_logs")
