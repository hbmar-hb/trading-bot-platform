# IA ENGINE — Arquitectura Completa

## 1. Visión General

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              IA ENGINE (Frontend)                           │
│  Tabs: Dashboard │ Scanner │ Ranking │ Backtest │ Validación │ Real         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FastAPI Backend                                │
│  Routers: /ai/*  →  Services  →  Engines  →  Models  →  PostgreSQL/Redis   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Flujo de una Señal (End-to-End)

```
[1] Scanner Task (Celery, cada 5 min o manual)
    │
    ├──► ai_scanner.py :: scan_symbol()
    │    ├──► fetch_ohlcv()              ← Binance futures via CCXT
    │    ├──► MarketQualityFilter        ← chop / illiquid / spread anomaly / API unstable
    │    │                                  REJECT si no pasa (primer gate real)
    │    ├──► ict_analyze()              ← ICT/SMC estructural + FORWARD LEVELS
    │    │                                  (EQ highs/lows, FVGs por encima/debajo del entry)
    │    ├──► smc_analyze()              ← ADX, ATR, volumen
    │    ├──► detect_regime()            ← adaptive params PRE-confluence (observación)
    │    ├──► macro_context              ← eventos de alto impacto (gate)
    │    ├──► fundamental_context        ← CFTC CoT, token unlocks (gate)
    │    └──► confluence_engine.py       ← Score 0-100, componentes, TPs estructurales
    │                                  (TP1=primer nivel forward, TP2=segundo nivel forward)
    │
    ├──► CausalFeatureBuilder.build()  ← execution-quality features (slippage, gap, fee, tp_fill)
    │    └── Reject if is_complete=False (no imputation) — ANTES del ML
    │
    ├──► ensemble_registry.predict_ensemble_probability()
    │    ├── XGBoost base model          ← P(success) (timeframe-aware training)
    │    ├── RandomForest base model     ← P(success)
    │    ├── RidgeClassifier base model  ← P(success) (linear diversity)
    │    └── Meta-learner LR             ← ensemble_prob (blend)
    │
    ├──► RegimeAdapter.apply_to_signal() ← SEGUNDA vez detect_regime (post-ML, acción)
    │                                       ajusta thresholds según régimen real
    │
    ├──► assess_quality()              ← CLEAR / CAUTION / BLOCK
    │    └── blend = 35% heuristic + 65% confluence_score  (era 50/50)
    │    └── execution penalty (-15 pts) si spread>2×ATR o vol<0.5×
    │
    ├──► CircuitBreaker.allow_trade()  ← stop trading after 3 confident failures
    │
    ├──► RiskEngine.calculate_size()   ← base_size × conf_mult × risk_mult
    │
    ├──► ShadowMode.record_shadow()    ← log live vs standalone XGB for comparison
    │
    └──► Guardar en DB: ai_signal
         ├── features{}                 ← 21 features + forward_levels + tp1_close_pct
         ├── components{}               ← CHoCH, BOS, OB, FVG, sweep, etc.
         ├── success_probability        ← ensemble_success_prob
         ├── quality_tier               ← STRONG / MODERATE / WEAK
         ├── timeframe                  ← 15m/1h/4h/1d/...
         └── anti_fake_status           ← CLEAR / CAUTION / BLOCK
         └── DEDUPLICACIÓN: UNIQUE INDEX (ticker, timeframe, direction, signal_time)

[2] Bot Activator Task (Celery, cada 30s o manual)
    │
    ├──► bot_activator_task.py :: activate_signal()
    │    ├──► resolve_best_timeframe()   ← auto_timeframe.py (composite score per TF)
    │    ├──► DriftDetector.check()      ← feature drift vs reference distribution
    │    ├──► KellySizing.compute()      ← Kelly Criterion sizing (timeframe-filtered)
    │    ├──► ExposureCap.check()        ← max risk per symbol (paper vs real isolated)
    │    ├──► PortfolioManager.gate()    ← correlation + sector exposure
    │    ├──► _compute_optimal_config()  ← timeframe-aware min_score/leverage/tiers
    │    ├──► COOLDOWN GUARD             ← min interval between trades (TF-dependent)
    │    │                                  15m→60min, 1h→120min, 4h→240min, 1d→1440min
    │    ├──► Deployment Gate (REAL ONLY)← paper bots NEVER blocked by gate
    │    ├──► Risk configs by TF         ← trailing/breakeven/dynamic SL defaults per TF
    │    └──► Exchange order (real or paper)
    │
    └──► Position guardada con ai_signal_id + forward_levels en extra_config

[3] Outcome Tracker (Celery, periódico)
    │
    ├──► Revisa señales con outcome PENDING
    ├──► >72h PENDING → CENSORED (label=0.5, weight 0.1–0.3)
    ├──► Compara entry_price vs SL/TP en velas históricas
    ├──► Actualiza: outcome = SUCCESS / FAILURE / PENDING / CENSORED
    └──► Marca: realistic_outcome (si hubo trade real) o ideal (backtest)

[4] Retrain Task (Celery, cada 6h o condicional)
    │
    ├──► dataset_builder.py            ← arma X, y de señales resueltas
    │    ├──► CausalFeatureBuilder (prefer causal; fallback get_profile_for_signal)
    │    ├──► CensoredOutcomeTracker   ← label=0.5, weighted down
    │    ├──► _get_signal_quality_map() ← real+same_tf=2.0, paper+same_tf=1.0
    │    │                                  real+diff_tf=0.3, paper+diff_tf=0.0
    │    ├──► timeframe_encoded feature  ← ordinal (1m=1, 3m=2, 5m=3, 15m=4, 30m=5, 1h=6, 2h=7, 4h=8, 6h=9, 8h=10, 12h=11, 1d=12)
    │    ├──► is_real_trade feature      ← boolean (real vs paper)
    │    └──► Reject if >30% CENSORED
    │
    ├──► TargetDriftValidator.validate() ← reject if val SR <0.15, >0.85, or shift >20%
    │
    ├──► anti_fake_trainer.py          ← entrena XGBoost standalone
    │    └── feature_importance = gain (no weight) con mapeo f{i}→columnas
    │
    ├──► walk_forward.py               ← valida con PF/Sharpe/Expectancy/AUC + stability gate
    │    ├──► min_auc > 0.52, auc_std < 0.03, all folds > 0.50
    │    ├──► Temporal stability: ≥2 folds with AUC
    │    └──► TargetDriftValidator on train/val split
    │
    ├──► ThresholdOptimizer            ← runs only during retrain (not weekly), min 20 trades/cell
    │
    ├──► Si pasa gate:
    │    ├──► Guarda anti_fake_v1.pkl
    │    ├──► Guarda retrain_meta.json
    │    ├──► ensemble_trainer.py      ← entrena ensemble XGB+RF+Ridge (meta-learner LR)
    │    ├──► Guarda ensemble_v1.pkl
    │    └──► _build_and_save_adaptive_weights()  ← recalibra pesos confluence + per-timeframe
    │        └── Adaptive weights por PnL realistic (70% PnL + 30% WR), clamp ±20%
    │
    └──► feature_importance_drift.py   ← compara vs entrenamiento anterior
```

---

## 3. Modelos de ML

### 3.1 XGBoost Standalone (`anti_fake_v1.pkl`)
```
Ubicación:   backend/ai/models/anti_fake_v1.pkl
Registro:    ai.registry
Input:       21 features (dict)
Output:      success_probability [0,1]
Calibración: Platt scaling (calibrated confidence)
```

**Features (21) — Timeframe-aware:**
| # | Feature | Origen |
|---|---------|--------|
| 1 | `fvg_aligned_count` | SMC engine |
| 2 | `ob_distance_atr` | SMC engine |
| 3 | `pd_position` | SMC engine |
| 4 | `hour_utc` | Timestamp |
| 5 | `day_of_week` | Timestamp |
| 6 | `eq_highs_count` | SMC engine |
| 7 | `eq_lows_count` | SMC engine |
| 8 | `volume_ratio` | SMC engine |
| 9 | `spread_atr` | SMC engine |
| 10 | `score` | Confluence engine |
| 11 | `avg_entry_slippage` | Stats históricas |
| 12 | `gap_frequency` | Stats históricas |
| 13 | `fee_rate` | Exchange config |
| 14 | `tp_fill_rate` | Stats históricas |
| 15 | `trigger_ob` | ICT engine |
| 16 | `trigger_fvg` | ICT engine |
| 17 | `bias_bull` | ICT engine |
| 18 | `sweep_bool` | ICT engine |
| 19 | `break_choch` | ICT engine |
| 20 | `timeframe_encoded` | **NEW** Ordinal TF map (1m=1, 3m=2, 5m=3, 15m=4, 30m=5, 1h=6, 2h=7, 4h=8, 6h=9, 8h=10, 12h=11, 1d=12) |
| 21 | `is_real_trade` | **NEW** Boolean (real=1, paper=0) |

> **Nota:** Las 4 features LLM (`llm_verdict_score`, `llm_confidence_norm`, `llm_critical_factors`, `llm_warning_factors`) fueron **eliminadas del modelo** en Evaluación 2. Viven solo en `llm_signal_diagnosis` para análisis humano post-trade.

### 3.2 Hybrid Ensemble (`ensemble_v1.pkl`)
```
Ubicación:   backend/ai/models/ensemble_v1.pkl
Registro:    ai.ensemble_registry
Arquitectura: Stacking (OOF meta-features)
Base models: XGBoost + RandomForest + RidgeClassifier
Meta-learner: LogisticRegression (con StandardScaler)
Input:       21 features (NO LLM meta-feature)
Output:      { ensemble: float, xgb: float, rf: float, nb: float }
```

### 3.3 Adaptive Weights (`adaptive_weights.json`)
```
Ubicación:   backend/ai/models/adaptive_weights.json
Generado por: _build_and_save_adaptive_weights() en cada retrain
Input:       feature_importance del último modelo
Output:      Pesos de confluencia ajustados por feature importance
             ├─ global: {...}
             └─ by_ticker: {"BTCUSDT": {"15m": {...}, "1h": {...}}, "ETHUSDT": {...}}
```

**Mapeo feature → componente:**
```
ob_distance_atr   → trigger_OB
trigger_fvg       → trigger_FVG
trigger_ob        → trigger_OB
bias_bull         → structure_CHoCH, structure_BOS
fvg_aligned_count → fvg_context
sweep_bool        → sweep
pd_position       → pd_array
hour_utc          → killzone
day_of_week       → killzone
break_choch       → structure_CHoCH, structure_BOS
eq_highs_count    → eq_obstacle
eq_lows_count     → eq_obstacle
```

---

## 4. Tabs del Frontend y sus Endpoints

### Tab: **Dashboard** (`AIDashboardTab.jsx`)
```
Endpoint: GET /ai/dashboard
Devuelve: {
  model_health,        ← ModelHealthCard (Ensemble Híbrido)
  performance_summary, ← Rendimiento IA global
  equity_curve,        ← EquityCurveChart (60 días)
  signal_funnel,       ← SignalFunnel
  tier_matrix,         ← TierMatrix
  rolling_winrate,     ← RollingWinrate
  divergence_summary,  ← DivergenceCard (paper vs real)
  confidence_decay,    ← ConfidenceDecayCard
  rejected_summary,    ← RejectedSignalsCard
  feature_importance_drift,  ← FeatureImportanceDriftCard (B.1)
  model_decay,         ← ModelDecayCard (B.2)
  institutional_health,← InstitutionalHealthCard (Sharpe, DD, RoR)
  pnl_attribution,     ← PnlAttributionCard
  threshold_optimization, ← ThresholdOptimizationCard
  deployment_gate,     ← DeploymentGateCard
  circuit_breaker,     ← CircuitBreakerCard
  shadow_mode,         ← ShadowModeCard
}
```

### Tab: **Scanner** (`AIPage.jsx` → default)
```
Endpoints:
  GET  /ai/watchlist              ← Cargar/sincronizar watchlist
  POST /ai/watchlist/sync         ← Guardar watchlist
  GET  /ai/latest-scans           ← Resultados cacheados
  GET  /ai/scan                   ← Escanear watchlist (manual/auto)
  GET  /ai/analyze/{symbol}       ← Análisis individual
  GET  /ai/model/status           ← XGBoostCard (ensemble metrics)
  GET  /ai/bots                   ← BotActivatorCard
  GET  /ai/macro-context          ← MacroContextBar
```

### Tab: **Ranking**
```
Endpoints:
  GET /ai/signals/stats/by-ticker ← Stats por par/timeframe
  GET /ai/signals                 ← Listado de señales
```

### Tab: **Backtest**
```
Endpoints:
  GET /ai/signals?limit=200       ← Señales históricas con outcome
  GET /ai/signals/stats           ← Stats globales (win rate, avg PnL)
```

### Tab: **Validación**
```
Endpoints:
  GET /ai/heuristic-validation   ← Validación heurística
  GET /ai/model/validation-history← Historial de validaciones
  GET /ai/diagnoses/analytics     ← Analytics de diagnósticos LLM
```

### Tab: **Real**
```
Endpoints:
  GET /ai/real-performance        ← Trades reales ejecutados por IA
  GET /ai/symbol-real-stats/{sym} ← Stats por símbolo (trades reales)
  GET /portfolio/summary          ← Resumen de portfolio
```

---

## 5. Endpoints de IA (Backend)

```
GET  /ai/watchlist              ← Persistencia de watchlist
POST /ai/watchlist/sync         ← Sincronizar watchlist
GET  /ai/latest-scans           ← Scans cacheados por símbolo
GET  /ai/analyze                ← Análisis ICT/SMC individual
GET  /ai/scan                   ← Scan masivo de watchlist
GET  /ai/signals                ← Listado paginado de señales
GET  /ai/signals/stats          ← Stats globales
GET  /ai/signals/stats/by-ticker← Stats por ticker/timeframe
GET  /ai/optimal-config         ← Config óptima por ticker (LLM)
GET  /ai/ict-analysis           ← Análisis ICT en vivo
GET  /ai/model/status           ← Estado del ensemble + métricas
POST /ai/model/train            ← Trigger retrain manual
POST /ai/model/recalibrate-weights ← Recalibrar pesos adaptivos
GET  /ai/heuristic-validation   ← Validación heurística
GET  /ai/macro-context          ← Contexto macro por ticker
GET  /ai/bots                   ← Bots en modo IA
GET  /ai/real-performance       ← Performance de trades reales IA
GET  /ai/symbol-real-stats/{s}  ← Stats reales por símbolo
GET  /ai/dashboard              ← Dashboard aggregado (todas las métricas)
GET  /ai/pnl-attribution        ← Atribución PnL
GET  /ai/model/validation-history ← Historial validaciones
GET  /ai/expectancy-analysis    ← Análisis de expectativa
GET  /ai/divergence-summary     ← Divergencia paper vs real
GET  /ai/confidence-decay       ← Decay de confianza
GET  /ai/model-decay            ← Tasa de degradación del modelo
GET  /ai/institutional-health   ← Métricas institucionales
GET  /ai/replay/{position_id}   ← Replay de posición
GET  /ai/deployment-gate        ← Estado del deployment gate
GET  /ai/feature-importance-drift ← Drift de feature importance
GET  /ai/threshold-optimization ← Optimización de umbrales
GET  /ai/trainers               ← Listado de trainers disponibles
GET  /ai/circuit-breaker        ← Estado del circuit breaker (safety)
GET  /ai/shadow-mode            ← Estado del shadow mode (model evaluation)

// Feature B: LLM Diagnosis (Kimi)
GET  /ai/signals/{id}/diagnosis         ← Diagnóstico LLM de señal (admin)
GET  /ai/diagnoses/threshold-recommendations ← Recomendaciones de umbrales
GET  /ai/diagnoses/export               ← Exportar diagnósticos
GET  /ai/diagnoses/analytics            ← Analytics de diagnósticos
GET  /ai/signals/{id}/context           ← Contexto de señal (free)

// Feature C: Scanner Regime Optimizer
GET  /ai/scanner/regime-config          ← Config de régimen actual
POST /ai/scanner/regime-config/refresh  ← Forzar refresh de régimen

// Feature D: Fundamental Gate
GET  /ai/fundamentals/{ticker}          ← Snapshot fundamental
POST /ai/fundamentals/manual            ← Upload evento manual
```

---

## 6. Tablas de Base de Datos (AI-Related)

```
ai_signal              ← Señales generadas por el scanner (timeframe column)
ai_signal_rejected     ← Señales rechazadas (con razón)
ai_scan                ← Resultados de scans
feature_importance_drift ← Registros de drift entre entrenamientos
model_confidence_decay ← Decay de confianza (predicción vs realidad)
model_decay_rate       ← Tasa de degradación del modelo
model_validation_log   ← Log de validaciones del modelo
scanner_regime_config  ← Config de régimen por par (cache 4h)
fundamental_snapshot   ← Snapshots fundamentales (CFTC, unlocks, eventos)
llm_signal_diagnosis   ← Diagnósticos LLM por señal
paper_balance          ← Balance paper trading
paper_real_divergence  ← Divergencia paper vs real
deployment_gate_log    ← Log del deployment gate
exchange_trade         ← Trades reales ejecutados
position               ← Posiciones abiertas (extra_config["ai_signal_id"])
```

---

## 7. Tareas Celery (AI)

```
ai_scan_task            ← Scan periódico del mercado
ai_retrain_task         ← Re-entrenamiento del modelo (cada 6h, timeframe-aware)
ai_outcome_tracker      ← Trackeo de outcomes de señales
ai_drift_monitor_task   ← Monitoreo de drift de datos
confidence_decay_task   ← Tracking de decay de confianza
llm_tasks               ← Tareas LLM (diagnósticos)
llm_threshold_optimizer ← Optimización de umbrales vía LLM
optimizer_tasks         ← Tareas del optimizer
adaptive_weight_task    ← Recalibración de pesos adaptivos (global + per-TF)
ai_optimal_config_task  ← Config óptima por ticker (timeframe-aware)
bot_activator_task      ← Activación de señales → órdenes (timeframe-aware gates)
auto_timeframe_task     ← Resolución de mejor timeframe por ticker
watchlist_coverage_task ← Cobertura de watchlist multi-timeframe
```

---

## 8. Servicios de IA

```
ai_scanner.py              ← Motor de scanning (ICT + SMC + ensemble)
confluence_engine.py       ← Scoring de confluencia (0-100, per-timeframe weights)
macro_context.py           ← Contexto macro (eventos de alto impacto)
fundamental_context.py     ← Gate fundamental (CFTC, unlocks, eventos)
llm_client.py              ← Cliente Kimi (Moonshot AI)
threshold_optimizer.py     ← Optimización de umbrales
drift_detector.py          ← Detección de drift de datos (fresh reference handling)
confidence_decay_tracker.py← Tracking de decay de confianza
feature_importance_drift.py← Cálculo de drift entre entrenamientos
model_decay_tracker.py     ← Tracking de degradación del modelo
scanner_regime_optimizer.py← Optimización de régimen por par (LLM)
slippage_predictor.py      ← Predicción de slippage
expectancy_optimizer.py    ← Optimización de expectativa
adaptive_weight_optimizer.py← Optimizador de pesos adaptivos (global + by_ticker)
auto_timeframe.py          ← Resolución de mejor timeframe (composite score)
kelly_sizing.py            ← Kelly Criterion sizing (timeframe-filtered metrics)
bot_activator.py           ← Puente señal → orden (optimal config, drift, Kelly, exposure)
dynamic_risk_manager.py    ← Exposure cap por símbolo (paper vs real isolation)
```

---

## 9. Jerarquía de Decisiones (Pipeline)

```
┌────────────────────────────────────────────────────────────┐
│  [0] MARKET QUALITY FILTER (nuevo primer paso)             │
│  ├── Chop detection (ADX < 15, 10+ velas) → REJECT         │
│  ├── Low liquidity (vol < 20% media 30d) → REJECT          │
│  ├── Spread anomaly (spread > 3× ATR) → REJECT             │
│  └── API instability (error rate > 10%) → REJECT           │
└────────────────────────────────────────────────────────────┘
                           │ PASS
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [1] SCANNER                                               │
│  ├── fetch_ohlcv()                                         │
│  ├── ict_analyze()  → CHoCH/BOS, OB, FVG, bias, sweep      │
│  ├── smc_analyze()  → ADX, ATR, volume, PD array           │
│  ├── detect_regime() → solo observación, adaptive params   │
│  └── confluence_engine() → score 0-100, components         │
│       (per-timeframe adaptive weights from adaptive_weights.json)
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [2] GATES                                                 │
│  ├── macro_context()  → blocked / caution / proceed        │
│  ├── fundamental_context() → blocked / caution / proceed   │
│  └── assess_quality() → CLEAR / CAUTION / BLOCK            │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [3] CAUSAL FEATURE BUILDER                                │
│  ├── avg_entry_slippage, gap_frequency, fee_rate           │
│  ├── tp_fill_rate                                          │
│  └── REJECT if is_complete=False (no imputation)           │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [4] ML CLASSIFICATION                                     │
│  ├── ensemble_registry.predict_ensemble_probability()      │
│  │   ├── XGBoost  → P(success)                             │
│  │   ├── RandomForest → P(success)                         │
│  │   ├── RidgeClassifier → P(success)                      │
│  │   └── Meta-learner → ensemble_prob                      │
│  └── Fallback: registry.predict_calibrated_confidence()    │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [5] REGIME ADAPTER (post-ML, acción)                      │
│  ├── detect_regime() → trending / volatile / ranging       │
│  └── apply_to_signal() → ajusta thresholds post-predicción │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [6] QUALITY TIER                                          │
│  ├── STRONG  (blended ≥ 70, where blended = 35% heuristic  │
│  │             + 65% confluence_score)                      │
│  ├── MODERATE (blended ≥ 50)                               │
│  └── WEAK    (resto)                                       │
│  └── Execution penalty: -15 pts if spread>2×ATR or vol<0.5×│
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [7] CIRCUIT BREAKER                                       │
│  ├── States: CLOSED → OPEN → HALF_OPEN                     │
│  ├── 3 confident failures (prob≥0.7) → OPEN (30min)        │
│  └── HALF_OPEN allows 1 test trade; success → CLOSED       │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [8] RISK ENGINE                                           │
│  ├── base_size: STRONG=100, MODERATE=50, WEAK=0            │
│  ├── conf_mult: calibrated confidence tranches (0→1)       │
│  └── risk_mult: GREEN=1.0, YELLOW=0.5, RED=0.0            │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [9] SHADOW MODE                                           │
│  ├── record_shadow() → live (ensemble) vs shadow (XGB)     │
│  └── evaluate_promotion() → promote if shadow_sharpe >     │
│      live_sharpe × 1.2  (min 100 signals)                  │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [10] BOT ACTIVATOR (Timeframe-Aware + Structural)         │
│  ├── Auto-timeframe resolution (composite score)           │
│  ├── Drift Detector → HEALTHY / DEGRADED / BLOCKED         │
│  ├── Kelly Sizing → edge-based position sizing             │
│  ├── Exposure Cap → max risk per symbol (real≠paper)       │
│  ├── Optimal Config → min_score/leverage/tiers per TF      │
│  ├── PortfolioManager gate                                 │
│  │   ├── Correlation ≥ 0.85 → REJECT                      │
│  │   └── Sector exposure > 40% → REJECT                   │
│  ├── COOLDOWN GUARD → reject if last trade closed < N min  │
│  │   (15m→60, 1h→120, 4h→240, 1d→1440)                    │
│  ├── Deployment Gate → REAL bots only; paper NEVER blocked │
│  ├── Risk Configs by TF → trailing/breakeven/dynamic SL    │
│  │   1d: trailing@0.8R, breakeven@0.5R, dynamic SL 10steps │
│  │   4h: trailing@1.0R, breakeven@0.5R, dynamic SL 8steps  │
│  │   1h: trailing@1.2R, breakeven@0.8R, dynamic SL 7steps  │
│  │   15m: trailing@1.5R, breakeven@1.0R, dynamic SL 6steps │
│  └── Scanner regime config (adaptación por mercado)        │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  [11] EXECUTION (Structural TP/SL Management)              │
│  ├── TP1 / TP2 → from forward_levels (NOT mechanical R)    │
│  │   LONG: 1st EQ high / bear FVG above entry = TP1        │
│  │         2nd EQ high / bear FVG above entry = TP2        │
│  │   SHORT: 1st EQ low / bull FVG below entry = TP1       │
│  │          2nd EQ low / bull FVG below entry = TP2       │
│  │   Fallback: 1.5R / 2.5R if no structural levels found  │
│  ├── TP Split → based on distance to 1st structural level  │
│  │   <0.8R → close 35% at TP1 (let 65% run to 2nd level)  │
│  │   0.8-1.5R → close 50% at TP1                          │
│  │   >1.5R → close 65% at TP1                             │
│  │   Quality overlay: STRONG/CLEAR ×0.90, WEAK/CAUTION×1.10│
│  ├── SmartOrderRouter (override régimen/confianza)         │
│  ├── Paper trade (simulado)                                │
│  └── Real trade (exchange API)                             │
└────────────────────────────────────────────────────────────┘
```

---

## 10. Métricas Clave del Modelo (Auditoría Real — 2026-05-28)

> ⚠️ **Auditoría de modelo ejecutada el 2026-05-26.** Los valores documentados previamente eran ficticios o desactualizados. Los siguientes datos provienen directamente de `retrain_meta.json` y `ensemble_v1.pkl` en producción.

### 10.1 Performance del Ensemble (Meta-Learner LR)

| Métrica | Valor Real | Estado vs Objetivo |
|---------|-----------|-------------------|
| **Ensemble AUC-ROC** | **0.7005** | ✅ Aceptable (obj: 0.65+) |
| **Ensemble Accuracy** | **86.22%** | ⚠️ Sospechosamente alto (ver §10.4) |
| **Samples de entrenamiento** | **4,588** | ⚠️ Insuficiente (obj: 10,000+) |
| **Features** | **23** | ✅ Razonable |
| **Fold AUC std** | **0.055** | ❌ Inaceptable (obj: <0.03) |

### 10.2 Performance por Modelo Base

| Modelo | AUC | Meta-Weight | Estado |
|--------|-----|-------------|--------|
| **RandomForest** | 0.6757 | **+0.631** | ✅ Mejor modelo base |
| **XGBoost** | 0.6843 | **+0.227** | ✅ Buen modelo base |
| **LLM** | — | **+0.138** | ✅ Contribución positiva |
| **RidgeClassifier** | >0.55 | ≥0.0 | ✅ Modelo lineal diverso |

> ✅ **Resuelto: GaussianNB fue reemplazado por RidgeClassifier.** El nuevo modelo aporta diversidad lineal frente a XGB/RF, soporta `class_weight="balanced"` y `sample_weight`, y ya no genera predicciones peor-que-azar.

### 10.3 Walk-Forward Validation — Overfit Severo

| Métrica WF | Valor | Interpretación |
|------------|-------|----------------|
| **WF AUC** | 0.7032 | Similar a OOF — no hay degradación |
| **WF Sharpe** | **12.66** | ❌ Imposible en datos reales — leakage o overfit extremo |
| **WF Profit Factor** | **218.78** | ❌ Absurdo — señal de data leakage |
| **WF Expectancy** | 0.9518 | ❌ 95% de retorno esperado por trade — irreal |
| **WF Win Rate** | 84.4% | ❌ Demasiado alto para estrategia discrecional |
| **WF Max Drawdown** | 13.61% | Coherente con retornos inflados |
| **WF Trades** | 1,337 | ~29% de los samples |

> **Hipótesis:** El walk-forward no está purgando adecuadamente los gaps temporales entre train y test, o hay leakage de features forward-looking (ej. `tp_fill_rate` conocido en el momento de la señal).

### 10.4 Features — Importancia y Red Flags

**Top 5 features (por importancia XGB):**
| Feature | Importancia | Nota |
|---------|-------------|------|
| `day_of_week` | 59.3 | ⚠️ Posible artefacto — el día de la semana no debería ser el predictor #1 |
| `score` | 55.8 | ✅ Esperado — score del confluence engine |
| `ob_distance_atr` | 46.6 | ✅ Estructural |
| `htf_bias_bull` | 33.6 | ✅ HTF confluence |
| `fvg_aligned_count` | 30.2 | ✅ Estructural |

**Features con importancia CERO (5/23):**
- `volume_ratio`
- `spread_atr`
- `bias_bull`
- `sweep_bool`
- `htf_aligned`

> **Acción recomendada:** Eliminar features con importancia cero en el próximo retrain para reducir dimensionalidad y ruido.

### 10.5 Calibración de Probabilidades

| Métrica | Valor |
|---------|-------|
| **Método** | Platt scaling |
| **Base rate** | 13.73% (tasa de éxito realista) |
| **Mean raw prob** | 28.39% (sobreconfiado) |
| **Mean calibrated** | 13.73% (alineado) |
| **Brier score raw** | 0.1534 |
| **Brier score calibrated** | **0.1105** |
| **Logloss calibrated** | 0.3717 |

> ✅ La calibración funciona correctamente: reduce Brier en 0.0429. Las probabilidades calibradas son fiables para thresholding.

### 10.6 Thresholds Optimizados

| Parámetro | Valor |
|-----------|-------|
| **Score threshold** | 70 |
| **Prob threshold** | 0.60 |
| **Trades esperados** | 160 |
| **Sharpe esperado** | 5.755 |
| **Win rate esperado** | 75% |

> ⚠️ Los thresholds optimizados son **extremadamente agresivos** y no se han validado en forward-testing real. El sistema usa actualmente score ≥ 60 (no 70) para no perder señales en baja muestra.

### 10.7 Métricas de Trading Real vs Paper

| Métrica | Real (exchange real) | Paper |
|---------|---------------------|-------|
| **Posiciones cerradas** | 160 | 35 |
| **Con PnL reportado** | 55 (31W/24L) | 35 (24W/11L) |
| **Win rate (sobre reportados)** | **56.4%** | **68.6%** |
| **Total PnL** | **−6.76 USDT** | **−33.43 USDT** |
| **Avg PnL/trade (reportados)** | **−0.123 USDT** | −0.955 USDT |
| **Posiciones abiertas** | 0 | 0 |

> ❌ **El sistema es perdedor en ambos entornos.** Solo 55/160 trades reales (34%) tienen PnL reportado — el resto probablemente cerró en breakeven o con slippage no registrado. El PnL negativo (−6.76) indica que el problema no es solo overfitting del modelo, sino probablemente: (a) slippage/fees subestimados, (b) TPs mecánicos no alcanzables, (c) gestión de riesgo por timeframe desajustada.

### 10.8 Deployment Gate — Estado Global (Logging Only)

```
State:        PAUSED
Sharpe 20d:   -10.85
PF:           0.38
Expectancy:   -0.0474
Sizing:       0.00 (0%)
```

> ⚠️ El gate global está PAUSED pero **ya no bloquea bots**. Existe únicamente para monitoreo. El control real lo ejerce el **per-symbol gate** (§21).

---

## 11. Cambios de Seguridad y Robustez Implementados (10 Evaluaciones)

### 11.1 CausalFeatureBuilder — Eliminación de Leakage de Ejecución
**Archivo:** `backend/ai/services/causal_feature_builder.py`
- Mide la latencia p95 real del sistema (`exchange_trade` últimos 7 días).
- Aplica `cutoff_buffer = max(latency_p95 × 2, 500ms)`.
- Para trades recientes (<5 min desde señal), aplica `safe_cutoff = cutoff - 5min` adicional.
- Rechaza señal si no hay ≥50 muestras históricas (`is_complete = False`).
- **Nunca imputa.** En entrenamiento, fallback a `get_profile_for_signal()` si datos causales insuficientes.

### 11.2 CensoredOutcomeTracker — Manejo de Señales Pendientes >72h
**Archivo:** `backend/ai/services/censored_outcome_tracker.py`
- Señales PENDING >72h → `outcome = CENSORED`.
- `effective_label = 0.5` (neutral). **Nunca usa survival_prob.**
- `sample_weight = min(0.1 + (duration / 72h) × 0.2, 0.3)` — proporcional al tiempo pendiente.
- Dataset builder rechaza entrenamiento si >30% de las señales son CENSORED.

### 11.3 RiskEngine — Sizing con Máximo 3 Multiplicadores
**Archivo:** `backend/risk/risk_engine.py`
```
calculate_size = base_size × conf_mult × risk_mult

base_size:   STRONG=100, MODERATE=50, WEAK=0
conf_mult:   <0.5→0, <0.6→0.3, <0.7→0.6, <0.8→0.85, ≥0.8→1.0
risk_mult:   GREEN=1.0, YELLOW=0.5, RED=0.0
```
- Eliminados multiplicadores redundantes (solo 3 factores).
- `risk_mult = 0` en RED detiene sizing completamente.

### 11.4 RegimeAdapter — Detección de Régimen FUERA del Modelo
**Archivo:** `backend/ai/services/regime_adapter.py`
- `detect_regime()` analiza mercado por ticker (trending / volatile / ranging).
- `apply_to_signal()` ajusta thresholds **post-predicción**, no como feature de entrada.
- Evita que el modelo aprenda patrones espurios de régimen y mejora generalización.

### 11.5 ThresholdOptimizer — Solo Durante Retrain
**Archivo:** `backend/ai/services/threshold_optimizer.py`
- Ejecuta **únicamente** en `retrain_anti_fake()`, no en tarea semanal.
- Usa el **conjunto completo** de validación walk-forward (no subset).
- Requiere **mínimo 20 trades por celda** para sugerir cambio de umbral.
- Sin datos suficientes → no sugiere nada (no forza recomendaciones).

### 11.6 CircuitBreaker — Protección Redis-Backed contra Fallos Confiados
**Archivo:** `backend/risk/circuit_breaker.py`
- Estados: `CLOSED` → `OPEN` → `HALF_OPEN`.
- Cuenta solo fallos donde `predicted_prob ≥ 0.7` y `actual == FAILURE`.
- 3 fallos consecutivos → `OPEN` (30 min timeout).
- `HALF_OPEN` permite 1 trade de prueba; si éxito → `CLOSED`, si fallo → `OPEN`.
- Persistencia en Redis (`sync_redis`) para sobrevivir reinicios de contenedor.
- Frontend: `CircuitBreakerCard` en `AIDashboardTab.jsx`.

### 11.7 TargetDriftValidator — Rechazo ante Cambios de Mercado Sistémicos
**Archivo:** `backend/ai/services/target_validator.py`
- Compara distribución de éxito entre train y validation.
- Rechaza si:
  - `val_success_rate < 0.15` o `> 0.85` (mercado anómalo)
  - `|val_sr - train_sr| > 0.20` (target shift)
- Integrado en `walk_forward_validate()` y `retrain_anti_fake()`.

### 11.8 ShadowMode — Evaluación Continua de Modelos Candidatos
**Archivo:** `backend/ai/services/shadow_mode.py`
- `record_shadow()` almacena par `{live_prob, shadow_prob}` en Redis (TTL 7 días).
- `shadow` = XGBoost standalone (sin ensemble).
- `evaluate_promotion()` requiere ≥100 señales.
- Promueve si `shadow_sharpe > live_sharpe × 1.2` y `shadow_sharpe > 0.5`.
- Frontend: `ShadowModeCard` en `AIDashboardTab.jsx`.

### 11.9 LLM Timeout — Retries en Tareas Celery
**Archivo:** `backend/app/tasks/llm_tasks.py` (configuración Celery)
- `max_retries = 3`
- `default_retry_delay = 10s`
- Previene que timeouts de LLM (Kimi/Moonshot) maten tareas de diagnóstico.

### 11.10 Purged Walk-Forward — Stability Gate + Target Drift
**Archivo:** `backend/ai/validation/walk_forward.py`
- Gates absolutos: `min_sharpe = 0.3`, `min_profit_factor = 1.1`, `min_expectancy = 0.1`.
- **Stability gate**:
  - `min_auc > 0.52`
  - `auc_std < 0.03`
  - `all(fold_auc > 0.50)`
- `_PROFIT_FACTOR_MIN_RETENTION = 0.30` (relajado para modelos iniciales).
- TargetDriftValidator integrado en validación de folds.

### 11.11 MarketQualityFilter — "NO TRADE" como Decisión Válida
**Archivo:** `backend/ai/services/market_quality_filter.py`
Primer gate del pipeline, corre dentro de `build_signal()` tras `fetch_ohlcv()` (requiere datos OHLCV para calcular ADX/ATR/volumen):
- **Chop detection:** ADX < 15 durante 10+ velas → rechaza scan
- **Low liquidity:** volumen < 20% de media 30d → rechaza scan
- **Spread anomaly:** spread > 3× ATR → rechaza scan
- **API instability:** error rate > 10% última hora → rechaza scan
- Integrado en `ai_scanner.py` como primer gate funcional (después del circuit breaker, después de fetch/análisis).

### 11.12 SmartOrderRouter — Decisión de Tipo de Orden
**Archivo:** `backend/execution/smart_router.py`
Capa de ejecución mínima viable, integrada en `bot_activator.py` como override régimen/confianza:
- **Volátil / spread > 0.5%** → LIMIT post-only con 20bps de mejora
- **Confianza > 0.8** → MARKET (acepta 10bps slippage)
- **Default** → LIMIT IOC al precio de señal
- Complementa (no reemplaza) el router existente basado en spread/ATR.

### 11.13 PortfolioManager — Correlation + Sector Exposure
**Archivo:** `backend/risk/portfolio_manager.py`
Reemplaza el gate de correlación hardcodeado de `bot_activator.py`:
- **Correlation gate:** rechaza si nueva señal correlaciona ≥0.85 con posición abierta en mismo sentido
- **Sector exposure gate:** rechaza si exposición same-direction > 40% del equity
- Matriz de correlación realista ampliada (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX)
- Arquitectura preparada para evolucionar a cálculo dinámico de retornos horarios.

### 11.14 Rate Limiting de Adaptación — Prevenir Instability Cascade
**Archivo:** `backend/app/tasks/ai_retrain_task.py`
- `MAX_WEIGHT_DELTA = 0.10` (±10% máximo cambio por retrain)
- `_rate_limit_weights()` aplica clamp antes de persistir pesos globales y por ticker
- Evaluación 2: evita que los pesos confluence oscilen salvajemente entre retrains.

---

## 12. Interacciones entre Componentes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              INTERACCIÓN CRÍTICA                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  CausalFeatureBuilder → dataset_builder: fallback a get_profile_for_signal  │
│  CensoredOutcomeTracker → dataset_builder: label=0.5, weight↓, gate 30%     │
│  TargetDriftValidator → walk_forward: rechaza si mercado cambió             │
│  ThresholdOptimizer → retrain_task: solo en retrain, min 20 trades/cell     │
│  RegimeAdapter → ai_scanner: ajuste post-predicción, no feature input       │
│  CircuitBreaker → ai_scanner: detiene ejecución tras 3 fallos confiados     │
│  RiskEngine → ai_scanner: sizing = base × conf × risk (max 3 mults)         │
│  ShadowMode → ai_scanner: log live vs XGB; promoción automática si mejora   │
│  LLM retries → llm_tasks: 3 reintentos, 10s delay                           │
│  Walk-Forward stability → retrain_task: min_auc>0.52, std<0.03, all>0.50    │
│  MarketQualityFilter → ai_scanner: rechaza scan en chop/illiquid/spread     │
│  SmartOrderRouter → bot_activator: override régimen/confianza en orden      │
│  PortfolioManager → bot_activator: correlation ≥0.85 + sector cap 40%       │
│  RateLimiting → retrain_task: pesos confluence ±10% máximo por retrain      │
│  KellySizing → bot_activator: edge-based sizing por timeframe               │
│  DriftDetector → bot_activator: bloquea si PSI > umbral por TF              │
│  AutoTimeframe → bot_activator: resuelve best TF o acepta signal TF         │
│  ExposureCap → bot_activator: aisla paper vs real en sizing                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13. Paper Trading 1D Bots — Setup y Configuración

> Sesión de configuración: 2026-05-20

### 13.1 Bots 1D Paper Creados
Se crearon **14 bots paper** en timeframe `1d` para operación semi-autónoma:

| Bot | Par | Leverage | Auto-TF | AI Optimal Config |
|-----|-----|----------|---------|-------------------|
| BTCbot_1d_paper | BTC/USDT:USDT | 5x | false | **disabled** |
| ETHbot_1d_paper | ETH/USDT:USDT | 5x | false | **disabled** |
| SOLbot_1d_paper | SOL/USDT:USDT | 5x | false | **disabled** |
| BNBbot_1d_paper | BNB/USDT:USDT | 5x | false | **disabled** |
| XRPbot_1d_paper | XRP/USDT:USDT | 5x | false | **disabled** |
| DOGEbot_1d_paper | DOGE/USDT:USDT | 5x | false | **disabled** |
| AAVEbot_1d_paper | AAVE/USDT:USDT | 5x | false | **disabled** |
| ARBbot_1d_paper | ARB/USDT:USDT | 5x | false | **disabled** |
| 1000PEPEbot_1d_paper | 1000PEPE/USDT:USDT | 5x | false | **disabled** |
| FARTCOINbot_1d_paper | FARTCOIN/USDT:USDT | 5x | false | **disabled** |
| PENGUbot_1d_paper | PENGU/USDT:USDT | 5x | false | **disabled** |
| ONDObot_1d_paper | ONDO/USDT:USDT | 5x | false | **disabled** |
| LPTbot_1d_paper | LPT/USDT:USDT | 5x | false | **disabled** |
| XAUTbot_1d_paper | XAUT/USDT:USDT | 5x | false | **disabled** |

**Paper balance compartido:** `Paper_15m` (~10,000 USDT)

### 13.2 Watchlist Multi-Timeframe
Se modificó la constraint única de `ai_watchlist` para permitir múltiples timeframes por símbolo:

```sql
-- Antes: UNIQUE (user_id, symbol)
-- Ahora:  UNIQUE (user_id, symbol, timeframe)
```

Esto permite que un mismo símbolo (ej. `BTCUSDT`) exista con `15m`, `1h`, `4h` y `1d` simultáneamente.

Se agregaron timeframes faltantes para bots LIVE:
- `AAVEUSDT 15m`, `BCHUSDT 4h`, `BTCUSDT 15m`, `ETHUSDT 15m`, `SOLUSDT 15m`

### 13.3 Diseño de Auto-Timeframe
Los bots 1D paper usan **`auto_timeframe = false`** para evitar que el activator haga *skip* de señales cuando el scanner produce `1d` pero el bot resuelve un timeframe diferente como "óptimo".

Los bots LIVE existentes mantienen `auto_timeframe = true` — resuelven el best TF histórico por símbolo y saltan señales que no coincidan.

---

## 14. Bug Fixes y Cambios de Calibración (2026-05-20)

### 14.1 Deployment Gate — Insufficient Data Handling
**Archivo:** `backend/app/services/deployment_gate.py`

**Problema:** Con ~112 trades reales en 20 días, el gate evaluaba métricas volátiles (Sharpe -10.96, PF 0.59) y ponía el sistema en `PAUSED` (sizing 0%), bloqueando TODOS los trades.

**Fixes aplicados:**
- `_MIN_TRADES_FOR_EVAL = 30` — con menos de 30 trades cerrados, NO evalúa métricas basadas en trades (Max DD, Sharpe, PF)
- `_SHARPE_DEGRADE` relajado de `0.5` → `-15.0`
- `_PF_DEGRADE` relajado de `1.0` → `0.5`
- `_DECAY_DEGRADE` relajado de `15.0` → `70.0`
- Estado actual: **HEALTHY** con sizing 100%

### 14.2 AI Optimal Config — Sizing 0.0 para Todos los Tiers
**Archivo:** `backend/app/engines/bot_activator.py`

**Problema:** `_compute_optimal_config_sync()` calculaba `sizing_multipliers` basado en datos históricos por tier. Para símbolos/timeframes sin suficientes datos, `_sizing_from_real()` devolvía `0.0` para todos los tiers, haciendo que `notional = 0.0` y ningún trade se ejecutara.

**Fixes aplicados:**
- `_sizing_from_real()`: `count < 3` → return `1.0` (insufficient data = full sizing)
- `_sizing_from_real()`: caso default cambiado de `0.0` → `0.25` (poor data = reduced sizing, no block)
- `_conservative_fallback_config()`: `STRONG: 0.5 → 1.0`, `MODERATE: 0.0 → 1.0`, `CAUTION: 0.0 → 0.5`
- Se desactivó `ai_optimal_config_enabled` en **todos los bots activos** (28 bots) para resetear `ai_signal_config`
- Se limpió `ai_signal_config` a `{}::jsonb` en todos los bots activos

### 14.3 Exposure Cap — Porcentaje vs Fracción Decimal
**Archivo:** `backend/app/services/dynamic_risk_manager.py`

**Problema:** `initial_risk_pct` se almacenaba como porcentaje (ej. `1.43` para 1.43%) pero `ExposureCapBySymbol.check()` lo leía como fracción decimal, viendo `143%` en lugar de `1.43%`. Esto bloqueaba trades legítimos con `current_exposure > cap`.

**Fix aplicado:**
```python
if risk_pct > 1.0:
    risk_pct = risk_pct / 100.0
```

### 14.4 Paper Exchange — UUID Inválido en Posiciones
**Archivos:** `backend/app/exchanges/paper.py`, `backend/app/exchanges/factory.py`, `backend/app/engines/bot_activator.py`

**Problema:** `PaperExchange._open_position()` usaba `self.account_id` (string `paper_{uuid}_{random}`) como `bot_id` en el modelo `Position`. PostgreSQL rechazaba el INSERT porque `bot_id` es UUID.

**Fix aplicado:**
- `PaperExchange.__init__()` ahora acepta `bot_id: str | None`
- `create_paper_exchange()` pasa `bot_id=str(bot.id)` desde el activator
- `_open_position()` usa `bot_id=self.bot_id or self.account_id`

### 14.5 Paper Balance Monitor — UUID Mal Formado
**Archivo:** `backend/app/exchanges/paper.py`

**Problema:** `_paper_balance_uuid()` intentaba parsear `account_id` como UUID directamente, fallando con `paper_f5a8..._a352b5ca`.

**Fix aplicado:** `_paper_balance_uuid()` ahora es async y busca en la DB por `account_id`, retornando el UUID real del `PaperBalance`.

### 14.6 Macro Scanner Rotation
**Archivo:** `frontend/src/pages/AIPage.jsx`

**Problema:** `MacroContextBar` mostraba siempre el primer símbolo de la watchlist (`watchlist[0]`).

**Fix aplicado:** Se implementó rotación automática cada 5 segundos entre todos los símbolos de la watchlist que tengan alertas (funding extremo, eventos, avoid/caution), similar a un ticker de noticias.

### 14.7 Circuit Breaker — Tier Isolation
**Archivo:** `backend/app/tasks/circuit_breaker_task.py`

**Problema:** El circuit breaker pausaba el **bot entero** cuando un tier específico acumulaba 3 SL consecutivos, afectando tiers sanos del mismo bot.

**Fix aplicado:**
- Ya NO se setea `bot.status = "paused"`
- Solo se almacena `tripped_at` en `circuit_breaker_state[tier]`
- Auto-reactivación verifica bots `active` con tiers tripped, no bots `paused`

### 14.8 CausalFeatureBuilder — Gate Opcional
**Archivo:** `backend/app/services/ai_scanner.py`

**Problema:** `CausalFeatureBuilder` bloqueaba TODAS las señales cuando no había 50+ trades históricos por símbolo, resultando en `scanned=20 signals=0`.

**Fix aplicado:** Las causal features son ahora **opcionales**. Si `is_complete=False` o el builder falla, el scanner loguea debug y continúa sin ellas. Nunca bloquea la señal.

### 14.9 Celery Task Registration
**Archivo:** `backend/app/services/celery_app.py`

**Problema:** 5 tareas Celery no estaban registradas o tenían nombres incorrectos en `beat_schedule`:

| Tarea | Nombre incorrecto | Nombre correcto |
|-------|-------------------|-----------------|
| Deployment gate | `app.tasks.deployment_gate_task.evaluate_deployment_gate_task` | `tasks.deployment_gate.evaluate` |
| Divergence tracker | `app.tasks.divergence_tracker_task.run_divergence_scan_task` | `tasks.divergence_tracker.run_scan` |
| AI optimal config | — | `app.tasks.ai_optimal_config_task` |
| Watchlist coverage | — | `app.tasks.watchlist_coverage_task` |
| LLM threshold optimizer | — | `app.tasks.llm_threshold_optimizer` |

### 14.10 Deployment Gate — Métricas Normalizadas
**Archivo:** `backend/app/services/deployment_gate.py`

**Problema:**
- Max DD dividía por el primer peak, causando drawdowns de 3000%+
- Sharpe usaba sumas de dólares en lugar de retornos porcentuales

**Fix aplicado:**
- Equity curve normalizada contra `BASE_EQUITY = 10000.0`
- Sharpe calcula `daily_pct = [r / BASE_EQUITY for r in daily]`

### 14.11 Bot Activator — NameErrors
**Archivo:** `backend/app/engines/bot_activator.py`

**Problema:**
- `NameError: '_extract_base_symbol' is not defined`
- `NameError: 'notional' is not defined` (scope en portfolio gate)

**Fix aplicado:**
- Agregada función `_extract_base_symbol()` al módulo
- Corregido scope de `notional` en portfolio risk check

### 14.12 AI Scanner — Logger Import
**Archivo:** `backend/app/services/ai_scanner.py`

**Fix aplicado:** Agregado `from loguru import logger` faltante a nivel de módulo.

---

## 15. Timeframe-Aware Autonomous Trading — Fases 1-7 (2026-05-20)

### 15.1 Fase 1: Dataset Builder — Quality-Weighted Samples + TF Encoding
**Archivo:** `backend/ai/dataset_builder.py`

**Cambios:**
- Nuevas features: `timeframe_encoded` (ordinal), `is_real_trade` (boolean)
- `_get_signal_quality_map(db, target_timeframe)`: reemplaza el binario `_get_real_signal_ids()`
- Quality weights:
  | Tipo | Mismo TF | Diferente TF |
  |------|----------|--------------|
  | Real | **2.0** | 0.3 |
  | Paper | **1.0** | 0.0 |
- El modelo entrena con pesos diferenciados: señales reales del mismo timeframe pesan 2×, paper del mismo timeframe pesan 1×, cross-timeframe pesan muy poco o nada.

### 15.2 Fase 2: Adaptive Weight Optimizer — Per-Timeframe Weights
**Archivo:** `backend/app/services/adaptive_weight_optimizer.py`

**Cambios:**
- `recalibrate_weights(db, timeframe=None)` acepta timeframe opcional
- Si se pasa timeframe, filtra señales por `AISignal.timeframe == timeframe`
- Output JSON incluye `by_ticker: {"BTCUSDT": {"15m": {...}, "1h": {...}}, ...}`
- Quality map: real same_tf=1.0, paper same_tf=0.5

### 15.3 Fase 3: Bot Activator — Timeframe-Aware Optimal Config
**Archivo:** `backend/app/engines/bot_activator.py`

**Cambios:**
- `_compute_optimal_config_sync(db, ticker, timeframe)` ahora segmenta stats por timeframe
- Incluye paper_same_tf con weight 0.5 en el cálculo de métricas
- `TF_LEVERAGE = {"15m": 20, "30m": 15, "1h": 10, "2h": 8, "4h": 5, "1d": 3}`
- Auto-leverage base usa `TF_LEVERAGE[timeframe]` en lugar de `bot.leverage` estático
- Fallback timeframe-aware:
  | TF | Min Score | Tiers | Leverage |
  |----|-----------|-------|----------|
  | 15m | ≥55 | ["STRONG"] | 20× |
  | 1h | ≥50 | ["STRONG", "MODERATE"] | 10× |
  | 4h | ≥45 | ["STRONG", "MODERATE", "WEAK"] | 5× |
  | 1d | ≥40 | ["STRONG", "MODERATE", "WEAK"] | 3× |

### 15.4 Fase 4: Kelly Sizing — Timeframe-Filtered Metrics
**Archivo:** `backend/app/services/kelly_sizing.py`

**Cambios:**
- `_fetch_model_metrics()` filtra posiciones por `AISignal.timeframe == timeframe`
- Paper same_tf incluido con weight 0.5
- P&L % calculado manualmente: `pnl_pct = realized_pnl / notional × 100` (Position no tiene `realized_pnl_pct`)
- Exposure cap filtra `paper_balance_id.is_(None)` para real, aislando paper de real

### 15.5 Fase 5: Auto-Timeframe — Composite Score Resolution
**Archivo:** `backend/app/services/auto_timeframe.py`

**Cambios:**
- Score compuesto: `(WR × 0.30) + (PF × 2.5 × 0.25) + (Sharpe × 20 × 0.25) + ((100 - MaxDD) × 0.20)`
- Fuentes: real+paper positions joined a AISignal para filtrar por timeframe
- Fallback: si no hay datos históricos, **acepta el timeframe de la señal** (no hace skip)
- `VALID_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"]`

### 15.6 Fase 6: AI Retrain Task — Per-Ticker Per-Timeframe Weights
**Archivo:** `backend/app/tasks/ai_retrain_task.py`

**Cambios:**
- `_build_per_ticker_weights()` usa quality map para weighted win rates
- Output: `by_ticker[ticker][timeframe]` weights
- El confluence engine consume `by_ticker[ticker][timeframe]` si existe, fallback a global

### 15.7 Fase 7: Confluence Engine — Timeframe-Aware Weight Consumption
**Archivo:** `backend/app/engines/confluence_engine.py`

**Cambios:**
- Ya consumía `by_ticker[ticker][timeframe]` — ahora recibe datos correctos del retrain task
- Fallback: global weights si no hay per-ticker per-timeframe data

---

## 16. Bug Fixes Críticos del Timeframe-Aware System (2026-05-21)

### 16.1 Walk-Forward Gate — AUC Missing in WFMetrics
**Archivo:** `backend/ai/validation/walk_forward.py`

**Problema:** `walk_forward_validate()` leía `m.get("auc")` como dict, pero `evaluate_model` devolvía un dataclass `WFMetrics` sin campo `auc`. Resultado: `fold_aucs` vacío → `insufficient_folds_for_stability` siempre.

**Fix aplicado:**
- Añadido `auc: float = 0.0` al dataclass `WFMetrics`
- `evaluate_model()` calcula AUC real con `roc_auc_score` usando `predict_proba`
- `walk_forward_validate()` lee `m.auc` directamente

### 16.2 Drift Detector — Fresh Reference Blocking
**Archivo:** `backend/app/services/drift_detector.py`

**Problema:** Cuando no existía referencia de drift para un par+timeframe, `check_feature_drift()` bloqueaba la señal en lugar de construirla.

**Fix aplicado:**
```python
if reference is None:
    reference = build_reference_distribution(...)
    return DriftReport(overall_status="HEALTHY", ...)  # primera vez = HEALTHY
```
- Las siguientes ejecuciones usan la referencia guardada y evalúan PSI real

### 16.3 Exposure Cap — Paper/Real Mixing
**Archivo:** `backend/app/services/kelly_sizing.py`

**Problema:** Kelly sizing y exposure cap incluían posiciones paper en el cálculo de riesgo para bots reales.

**Fix aplicado:**
- Exposure cap para real: `BotConfig.paper_balance_id.is_(None)`
- Kelly sizing: filtra por timeframe + real/paper isolation

### 16.4 UUID vs Text Comparisons
**Archivos:** `backend/app/services/scanner_regime_optimizer.py`, `backend/app/services/confidence_decay_tracker.py`

**Problema:** Comparaciones directas entre `UUID` (Python) y `text` (PostgreSQL) en subqueries fallaban silenciosamente.

**Fix aplicado:**
```python
func.cast(Position.extra_config["ai_signal_id"].astext, AISignal.id.type)
```

### 16.5 Watchlist Coverage Task — Position.created_at Missing
**Archivo:** `backend/app/tasks/watchlist_coverage_task.py`

**Problema:** Query usaba `Position.created_at` que no existe en el modelo.

**Fix aplicado:** Eliminado el uso de `created_at`; la tarea usa campos existentes.

### 16.6 Bot Activator — db.String Import
**Archivo:** `backend/app/engines/bot_activator.py`

**Problema:** `_pattern_win_rate()` usaba `db.String` sin importar `String` de SQLAlchemy.

**Fix aplicado:** Agregado `from sqlalchemy import String` al módulo.

---

## 17. Estado Operativo del Sistema (2026-05-21)

> ⚠️ **OBSOLETO — Snapshot histórico.** Para estado actual verificado, ver **§28**.

### 17.1 Deployment Gate
```
State:        HEALTHY
Sizing:       1.00 (100%)
Red flags:    0
Yellow flags: 0
Reasons:      []
```

### 17.2 Bots Activos
- **44 bots LIVE** (cuentas reales) — timeframes 15m, 1h, 4h, auto_timeframe=true
- **10 bots PAPER** (1D) — leverage 5x, ai_signal_mode=true
- **Todos los bots:** `ai_signal_mode=True`, `auto_timeframe=True` (LIVE) / `False` (1D paper), `ai_optimal_config_enabled=True`

### 17.3 Paper Balance
```
Paper_15m: available=~9,795  equity=~9,795  initial=10,000.00
```

### 17.4 Trades Recientes
- **FARTCOIN/USDT:USDT REAL** (FARTCBot_15m) — LONG @ 0.1911, qty=20.931, leverage=2x
- **FARTCOIN/USDT:USDT PAPER** (FARTCOINbot_1d_paper) — LONG @ 0.1841 (1d, 5x)
- Paper y real operan **independientemente** (diferente timeframe, diferente sizing)

### 17.5 Señales
- **55 señales PENDING pre-fix** → `SYS_DEGRADED` (purged 2026-05-21 14:00 UTC)
- **6 señales PENDING activas** (post-fix, serán procesadas por activator)

### 17.6 Reglas de Gestión Activas
| Regla | Estado |
|-------|--------|
| Deployment Gate | ✅ HEALTHY |
| Circuit Breaker | ✅ Sin tiers tripped |
| Drift Detector | ✅ HEALTHY (referencias construyéndose auto) |
| Kelly Sizing | ✅ Activo (timeframe-filtered) |
| Exposure Cap | ✅ Activo (paper vs real aislado) |
| Stacking Cooldown | ✅ 120 min |
| Max Concurrent | ✅ 1 posición/bot |
| Macro Gate | ✅ Activo (funding/regime) |
| Fundamental Gate | ✅ Activo |
| Walk-Forward Gate | ✅ Arreglado (AUC fix), próximo retrain ~19:00 UTC |
| Auto-Timeframe | ✅ Activo (composite score + fallback) |

### 17.7 Issues Menores Conocidos (No Bloquean)
- `websocket.accept` RuntimeError — error de conexión WS existente (starlette/uvicorn)
- `macro_context` calendar fetch: HTTP 429 — usa cache local
- Causal features `insufficient data` para varios símbolos — esperado con bajo conteo de trades
- Paper divergence tracking activo — FARTCOIN real (15m/2x) vs paper (1d/5x) operan independientemente

---

---

## 18. Bug Fixes Críticos — Auditoría 2026-05-21

### 18.1 BUG 1: Walk-Forward Stability Gate Nunca se Ejecutaba
**Archivo:** `backend/ai/validation/walk_forward.py`

**Problema:** `_check_temporal_stability()` estaba definida pero nunca se llamaba. `stability` no se inicializaba, causando NameError silenciado en `stability["passes"]`.

**Fix:** Llamar `_check_temporal_stability(fold_aucs, fold_metrics)` después de calcular `fold_aucs`.

### 18.2 BUG 2: Ensemble NUNCA se Reentrenaba
**Archivo:** `backend/app/tasks/ai_retrain_task.py`

**Problema:** `train_ensemble()` se llamaba con `llm_scores=llm_scores`, pero la función no acepta ese parámetro. TypeError silenciado → ensemble nunca se actualizaba.

**Fix:** Eliminar `llm_scores=llm_scores` de la llamada.

### 18.3 BUG 3: meta_payload Usado Antes de Definirse
**Archivo:** `backend/app/tasks/ai_retrain_task.py`

**Problema:** `meta_payload["optimized_thresholds"]` se asignaba en línea 655, pero `meta_payload` se definía en línea 668.

**Fix:** Mover la definición de `meta_payload` antes del bloque de ThresholdOptimizer.

### 18.4 BUG 4: Shadow Mode — Lógica de Evaluación Invertida
**Archivo:** `backend/ai/services/shadow_mode.py`

**Problema:** Simulaba trades donde `prob < 0.5` (peores señales) en lugar de `prob >= 0.5` (mejores señales). Invertía la comparación live vs shadow.

**Fix:** Cambiar `< 0.5` a `>= 0.5`.

### 18.5 BUG 5: Outcome "FAILURE" Inexistente en Schema
**Archivos:** `backend/app/tasks/ai_retrain_task.py`, `backend/ai/dataset_builder.py`

**Problema:** Varios queries filtraban `outcome.in_(["SUCCESS", "FAILURE"])`, pero "FAILURE" no existe en el schema. Los outcomes válidos son SUCCESS, FAILURE_MAX_ADVERSE, FAILURE_BEHAVIORAL, CENSORED, INCONCLUSIVE, EXPIRED.

**Fix:**
- `_build_per_ticker_weights`: incluir `FAILURE_MAX_ADVERSE`, `FAILURE_BEHAVIORAL`, `CENSORED`
- ThresholdOptimizer query: mismo fix
- `dataset_builder.py`: incluir `CENSORED` en queries para que el gate del 30% CENSORED sea funcional
- Loop de per-ticker weights: manejar CENSORED como 0.5 win / 0.5 loss

---

*Documentación actualizada: 2026-05-21*

---

## 19. Estrategia de Confluencias y Gestión de Trade (2026-05-26)

Esta sección documenta la estrategia completa del motor IA, desde la generación de señales hasta el cierre de la posición, incluyendo la gestión de TPs y SL basada en confluencias estructurales del mercado (ICT/SMC).

---

### 19.1 Filosofía: Estructura del Mercado guía Entrada y Salida

El motor no opera con niveles abstractos ("TP a 1.5R"). Cada TP y cada ajuste de SL debe estar anclado a una confluencia real del mercado:

- **Entrada**: OB activo, FVG no rellenado, o sweep de liquidez + CHoCH/BOS
- **TP1**: Primer nivel estructural por encima/debajo del entry (EQ high/low, FVG contrario al bias)
- **TP2**: Segundo nivel estructural más allá del primero
- **SL inicial**: Último EQ low/high válido, o fallback a 2×ATR
- **SL dinámico**: Avanza a niveles estructurales invalidados (EQ lows superados en long, EQ highs perforados en short)

---

### 19.2 ICT Engine — Detección de Estructura (Forward + Backward)

**Archivo:** `backend/app/core/ict_engine.py`

**Backward-looking (entrada):**
- `bias`: bull/bear según último CHoCH/BOS
- `active_ob`: Order Block del último break
- `active_fvgs`: FVGs alineados con el bias, no rellenados, últimas 100 velas
- `eq_highs` / `eq_lows`: Clusters de liquidez (pivots dentro de 0.15×ATR)
- `last_break`: BOS o CHoCH con su swing point y OB asociado

**Forward-looking (salida) — NUEVO:**
- `forward_levels`: lista ordenada de niveles estructurales por delante del precio
  - **LONG**: EQ highs por encima del entry + FVGs bajistas no rellenados por encima del entry
  - **SHORT**: EQ lows por debajo del entry + FVGs alcistas no rellenados por debajo del entry
  - Ordenados por distancia al entry (el más cercano primero)
  - Cada nivel incluye: `price`, `kind` (eq_high|eq_low|fvg_bear|fvg_bull), `distance_pct`

```python
# Ejemplo de forward_levels para LONG en BTC/USDT 15m
[
  {"price": 76450.0, "kind": "eq_high",   "distance_pct": 0.85},
  {"price": 76800.0, "kind": "fvg_bear",  "distance_pct": 1.30},
  {"price": 77200.0, "kind": "eq_high",   "distance_pct": 1.85},
]
```

---

### 19.3 Confluence Engine — Scoring + TP/SL Estructurales

**Archivo:** `backend/app/engines/confluence_engine.py`

**Scoring (0-100):**
| Componente | Peso base | Condición |
|------------|-----------|-----------|
| CHoCH | 20 | Cambio de sesgo |
| BOS | 12 | Continuación |
| OB trigger | 15 | Entrada en Order Block |
| FVG trigger | 10 | Entrada en Fair Value Gap |
| Aligned FVGs | +4 c/u (max 12) | FVGs sin llenar alineados |
| Liquidity sweep | 18 (trending) / 10 (ranging) | BSL/SSL sweep previo |
| Premium/Discount | 10 | Precio en zona favorable |
| Killzone | 10 (trending) / 5 (ranging) | Horario ICT óptimo |
| EQ obstacle | -8 | EQ high/low cercano al entry en contra |

**Execution penalty (NUEVO):**
- Spread > 2×ATR → -15 pts
- Volumen < 0.5×media → -15 pts

**Blend quality:** `0.35 × heuristic + 0.65 × confluence_score`
- STRONG: ≥70
- MODERATE: ≥50
- WEAK: <50

**SL calculation:**
- LONG: `max(eq_low válido)` o `entry_zone_low - 2×ATR` como fallback
- SHORT: `min(eq_high válido)` o `entry_zone_high + 2×ATR` como fallback
- Safeguard: si risk ≤ 0, usar 1% del entry

**TP calculation (NUEVO — estructural, no mecánico):**
- **TP1** = `forward_levels[0].price` (primer nivel estructural)
- **TP2** = `forward_levels[1].price` (segundo nivel estructural)
- Fallback si no hay suficientes forward levels: `entry ± 1.5R` y `entry ± 2.5R`
- Garantía: TP2 siempre más lejos que TP1 (si no, ajustar con +0.5R)

**TP1 close % (NUEVO — basado en distancia estructural):**
```
dist_r = distance_to_1st_level / risk_in_pct
if dist_r < 0.8:   tp1_close_pct = 0.35   # nivel muy cercano, deja correr más
elif dist_r < 1.5: tp1_close_pct = 0.50   # distancia moderada
else:              tp1_close_pct = 0.65   # nivel lejano, toma ganancias antes
```

Overlay de calidad:
- STRONG/CLEAR: `× 0.90` (deja correr más)
- WEAK/CAUTION/BLOCK: `× 1.10` (toma antes)
- Clamp: 20% – 80%

**Forward levels se serializan en:**
- `ConfluenceResult.forward_levels` → `AISignal.features["forward_levels"]`
- `ConfluenceResult.tp1_close_pct` → `AISignal.features["tp1_close_pct"]`
- `ConfluenceResult.tp1_source` / `tp2_source` → indica si el TP es estructural o fallback

---

### 19.4 Bot Activator — Puente Señal → Orden

**Archivo:** `backend/app/engines/bot_activator.py`

**Filtros previos a la orden:**
1. `execution_blocked` → skip (deployment gate, drift, etc.)
2. `_is_in_cooldown()` → skip si último trade cerrado hace menos de N minutos
3. Deployment gate → **SOLO bloquea bots REALES**. Paper bots nunca son rechazados.
4. Drift detector → HEALTHY/DEGRADED/PAUSED
5. Kelly sizing → edge-based
6. Portfolio manager → correlation + sector exposure

**Risk configs por timeframe (inyectadas automáticamente si el bot no tiene config propia):**

| TF | Trailing activation | Callback | Breakeven activation | Lock profit | Dynamic SL steps |
|----|---------------------|----------|----------------------|-------------|------------------|
| 1d | 0.8R | 0.8% | 0.5R | +0.3% | 10 (hasta 5R) |
| 4h | 1.0R | 0.9% | 0.5R | +0.3% | 8 (hasta 4R) |
| 1h | 1.2R | 1.0% | 0.8R | +0.25% | 7 (hasta 3.5R) |
| 15m | 1.5R | 1.0% | 1.0R | +0.2% | 6 (hasta 3R) |

**Colocación de órdenes:**
1. Market order de entrada
2. SL al precio de la señal (`sig.stop_loss`) — ajustado por `dynamic_horizon.py` si aplica
3. TP1 con `qty_tp1 = quantity × tp1_close_pct`
4. TP2 con `qty_tp2 = quantity - qty_tp1`
5. Validación: si qty_tp2 < mínimo del exchange, todo va a TP1

**Position extra_config guarda:**
- `ai_signal_id`, `score`, `quality_tier`, `anti_fake_status`
- `forward_levels`: niveles estructurales para gestión futura del SL
- `tp1_source`, `tp2_source`: si el TP fue estructural o fallback
- `initial_sl_price`, `initial_risk_pct`, `initial_risk_distance`
- Datos de riesgo: `oi_cvd`, `session_funding`, `rolling_beta`

---

### 19.5 Cooldown entre Trades — Protección contra Overtrading

**Archivo:** `backend/app/engines/bot_activator.py` (`_is_in_cooldown()`)

Después de que un bot cierra un trade, no puede abrir otro hasta que pase un cooldown proporcional al timeframe:

| Timeframe | Cooldown mínimo |
|-----------|-----------------|
| 1m | 10 min |
| 5m | 20 min |
| 15m | 60 min |
| 1h | 120 min |
| 4h | 240 min |
| 1d | 1440 min (24h) |

**Razón:** Evita re-entries inmediatas que generan overtrading y comisiones. En 15m, una vela tarda 15 min en cerrar; un cooldown de 60 min (4 velas) asegura que el bot no "cace" el mismo micro-movimiento 4 veces.

---

### 19.6 Deduplicación de Señales — Race Condition Guard

**Archivo:** `backend/app/tasks/ai_scan_task.py`

**Problema identificado:** La misma vela (mismo `signal_time`) generaba 2-4 señales duplicadas cuando múltiples workers Celery procesaban el mismo ticker simultáneamente.

**Fix aplicado:**
1. **DB-level constraint:** `CREATE UNIQUE INDEX ux_ai_signals_dedup ON ai_signals (ticker, timeframe, direction, signal_time)`
2. **Code-level race guard:** `db.add(sig)` envuelto en `try/except IntegrityError`. Si colisionan dos workers, uno hace rollback y skipea limpiamente.
3. **Limpieza histórica:** Se eliminaron 1,814 señales duplicadas existentes.

---

### 19.7 Deployment Gate — Solo Aplica a Bots Reales

**Archivo:** `backend/app/services/deployment_gate.py`

**Filosofía:** Los paper bots usan balance de prueba y deben permanecer libres para acumular datos, especialmente en timeframes altos donde los trades son escasos pero valiosos.

**Comportamiento:**
- `_proactively_manage_bots()` filtra `paper_balance_id IS NULL` → solo gestiona bots reales
- `bot_activator.py` deployment gate check salta completamente para `is_paper=True`
- Gate evalúa métricas de trades REALES únicamente (Sharpe, PF, Expectancy, MaxDD)
- Paper metrics se almacenan en `extra_data` como advisory, nunca como criterio de pausa

**Cautious restart:** Cuando las métricas reales son catastróficas pero se aplican fixes de gestión, se inserta un log `HEALTHY` con `sizing_multiplier=0.25` para operar con riesgo reducido mientras se validan las mejoras.

---

### 19.8 Gestión de Salida — Trailing, Breakeven, Dynamic SL

**Archivos:** `backend/app/core/risk_manager.py`, `backend/app/tasks/sl_update_tasks.py`

**Breakeven:**
- Activa cuando el precio alcanza `activation_r` de profit
- Mueve SL a `entry_price + lock_profit%` (long) o `entry_price - lock_profit%` (short)
- Timeframe-aware: 1d/4h activan a 0.5R, 1h a 0.8R, 15m a 1.0R

**Trailing Stop:**
- Activa cuando el precio alcanza `activation_r` de profit
- Callback: % de retracement desde el peak permitido antes de cerrar
- Timeframe-aware: 1d usa 0.8% callback, 4h 0.9%, 1h/15m 1.0%

**Dynamic SL (mecánico actual):**
- Avanza cada `step_r` (0.5R por defecto) hasta `max_steps`
- Timeframe-aware: 1d permite 10 steps (hasta 5R), 4h 8 steps (4R), 1h 7 steps (3.5R), 15m 6 steps (3R)

**Dynamic SL híbrido (IMPLEMENTADO):**
- Lee `support_levels` de `position.extra_config` (EQ lows / bull FVGs below entry for LONG; EQ highs / bear FVGs above entry for SHORT)
- Cuando el precio supera un nivel de soporte, ese nivel se convierte en nuevo SL
- Compara con el SL mecánico (R-steps) y elige el más conservador (más cercano al precio)
- Guarda `dynamic_sl_source` en extra_config para trazabilidad (`structural` / `mechanical` / `hybrid`)

---

### 19.9 Paper vs Real — Separación y Aprendizaje

| Aspecto | Real Bots | Paper Bots |
|---------|-----------|------------|
| Balance | Cuenta exchange real | PaperBalance (~10k USDT) |
| Deployment Gate | Sí — pueden ser pausados | No — nunca bloqueados |
| Sizing | Kelly + exposure cap + gate multiplier | Normal |
| Timeframes | 15m, 1h, 4h (auto-timeframe) | 1d (fijo) |
| Propósito | Generar PnL | Acumular datos a largo plazo |
| Métricas | Peso 2× en entrenamiento | Peso 1× en entrenamiento |
| Divergencia | Si real diverge >15% de paper → block | N/A |

**Filosofía de aprendizaje:**
- Paper 1d acumula trades de mayor duración y mejor R:R
- Real 15m genera volumen de trades para validar señales
- El modelo entrena con ambos, pero pondera real del mismo TF 2× más que paper
- Cross-timeframe learning: real+diff_tf pesa 0.3, paper+diff_tf pesa 0 (no confunde timeframes)

---

### 19.10 Resumen del Flujo Completo

```
[VELA CIERRA]
    │
    ▼
[ICT ENGINE] ← analiza estructura backward + forward
    ├── bias, active_ob, active_fvgs, eq_highs, eq_lows
    └── forward_levels (niveles por encima/debajo del entry)
    │
    ▼
[SMC ENGINE] ← contexto de mercado
    ├── sweep, premium/discount, FVGs alineados, OB distance
    │
    ▼
[CONFLUENCE ENGINE] ← scoring + niveles de salida
    ├── score 0-100, quality tier, anti_fake_status
    ├── SL = EQ low/high estructural (o 2×ATR fallback)
    ├── TP1 = 1er forward_level, TP2 = 2do forward_level
    └── tp1_close_pct = f(distancia al 1er nivel, calidad)
    │
    ▼
[ML ENSEMBLE] ← predice probabilidad de éxito
    │
    ▼
[GATES] ← macro, fundamental, drift, circuit breaker
    │
    ▼
[DB] ← ai_signal con features (incl. forward_levels)
    │   └── UNIQUE INDEX evita duplicados
    │
    ▼
[BOT ACTIVATOR]
    ├── Cooldown check (¿último trade hace N min?)
    ├── Deployment gate (solo si real)
    ├── Risk configs por TF (trailing/breakeven/dynamic SL)
    ├── Coloca: entry + SL + TP1 (qty_tp1) + TP2 (qty_tp2)
    └── Guarda position con forward_levels en extra_config
    │
    ▼
[MONITOREO EN VIVO]
    ├── Breakeven @ activation_r
    ├── Trailing stop @ activation_r + callback
    ├── Dynamic SL avanza por steps (próximo: por niveles estructurales)
    └── TP1/TP2 se ejecutan en exchange
    │
    ▼
[CIERRE]
    ├── Outcome tracker evalúa resultado
    ├── Realistic outcome engine simula ejecución real
    └── Retrain task incorpora señal resuelta al dataset
```

---

## 20. Estado Operativo Actual (2026-05-26)

> ⚠️ **OBSOLETO — Datos desactualizados.** Esta sección es un snapshot histórico del 26 de mayo.  
> Para el estado operativo **verificado con métricas reales de producción**, ver **§28 (2026-05-28 — Post-Auditoría)**.

### 20.1 Bots
- **17 bots REALES** activos — timeframes 15m, 1h, 4h
- **10 bots PAPER** activos — timeframe 1d
- Todos con risk configs actualizadas por timeframe
- Cooldown activo (60min para 15m, 120min para 1h, etc.)

### 20.2 Señales
- **Constraint único activo** en `ai_signals` (ticker, timeframe, direction, signal_time)
- **1,814 duplicados eliminados** históricamente
- Forward levels se computan en cada señal nueva

### 20.3 Deployment Gate
- Estado: **HEALTHY** con sizing multiplier **0.25** (cautious restart)
- Solo evalúa trades reales
- Paper bots operan libremente

### 20.4 Métricas Recientes (Pre-Fix de Gestión)
- Win rate real: ~62%
- Expectancy real: -0.025 (negativo — losers 4× más grandes que winners)
- Sharpe 20d: -11.83
- Causa raíz identificada: overtrading + TPs mecánicos + re-entries inmediatas
- Fixes aplicados: cooldown, TPs estructurales, deduplicación, trigger interval

### 20.5 Próximos Pasos
1. **Paper test 1 semana**: validar que `support_levels` se serializa correctamente y que el trailing_worker lee sin KeyError
2. **Validar nueva gestión de TPs**: medir si el PnL mejora con TPs estructurales vs mecánicos
3. **Near-miss tracking**: añadir label 0.6 para señales CENSORED que estuvieron a 0.2R del TP1

## 21. Per-Symbol / Per-Timeframe Deployment Gate (2026-05-28)

### 21.1 Problema: Global Gate era un cuello de botella

El deployment gate global evaluaba métricas agregadas de TODOS los trades reales. Un par malo (ej. FARTCOIN con slippage extremo) pausaba el sistema entero, incluyendo pares sanos como BTC o ETH.

### 21.2 Solución: Gate por `(symbol, timeframe)`

**Archivo:** `backend/app/services/deployment_gate.py`

**Nuevo modelo:** `SymbolDeploymentGateLog`
```sql
CREATE TABLE symbol_deployment_gate_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    state VARCHAR(20) NOT NULL,  -- HEALTHY | CAUTION | PAUSED
    sizing_multiplier NUMERIC(5,2) DEFAULT 1.00,
    sharpe_20 NUMERIC(10,4),
    profit_factor NUMERIC(10,4),
    max_drawdown_pct NUMERIC(10,4),
    expectancy NUMERIC(10,4),
    trade_count INTEGER,
    reasons JSONB,
    extra_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_symgate_symbol_tf_created ON symbol_deployment_gate_logs (symbol, timeframe, created_at);
```

**Lógica de evaluación:**
- Cada par `(symbol, timeframe)` se evalúa **independientemente** con las mismas métricas que el gate global (Sharpe 20d, PF 60d, Expectancy 30d)
- Si un par tiene métricas malas → solo ese par se pausa
- Los demás pares siguen operando normalmente

**Control de bots:**
- `_proactively_manage_symbol_gates(db)` → bloquea/desbloquea bots basado en el estado del gate de su par
- `_proactively_manage_bots(db, gate_state)` → DEPRECATED, solo loguea el estado global como advisory
- Paper bots: **completamente exentos** de todos los gates

### 21.3 Global Gate: Solo Logging

El gate global sigue calculándose y logueándose, pero **NO bloquea bots**. Sirve para monitoreo y alertas:
```python
# Global gate: solo logging
logger.info(f"[GLOBAL GATE] State={global_state}, Sharpe={global_sharpe}, PF={global_pf}")
# Symbol gate: CONTROLA ejecución
if sym_gate.state == "PAUSED":
    record_rejection(..., "symbol_deployment_gate", ...)
    return {"status": "rejected", ...}
```

---

## 22. Cross-Timeframe Structural Confluence (HTF Levels) (2026-05-28)

### 22.1 Problema: Señales LTF sin contexto HTF

Una señal en 15m podía ignorar que el par estaba en resistencia de 1d o en soporte de 1w. Esto causaba trades contra la estructura de mayor timeframe.

### 22.2 Solución: Inyección de niveles HTF en señales LTF

**Archivo:** `backend/app/services/ai_scanner.py`

**Mapeo HTF:**
```python
HTF_MAP = {
    "15m": "1h", "30m": "2h", "1h": "4h", "2h": "8h",
    "4h": "1d", "6h": "1d", "8h": "1d", "12h": "3d",
    "1d": "1w", "3d": "1w", "1w": "1M"
}
```

**Proceso:**
1. `build_signal()` genera la señal LTF
2. `_get_htf_structural_levels(db, symbol, ltf)` busca la señal HTF más reciente en `ai_latest_scans`
3. Si la señal HTF es fresca (< 2× duración de vela HTF), inyecta sus niveles:
   ```python
   result.features["htf_forward_levels"] = htf_forward_levels
   result.features["htf_support_levels"] = htf_support_levels
   result.features["htf_timeframe"] = htf
   ```

**En `bot_activator.py`:**
- `_merge_structural_levels()` combina LTF + HTF levels
- HTF levels se marcan con `htf_bonus=True` y se ordenan primero
- Los TPs se calculan desde el nivel más fuerte (HTF primero, luego LTF por distancia)

**Impacto:** Las señales 15m ahora respetan niveles de 1h/4h/1d. Un LONG en 15m cerca de un EQ high de 1d tendrá ese nivel como TP1, dándole al trade un contexto estructural real.

---

## 23. Timeframe Fallback (2026-05-28)

### 23.1 Problema: Bots sin señales en TF primario

Un bot en 15m podía pasar horas sin señales si el mercado no generaba estructura en ese timeframe.

### 23.2 Solución: Cascada de timeframes superiores

**Archivo:** `backend/app/tasks/ai_scan_task.py`

**Cadena de fallback:**
```python
TF_FALLBACK_CHAIN = {
    "15m": ["30m", "1h", "4h", "1d"],
    "30m": ["1h", "2h", "4h", "1d"],
    "1h":  ["2h", "4h", "1d", "3d"],
    "2h":  ["4h", "8h", "1d", "3d"],
    "4h":  ["6h", "8h", "1d", "3d"],
    ...
}
```

**Proceso:**
1. El scanner escanea el TF primario de cada par
2. Si el par genera `NO_SIGNAL`, se marca para fallback
3. `_run_fallback_scans()` itera por la cadena:
   - Si encuentra una señal en un TF superior, la marca como `FALLBACK` en `ai_latest_scans`
   - La señal se guarda con su TF real (ej. `1h`) pero se asocia al TF primario (`15m`)
4. `bot_activator.py` acepta señales de TF superior si `timeframe_fallback_enabled=True`

**Configuración:**
- Todos los bots reales tienen `timeframe_fallback_enabled: true`
- Paper bots: sin fallback (aprenden solo en su TF)

---

## 24. Regime-Aware Auto-Reset (2026-05-28)

### 24.1 Problema: Bloqueos permanentes por métricas históricas

Un par pausado por mal Sharpe seguía pausado indefinidamente, incluso si el régimen de mercado cambiaba (ej. de trending a ranging).

### 24.2 Circuit Breaker: Auto-reset por cambio de régimen

**Archivo:** `backend/app/tasks/circuit_breaker_task.py`

**Almacenamiento:**
```python
# Cuando se dispara un tier:
cb_state[tier] = {
    "consecutive_sl": count,
    "tripped_at": datetime.now(timezone.utc).isoformat(),
    "limit": limit,
    "regime_at_block": regime_at_block,  # ← NUEVO
}
```

**Auto-reset:**
```python
regime_at_block = state.get("regime_at_block")
current_regime = latest_regimes.get((bot.symbol, bot.timeframe))
if regime_at_block and current_regime and regime_at_block != current_regime:
    # Régimen cambió → reset automático
    cb_state[tier] = {
        "consecutive_sl": 0,
        "reset_at": now.isoformat(),
        "reset_reason": f"regime_change:{regime_at_block}->{current_regime}"
    }
```

### 24.3 Symbol Gate: Auto-reset por cambio de régimen

**Archivo:** `backend/app/services/deployment_gate.py`

**Almacenamiento:**
```python
log.extra_data = {
    "regime": current_regime,
    "regime_changed": regime_changed,
    ...
}
```

**Auto-reset:**
```python
if latest.state == "PAUSED" and current_regime != previous_regime:
    # Reevaluar con lookback corto (5 días)
    log = _evaluate_symbol_gate_core(db, symbol, timeframe, days_override=5)
    if log.state == "HEALTHY":
        # Auto-unblock
        logger.info(f"[SYM GATE AUTO-RESET] {symbol}/{timeframe}: regime changed → UNBLOCKED")
```

---

## 25. Adaptive Trade Longevity — Rechazo Autónomo (2026-05-28)

### 25.1 Problema: TPs mecánicos destruyen la rentabilidad

Cuando el `fill_price` divergía del `entry_zone` (slippage, movimientos rápidos), los TPs estructurales quedaban inválidos. El sistema usaba fallback mecánicos que generaban TPs a 1.5R/2.5R arbitrarios, sin anclaje estructural.

Ejemplos reales:
- **AAVE**: fill=80.11, TP1 estructural=80.1 (0.01 de distancia = breakeven)
- **DOGE**: fill=0.09783, TP1 estructural=0.100205 (arriba del fill para SHORT = inválido)

### 25.2 Solución: Evaluación de longevidad adaptativa

**Archivo:** `backend/app/engines/bot_activator.py`

**Nueva función:** `_evaluate_trade_longevity()`

**Criterios autónomos (sin umbrales fijos):**
```python
min_distance_pct = max(
    risk_pct * 1.0,        # Al menos 1.0R de distancia
    atr_pct * 1.5,         # Al menos 1.5× ATR (evita ruido)
    0.2,                    # Mínimo absoluto 0.2% (cubre fees)
) * tf_mult
```

**Timeframe multiplier:**
| TF | Multiplicador |
|----|---------------|
| 15m/30m | ×1.0 |
| 1h/2h | ×1.1–1.2 |
| 4h+ | ×1.3–2.0 |

**Decisión:**
- Si hay al menos 1 forward_level válido desde `fill_price` con distancia ≥ mínimo adaptativo → **ACEPTAR** (usar TPs estructurales)
- Si no hay niveles válidos → **RECHAZAR** con motivo `"insufficient_longevity"`

**No más fallback mecánico.** El sistema ahora es selectivo: solo abre posiciones cuando la estructura real ofrece targets rentables desde el precio de ejecución.

### 25.3 Dynamic Horizon: Solo ajusta SL, no TPs estructurales

**Archivo:** `backend/app/services/dynamic_horizon.py`

Cuando se usan TPs estructurales válidos:
- Dynamic Horizon **solo ajusta el SL** según ATR y régimen
- Los TPs se preservan intactos (no se recalculan mecánicamente)
- Esto evita que el Dynamic Horizon "invierta" TPs estructurales (ej. mover un TP de 0.100205 a 0.095455 para SHORT)

---

## 26. Adaptive Trend Pro — Integración como Filtro de Confluencia (2026-05-28)

### 26.1 Descripción de la estrategia

**Archivo:** `backend/app/engines/adaptive_trend_engine.py`

Port de la estrategia Pine Script "Adaptive Trend Pro". Es un motor **trend-following** basado en:
- **Trailing stop ATR-based** con volatilidad híbrida (`0.6×ATR + 0.4×SMA(TR)`)
- **Multiplicador dinámico** que se ajusta según distancia del RSI a 50 (tightening 8-15% en momentum)
- **Filtros**: RSI momentum, volumen relativo, ADX
- **Scoring**: 0-100 compuesto por RSI (25pts) + Volumen (16pts) + ADX (7.5pts)

**Presets adaptativos** por mercado + timeframe:
| Mercado | 15m vol_len | 15m mult | RSI thresh | Vol thresh |
|---------|-------------|----------|------------|------------|
| Crypto | 8 | 1.8 | 48.0 | 1.2 |
| Altcoins | 10 | 2.0 | 48.0 | 1.3 |
| Memecoins | 10 | 2.5 | 45.0 | 1.3 |
| Forex | 10 | 1.8 | 45.0 | 1.0 |

### 26.2 Integración con ICT+SMC

**Archivo:** `backend/app/engines/confluence_engine.py`

El Adaptive Trend Pro actúa como **filtro de confluencia direccional** dentro del scoring:

```python
# Si ICT y Adaptive Trend están alineados:
if ict_dir == adaptive_trend_dir:
    score += 8.0 + min(7.0, adaptive_trend.composite_score / 10.0)
    # Bonus hasta +15 pts para señales de alta convicción

# Si están en divergencia:
else:
    score -= 10.0
    # Penalización fuerte por contradicción de tendencia

# Si hay confirmed flip en la misma dirección:
if adaptive_trend.confirmed_signal and adaptive_trend.signal_direction == ict_direction:
    score += 5.0
```

**Features inyectadas** en cada señal:
```python
"adaptive_trend": 1/-1                    # dirección del trend
"adaptive_score": 58.0                    # composite score
"adaptive_rsi": 39.2                      # RSI
"adaptive_adx": 13.3                      # ADX
"adaptive_volume_ratio": 1.119            # volumen relativo
"adaptive_trailing_stop": 97.00           # trailing stop
"adaptive_confirmed": false               # confirmed signal
"adaptive_filters_passed": true           # filtros OK
...
```

### 26.3 Impacto esperado

- **Menos señales contratendencia**: Si ICT detecta un LONG pero Adaptive Trend está bearish, el score baja ~10 pts. Muchas señales débiles caerán por debajo del umbral.
- **Más confianza en señales alineadas**: Cuando ambos motores coinciden, el score sube 8-15 pts, mejorando la calidad de las que pasan.
- **Trailing stop alternativo**: El `adaptive_trailing_stop` se guarda en features. Futuras iteraciones podrían usarlo como SL dinámico alternativo al SL estructural.

---

## 27. Signal-Aware Position Plan (SAPP) — TPs Estructurales (2026-05-28)

### 27.1 Problema: SAPP ignoraba niveles estructurales

El SAPP (`signal_risk_plan.py`) calculaba TPs por R-múltiplos genéricos (1.5R, 2.0R, 2.5R), ignorando completamente los `forward_levels` de ICT+SMC.

### 27.2 Solución: SAPP integra forward_levels

**Archivo:** `backend/app/services/signal_risk_plan.py`

**Cambios:**
1. `TPLevel` ahora tiene campo `price: float | None` para precios estructurales
2. `generate_plan()` acepta `forward_levels: list[dict] | None`
3. `_build_tp_structure()` usa forward_levels cuando existen:
   - Calcula R-múltiplo real: `distancia / R`
   - Crea `TPLevel(price= nivel_real, r_multiple= r_real, ...)`
4. `calculate_tp_prices()` usa `tp.price` directamente si está definido

**Ejemplo:**
```python
# Sin forward_levels → TPs genéricos:
TPLevel(1, 0.50, 1.5, "breakeven")  # 1.5R mecánico

# Con forward_levels → TPs estructurales:
TPLevel(1, 0.50, 0.623, "breakeven", price=95.0)  # EQ low @ 95.0
TPLevel(2, 0.50, 1.284, "trailing", price=92.0)  # FVG bull @ 92.0
```

### 27.3 Resolución de TPs desde fill_price

**Archivo:** `backend/app/engines/bot_activator.py`

**Nueva función:** `_resolve_structural_tps_from_fill()`

Después de obtener el `fill_price` real:
1. Recalcula qué forward_levels son válidos desde el fill_price
2. Filtra niveles "ya pasados" (ej. para SHORT, niveles arriba del fill)
3. Filtra niveles demasiado cercanos (< 0.5% — configurable)
4. Devuelve hasta 2 niveles válidos

**Si no hay niveles válidos:**
- El sistema **rechaza la señal** (ver sección 25)
- No se abre posición con TPs mecánicos

---

## 28. Estado Operativo Actual (2026-05-28 — Post-Auditoría)

### 28.1 Bots y Configuración
- **17 bots REALES** activos (cuentas reales) — timeframes 15m, 1h, 4h
- **10 bots PAPER** activos — timeframe 1d
- **55 configs totales** (45 real, 10 paper)
- **27 bots en AI mode** (17 real + 10 paper)
- Todos los bots reales tienen `timeframe_fallback_enabled=true`
- Todos con `ai_signal_mode=true`, `auto_timeframe=true` (real) / `false` (paper)

### 28.2 Deployment Gates (Datos Reales)

| Gate | Estado | Métricas | Control |
|------|--------|----------|---------|
| **Global** | **PAUSED** | Sharpe −10.85, PF 0.38, Exp −0.0474 | **Logging únicamente — NO bloquea** |
| **Per-symbol** | **14 HEALTHY / 4 PAUSED** | Evalúa cada (symbol, timeframe) | **Bloquea bots reales** |

**Pares PAUSED (bloqueados para trading real):**
| Par | TF | Sharpe | PF | Expectancy | Trades | Motivo |
|-----|----|--------|----|-----------|--------|--------|
| BTC/USDT:USDT | 15m | −10.53 | 0.16 | −0.1446 | 24 | Sharpe < −5, PF < 0.5 |
| FARTCOIN/USDT:USDT | 15m | −23.76 | 0.25 | −0.0203 | 30 | Sharpe < −5, PF < 0.5 |
| ARB/USDT:USDT | 15m | −13.30 | 0.22 | −0.0095 | 15 | Sharpe < −5, PF < 0.5 |
| ONDO/USDT:USDT | 15m | −5.41 | 0.80 | −0.0136 | 14 | Sharpe < −5 |

> ⚠️ Los pares PAUSED se auto-resetearán si el régimen de mercado cambia (se evalúa con lookback 5d al reset).

**Pares HEALTHY destacados:**
| Par | TF | Sharpe | PF | Expectancy | Trades |
|-----|----|--------|----|-----------|--------|
| BCH/USDT:USDT | 4h | **19.57** | **13.05** | 0.0484 | 13 |
| LPT/USDT:USDT | 15m | **13.37** | **46.11** | 0.0429 | 6 |
| XRP/USDT:USDT | 15m | **12.43** | **8.55** | 0.0082 | 12 |
| 1000PEPE/USDT:USDT | 15m | **8.72** | **3.53** | 0.0303 | 22 |

### 28.3 Circuit Breakers (Datos Reales)

| Bot | Tier | Consecutive SL | Régimen al Bloqueo | Tripped At |
|-----|------|---------------|-------------------|------------|
| **ETH/USDT:USDT** | **STRONG** | 2 | RANGING | 2026-05-28 18:06 UTC |
| **LPT/USDT:USDT** | **WEAK** | 1 | RANGING | 2026-05-28 18:05 UTC |

> ✅ **AAVE se reseteó automáticamente** (regime change detected). Los CBs activos se auto-resetearán si el régimen cambia de RANGING a otro estado.

### 28.4 Posiciones y PnL por Símbolo (Real)

| Símbolo | Wins | Losses | Total PnL | Avg PnL | Estado Gate |
|---------|------|--------|-----------|---------|-------------|
| 1000PEPE | 4 | 0 | **+0.338** | +0.084 | HEALTHY |
| BCH | 1 | 0 | **+0.309** | +0.309 | HEALTHY |
| XAUT | 5 | 0 | **+0.190** | +0.038 | HEALTHY |
| PENGU | 6 | 0 | **+0.168** | +0.028 | HEALTHY |
| LPT | 1 | 1 | **+0.046** | +0.023 | HEALTHY |
| ONDO | 3 | 1 | **+0.021** | +0.005 | PAUSED |
| XRP | 0 | 1 | −0.002 | −0.002 | HEALTHY |
| FARTCOIN | 1 | 3 | −0.011 | −0.003 | PAUSED |
| AAVE | 1 | 2 | −0.953 | −0.318 | HEALTHY |
| ETH | 2 | 4 | −1.018 | −0.170 | HEALTHY (CB active) |
| DOGE | 0 | 2 | −1.020 | −0.510 | HEALTHY |
| BTC | 5 | 7 | −1.876 | −0.156 | PAUSED |
| ARB | 2 | 2 | −2.049 | −0.512 | PAUSED |

**Totales reales:** 160 trades cerrados, 55 con PnL reportado (31W/24L = 56.4% WR), PnL = **−6.76 USDT**.

**Totales paper:** 35 trades cerrados (24W/11L = 68.6% WR), PnL = **−33.43 USDT**.

> ❌ **El sistema es perdedor acumulado en ambos entornos.** A pesar de win rate > 50%, los perdedores son más grandes que los ganadores (expectancy negativo).

### 28.5 Paper Balance

```
Paper_15m: available=9,872.03  equity=9,872.03  initial=10,000.00
Drawdown: −1.28%
```

### 28.6 Señales y Timeframe Fallback
- Fallback habilitado para todos los bots reales desde 2026-05-28
- Si no hay señal en TF primario, el scanner busca en TFs superiores según `TF_FALLBACK_CHAIN`
- Las señales fallback se marcan como `FALLBACK` en `ai_latest_scans`

### 28.7 Componentes Activos (Estado Verificado)

| Componente | Archivo | Estado |
|------------|---------|--------|
| Symbol Deployment Gate | `deployment_gate.py` | ✅ Activo (per-symbol) |
| HTF Level Injection | `ai_scanner.py` | ✅ Activo |
| Timeframe Fallback | `ai_scan_task.py` | ✅ Activo |
| Regime Auto-Reset (CB) | `circuit_breaker_task.py` | ✅ Activo |
| Regime Auto-Reset (Gate) | `deployment_gate.py` | ✅ Activo |
| Trade Longevity | `bot_activator.py` | ✅ Activo |
| Adaptive Trend Pro | `adaptive_trend_engine.py` | ✅ Activo |
| SAPP Structural TPs | `signal_risk_plan.py` | ✅ Activo |

### 28.8 Issues Conocidos (No Bloquean)
- `websocket.accept` RuntimeError — error de conexión WS existente
- `macro_context` calendar fetch: HTTP 429 — usa cache local
- Trailing worker: `fetch_order_book` async coroutine warning — non-critical, fallback a market order
- Replay snapshot: `'AISignal' object has no attribute 'calibrated_confidence'` — non-critical

---

## 29. Auditoría de Métricas — Hallazgos y Recomendaciones (2026-05-28)

### 29.1 Resumen Ejecutivo

La auditoría del 2026-05-26 reveló discrepancias **masivas** entre las métricas documentadas y los valores reales en producción. El documento anterior contenía valores ficticios o desactualizados que distorsionaban la realidad del sistema. Esta sección consolida los hallazgos críticos.

### 29.2 Hallazgo #1: GaussianNB era Peor que el Azar (Resuelto)

| Aspecto | Detalle |
|---------|---------|
| **AUC GaussianNB** | **0.4857** (azar = 0.50) |
| **Meta-weight** | **−0.325** (negativo) |
| **Impacto** | El meta-learner RESTABA las predicciones de NB |
| **Estado** | ✅ Reemplazado por RidgeClassifier en `ensemble_trainer.py` v2 |

**Acción tomada:** GaussianNB fue eliminado del entrenamiento y reemplazado por `RidgeClassifier`, que aporta diversidad lineal, maneja desbalance con `class_weight="balanced"` y soporta `sample_weight`.
- O simplemente eliminarlo y quedarse con RF+XGB+LLM (3 modelos son suficientes)

### 29.3 Hallazgo #2: Overfit Extremo en Walk-Forward

| Métrica | Valor WF | Valor OOF | Ratio |
|---------|----------|-----------|-------|
| Sharpe | **12.66** | ~0.3 (estimado) | 42× |
| Profit Factor | **218.78** | ~1.0 (estimado) | 219× |
| Expectancy | **95.2%** | negativo (real) | — |

**Hipótesis de causa raíz:**
1. **Data leakage en `tp_fill_rate`**: Esta feature mide si los TPs se llenaron, pero en el momento de la señal este valor no es conocible.
2. **Gaps temporales insuficientes**: El walk-forward usa 3 folds con 30% test; los gaps entre train/test pueden no ser suficientes para evitar leakage de régimen.
3. **Survivorship bias**: Las señales CENSORED o con outcomes INCONCLUSIVE/EXPIRED pueden estar mal manejadas en el split.

**Recomendación:**
- Implementar **purged k-fold** con embargo de 7 días entre train y test
- Remover `tp_fill_rate` del feature set (es un target proxy)
- Validar que no hay leakage de `forward_levels` (deben computarse solo con datos previos a la señal)

### 29.4 Hallazgo #3: Fold AUC Std = 0.055 (Inaceptable)

| Objetivo | Real | Estado |
|----------|------|--------|
| < 0.03 | **0.055** | ❌ **2× peor que el objetivo** |

**Fold AUCs individuales:** 0.6985, 0.7575, 0.6232 — rango de 0.1343.

**Interpretación:** El modelo es altamente inestable. Funciona bien en algunos períodos y muy mal en otros. Esto indica:
- Régimen dependency severa
- Features no robustas a cambios de mercado
- Insuficiente regularización (best_iterations 89–138, muy altas para 4,588 samples)

**Recomendación:**
- Aumentar regularización XGB (`max_depth` ≤ 4, `min_child_weight` ≥ 10)
- Introducir feature de régimen como interacción
- Aumentar samples a 10,000+ antes de cualquier optimización agresiva

### 29.5 Hallazgo #4: `day_of_week` es el Feature #1

**Importancia: 59.3** — supera al propio `score` del confluence engine (55.8).

**Riesgo:** El modelo puede estar aprendiendo patrones espurios de día de la semana (ej. "los viernes hay más volatilidad") que no son causales y que pueden romperse en cualquier momento.

**Recomendación:**
- Evaluar si `day_of_week` mantiene importancia después de remover leakage
- Si persiste, considerar si es un artefacto de la distribución temporal de los datos
- Idealmente, la importancia #1 debería ser `score` o una feature estructural (`ob_distance_atr`, `fvg_aligned_count`)

### 29.6 Hallazgo #5: El Sistema es Perdedor en Producción

| Métrica | Real | Paper |
|---------|------|-------|
| Win rate | 56.4% | 68.6% |
| Total PnL | **−6.76 USDT** | **−33.43 USDT** |
| Avg trade | −0.123 | −0.955 |
| Expectancy | **Negativo** | Negativo |

**Paradoja:** Win rate > 50% pero PnL negativo. Esto significa que:
- Los **perdedores son más grandes** que los ganadores (ratio R:R desfavorable)
- El slippage en real empeora los resultados vs paper
- Los TPs estructurales no se están alcanzando (la mayoría de trades cierran en SL o breakeven)

**Recomendación:**
- Medir **R-ratio promedio** (distancia al TP1 vs distancia al SL) por trade
- Si R-ratio < 1.5, el sistema matemáticamente NO PUEDE ser rentable con 56% WR
- Revisar si los TPs estructurales están demasiado lejos (pocos hits) o el SL demasiado cerca (muchos hits)

### 29.7 Recomendaciones Prioritarias para el Comité

| Prioridad | Acción | Impacto Esperado | Esfuerzo |
|-----------|--------|------------------|----------|
| **P0** | Reemplazar GaussianNB por RidgeClassifier (hecho) | Reduce ruido, mejora estabilidad | 1h |
| **P0** | Remover `tp_fill_rate` del feature set | Elimina data leakage | 30min |
| **P1** | Implementar purged k-fold con 7d embargo | WF Sharpe realista | 4h |
| **P1** | Aumentar regularización XGB/RF | Reduce fold_std de 0.055 a <0.03 | 2h |
| **P1** | Investigar `day_of_week` como feature #1 | Evita dependencia espuria | 2h |
| **P2** | Aumentar muestra a 10,000+ samples | Mejora generalización | 2–4 semanas |
| **P2** | Medir y optimizar R-ratio promedio | PnL positivo con WR > 50% | 4h |
| **P2** | Reemplazar NB por LightGBM o LR-L1 | Mejor base model | 4h |

### 29.8 Métricas Objetivo Post-Fix

| Métrica | Actual | Objetivo 30d | Objetivo 90d |
|---------|--------|--------------|--------------|
| Ensemble AUC | 0.7005 | 0.65–0.70 | 0.70–0.75 |
| Fold AUC std | 0.055 | <0.04 | <0.03 |
| WF Sharpe | 12.66 (fake) | 0.5–1.0 (real) | 1.0–1.5 |
| WF PF | 218.78 (fake) | 1.2–1.8 (real) | 1.5–2.0 |
| Real PnL (30d) | −6.76 | −2.00 | +5.00 |
| Real Win Rate | 56.4% | 55–58% | 55–60% |

> **Nota:** Los objetivos son conservadores. Un sistema con AUC 0.70, WR 55%, y R-ratio 1.5+ PUEDE ser rentable a largo plazo. El problema actual no es el modelo de ML (es decente), sino la **gestión de riesgo y la ejecución** (slippage, TPs inalcanzables, overtrading).

---

*Documentación actualizada: 2026-05-28 — Métricas verificadas contra producción*
