"""add telegram notifications fields to users

Revision ID: 009_add_telegram_notifications
Revises: 008_add_chat
Create Date: 2026-05-03 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '009_add_telegram_notifications'
down_revision = '008_add_chat'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('telegram_chat_id', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('notify_on_open', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('notify_on_partial', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('notify_on_close', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    op.drop_column('users', 'notify_on_close')
    op.drop_column('users', 'notify_on_partial')
    op.drop_column('users', 'notify_on_open')
    op.drop_column('users', 'telegram_chat_id')
