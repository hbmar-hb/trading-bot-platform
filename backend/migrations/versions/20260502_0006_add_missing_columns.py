"""add missing columns to positions and bot_configs

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
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS extra_config JSONB DEFAULT '{}'")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS exchange_position_id VARCHAR(100)")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS signal_confirmation_minutes INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_applied_at TIMESTAMPTZ")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_trades_at_apply INTEGER DEFAULT 0")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_applied_params JSONB DEFAULT '{}'")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_enabled BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_config JSONB NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_last_eval_at TIMESTAMPTZ")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_trades_at_eval INTEGER DEFAULT 0")
    op.execute("ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_history JSONB NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    op.drop_column('bot_configs', 'auto_optimize_history')
    op.drop_column('bot_configs', 'auto_optimize_trades_at_eval')
    op.drop_column('bot_configs', 'auto_optimize_last_eval_at')
    op.drop_column('bot_configs', 'auto_optimize_config')
    op.drop_column('bot_configs', 'auto_optimize_enabled')
    op.drop_column('bot_configs', 'optimizer_applied_params')
    op.drop_column('bot_configs', 'optimizer_trades_at_apply')
    op.drop_column('bot_configs', 'optimizer_applied_at')
    op.drop_column('bot_configs', 'signal_confirmation_minutes')
    op.drop_column('positions', 'exchange_position_id')
    op.drop_column('positions', 'extra_config')
