"""add 2fa fields to users

Revision ID: 002_add_2fa
Revises: 001_initial
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '002_add_2fa'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('totp_secret', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'totp_enabled')
    op.drop_column('users', 'totp_secret')
