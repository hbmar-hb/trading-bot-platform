"""add paper trading support

Revision ID: 004_add_paper_trading
Revises: 003_add_health_check
Create Date: 2026-04-09 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004_add_paper_trading'
down_revision = '003_add_health_check'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear tabla paper_balances
    op.create_table('paper_balances',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', sa.String(100), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('available_balance', sa.Numeric(20, 8), nullable=False),
        sa.Column('total_equity', sa.Numeric(20, 8), nullable=False),
        sa.Column('initial_balance', sa.Numeric(20, 8), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id')
    )
    
    # Hacer exchange_account_id nullable en bot_configs
    op.alter_column('bot_configs', 'exchange_account_id',
                    existing_type=postgresql.UUID(as_uuid=True),
                    nullable=True)
    
    # Añadir paper_balance_id a bot_configs
    op.add_column('bot_configs', sa.Column('paper_balance_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(None, 'bot_configs', 'paper_balances', ['paper_balance_id'], ['id'])


def downgrade() -> None:
    # Eliminar foreign key y columna paper_balance_id
    op.drop_constraint(None, 'bot_configs', type_='foreignkey')
    op.drop_column('bot_configs', 'paper_balance_id')
    
    # Hacer exchange_account_id no nullable de nuevo
    op.alter_column('bot_configs', 'exchange_account_id',
                    existing_type=postgresql.UUID(as_uuid=True),
                    nullable=False)
    
    # Eliminar tabla paper_balances
    op.drop_table('paper_balances')
