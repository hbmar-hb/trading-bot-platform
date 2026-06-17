"""add model decay rate table

Revision ID: 20260515_2000
Revises: 20260515_1900
Create Date: 2026-05-15 20:00:00.000000+00:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20260515_2000'
down_revision: Union[str, None] = '20260515_1900'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'model_decay_rates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(64), nullable=False),
        sa.Column('decay_per_week', sa.Float(), nullable=False),
        sa.Column('r_squared', sa.Float(), nullable=False),
        sa.Column('current_divergence', sa.Float(), nullable=False),
        sa.Column('projected_days_to_uncalibrated', sa.Float(), nullable=True),
        sa.Column('alert_level', sa.String(20), nullable=False, server_default='none'),
        sa.Column('record_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_model_decay_rate_model_version', 'model_decay_rates', ['model_version'])
    op.create_index('ix_model_decay_rate_computed', 'model_decay_rates', ['computed_at', 'model_version'])


def downgrade() -> None:
    op.drop_index('ix_model_decay_rate_computed', table_name='model_decay_rates')
    op.drop_index('ix_model_decay_rate_model_version', table_name='model_decay_rates')
    op.drop_table('model_decay_rates')
