"""add scanner_regime_configs table

Revision ID: 20260518_1200
Revises: 20260518_1100
Create Date: 2026-05-18 12:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260518_1200'
down_revision = '20260518_1100'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'scanner_regime_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('symbol', sa.String(50), nullable=False, index=True),
        sa.Column('timeframe', sa.String(10), nullable=False, index=True),
        sa.Column('regime', sa.String(30), nullable=False, index=True),
        sa.Column('params', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('signals_generated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('win_rate', sa.Float(), nullable=True),
        sa.Column('avg_pnl', sa.Float(), nullable=True),
        sa.Column('model_used', sa.String(50), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('symbol', 'timeframe', 'regime', name='uix_scanner_regime'),
    )


def downgrade() -> None:
    op.drop_table('scanner_regime_configs')
