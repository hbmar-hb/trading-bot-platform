"""add ai_signal_shadow_evaluations table

Revision ID: 20260624_0800
Revises: 20260622_1107
Create Date: 2026-06-24 08:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = '20260624_0800'
down_revision = '20260622_1107'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if inspect(conn).has_table('ai_signal_shadow_evaluations'):
        return
    op.create_table(
        'ai_signal_shadow_evaluations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ai_signal_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bot_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('ticker', sa.String(length=30), nullable=False),
        sa.Column('timeframe', sa.String(length=10), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('quality_tier', sa.String(length=10), nullable=True),
        sa.Column('anti_fake_status', sa.String(length=10), nullable=True),
        sa.Column('success_probability', sa.Float(), nullable=True),
        sa.Column('profile', sa.String(length=20), nullable=False),
        sa.Column('profile_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('blocked_at', sa.String(length=40), nullable=True),
        sa.Column('block_reason', sa.String(length=200), nullable=True),
        sa.Column('would_execute', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('simulated_notional', sa.Float(), nullable=True),
        sa.Column('simulated_leverage', sa.Integer(), nullable=True),
        sa.Column('features_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('outcome', sa.String(length=20), nullable=True),
        sa.Column('pnl_pct', sa.Float(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ai_signal_id'], ['ai_signals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['bot_id'], ['bot_configs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ai_signal_shadow_evaluations_ai_signal_id'), 'ai_signal_shadow_evaluations', ['ai_signal_id'], unique=False)
    op.create_index(op.f('ix_ai_signal_shadow_evaluations_bot_id'), 'ai_signal_shadow_evaluations', ['bot_id'], unique=False)
    op.create_index(op.f('ix_ai_signal_shadow_evaluations_evaluated_at'), 'ai_signal_shadow_evaluations', ['evaluated_at'], unique=False)
    op.create_index(op.f('ix_ai_signal_shadow_evaluations_outcome'), 'ai_signal_shadow_evaluations', ['outcome'], unique=False)
    op.create_index(op.f('ix_ai_signal_shadow_evaluations_passed'), 'ai_signal_shadow_evaluations', ['passed'], unique=False)
    op.create_index(op.f('ix_ai_signal_shadow_evaluations_profile'), 'ai_signal_shadow_evaluations', ['profile'], unique=False)
    op.create_index(op.f('ix_ai_signal_shadow_evaluations_ticker'), 'ai_signal_shadow_evaluations', ['ticker'], unique=False)
    op.create_index('ix_ai_signal_shadow_evaluations_ticker_tf_eval', 'ai_signal_shadow_evaluations', ['ticker', 'timeframe', 'evaluated_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_signal_shadow_evaluations_ticker_tf_eval', table_name='ai_signal_shadow_evaluations')
    op.drop_index(op.f('ix_ai_signal_shadow_evaluations_ticker'), table_name='ai_signal_shadow_evaluations')
    op.drop_index(op.f('ix_ai_signal_shadow_evaluations_profile'), table_name='ai_signal_shadow_evaluations')
    op.drop_index(op.f('ix_ai_signal_shadow_evaluations_passed'), table_name='ai_signal_shadow_evaluations')
    op.drop_index(op.f('ix_ai_signal_shadow_evaluations_outcome'), table_name='ai_signal_shadow_evaluations')
    op.drop_index(op.f('ix_ai_signal_shadow_evaluations_evaluated_at'), table_name='ai_signal_shadow_evaluations')
    op.drop_index(op.f('ix_ai_signal_shadow_evaluations_bot_id'), table_name='ai_signal_shadow_evaluations')
    op.drop_index(op.f('ix_ai_signal_shadow_evaluations_ai_signal_id'), table_name='ai_signal_shadow_evaluations')
    op.drop_table('ai_signal_shadow_evaluations')
