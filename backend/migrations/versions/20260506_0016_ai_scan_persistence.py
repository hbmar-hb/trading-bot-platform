"""Add ai_watchlist and ai_latest_scans tables.

Revision ID: 016_ai_scan_persistence
Revises: 015_bot_config_ai_mode
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = "016_ai_scan_persistence"
down_revision = "015_bot_config_ai_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ai_watchlist (
            id        UUID        NOT NULL DEFAULT gen_random_uuid(),
            user_id   UUID        NOT NULL,
            symbol    VARCHAR(30) NOT NULL,
            timeframe VARCHAR(10) NOT NULL DEFAULT '1h',
            PRIMARY KEY (id),
            CONSTRAINT uq_ai_watchlist_user_symbol UNIQUE (user_id, symbol)
        )
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ai_latest_scans (
            symbol      VARCHAR(30) NOT NULL,
            timeframe   VARCHAR(10) NOT NULL,
            status      VARCHAR(20) NOT NULL,
            context     JSONB,
            signal_data JSONB,
            signal_id   UUID,
            scanned_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (symbol, timeframe)
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS ai_latest_scans"))
    conn.execute(sa.text("DROP TABLE IF EXISTS ai_watchlist"))
