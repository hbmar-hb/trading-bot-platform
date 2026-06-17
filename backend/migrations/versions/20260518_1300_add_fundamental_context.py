"""add fundamental_snapshots table

Revision ID: 20260518_1300
Revises: 20260518_1200
Create Date: 2026-05-18 13:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260518_1300'
down_revision = '20260518_1200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fundamental_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('ticker', sa.String(50), nullable=False, index=True),
        sa.Column('source', sa.String(30), nullable=False, index=True),
        sa.Column('data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('signal', sa.String(20), nullable=False, server_default='NEUTRAL'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.add_column('bot_configs', sa.Column('fundamental_gate_enabled', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('bot_configs', sa.Column('fundamental_sensitivity', sa.String(20), nullable=False, server_default='normal'))


def downgrade() -> None:
    op.drop_table('fundamental_snapshots')
    op.drop_column('bot_configs', 'fundamental_gate_enabled')
    op.drop_column('bot_configs', 'fundamental_sensitivity')
