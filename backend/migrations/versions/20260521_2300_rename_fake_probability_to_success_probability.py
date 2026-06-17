"""rename fake_probability to success_probability

Revision ID: 20260521_2300
Revises: 20260518_1400
Create Date: 2026-05-21 23:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260521_2300'
down_revision: Union[str, None] = '20260518_1400'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defensivo: renombra solo si la columna antigua aún existe
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ai_signals' AND column_name = 'fake_probability'
            ) THEN
                ALTER TABLE ai_signals RENAME COLUMN fake_probability TO success_probability;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'trade_replay_snapshots' AND column_name = 'fake_probability'
            ) THEN
                ALTER TABLE trade_replay_snapshots RENAME COLUMN fake_probability TO success_probability;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'ai_signals' AND column_name = 'success_probability'
            ) THEN
                ALTER TABLE ai_signals RENAME COLUMN success_probability TO fake_probability;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'trade_replay_snapshots' AND column_name = 'success_probability'
            ) THEN
                ALTER TABLE trade_replay_snapshots RENAME COLUMN success_probability TO fake_probability;
            END IF;
        END $$;
    """)
