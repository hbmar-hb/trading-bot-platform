"""add resolved_timeframe to ai_watchlist

Revision ID: 20260517_1300
Revises: 20260517_1200
Create Date: 2026-05-17 13:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260517_1300'
down_revision = '20260517_1200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_watchlist', sa.Column('resolved_timeframe', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('ai_watchlist', 'resolved_timeframe')
