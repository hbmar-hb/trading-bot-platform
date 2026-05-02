"""add must_change_password to users

Revision ID: 007_add_must_change_password
Revises: 006_add_missing_columns
Create Date: 2026-05-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '007_add_must_change_password'
down_revision = '006_add_missing_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
