"""add health check fields to exchange_accounts

Revision ID: 003_add_health_check
Revises: 002_add_2fa
Create Date: 2026-04-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '003_add_health_check'
down_revision = '002_add_2fa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Añadir columnas de health check a exchange_accounts
    op.add_column('exchange_accounts', sa.Column('last_health_check_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('exchange_accounts', sa.Column('last_health_status', sa.String(20), nullable=True))
    op.add_column('exchange_accounts', sa.Column('last_health_error', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('exchange_accounts', 'last_health_error')
    op.drop_column('exchange_accounts', 'last_health_status')
    op.drop_column('exchange_accounts', 'last_health_check_at')
