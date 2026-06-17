# Informe Técnico — Motor IA de Trading Bot Platform
**Fecha:** 2026-05-10
**Versión:** Pipeline completo con XGBoost Anti-Fake, Macro Context, Portfolio Manager, Dynamic Leverage y Validación Heurística.

---

## 1. Arquitectura del Pipeline IA (Actualizada)

```
Celery Beat (5 min)
  → ai_scan_task.scan_all_watchlists()
      → Fetch OHLCV (Binance Futures, 200 velas)
          → ict_engine.analyze()        [BOS/CHoCH/OB/FVG/EQ/bias/trigger/grade]
              → smc_engine.analyze()    [sweep, P/D, aligned FVGs, ADX]
                  → confluence_engine.py    [scoring 0-100 ICT+SMC, SL/TP1/TP2]
                      → HTF Confirmation Gate
                          → signal_quality_engine.py  [anti-fake: tier + status + red flags]
                              → macro_context gate    [funding rates, economic calendar]
                                  → Dedup check → DB (AISignal with features JSONB)
                                      → Celery: activate_signal.delay(sig.id)
                                          → bot_activator.activate(ai_signal_id)
                                              → portfolio_manager check
                                                  → dynamic_leverage calc
                                                      → Exchange (real o paper)

Celery Beat (15 min)
  → ai_outcome_tracker.py   [etiqueta SUCCESS/FAILURE/EXPIRED/INVALID]
  → circuit_breaker_task.py [evalúa SL consecutivos por quality_tier]

Celery Beat (domingos 03:00 UTC)
  → ai_retrain_task.py      [entrena XGBoost anti-fake si ≥200 muestras]
```

---

## 2. Archivos del Sistema IA

### Core del análisis
| Archivo | Rol |
|---------|-----|
| `backend/app/engines/ict_engine.py` | Detección de estructura de mercado (BOS, CHoCH, OB, FVG, EQ, bias, grade A+/A/A-) |
| `backend/app/engines/smc_engine.py` | Liquidity sweep, premium/discount, FVGs alineados, ADX (Wilder) |
| `backend/app/engines/confluence_engine.py` | Scoring 0-100. Devuelve `ConfluenceResult` con SL/TP1/TP2 y features dict para ML |
| `backend/app/engines/signal_quality_engine.py` | Anti-fake heurístico. Blended 80% heuristic + 20% confluence. Tiers: STRONG≥75, MODERATE≥50, WEAK<50. Status: CLEAR/CAUTION/BLOCK |

### Pipeline de ejecución
| Archivo | Rol |
|---------|-----|
| `backend/app/services/ai_scanner.py` | `build_signal()` orquesta ICT→SMC→Confluence→Quality→HTF→Macro. `fetch_ohlcv()` con semáforo de 6 reqs |
| `backend/app/tasks/ai_scan_task.py` | Celery Beat 5min. Scanea watchlist, deduplica, dispara `activate_signal` |
| `backend/app/tasks/ai_outcome_tracker.py` | Celery Beat 15min. Walk-forward de velas post-señal. Etiqueta PENDING→SUCCESS/FAILURE/EXPIRED/INVALID |
| `backend/app/tasks/ai_retrain_task.py` | Dispara entrenamiento XGBoost semanal |
| `backend/app/tasks/circuit_breaker_task.py` | Evalúa SL consecutivos por `quality_tier`. Auto-reset 24h |
| `backend/app/tasks/kill_switch_task.py` | Cierra TODAS las posiciones en <10s (emergencia) |

### Puente a órdenes
| Archivo | Rol |
|---------|-----|
| `backend/app/engines/bot_activator.py` | Recibe señal, filtra por tier/status/score/concurrency/circuit breaker/macro gate, aplica sizing dinámico, portfolio risk guard, dynamic leverage, ejecuta en exchange |
| `backend/app/services/portfolio_manager.py` | Evalúa riesgo agregado (exposure, correlación alts/BTC) antes de abrir posición |
| `backend/app/services/dynamic_leverage.py` | Ajusta leverage en tiempo real según ATR spike, funding rate extremo, eventos macro |
| `backend/app/services/macro_context.py` | Funding rates + calendario económico como gate |

