"""enable ai_optimal_config_enabled default true and activate for existing AI bots

Revision ID: 9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p4q
Revises: 8a9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p
Create Date: 2026-05-13 19:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p4q'
down_revision: Union[str, None] = '8a9b0c1d2e3f4g5h6i7j8k9l0m1n2o3p'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Change default for new bots
    op.alter_column(
        'bot_configs',
        'ai_optimal_config_enabled',
        server_default='true',
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )

    # 2. Activate for all existing AI bots (those with ai_signal_mode=True)
    op.execute(
        "UPDATE bot_configs SET ai_optimal_config_enabled = true WHERE ai_signal_mode = true"
    )


def downgrade() -> None:
    # Revert default
    op.alter_column(
        'bot_configs',
        'ai_optimal_config_enabled',
        server_default='false',
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )

    # We intentionally do NOT revert the data for existing bots
    # (downgrade should not silently disable user settings)
