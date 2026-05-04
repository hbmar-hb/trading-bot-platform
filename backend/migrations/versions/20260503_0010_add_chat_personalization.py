"""add chat personalization fields to users

Revision ID: 010_add_chat_personalization
Revises: 009_add_telegram_notifications
Create Date: 2026-05-03 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '010_add_chat_personalization'
down_revision = '009_add_telegram_notifications'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('chat_bg_color', sa.String(20), nullable=True, server_default='#1f2937'))
    op.add_column('users', sa.Column('chat_bg_shape', sa.String(20), nullable=True, server_default='none'))
    op.add_column('users', sa.Column('chat_font_family', sa.String(50), nullable=True, server_default='Inter'))
    op.add_column('users', sa.Column('chat_font_size', sa.Integer(), nullable=True, server_default='14'))


def downgrade() -> None:
    op.drop_column('users', 'chat_font_size')
    op.drop_column('users', 'chat_font_family')
    op.drop_column('users', 'chat_bg_shape')
    op.drop_column('users', 'chat_bg_color')