### API
| Archivo | Rol |
|---------|-----|
| `backend/app/api/routes/ai.py` | Endpoints: `/ai/heuristic-validation`, `/ai/model/status`, `/ai/model/train`, `/ai/bots`, `/ai/macro-context` |
| `backend/app/api/routes/bots.py` | Deep-merge de `ai_signal_config` en `update_bot` para preservar estado runtime |
| `backend/app/api/routes/portfolio.py` | Resumen de exposición agregada |

### Modelos
| Archivo | Rol |
|---------|-----|
| `backend/app/models/ai_signal.py` | Tabla `ai_signals`. Incluye `quality_score`, `quality_tier`, `anti_fake_status`, `outcome`, `pnl_pct`, `outcome_bars`, `features`, `components`, `warnings` |
| `backend/app/models/bot_config.py` | `ai_signal_mode`, `ai_signal_config` JSONB con filtros, sizing, circuit breaker, portfolio limits |
| `backend/app/models/position.py` | `extra_config` guarda `quality_tier` de la señal que originó la posición |

### Frontend
| Archivo | Rol |
|---------|-----|
| `frontend/src/pages/AIPage.jsx` | 3 pestañas: Scanner / Backtest / Validación. Componentes: `XGBoostCard`, `BotActivatorCard`, `StatsBar` |
| `frontend/src/pages/BotEditPage.jsx` | Controles modo IA: tiers, statuses, sizing multipliers, circuit breaker thresholds, portfolio limits |
| `frontend/src/pages/DocumentationPage.jsx` | Docs integradas en `/docs` |
| `frontend/src/services/aiService.js` | `heuristicValidation()`, `modelStatus()`, `trainModel()`, `listAiBots()`, `macroContext()` |
| `frontend/src/services/killSwitch.js` | Servicio frontend para kill switch de emergencia |

### ML / XGBoost
| Archivo | Rol |
|---------|-----|
| `backend/ai/trainers/anti_fake_trainer.py` | Entrena XGBClassifier binario (FAILURE=1, SUCCESS=0). Min 200 muestras. Métricas: AUC, accuracy, feature importance |
| `backend/ai/registry.py` | Lazy load thread-safe de `anti_fake_v1.pkl`. `predict_success_probability()` devuelve P(SUCCESS) 0-1 |
| `backend/ai/dataset_builder.py` | Construye dataset X/y desde señales resueltas usando 15 features estructurales + one-hot encoding |
| `backend/ai/models/anti_fake_v1.pkl` | Artefacto generado en runtime |

---

## 3. Pipeline Detallado por Fases

### Fase 1 — ICT Engine (`ict_engine.py`)
- **Pivots de swing**: ventana 2×n+1 (n=5), mecha > 0.3×ATR sobre cierres vecinos
- **State machine BOS/CHoCH**: body break del último swing high/low
- **Order Block**: última vela contraria antes del swing (15 barras de lookback)
- **FVG**: imbalance de 3 velas (bull: high[i-1] < low[i+1])
- **EQ Highs/Lows**: pools de liquidez con tolerancia ATR×0.15
- **Signal Grade**: A+ (BOS+bull+long), A (CHoCH), A- (BOS+bear+short)

### Fase 2 — SMC Engine (`smc_engine.py`)
- **Liquidity Sweep**: mecha rompe EQ pero cierre vuelve dentro (fake-out)
- **Premium/Discount**: posición en rango de 20 velas (0.0=discount, 1.0=premium)
- **Aligned FVGs**: FVGs no rellenados que coinciden con el bias
- **ADX**: Wilder smoothing (α=1/14). ADX<25 → mercado en rango (reduce peso sweep/killzone)

