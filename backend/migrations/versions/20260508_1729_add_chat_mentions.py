"""add_chat_mentions

Revision ID: a8bacee40765
Revises: 019_trigger_grade_multivalue
Create Date: 2026-05-08 17:29:19.501585

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a8bacee40765'
down_revision: Union[str, None] = '019_trigger_grade_multivalue'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_mentions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('room_id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('mentioned_by', sa.UUID(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['room_id'], ['chat_rooms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mentioned_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chat_mentions_user_id', 'chat_mentions', ['user_id'], unique=False)
    op.create_index('ix_chat_mentions_room_id', 'chat_mentions', ['room_id'], unique=False)
    op.create_index('ix_chat_mentions_is_read', 'chat_mentions', ['is_read'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_chat_mentions_is_read', table_name='chat_mentions')
    op.drop_index('ix_chat_mentions_room_id', table_name='chat_mentions')
    op.drop_index('ix_chat_mentions_user_id', table_name='chat_mentions')
    op.drop_table('chat_mentions')
