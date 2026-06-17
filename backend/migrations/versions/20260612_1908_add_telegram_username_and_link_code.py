"""add telegram username and link code to users

Revision ID: 20260612_1908
Revises: 20260612_1044
Create Date: 2026-06-12 19:08:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '20260612_1908'
down_revision = '20260612_1044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('telegram_username', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('telegram_link_code', sa.String(64), nullable=True))
    op.create_unique_constraint('uq_users_telegram_link_code', 'users', ['telegram_link_code'])


def downgrade() -> None:
    op.drop_constraint('uq_users_telegram_link_code', 'users', type_='unique')
    op.drop_column('users', 'telegram_link_code')
    op.drop_column('users', 'telegram_username')