### Fase 3 — Confluence Engine (`confluence_engine.py`)
**Scoring**:
| Factor | Puntos | Condición |
|--------|--------|-----------|
| CHoCH | +20 | last_break.kind == "CHoCH" |
| BOS | +12 | last_break.kind == "BOS" |
| Trigger OB | +15 | trigger == "ob" |
| Trigger FVG | +10 | trigger == "fvg" |
| Aligned FVGs | +4 c/u, max +12 | min(count×4, 12) |
| Liquidity sweep | +18 (trending) / +10 (rango) | ADX ≥25 vs <25 |
| Premium/Discount | +10 | Long + pd<0.5 o Short + pd>0.5 |
| Killzone | +10 (trending) / +5 (rango) | Hora UTC en zona óptima |
| EQ obstacle | -8 | EQ dentro de 1% del entry |

**Confidence**: HIGH ≥75 | MEDIUM ≥55 | LOW <55

**Niveles**:
```
entry_zone = (bottom, top) del OB o FVG
mid = (entry_zone[0] + entry_zone[1]) / 2

LONG:  sl = max(eq_lows debajo de mid) o mid - ATR×2
       risk = mid - sl  (safeguard: si risk<=0, sl = mid×0.99)
       tp1 = mid + risk×1.5
       tp2 = mid + risk×2.5

SHORT: sl = min(eq_highs encima de mid) o mid + ATR×2
       risk = sl - mid  (safeguard: si risk<=0, sl = mid×1.01)
       tp1 = mid - risk×1.5
       tp2 = mid - risk×2.5
```

### Fase 4 — Signal Quality Engine (`signal_quality_engine.py`)
**Heuristic scoring** (reglas puras, NO es ML):
| Factor | Puntos | Condición |
|--------|--------|-----------|
| Volumen | +15 / +7 | ratio >1.5 / 1.0-1.5 |
| Spread | +15 / +7 | spread_atr <1.0 / 1.0-1.5 |
| Sweep | +20 | sweep_detected == True |
| FVGs | +15 / +8 | aligned ≥2 / ==1 |
| Killzone | +15 | killzone is not None |
| P/D (long) | +15 / +8 | <0.35 / 0.35-0.5 |
| P/D (short) | +15 / +8 | >0.65 / 0.5-0.65 |
| Trigger OB | +10 | trigger == "ob" |
| Trigger FVG | +5 | trigger == "fvg" |

**Blending** (recalibrado):
```python
# ANTES: 0.6 * heuristic + 0.4 * confluence_score
# AHORA:  0.8 * heuristic + 0.2 * confluence_score
blended = round(0.8 * heuristic + 0.2 * confluence_score, 1)
```
Razón: confluence_score alto a menudo significaba movimiento ya extendido (sobre-compra/venta).

**Tiers**: STRONG ≥75 | MODERATE ≥50 | WEAK <50

**Anti-Fake Status**:
- CLEAR (0 red flags) → recommendation = "ENTER" si tier permite
- CAUTION (1 red flag) → recommendation = "WAIT"
- BLOCK (2+ red flags) → recommendation = "AVOID"

Red flags: volume_ratio < 0.5, spread_atr > 2.0

### Fase 5 — HTF Confirmation Gate (`ai_scanner.py`)
```python
_HTF_MAP = {"1m":"5m", "5m":"30m", "15m":"1h", "1h":"4h", "4h":"1d", "1d":"1w"}
if htf_bias contradicts signal_direction:
    return NO_SIGNAL
```

### Fase 6 — Macro Context Gate (`macro_context.py`)
- Funding rate >0.03%/8h + dirección LONG → blocked
- High impact event en próximos 60 min → caution/avoid

### Fase 7 — XGBoost Anti-Fake (`backend/ai/`)
**Distinción clave**: Signal Quality Engine (heurístico, reglas) ≠ XGBoost (ML, aprende de datos)

