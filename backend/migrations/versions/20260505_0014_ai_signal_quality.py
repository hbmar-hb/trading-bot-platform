"""Add quality assessment columns to ai_signals (Fase 1.5)

Revision ID: 014_ai_signal_quality
Revises: 013_ai_signals
Create Date: 2026-05-05
"""

from alembic import op

revision = '014_ai_signal_quality'
down_revision = '013_ai_signals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ai_signals
            ADD COLUMN IF NOT EXISTS quality_score    FLOAT,
            ADD COLUMN IF NOT EXISTS quality_tier     VARCHAR(10),
            ADD COLUMN IF NOT EXISTS anti_fake_status VARCHAR(10),
            ADD COLUMN IF NOT EXISTS red_flags        JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS green_flags      JSONB NOT NULL DEFAULT '[]'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE ai_signals
            DROP COLUMN IF EXISTS quality_score,
            DROP COLUMN IF EXISTS quality_tier,
            DROP COLUMN IF EXISTS anti_fake_status,
            DROP COLUMN IF EXISTS red_flags,
            DROP COLUMN IF EXISTS green_flags
    """)
