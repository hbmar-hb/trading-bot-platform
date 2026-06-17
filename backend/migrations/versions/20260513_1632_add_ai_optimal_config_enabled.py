"""add ai_optimal_config_enabled to bot_config

Revision ID: 8a9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p
Revises: 1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
Create Date: 2026-05-13 16:32:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8a9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p'
down_revision: Union[str, None] = '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bot_configs',
        sa.Column('ai_optimal_config_enabled', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    op.drop_column('bot_configs', 'ai_optimal_config_enabled')
