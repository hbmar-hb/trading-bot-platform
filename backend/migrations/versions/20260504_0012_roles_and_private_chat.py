"""Add moderator role support, private chat rooms and room members

Revision ID: 012_roles_and_private_chat
Revises: 20260503_2330_add_chat_font_color
Create Date: 2026-05-04 00:00:00.000000
"""

from alembic import op

revision = '012_roles_and_private_chat'
down_revision = '826dafea5494'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_private column on chat_rooms
    op.execute("""
        ALTER TABLE chat_rooms
        ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # Private room membership table
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_room_members (
            room_id UUID NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (room_id, user_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_room_members_user_id ON chat_room_members(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_room_members")
    op.execute("ALTER TABLE chat_rooms DROP COLUMN IF EXISTS is_private")
