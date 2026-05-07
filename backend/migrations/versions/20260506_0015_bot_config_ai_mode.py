"""Add ai_signal_mode to bot_configs.

Revision ID: 015_bot_config_ai_mode
Revises: 014_ai_signal_quality
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "015_bot_config_ai_mode"
down_revision = "014_ai_signal_quality"
branch_labels = None
depends_on = None


_DEFAULT_CFG = '{"min_score":60,"require_clear":true,"max_concurrent":1}'


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(
        "ALTER TABLE bot_configs "
        "ADD COLUMN IF NOT EXISTS ai_signal_mode BOOLEAN NOT NULL DEFAULT false"
    ))

    # Add JSONB column as nullable first to avoid inline-literal colon parse issue
    conn.execute(sa.text(
        "ALTER TABLE bot_configs "
        "ADD COLUMN IF NOT EXISTS ai_signal_config JSONB"
    ))
    # Backfill existing rows via bound parameter (avoids `:key` being parsed)
    conn.execute(
        sa.text("UPDATE bot_configs SET ai_signal_config = CAST(:v AS JSONB) WHERE ai_signal_config IS NULL"),
        {"v": _DEFAULT_CFG},
    )
    conn.execute(sa.text(
        "ALTER TABLE bot_configs ALTER COLUMN ai_signal_config SET NOT NULL"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE bot_configs DROP COLUMN IF EXISTS ai_signal_mode"))
    conn.execute(sa.text("ALTER TABLE bot_configs DROP COLUMN IF EXISTS ai_signal_config"))
