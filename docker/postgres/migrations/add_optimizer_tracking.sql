-- Migración: Agregar campos de tracking del optimizer a bot_configs
-- Fecha: 2026-04-18

ALTER TABLE bot_configs 
ADD COLUMN IF NOT EXISTS optimizer_applied_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS optimizer_trades_at_apply INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS optimizer_applied_params JSONB DEFAULT '{}';
