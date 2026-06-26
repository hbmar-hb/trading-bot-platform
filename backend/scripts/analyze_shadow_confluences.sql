-- Análisis de correlación entre confluencias y outcome en shadow mode
-- Uso: psql -U admin -d tradingbot -f backend/scripts/analyze_shadow_confluences.sql

-- 1. Win rate por combinación de confluencias (perfil bot_match)
SELECT
    features_snapshot->>'has_ob' AS has_ob,
    features_snapshot->>'has_killzone' AS has_killzone,
    features_snapshot->>'htf_aligned' AS htf_aligned,
    COUNT(*) AS n,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS n_passed,
    SUM(CASE WHEN outcome = 'SUCCESS' THEN 1 ELSE 0 END) AS n_success,
    SUM(CASE WHEN outcome = 'FAILURE' THEN 1 ELSE 0 END) AS n_failure,
    ROUND(
        AVG(CASE WHEN outcome = 'SUCCESS' THEN 1 ELSE 0 END) * 100, 2
    ) AS win_rate_pct,
    ROUND(AVG(pnl_pct)::numeric, 4) AS avg_pnl_pct,
    ROUND(AVG((features_snapshot->>'adaptive_trend_score')::numeric), 2) AS avg_adaptive_score
FROM ai_signal_shadow_evaluations
WHERE profile = 'bot_match'
  AND outcome IS NOT NULL
GROUP BY
    features_snapshot->>'has_ob',
    features_snapshot->>'has_killzone',
    features_snapshot->>'htf_aligned'
ORDER BY n DESC, win_rate_pct DESC;

-- 2. Desglose por estructura de mercado y número de FVGs alineados
SELECT
    features_snapshot->>'structure_type' AS structure_type,
    (features_snapshot->>'fvg_count')::int AS fvg_count,
    COUNT(*) AS n,
    SUM(CASE WHEN outcome = 'SUCCESS' THEN 1 ELSE 0 END) AS n_success,
    ROUND(
        AVG(CASE WHEN outcome = 'SUCCESS' THEN 1 ELSE 0 END) * 100, 2
    ) AS win_rate_pct,
    ROUND(AVG(pnl_pct)::numeric, 4) AS avg_pnl_pct
FROM ai_signal_shadow_evaluations
WHERE profile = 'bot_match'
  AND outcome IS NOT NULL
GROUP BY
    features_snapshot->>'structure_type',
    (features_snapshot->>'fvg_count')::int
ORDER BY n DESC, win_rate_pct DESC;

-- 3. Comparativa rápida de perfiles para las mismas señales
SELECT
    profile,
    COUNT(*) AS n_evaluated,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS n_passed,
    SUM(CASE WHEN passed AND outcome = 'SUCCESS' THEN 1 ELSE 0 END) AS n_passed_success,
    SUM(CASE WHEN passed AND outcome = 'FAILURE' THEN 1 ELSE 0 END) AS n_passed_failure,
    ROUND(
        AVG(CASE WHEN passed AND outcome = 'SUCCESS' THEN 1 ELSE 0 END) * 100, 2
    ) AS win_rate_passed_pct,
    ROUND(AVG(CASE WHEN passed THEN pnl_pct END)::numeric, 4) AS avg_pnl_passed_pct
FROM ai_signal_shadow_evaluations
WHERE outcome IS NOT NULL
GROUP BY profile
ORDER BY profile;
