#!/bin/bash
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot << 'SQL'
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS extra_config JSONB DEFAULT '{}';
ALTER TABLE positions ADD COLUMN IF NOT EXISTS exchange_position_id VARCHAR(100);
ALTER TABLE positions ALTER COLUMN symbol TYPE VARCHAR(50);
ALTER TABLE bot_configs ALTER COLUMN symbol TYPE VARCHAR(50);
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS signal_confirmation_minutes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_applied_at TIMESTAMPTZ;
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_trades_at_apply INTEGER DEFAULT 0;
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS optimizer_applied_params JSONB DEFAULT '{}';
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_config JSONB NOT NULL DEFAULT '{}';
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_last_eval_at TIMESTAMPTZ;
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_trades_at_eval INTEGER DEFAULT 0;
ALTER TABLE bot_configs ADD COLUMN IF NOT EXISTS auto_optimize_history JSONB NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS trading_signals (
    id UUID PRIMARY KEY,
    bot_id UUID REFERENCES bot_configs(id) ON DELETE CASCADE,
    symbol VARCHAR(50),
    action VARCHAR(20),
    price NUMERIC(20,8),
    payload JSONB DEFAULT '{}',
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL
echo "=== Schema aplicado ==="
bash /root/restore-clean.sh
