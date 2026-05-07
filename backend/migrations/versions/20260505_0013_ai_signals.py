"""AI signals table for confluence engine + outcome tracking

Revision ID: 013_ai_signals
Revises: 012_roles_and_private_chat
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op

revision = '013_ai_signals'
down_revision = '012_roles_and_private_chat'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_signals (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ticker      VARCHAR(30)  NOT NULL,
            ccxt_symbol VARCHAR(40)  NOT NULL,
            timeframe   VARCHAR(10)  NOT NULL,
            direction   VARCHAR(10)  NOT NULL,
            score       FLOAT        NOT NULL,
            confidence  VARCHAR(10)  NOT NULL,

            entry_price      FLOAT NOT NULL,
            entry_zone_low   FLOAT NOT NULL,
            entry_zone_high  FLOAT NOT NULL,
            stop_loss        FLOAT NOT NULL,
            take_profit_1    FLOAT NOT NULL,
            take_profit_2    FLOAT NOT NULL,

            features    JSONB NOT NULL DEFAULT '{}',
            components  JSONB NOT NULL DEFAULT '{}',
            warnings    JSONB NOT NULL DEFAULT '[]',
            explanation TEXT,

            outcome       VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            pnl_pct       FLOAT,
            outcome_bars  INTEGER,
            resolved_at   TIMESTAMPTZ,

            signal_time TIMESTAMPTZ NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_signals_created_at  ON ai_signals(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_signals_outcome      ON ai_signals(outcome)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_signals_ticker_tf    ON ai_signals(ticker, timeframe)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_signals")
