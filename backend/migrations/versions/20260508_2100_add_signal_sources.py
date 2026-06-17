"""add_signal_sources

Revision ID: 085894bfae254bc0989ffc00a0fb38a5
Revises: c672f8cae96143578cf56120245a662c
Create Date: 2026-05-08 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '085894bfae254bc0989ffc00a0fb38a5'
down_revision: Union[str, None] = 'c672f8cae96143578cf56120245a662c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Añadir nuevos campos
    op.add_column(
        'bot_configs',
        sa.Column('webhook_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'bot_configs',
        sa.Column('indicator_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )

    # 2. Migrar datos: bots con trigger_indicator NOT NULL → indicator_enabled = True
    op.execute("""
        UPDATE bot_configs
        SET indicator_enabled = true
        WHERE trigger_indicator IS NOT NULL
    """)

    # 3. Migrar conflict_config existente al nuevo formato simplificado
    # Bots con ai_signal_mode=true → source=ia
    # Bots con trigger_indicator NOT NULL → source=indicator (o webhook si no)
    op.execute("""
        UPDATE bot_configs
        SET conflict_config = jsonb_build_object(
            'same_direction', 'reject',
            'opposite_direction', jsonb_build_object(
                'ia', CASE WHEN ai_signal_mode THEN 'close_and_open' ELSE 'close_and_open' END,
                'webhook', 'close_and_open',
                'indicator', CASE WHEN trigger_indicator IS NOT NULL THEN 'close_and_open' ELSE 'close_and_open' END
            ),
            'auto_evaluate_profit', true
        )
        WHERE conflict_config IS NULL
           OR conflict_config = '{}'
           OR conflict_config ? 'ia_vs_manual_same_direction'
    """)


def downgrade() -> None:
    op.drop_column('bot_configs', 'indicator_enabled')
    op.drop_column('bot_configs', 'webhook_enabled')
