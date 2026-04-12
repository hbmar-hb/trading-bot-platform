-- Migration: Add extra_config column to positions table
-- This column stores additional configuration like trailing stop, breakeven, dynamic SL settings

ALTER TABLE positions ADD COLUMN IF NOT EXISTS extra_config JSONB DEFAULT NULL;

-- Index for querying by config keys if needed
CREATE INDEX IF NOT EXISTS idx_positions_extra_config ON positions USING GIN (extra_config) WHERE extra_config IS NOT NULL;