**Dataset builder** (`dataset_builder.py`):
```python
FEATURE_COLS = [
    "fvg_aligned_count", "ob_distance_atr", "sweep_detected", "pd_position",
    "hour_utc", "day_of_week", "eq_highs_count", "eq_lows_count",
    "volume_ratio", "spread_atr", "score",
    "trigger_ob", "trigger_fvg", "bias_bull", "sweep_bool", "break_choch",
]
label = 1 if outcome == "FAILURE" else 0
```

**Trainer** (`anti_fake_trainer.py`):
```python
XGBClassifier(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.8, colsample_bytree=0.8,
    scale_pos_weight=neg/pos,  # balance de clases
    eval_metric="logloss",
)
```

**Uso**: El modelo NO reemplaza el STATUS heurístico. Se usa como:
1. Validación cruzada: si predice >70% FAILURE para CLEAR, elevar a CAUTION
2. Feature importance: indica qué variables predicen fallos históricamente
3. Threshold tuning: ajusta umbrales del heuristic engine con datos reales

### Fase 8 — Bot Activator (`bot_activator.py`)
Flujo de decisión por bot:
1. ¿Stale? signal_time > 3×timeframe → reject
2. ¿`sig.quality_tier` en `allowed_tiers`? → skip
3. ¿`sig.anti_fake_status` en `allowed_statuses`? → skip (BLOCK nunca permitido)
4. ¿Circuit breaker abierto para ese tier? → skip
5. ¿`sig.score >= min_score`? → skip
6. ¿Macro context bloquea? → skip
7. ¿Portfolio risk excede límites? → block o reduce sizing
8. ¿Max concurrent alcanzado? → skip
9. Resolver conflictos (close_and_open / keep_both / reject)
10. Aplicar sizing multipliers: `notional *= tier_mult * status_mult`
11. Calcular dynamic leverage (ATR, funding, macro)
12. Market order + SL + TP1(60%) + TP2(40%)

**Fallback crítico**: Si falla colocación de TP → cierra posición inmediatamente (no naked risk).

### Fase 9 — Outcome Tracker (`ai_outcome_tracker.py`)
Walk-forward de velas posteriores (máx 50):
```python
for each candle_after_signal:
    if LONG:
        tp_hit = high >= tp1
        sl_hit = low  <= sl
    else:
        tp_hit = low  <= tp1
        sl_hit = high >= sl

    if tp_hit and sl_hit:
        # Tie-breaker con close vs entry
        outcome = "SUCCESS" if favor close else "FAILURE"
        ref = tp1 if SUCCESS else sl
    elif tp_hit:
        outcome, ref = "SUCCESS", tp1
    elif sl_hit:
        outcome, ref = "FAILURE", sl

    pnl = (ref - entry) / entry * 100   # LONG
    pnl = (entry - ref) / entry * 100   # SHORT
```

**Estados**:
| Estado | Significado | Cuándo |
|--------|-------------|--------|
| SUCCESS | TP1 tocado primero | high ≥ tp1 (long) antes que low ≤ sl |
| FAILURE | SL tocado primero | low ≤ sl (long) antes que high ≥ tp1 |
| EXPIRED | Sin resolución | 50 barras sin tocar TP1 ni SL |
| INVALID | Niveles invertidos | tp1 ≤ entry o sl ≥ entry (long) — bug histórico |

---

## 4. Lógica de Filtros Configurables por Bot

```python
cfg = bot.ai_signal_config or {}
allowed_tiers    = cfg.get("allowed_tiers", ["STRONG"])
allowed_statuses = cfg.get("allowed_statuses", ["CLEAR"])
```

**Defaults de sizing**:
```json
{
  "STRONG": 1.0, "MODERATE": 1.0, "WEAK": 1.0,
  "CLEAR": 1.0, "CAUTION": 1.0
}
```

**Circuit breaker thresholds**:
```json
{
  "STRONG": {"consecutive_sl": 3},
  "MODERATE": {"consecutive_sl": 2},
  "WEAK": {"consecutive_sl": 1}
}
```

---

## 5. Portfolio Manager (`portfolio_manager.py`)

Evalúa riesgo agregado antes de abrir posición:

