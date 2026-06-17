"""add auto_timeframe to bot_config

Revision ID: 20260517_1200
Revises: 20260515_2000
Create Date: 2026-05-17 12:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260517_1200'
down_revision = '20260515_2000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bot_configs', sa.Column('auto_timeframe', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('bot_configs', 'auto_timeframe')
