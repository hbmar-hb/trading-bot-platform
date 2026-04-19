-- Migración: Agregar campos de auto-optimización a bot_configs
-- Fecha: 2026-04-18

ALTER TABLE bot_configs 
ADD COLUMN IF NOT EXISTS auto_optimize_enabled BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS auto_optimize_config JSONB DEFAULT '{
    "confidence_threshold": 5,
    "high_confidence_threshold": 20,
    "max_sl_change_pct": 30,
    "max_leverage_change": 2,
    "max_tp_change_pct": 20,
    "reeval_after_trades": 5
}'::jsonb,
ADD COLUMN IF NOT EXISTS auto_optimize_last_eval_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS auto_optimize_trades_at_eval INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS auto_optimize_history JSONB DEFAULT '[]'::jsonb;
