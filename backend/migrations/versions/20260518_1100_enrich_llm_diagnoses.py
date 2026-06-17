"""enrich llm_signal_diagnoses with outcome fields

Revision ID: 20260518_1100
Revises: 20260518_1000
Create Date: 2026-05-18 11:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260518_1100'
down_revision = '20260518_1000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('llm_signal_diagnoses', sa.Column('outcome', sa.String(30), nullable=True))
    op.add_column('llm_signal_diagnoses', sa.Column('pnl_pct', sa.Float(), nullable=True))
    op.add_column('llm_signal_diagnoses', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('llm_signal_diagnoses', 'outcome')
    op.drop_column('llm_signal_diagnoses', 'pnl_pct')
    op.drop_column('llm_signal_diagnoses', 'resolved_at')