| Métrica | Límite default | Acción |
|---------|----------------|--------|
| Total exposure | 50% | Block si excede |
| Symbol exposure | 30% | Reduce sizing 50% |
| Directional exposure | 40% | Reduce sizing 50% |
| Alt correlation | 3 alts LONG + BTC bear | Reduce sizing 50% |

---

## 6. Dynamic Leverage (`dynamic_leverage.py`)

Ajusta leverage en tiempo real:
- ATR spike >2× histórico → reduce leverage
- Funding rate extremo → reduce leverage
- Evento macro de alto impacto → reduce leverage o bloquea

---

## 7. Endpoint de Validación Heurística

```
GET /ai/heuristic-validation?ticker=BTCUSDT&timeframe=1h&days=30
```

Respuesta:
```json
{
  "filters": { "days": 30 },
  "summary": { "total_signals": 500, "resolved": 400 },
  "by_tier_status": [
    { "tier": "STRONG", "status": "CLEAR", "count": 200, "resolved": 180,
      "success": 120, "failure": 50, "expired": 10, "win_rate": 66.7, "avg_pnl_pct": 1.2 }
  ],
  "by_tier": [ ... ],
  "by_status": [ ... ]
}
```

---

## 8. Decisiones de Diseño Técnico

### 8.1 ¿Por qué blended 80/20 en Signal Quality?
El confluence_score a menudo refleja un movimiento ya extendido (sobre-compra/venta), no probabilidad de continuación. Bajar su peso de 40% a 20% mejoró resultados.

### 8.2 ¿Por qué deep-merge en update_bot?
El frontend nunca debería sobrescribir estado runtime generado por tareas Celery. Sin deep-merge, editar el bot desde la UI borraría `circuit_breaker_state`.

### 8.3 ¿Por qué circuit breaker en JSONB?
- Menor fricción: no requiere migración Alembic
- Estado efímero (auto-reset 24h)
- Cohesión: config y estado viajan juntos

### 8.4 ¿Por qué no incluir BLOCK en allowed_statuses?
BLOCK = 2+ red flags. Por diseño de seguridad, nunca se permite operar señales BLOCK.

### 8.5 ¿Por qué el outcome tracker no distingue tier?
El tracker resuelve señales comparando precios contra TP1/SL. El tier ya está guardado en AISignal. El circuit breaker agrupa por tier vía `Position.extra_config["quality_tier"]`.

### 8.6 ¿Por qué XGBoost no reemplaza el heurístico?
- Heurístico funciona desde la primera señal (sin necesidad de 200 muestras)
- XGBoost necesita datos históricos y mejora con el tiempo
- Son capas complementarias: heurístico para interpretabilidad inmediata, ML para detección de patrones no obvios

---

## 9. Testing Recomendado

### Backend
```bash
# Verificar sintaxis
cd backend && python -m py_compile app/engines/bot_activator.py

# Test unitario del activator con tier MODERATE
# Crear bot con allowed_tiers=["STRONG","MODERATE"], sizing_multipliers={"MODERATE":0.5}
# Crear AISignal MODERATE+CLEAR → verificar notional/2

# Test circuit breaker
# Crear 2 posiciones AI cerradas en SL con quality_tier="MODERATE"
# Ejecutar check_circuit_breakers → verificar trip MODERATE
```

### Frontend
```bash
cd frontend && npm run build
# Navegar a /bots/{id}/edit → modo AI
# Navegar a /ai → pestaña Validación
# Verificar que /ai/heuristic-validation retorna datos
```

---

## 10. Próximos Pasos Técnicos Sugeridos

1. **Adaptive Weight Optimizer**: Shadow mode con dos scores (heurístico + pesos alternativos) comparando outcomes sin afectar trading.
2. **XGBoost v2**: Cuando haya ≥200 muestras por tier, entrenar modelos separados por tier en lugar de uno global.
3. **Macro features**: Integrar funding rates y calendario económico como features en `dataset_builder.py`.

---

*Fin del informe técnico actualizado.*
