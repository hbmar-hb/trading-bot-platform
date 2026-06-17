"""add montecarlo module tables and bot_config column

Revision ID: 20260530_0954
Revises: 20260526_1236
Create Date: 2026-05-30 09:54:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260530_0954'
down_revision = '20260526_1236'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tabla de estrategias
    op.create_table(
        'montecarlo_strategies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('parameters', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('indicators', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_montecarlo_strategies_user_id', 'montecarlo_strategies', ['user_id'])

    # Tabla de backtests
    op.create_table(
        'montecarlo_backtests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('strategy_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.String(50), nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('from_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('to_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('initial_capital', sa.Numeric(18, 4), nullable=False, server_default='10000.0'),
        sa.Column('fee_rate', sa.Numeric(8, 6), nullable=False, server_default='0.0006'),
        sa.Column('slippage_pct', sa.Numeric(8, 6), nullable=False, server_default='0.0'),
        sa.Column('trades', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('metrics', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('equity_curve', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('status', sa.String(20), nullable=False, server_default='completed'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['strategy_id'], ['montecarlo_strategies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_montecarlo_backtests_user_id', 'montecarlo_backtests', ['user_id'])
    op.create_index('ix_montecarlo_backtests_strategy_id', 'montecarlo_backtests', ['strategy_id'])

    # Tabla de simulaciones
    op.create_table(
        'montecarlo_simulations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('backtest_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('simulation_type', sa.String(30), nullable=False),
        sa.Column('n_simulations', sa.Integer(), nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('equity_curves', postgresql.JSONB(), nullable=True),
        sa.Column('validation', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['backtest_id'], ['montecarlo_backtests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_montecarlo_simulations_user_id', 'montecarlo_simulations', ['user_id'])
    op.create_index('ix_montecarlo_simulations_backtest_id', 'montecarlo_simulations', ['backtest_id'])

    # Columna en bot_configs
    op.add_column('bot_configs', sa.Column('montecarlo_config', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('bot_configs', 'montecarlo_config')
    op.drop_index('ix_montecarlo_simulations_backtest_id', table_name='montecarlo_simulations')
    op.drop_index('ix_montecarlo_simulations_user_id', table_name='montecarlo_simulations')
    op.drop_table('montecarlo_simulations')
    op.drop_index('ix_montecarlo_backtests_strategy_id', table_name='montecarlo_backtests')
    op.drop_index('ix_montecarlo_backtests_user_id', table_name='montecarlo_backtests')
    op.drop_table('montecarlo_backtests')
    op.drop_index('ix_montecarlo_strategies_user_id', table_name='montecarlo_strategies')
    op.drop_table('montecarlo_strategies')
