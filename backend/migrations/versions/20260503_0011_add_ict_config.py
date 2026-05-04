"""add ict_scan_enabled and ict_config to bot_configs

Revision ID: 011_add_ict_config
Revises: 010_add_chat_personalization
Create Date: 2026-05-03 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '011_add_ict_config'
down_revision = '010_add_chat_personalization'
branch_labels = None
depends_on = None

_ICT_CONFIG_DEFAULT = {
    "pivot_len": 5,
    "atr_mult": 1.5,
    "atr_len": 14,
    "entry_mode": "ob_or_fvg",
    "candles_limit": 200,
}


def upgrade() -> None:
    op.add_column(
        'bot_configs',
        sa.Column(
            'ict_scan_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )
    op.add_column(
        'bot_configs',
        sa.Column(
            'ict_config',
            JSONB(),
            nullable=False,
            server_default=sa.text(
                "'{\"pivot_len\": 5, \"atr_mult\": 1.5, \"atr_len\": 14, "
                "\"entry_mode\": \"ob_or_fvg\", \"candles_limit\": 200}'::jsonb"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column('bot_configs', 'ict_config')
    op.drop_column('bot_configs', 'ict_scan_enabled')
