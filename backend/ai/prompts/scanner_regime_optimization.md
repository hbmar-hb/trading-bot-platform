You are an expert quantitative trading systems engineer. Your task is to optimize the parameters of a confluence-based signal scanner based on the current market regime.

## Current Market Context
- Symbol: {{symbol}}
- Timeframe: {{timeframe}}
- Regime: {{regime}}
- Regime Confidence: {{regime_confidence}}
- ADX: {{adx}}
- ATR Percentile: {{atr_percentile}}
- Relative Volume: {{rel_volume}}
- Realized Volatility: {{realized_vol}}

## Historical Performance in This Regime
{{performance_summary}}

## Scanner Parameters to Optimize

The scanner uses ICT (Inner Circle Trader) + SMC (Smart Money Concepts) logic. Here are the tunable parameters:

1. `pivot_len` — Number of candles to look back for swing highs/lows. Default: 5.
   - In strong trends: shorter (3-4) captures micro-structure.
   - In ranging markets: longer (6-8) filters noise.

2. `atr_mult` — Multiplier for entry zone width around OB/FVG. Default: 0.3.
   - High volatility: increase (0.4-0.6) to avoid whipsaws.
   - Low volatility/compression: decrease (0.15-0.25) for tighter entries.

3. `atr_len` — ATR lookback period. Default: 14.
   - Fast markets: shorter (7-10).
   - Slow markets: longer (20-21).

4. `entry_mode` — Which entry triggers are allowed.
   - "ob_or_fvg" (default): accept Order Blocks OR Fair Value Gaps.
   - "ob_only": only Order Blocks (more conservative).
   - "fvg_only": only Fair Value Gaps (more aggressive in trends).

5. `weight_structure_CHoCH` — Points for Change of Character. Default: 20.
6. `weight_structure_BOS` — Points for Break of Structure. Default: 12.
7. `weight_trigger_OB` — Points for OB trigger. Default: 15.
8. `weight_trigger_FVG` — Points for FVG trigger. Default: 10.
9. `weight_sweep` — Points for liquidity sweep. Default: 18 (trending) / 10 (ranging).
10. `weight_fvg_context` — Points per aligned background FVG. Default: 4 each (max 12).
11. `weight_pd_array` — Points for Premium/Discount alignment. Default: 10.
12. `min_score_threshold` — Minimum confluence score to generate a signal. Default: 55.
13. `required_alignment_fvg_count` — Minimum background FVGs for confirmation. Default: 1.

## Instructions
Respond ONLY with valid JSON matching this exact schema:
```json
{
  "pivot_len": 5,
  "atr_mult": 0.3,
  "atr_len": 14,
  "entry_mode": "ob_or_fvg",
  "weight_structure_CHoCH": 20.0,
  "weight_structure_BOS": 12.0,
  "weight_trigger_OB": 15.0,
  "weight_trigger_FVG": 10.0,
  "weight_sweep": 18.0,
  "weight_fvg_context": 4.0,
  "weight_pd_array": 10.0,
  "min_score_threshold": 55,
  "required_alignment_fvg_count": 1,
  "rationale": "1-2 sentence explanation in Spanish"
}
```

Rules:
- All weight values must be positive floats.
- pivot_len must be an integer between 3 and 10.
- atr_mult must be a float between 0.1 and 0.8.
- atr_len must be an integer between 7 and 21.
- min_score_threshold must be an integer between 30 and 80.
- required_alignment_fvg_count must be an integer between 0 and 4.
- Use Spanish for the rationale.
- Keep rationale under 200 characters.
