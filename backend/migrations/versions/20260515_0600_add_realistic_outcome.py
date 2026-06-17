"""add realistic outcome columns to ai_signals

Revision ID: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q
Revises: 9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p4q
Create Date: 2026-05-15 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q'
down_revision: Union[str, None] = '9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p4q'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add realistic outcome columns
    op.execute(
        "ALTER TABLE ai_signals ADD COLUMN IF NOT EXISTS realistic_outcome VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE ai_signals ADD COLUMN IF NOT EXISTS realistic_pnl_pct FLOAT"
    )
    # Create indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_signals_realistic_outcome ON ai_signals (realistic_outcome)"
    )
    # Create functional index on positions extra_config ai_signal_id for faster joins
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_positions_ai_signal_id
        ON positions ((extra_config->>'ai_signal_id'))
        WHERE extra_config->>'ai_signal_id' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index('ix_ai_signals_realistic_outcome', table_name='ai_signals')
    op.drop_column('ai_signals', 'realistic_outcome')
    op.drop_column('ai_signals', 'realistic_pnl_pct')
    op.execute("DROP INDEX IF EXISTS ix_positions_ai_signal_id")
