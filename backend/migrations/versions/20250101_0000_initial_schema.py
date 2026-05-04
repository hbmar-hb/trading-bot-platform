"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('username', sa.String(50), nullable=False),
        sa.Column('email', sa.String(100), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # ── refresh_tokens ─────────────────────────────────────────
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_index('ix_refresh_tokens_token', 'refresh_tokens', ['token'], unique=True)

    # ── exchange_accounts ──────────────────────────────────────
    op.create_table(
        'exchange_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('exchange', sa.String(20), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('api_key_encrypted', sa.String(500), nullable=False),
        sa.Column('secret_encrypted', sa.String(500), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # ── bot_configs ────────────────────────────────────────────
    op.create_table(
        'bot_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('exchange_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('exchange_accounts.id'), nullable=False),
        sa.Column('bot_name', sa.String(100), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('position_sizing_type', sa.String(20), nullable=False, server_default='percentage'),
        sa.Column('position_value', sa.Numeric(18, 4), nullable=False),
        sa.Column('leverage', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('initial_sl_percentage', sa.Numeric(8, 4), nullable=False),
        sa.Column('take_profits', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('trailing_config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('breakeven_config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('dynamic_sl_config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('webhook_secret', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='paused'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # ── positions ──────────────────────────────────────────────
    op.create_table(
        'positions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('bot_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bot_configs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('exchange', sa.String(20), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('leverage', sa.Integer(), nullable=True),
        sa.Column('current_sl_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('current_tp_prices', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('unrealized_pnl', sa.Numeric(20, 8), nullable=False, server_default='0'),
        sa.Column('realized_pnl', sa.Numeric(20, 8), nullable=True),
        sa.Column('exchange_order_id', sa.String(100), nullable=True),
        sa.Column('exchange_sl_order_id', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_positions_status', 'positions', ['status'])

    # ── signal_logs ────────────────────────────────────────────
    op.create_table(
        'signal_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('bot_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bot_configs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('signal_action', sa.String(20), nullable=False),
        sa.Column('raw_payload', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('signal_hash', sa.String(64), nullable=False),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_signal_logs_bot_id', 'signal_logs', ['bot_id'])
    op.create_index('ix_signal_logs_signal_hash', 'signal_logs', ['signal_hash'], unique=True)

    # ── bot_logs ───────────────────────────────────────────────
    op.create_table(
        'bot_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('bot_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bot_configs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_bot_logs_bot_id', 'bot_logs', ['bot_id'])
    op.create_index('ix_bot_logs_event_type', 'bot_logs', ['event_type'])
    op.create_index('ix_bot_logs_created_at', 'bot_logs', ['created_at'])


def downgrade() -> None:
    op.drop_table('bot_logs')
    op.drop_table('signal_logs')
    op.drop_table('positions')
    op.drop_table('bot_configs')
    op.drop_table('exchange_accounts')
    op.drop_table('refresh_tokens')
    op.drop_table('users')
