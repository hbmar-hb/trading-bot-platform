-- ============================================
-- V2.1 Bot Activation Script
-- ============================================
-- 1. Disable auto-optimizer for ALL AI bots (active + to-be-activated)
-- 2. Inject V2.1 confluence config into ai_signal_config
-- 3. Activate paused crypto bots with AI-AUTO mode
-- 4. Keep paused: commodities, indices, stocks (NATGAS, OIL, NASDAQ, AAPL, GOOGL)

BEGIN;

-- ── Step 1: Disable auto-optimize for ALL current AI bots ───────────────
UPDATE bot_configs
SET auto_optimize_enabled = FALSE
WHERE ai_signal_mode = TRUE;

-- ── Step 2: Inject V2.1 confluence config into ALL bots (preserves existing keys) ──
UPDATE bot_configs
SET ai_signal_config = jsonb_set(
    COALESCE(ai_signal_config, '{}'::jsonb),
    '{confluence}',
    '{
        "require_htf_alignment": true,
        "require_liquidity_sweep": {
            "enabled": true,
            "lookback_candles": 20,
            "htf_alternative": true,
            "timeframes": ["15m", "1h"]
        },
        "pd_gate_strictness": 0.70,
        "asia_gate_enabled": true,
        "killzone_gate_mode": "asia_only"
    }'::jsonb,
    true
)
WHERE ai_signal_mode = TRUE
   OR (
       status = 'paused'
       AND bot_name NOT LIKE '%NATGAS%'
       AND bot_name NOT LIKE '%NCCO%'
       AND bot_name NOT LIKE '%NCSI%'
       AND bot_name NOT LIKE '%NCSK%'
   );

-- ── Step 3: Activate paused CRYPTO bots with AI-AUTO ─────────────────────
UPDATE bot_configs
SET
    status = 'active',
    ai_signal_mode = TRUE,
    auto_optimize_enabled = FALSE
WHERE status = 'paused'
  AND bot_name NOT LIKE '%NATGAS%'
  AND bot_name NOT LIKE '%NCCO%'
  AND bot_name NOT LIKE '%NCSI%'
  AND bot_name NOT LIKE '%NCSK%';

COMMIT;
