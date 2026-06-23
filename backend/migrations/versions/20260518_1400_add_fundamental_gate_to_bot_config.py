"""add fundamental gate columns to bot_configs

Revision ID: 20260518_1400
Revises: 20260518_1300
Create Date: 2026-05-18 14:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260518_1400'
down_revision = '20260518_1300'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # La migración 20260518_1300 ya podría haber creado estas columnas;
    # la duplicación causaba errores en nuevas bases de datos. Se hace idempotente.
    from sqlalchemy import inspect
    columns = {c['name'] for c in inspect(op.get_bind()).get_columns('bot_configs')}
    if 'fundamental_gate_enabled' not in columns:
        op.add_column('bot_configs', sa.Column('fundamental_gate_enabled', sa.Boolean(), nullable=False, server_default='true'))
    if 'fundamental_sensitivity' not in columns:
        op.add_column('bot_configs', sa.Column('fundamental_sensitivity', sa.String(20), nullable=False, server_default='normal'))


def downgrade() -> None:
    op.drop_column('bot_configs', 'fundamental_gate_enabled')
    op.drop_column('bot_configs', 'fundamental_sensitivity')
