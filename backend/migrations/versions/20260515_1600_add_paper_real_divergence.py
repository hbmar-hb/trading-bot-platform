"""Add paper_real_divergence table.

Revision ID: 20260515_1600
Revises: b1c2d3e4f5g6h7i8j9k0l1m2n3o4p5q6r7
Create Date: 2026-05-15 16:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260515_1600"
down_revision: Union[str, None] = "b1c2d3e4f5g6h7i8j9k0l1m2n3o4p5q6r7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_real_divergence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(50), nullable=False, index=True),
        sa.Column("direction", sa.String(10), nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paper_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("real_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paper_avg_entry", sa.Numeric(20, 8), nullable=True),
        sa.Column("real_avg_entry", sa.Numeric(20, 8), nullable=True),
        sa.Column("entry_divergence_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("paper_avg_exit", sa.Numeric(20, 8), nullable=True),
        sa.Column("real_avg_exit", sa.Numeric(20, 8), nullable=True),
        sa.Column("exit_divergence_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("paper_avg_pnl_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("real_avg_pnl_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("pnl_divergence_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("weighted_divergence_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_critical", sa.Boolean, nullable=False, server_default="false", index=True),
        sa.Column("block_reason", sa.String(200), nullable=True),
        sa.Column("extra_data", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Index("idx_paper_real_div_sym_dir_end", "symbol", "direction", "window_end"),
        sa.Index("idx_paper_real_div_critical", "is_critical"),
    )


def downgrade() -> None:
    op.drop_table("paper_real_divergence")
