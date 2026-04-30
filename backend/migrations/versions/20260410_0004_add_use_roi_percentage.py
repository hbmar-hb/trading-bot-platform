"""add use_roi_percentage to bot_configs

Revision ID: 005_add_use_roi_percentage
Revises: 004_add_paper_trading
Create Date: 2026-04-10 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '005_add_use_roi_percentage'
down_revision = '004_add_paper_trading'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bot_configs', sa.Column('use_roi_percentage', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('bot_configs', 'use_roi_percentage')
