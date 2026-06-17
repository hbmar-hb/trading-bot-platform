"""add telegram_chat_id and telegram_thread_id to bot_config

Revision ID: 20260611_1643
Revises: 20260530_0954
Create Date: 2026-06-11 16:43:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260611_1643'
down_revision = '20260530_0954'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'bot_configs',
        sa.Column('telegram_chat_id', sa.String(length=50), nullable=True)
    )
    op.add_column(
        'bot_configs',
        sa.Column('telegram_thread_id', sa.Integer(), nullable=True)
    )
    op.add_column(
        'bot_configs',
        sa.Column('alerts_only', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )


def downgrade() -> None:
    op.drop_column('bot_configs', 'alerts_only')
    op.drop_column('bot_configs', 'telegram_thread_id')
    op.drop_column('bot_configs', 'telegram_chat_id')
