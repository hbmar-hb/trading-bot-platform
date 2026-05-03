"""add chat rooms and messages

Revision ID: 008_add_chat
Revises: 007_add_must_change_password
Create Date: 2026-05-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '008_add_chat'
down_revision = '007_add_must_change_password'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_rooms (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL UNIQUE,
            description VARCHAR(500),
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            room_id UUID NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id),
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_room_id ON chat_messages(room_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_created_at ON chat_messages(created_at)")


def downgrade() -> None:
    op.drop_table('chat_messages')
    op.drop_table('chat_rooms')
