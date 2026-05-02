"""add all missing columns

Revision ID: 006_add_missing_columns
Revises: 005_add_use_roi_percentage
Create Date: 2026-05-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006_add_missing_columns'
down_revision = '005_add_use_roi_percentage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users: columnas faltantes ───────────────────────────────
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user'")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false")

    # ── positions: columnas faltantes + ampliar symbol ──────────
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS extra_config JSONB DEFAULT '{}'")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS exchange_position_id VARCHAR(100)")
    op.execute("ALTER TABLE positions ALTER COLUMN symbol TYPE VARCHAR(50)")

    # ── bot_configs: columnas faltantes + ampliar symbol ────────
    op.execute("ALTER TABLE bot_configs ALTER COLUMN symbol TYPE VARCHAR(50)")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS signal_confirmation_minutes INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_applied_at TIMESTAMPTZ")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_trades_at_apply INTEGER DEFAULT 0")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_applied_params JSONB DEFAULT '{}'")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_enabled BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_config JSONB NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_last_eval_at TIMESTAMPTZ")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_trades_at_eval INTEGER DEFAULT 0")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_history JSONB NOT NULL DEFAULT '[]'")

    # ── trading_signals: tabla faltante ─────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_signals (
            id UUID PRIMARY KEY,
            bot_id UUID REFERENCES bot_configs(id) ON DELETE CASCADE,
            symbol VARCHAR(50),
            action VARCHAR(20),
            price NUMERIC(20,8),
            payload JSONB DEFAULT '{}',
            received_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    pass
