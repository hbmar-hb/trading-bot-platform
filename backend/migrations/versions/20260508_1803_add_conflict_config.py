"""add_conflict_config

Revision ID: c672f8cae96143578cf56120245a662c
Revises: a8bacee40765
Create Date: 2026-05-08 18:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c672f8cae96143578cf56120245a662c'
down_revision: Union[str, None] = 'a8bacee40765'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bot_configs',
        sa.Column(
            'conflict_config',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("""'{"ia_vs_manual_same_direction": "reject", "ia_vs_manual_opposite_direction": "allow_with_alert", "ia_vs_signal_same_direction": "reject", "ia_vs_signal_opposite_direction": "close_signal_open_ia", "signal_vs_manual_same_direction": "reject", "signal_vs_manual_opposite_direction": "reject", "manual_requires_confirmation": true}'"""),
        )
    )


def downgrade() -> None:
    op.drop_column('bot_configs', 'conflict_config')
