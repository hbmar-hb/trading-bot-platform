"""add llm_signal_diagnoses table

Revision ID: 20260518_1000
Revises: 20260518_0800
Create Date: 2026-05-18 10:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260518_1000'
down_revision = '20260518_0800'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_signal_diagnoses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('ai_signal_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ai_signals.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('trigger_source', sa.String(50), nullable=False, index=True),
        sa.Column('prompt_version', sa.String(20), nullable=False),
        sa.Column('model_used', sa.String(50), nullable=False),
        sa.Column('raw_response', sa.Text(), nullable=True),
        sa.Column('diagnosis_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, default=dict),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('llm_signal_diagnoses')
