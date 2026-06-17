"""Add source column to positions table

Revision ID: 20260507_0017
Revises: 20260506_0016
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa

revision = '017_position_source'
down_revision = '016_ai_scan_persistence'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'positions',
        sa.Column('source', sa.String(20), nullable=False, server_default='bot'),
    )


def downgrade():
    op.drop_column('positions', 'source')
