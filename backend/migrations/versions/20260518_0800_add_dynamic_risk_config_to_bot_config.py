"""add dynamic_risk_config to bot_config

Revision ID: 20260518_0800
Revises: 20260517_1300
Create Date: 2026-05-18 08:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260518_0800'
down_revision = '20260517_1300'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'bot_configs',
        sa.Column(
            'dynamic_risk_config',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        )
    )


def downgrade() -> None:
    op.drop_column('bot_configs', 'dynamic_risk_config')
