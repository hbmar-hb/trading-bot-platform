-- Migration: Create exchange_trades table
-- Separates bot trades from manual trades for analysis

CREATE TABLE IF NOT EXISTS exchange_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    position_id UUID REFERENCES positions(id) ON DELETE SET NULL,
    bot_id UUID REFERENCES bot_configs(id) ON DELETE SET NULL,
    
    -- Source: 'bot' for bot trades, 'manual' for manual trades
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    
    -- Trade data from exchange
    exchange_trade_id VARCHAR(100) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    
    -- Quantities and prices
    quantity NUMERIC(20, 8) NOT NULL,
    entry_price NUMERIC(20, 8),
    exit_price NUMERIC(20, 8),
    
    -- PnL
    realized_pnl NUMERIC(20, 8),
    fee NUMERIC(20, 8) DEFAULT 0,
    fee_asset VARCHAR(20),
    
    -- Timestamps from exchange
    opened_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    
    -- Metadata
    order_type VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'closed',
    raw_data TEXT,
    
    -- Sync control
    synced_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_source CHECK (source IN ('bot', 'manual')),
    CONSTRAINT chk_side CHECK (side IN ('long', 'short'))
);

-- Indexes for performance
CREATE INDEX idx_exchange_trades_user_id ON exchange_trades(user_id);
CREATE INDEX idx_exchange_trades_account_id ON exchange_trades(exchange_account_id);
CREATE INDEX idx_exchange_trades_position_id ON exchange_trades(position_id);
CREATE INDEX idx_exchange_trades_bot_id ON exchange_trades(bot_id);
CREATE INDEX idx_exchange_trades_source ON exchange_trades(source);
CREATE INDEX idx_exchange_trades_symbol ON exchange_trades(symbol);
CREATE INDEX idx_exchange_trades_closed_at ON exchange_trades(closed_at DESC);
CREATE INDEX idx_exchange_trades_exchange_trade_id ON exchange_trades(exchange_trade_id);

-- Composite index for common queries
CREATE INDEX idx_exchange_trades_user_source_closed 
    ON exchange_trades(user_id, source, closed_at DESC);

COMMENT ON TABLE exchange_trades IS 'Imported trades from exchanges - bot vs manual separation';
COMMENT ON COLUMN exchange_trades.source IS 'bot = executed by bot, manual = user manual trade';
