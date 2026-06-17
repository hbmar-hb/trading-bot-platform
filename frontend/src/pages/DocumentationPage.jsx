import { useState, useEffect, useRef } from 'react'
import {
  BookOpen, ChevronRight, Zap, Brain, Bot, ShieldAlert,
  TrendingUp, KeyRound, FileText, Settings, BarChart3,
  AlertTriangle, CheckCircle2, HelpCircle, Mail, Layers,
  AlertOctagon, Activity, Gauge, Sparkles, Cpu,
  GitMerge, Scale, BrainCircuit, Target, ShieldCheck,
  BarChart4, TrendingDown, LineChart, Database, Server,
  Microscope, Workflow, Fingerprint,
} from 'lucide-react'
import { cn } from '@/utils/cn'

/* ── Section data ─────────────────────────────────────────────── */

/* ── IA Engine Section (consolidated) ─────────────────────────── */

function IAEngineSection() {
  const [tab, setTab] = useState('arquitectura')

  const tabs = [
    { id: 'arquitectura',   label: 'Arquitectura' },
    { id: 'scanner',        label: 'Scanner & Señales' },
    { id: 'dashboard',      label: 'Dashboard & Ranking' },
    { id: 'configuracion',  label: 'Configuración' },
    { id: 'autonomia',      label: 'Autonomía' },
  ]

  return (
    <>
      <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-3">IA ENGINE</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed mb-4">
        Motor de trading autónomo que combina análisis técnico ICT/SMC con Machine Learning
        para generar, evaluar y ejecutar señales de forma inteligente.
      </p>

      <div className="flex gap-0 border-b border-slate-200 dark:border-slate-800 mb-5">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              'px-4 py-2 text-xs font-medium border-b-2 -mb-px transition-colors',
              tab === t.id
                ? 'border-violet-500 text-violet-600 dark:text-violet-400'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'arquitectura' && (
        <div className="space-y-5">
          {/* ── Pipeline de Señales (actualizado) ── */}
          <div className="card p-4 border-l-4 border-violet-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <Workflow size={16} className="text-violet-500" />
              Pipeline de Señales — Ecosistema Completo
            </h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p><strong>1. Datos OHLCV</strong> (cada 5 min) → Análisis ICT/SMC (<code>confluence_engine.py</code>)</p>
              <p><strong>2. Scoring de confluencia</strong> (0-100 pts) — CHoCH, BOS, OB, FVG, sweep, P/D, killzone. <strong>Pesos adaptativos</strong> por feature importance del ensemble</p>
              <p><strong>3. Calidad heurística</strong> — red flags, volume, spread, sweep, FVGs, RSI/Stoch + Volume Profile POC</p>
              <p><strong>4. Ensemble Híbrido Anti-Fake</strong> — XGBoost + RandomForest + GaussianNB + meta-learner LR que asigna <code>ensemble_success_prob</code></p>
              <p><strong>5. Bot Activator</strong> → múltiples gates de riesgo (Kelly, drift, macro, portfolio, rolling beta) → Exchange</p>
              <p><strong>6. Outcome Tracker</strong> — cada 15 min evalúa TP1/SL. El resultado real alimenta el próximo retrain con <strong>sample_weight 5×</strong></p>
            </div>
          </div>

          {/* ── Por qué este sistema aprende con cada trade ── */}
          <div className="card p-4 border-l-4 border-amber-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <BrainCircuit size={16} className="text-amber-500" />
              ¿Por qué es un sistema que aprende con cada trade?
            </h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p>
                La mayoría de sistemas de trading usan backtest estático: calculan una vez, optimizan parámetros, y operan durante meses con la misma lógica. 
                Nuestro motor es diferente: <strong>cada posición que abres o cierras en el exchange se convierte automáticamente en un dato de entrenamiento</strong>.
              </p>
              <p className="font-semibold text-slate-700 dark:text-slate-300">Ciclo de feedback en vivo:</p>
              <ol className="list-decimal list-inside space-y-1 text-xs">
                <li>El scanner genera una señal con estructura de mercado + execution analytics (slippage, fees, gap frequency).</li>
                <li>El bot activator decide si ejecutar basándose en el ensemble + gates de riesgo.</li>
                <li>Si se ejecuta, la posición real queda vinculada a la señal via <code>extra_config.ai_signal_id</code>.</li>
                <li>El outcome tracker resuelve la señal cuando toca TP1 o SL (cada 15 min).</li>
                <li>El retrain automático (cada 6h) detecta señales nuevas y <strong>re-entrena todo el ensemble</strong> con los datos actualizados.</li>
                <li>Las señales provenientes de trades reales reciben <strong>sample_weight = 5×</strong> vs backtest sintético, forzando al modelo a aprender patrones de ejecución real.</li>
              </ol>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                <strong>Resultado:</strong> el modelo no memoriza reglas fijas. Cada slippage, cada gap, cada rechazo de una orden, cada TP1 parcialmente llenado, mejora la calibración del ensemble.
              </p>
            </div>
          </div>

          {/* ── Backtest en paralelo ── */}
          <div className="card p-4 border-l-4 border-sky-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <Database size={16} className="text-sky-500" />
              Backtest Sintético vs Trades Reales
            </h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p>
                El motor opera con <strong>dos universos de datos en paralelo</strong>:
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
                  <p className="font-semibold mb-1 text-slate-700 dark:text-slate-300">Universo A: Backtest Sintético (~3,200 señales)</p>
                  <p className="text-slate-500 dark:text-slate-400">
                    Cada señal del scanner se resuelve automáticamente simulando TP1 hit vs SL hit en OHLCV. 
                    El <code>realistic_outcome_engine</code> inyecta slippage, fees, funding y probabilidad de wick fill. 
                    Peso en entrenamiento: <strong>1×</strong>.
                  </p>
                </div>
                <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
                  <p className="font-semibold mb-1 text-slate-700 dark:text-slate-300">Universo B: Trades Reales (~12-18 actualmente)</p>
                  <p className="text-slate-500 dark:text-slate-400">
                    Señales que fueron ejecutadas en el exchange (BingX) con tamaño real, slippage real, comisiones reales. 
                    El outcome se resuelve desde el exchange, no desde OHLCV. 
                    Peso en entrenamiento: <strong>5×</strong>.
                  </p>
                </div>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Aunque solo hay ~18 trades reales hoy, el backtest proporciona la masa crítica (~3,200) para entrenar el ensemble. 
                A medida que los trades reales crecen (objetivo: 50+), el modelo irá migrando gradualmente de "backtest-dominado" a "real-dominado" sin intervención manual.
              </p>
            </div>
          </div>

          {/* ── Scoring de Confluencia ── */}
          <div className="card p-4 border-l-4 border-blue-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Scoring de Confluencia (Fase 1)</h3>
            <table className="w-full text-xs text-left mt-2">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="py-1.5 pr-3">Componente</th>
                  <th className="py-1.5">Puntos base</th>
                  <th className="py-1.5">Adaptativo</th>
                </tr>
              </thead>
              <tbody className="text-slate-600 dark:text-slate-300">
                <tr><td className="py-1">CHoCH (cambio de estructura)</td><td className="py-1 font-mono">+20</td><td className="py-1 font-mono text-violet-500">~14.2</td></tr>
                <tr><td className="py-1">BOS (ruptura de estructura)</td><td className="py-1 font-mono">+12</td><td className="py-1 font-mono text-violet-500">~8.5</td></tr>
                <tr><td className="py-1">Order Block trigger</td><td className="py-1 font-mono">+15</td><td className="py-1 font-mono text-violet-500">~22.5</td></tr>
                <tr><td className="py-1">Fair Value Gap trigger</td><td className="py-1 font-mono">+10</td><td className="py-1 font-mono text-violet-500">~10.3</td></tr>
                <tr><td className="py-1">2+ FVGs alineados</td><td className="py-1 font-mono">+12</td><td className="py-1 font-mono text-violet-500">~8.3</td></tr>
                <tr><td className="py-1">Liquidity sweep</td><td className="py-1 font-mono">+18</td><td className="py-1 font-mono text-violet-500">~12.0</td></tr>
                <tr><td className="py-1">Premium/Discount zone</td><td className="py-1 font-mono">+10</td><td className="py-1 font-mono text-violet-500">~6.3</td></tr>
                <tr><td className="py-1">Killzone activa</td><td className="py-1 font-mono">+5 / +10</td><td className="py-1 font-mono text-violet-500">~8.8</td></tr>
                <tr><td className="py-1">Obstáculo EQ</td><td className="py-1 font-mono text-red-500">-8</td><td className="py-1 font-mono text-violet-500">~6.8</td></tr>
              </tbody>
            </table>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
              Los pesos <strong className="text-violet-500">adaptativos</strong> se calculan desde <code>feature_importance</code> del ensemble híbrido.
              Si hay ≥20 señales por ticker/timeframe, usa pesos específicos; si no, fallback a global.
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Umbrales: <strong>HIGH ≥75</strong> | <strong>MEDIUM ≥55</strong> | <strong>LOW &lt;55</strong>
            </p>
          </div>

          {/* ── Ensemble Híbrido + Meta-Learning ── */}
          <div className="card p-4 border-l-4 border-pink-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <GitMerge size={16} className="text-pink-500" />
              Fase 2 — Ensemble Híbrido + Meta-Learning
            </h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              En lugar de confiar en un solo modelo XGBoost, el motor usa <strong>3 modelos base diversos</strong> cuyas predicciones se combinan via un meta-learner (stacking OOF). Esto reduce overfitting y mejora la generalización a trades reales.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-slate-600 dark:text-slate-300 mb-3">
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2 border-l-2 border-pink-400">
                <p className="font-semibold mb-1">XGBoost</p>
                <p>500 estimadores, depth=3, lr=0.05</p>
                <p className="text-[10px] text-slate-400 mt-1">Reg: α=0.5, λ=3, γ=2, min_child=10</p>
              </div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2 border-l-2 border-emerald-400">
                <p className="font-semibold mb-1">RandomForest</p>
                <p>300 árboles, depth=6, sqrt features</p>
                <p className="text-[10px] text-slate-400 mt-1">Bagging + class_weight balanced</p>
              </div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2 border-l-2 border-blue-400">
                <p className="font-semibold mb-1">LogisticRegression L1</p>
                <p>C=0.5, liblinear, balanced</p>
                <p className="text-[10px] text-slate-400 mt-1">Captura relaciones lineales</p>
              </div>
            </div>
            <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3 text-xs text-slate-600 dark:text-slate-300 mb-2">
              <p className="font-semibold mb-1">Meta-learner: LogisticRegression L2</p>
              <p>Entrenado en las <strong>predicciones OOF</strong> (out-of-fold) de los 3 modelos base. Peso final = <code>softmax(meta_learner.coef_)</code>.</p>
              <p className="mt-1 text-slate-500 dark:text-slate-400">
                Ejemplo de pesos tras último entrenamiento: XGB <strong>+0.23</strong> | RF <strong>+1.17</strong> | LR <strong>-0.40</strong>
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-600 dark:text-slate-300">
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Target</p><p>1 = señal falsa (FAILURE) | 0 = señal válida (SUCCESS)</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Reentrenamiento</p><p>Cada 6h (si ≥24h o ≥50 señales nuevas). Mínimo: 50 señales.</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">CV</p><p>GroupKFold por ticker/timeframe (evita leakage de símbolo)</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Calibración</p><p>Platt Scaling post-entreno para probabilidades calibradas</p></div>
            </div>
            <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
              <p className="font-semibold text-slate-700 dark:text-slate-300">Umbrales ML (ensemble):</p>
              <ul className="list-disc list-inside mt-1 space-y-0.5">
                <li><code>ensemble_success_prob ≤ 0.30</code> → BLOCK</li>
                <li><code>ensemble_success_prob ≤ 0.50</code> → CAUTION</li>
                <li><code>ensemble_success_prob &gt; 0.50</code> → CLEAR</li>
              </ul>
            </div>
          </div>

          {/* ── Medidas Anti-Overfitting ── */}
          <div className="card p-4 border-l-4 border-emerald-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <ShieldCheck size={16} className="text-emerald-500" />
              Medidas Anti-Overfitting
            </h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p>El modelo anterior sufría de overfitting extremo (AUC 0.97 / Accuracy 97.5%) porque memorizaba outcomes sintéticos deterministas. El nuevo pipeline aplica 6 capas de protección:</p>
              <ol className="list-decimal list-inside space-y-1 text-xs">
                <li><strong>Eliminación de leakage:</strong> <code>realistic_pnl_pct</code> ya no se usa como feature (era target leakage directo).</li>
                <li><strong>Regularización agresiva:</strong> max_depth=3, reg_alpha=0.5, reg_lambda=3.0, gamma=2.0, min_child_weight=10, subsample=0.7.</li>
                <li><strong>GroupKFold:</strong> validación cruzada agrupada por ticker/timeframe — un símbolo nunca aparece en train y test simultáneamente.</li>
                <li><strong>Noise injection:</strong> ruido gaussiano proporcional al std de cada feature (1%) inyectado en cada fold de entrenamiento.</li>
                <li><strong>Early stopping:</strong> 30 rounds con eval_set, evitando que los 500 estimadores se conviertan en memorización pura.</li>
                <li><strong>OOF AUC como métrica principal:</strong> en vez de un simple train/test split, se reporta AUC out-of-fold (más realista).</li>
              </ol>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Resultado: AUC bajó de 0.97 a ~0.79 — el modelo ahora generaliza en vez de memorizar.
              </p>
            </div>
          </div>

          {/* ── Walk-Forward Validation Gate ── */}
          <div className="card p-4 border-l-4 border-amber-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <Scale size={16} className="text-amber-500" />
              Walk-Forward Validation Gate
            </h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p>
                Antes de que un nuevo modelo reemplace al anterior, debe pasar una simulación de trading walk-forward (time-series aware):
              </p>
              <ul className="list-disc list-inside space-y-1 text-xs">
                <li>Se entrena en una ventana de N muestras, se evalúa en la siguiente ventana de M muestras.</li>
                <li>El modelo predice "operar" o "no operar" en cada señal del test set.</li>
                <li>Se calcula Sharpe, Profit Factor, Expectancy, Win Rate y Max Drawdown agregados.</li>
                <li>El nuevo modelo solo se acepta si mejora o retiene métricas clave del modelo anterior.</li>
                <li>Folds con una sola clase se saltan gracefulmente (no crashean el gate).</li>
              </ul>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                <strong>Nota:</strong> con datos sintéticos sesgados, el gate puede ser demasiado estricto. Se relajó temporalmente (max_drawdown 50%, win_rate 30%) para permitir iteración rápida durante desarrollo.
              </p>
            </div>
          </div>

          {/* ── Feature Importance Actual ── */}
          <div className="card p-4 border-l-4 border-cyan-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <Fingerprint size={16} className="text-cyan-500" />
              Feature Importance Actual (post-regularización)
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">Tras entrenamiento con ~3,243 señales (AUC=0.79, ACC=87%):</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-slate-600 dark:text-slate-300">
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><span className="font-semibold">day_of_week</span> 31.7%</div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><span className="font-semibold">ob_distance_atr</span> 8.4%</div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><span className="font-semibold">fvg_aligned_count</span> 8.2%</div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><span className="font-semibold">bias_bull</span> 7.8%</div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><span className="font-semibold">score</span> 7.0%</div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><span className="font-semibold">eq_highs_count</span> 5.9%</div>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
              La distribución es mucho más dispersa que antes (donde 2-3 features dominaban 40%+). Esto es señal de que el modelo ya no memoriza un solo patrón.
            </p>
          </div>
        </div>
      )}

      {tab === 'scanner' && (
        <div className="space-y-5">
          <div className="card p-4 border-l-4 border-blue-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Ciclo de Vida de una Señal</h3>
            <ol className="list-decimal list-inside space-y-2 text-sm text-slate-600 dark:text-slate-300">
              <li><strong>Fetch OHLCV:</strong> Descarga velas de Binance Futures.</li>
              <li><strong>ICT Engine:</strong> Detecta BOS, CHoCH, Order Blocks, FVG, EQ highs/lows.</li>
              <li><strong>Confluence Engine:</strong> Puntúa 0-100 según convergencia de factores.</li>
              <li><strong>HTF Gate:</strong> Verifica que el timeframe mayor no contradiga la dirección.</li>
              <li><strong>Quality Engine:</strong> Evalúa anti-fake (volumen, spread, sweep, killzone, RSI/Stoch).</li>
              <li><strong>Dedup + Persistencia:</strong> Guarda en base de datos si es nueva.</li>
              <li><strong>Bot Activator:</strong> Si pasa filtros del bot, ejecuta orden en el exchange.</li>
              <li><strong>Outcome Tracker:</strong> Cada 15 min evalúa si tocó TP1 o SL primero.</li>
            </ol>
          </div>

          <div className="card p-4 border-l-4 border-violet-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Watchlist</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              El scanner solo analiza los pares en tu <strong>watchlist</strong>. Sin watchlist, no hay señales.
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li>Máximo <strong>15 pares</strong> por usuario.</li>
              <li>Timeframe diferente por par (ej. BTC 1h, SOL 4h).</li>
              <li>El scanner fetchea HTF automáticamente (ej. si vigilas 4h, analiza 1d).</li>
            </ul>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="card p-4 border-l-4 border-emerald-500">
              <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Tiers de Calidad</h3>
              <table className="w-full text-xs mt-2">
                <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                  <tr><th className="text-left px-2 py-1.5">Tier</th><th className="text-left px-2 py-1.5">Score</th><th className="text-left px-2 py-1.5">Significado</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-600 dark:text-slate-300">
                  <tr><td className="px-2 py-1.5"><span className="bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400 px-1.5 py-0.5 rounded text-[10px] font-bold">STRONG</span></td><td className="px-2 py-1.5">≥70</td><td className="px-2 py-1.5">Máxima confluencia</td></tr>
                  <tr><td className="px-2 py-1.5"><span className="bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400 px-1.5 py-0.5 rounded text-[10px] font-bold">MODERATE</span></td><td className="px-2 py-1.5">45-69</td><td className="px-2 py-1.5">Confluencia media</td></tr>
                  <tr><td className="px-2 py-1.5"><span className="bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400 px-1.5 py-0.5 rounded text-[10px] font-bold">WEAK</span></td><td className="px-2 py-1.5">&lt;45</td><td className="px-2 py-1.5">Pocos factores</td></tr>
                </tbody>
              </table>
            </div>
            <div className="card p-4 border-l-4 border-amber-500">
              <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Anti-Fake Status</h3>
              <table className="w-full text-xs mt-2">
                <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                  <tr><th className="text-left px-2 py-1.5">Status</th><th className="text-left px-2 py-1.5">Red flags</th><th className="text-left px-2 py-1.5">Acción</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-600 dark:text-slate-300">
                  <tr><td className="px-2 py-1.5"><span className="bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400 px-1.5 py-0.5 rounded text-[10px] font-bold">CLEAR</span></td><td className="px-2 py-1.5">0</td><td className="px-2 py-1.5">Operar</td></tr>
                  <tr><td className="px-2 py-1.5"><span className="bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400 px-1.5 py-0.5 rounded text-[10px] font-bold">CAUTION</span></td><td className="px-2 py-1.5">1</td><td className="px-2 py-1.5">Precaución</td></tr>
                  <tr><td className="px-2 py-1.5"><span className="bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400 px-1.5 py-0.5 rounded text-[10px] font-bold">BLOCK</span></td><td className="px-2 py-1.5">2+</td><td className="px-2 py-1.5">No operar</td></tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-indigo-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Backtest</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Histórico de señales generadas con simulación de resultado. Puedes filtrar por tier y ver curva de P&L.
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li>Outcome: SUCCESS (TP1 primero), FAILURE (SL), EXPIRED (50 velas sin resultado).</li>
              <li>Señales INVALID (niveles invertidos) se excluyen de estadísticas.</li>
              <li>Usa el backtest para decidir si activar MODERATE o CAUTION en tu bot.</li>
            </ul>
          </div>

          <div className="card p-4 border-l-4 border-teal-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Validación Heurística</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Informe estadístico que indica si el heurístico está bien calibrado. Filtra por período (7-365 días).
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li>Revisa la <strong>matriz Tier × Status</strong> antes de cambiar la config de un bot.</li>
              <li>Si CAUTION tiene WR similar a CLEAR, el heurístico es demasiado conservador.</li>
            </ul>
          </div>

          <div className="card p-4 border-l-4 border-sky-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Panel de Detalle Expandido</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Haz clic en cualquier tarjeta del scanner para expandir un panel inline con 3 pestañas:
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li><strong>Detalle:</strong> Gráfico de velas con análisis ICT superpuesto (zona de entrada, SL, TP, score).</li>
              <li><strong>Backtest:</strong> Histórico de señales del par con resumen y tabla detallada.</li>
              <li><strong>Validación:</strong> Matriz Tier × Status y filtros de período para calibrar el heurístico.</li>
            </ul>
          </div>
        </div>
      )}

      {tab === 'dashboard' && (
        <div className="space-y-5">
          <div className="card p-4 border-l-4 border-rose-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Dashboard IA</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Panel visual en la pestaña <strong>Dashboard</strong> de IA Engine que resume la salud del motor:
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-600 dark:text-slate-300 mb-2">
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">KPIs</p><p>WR señales (30d) · PnL Acumulado IA real · AUC-ROC · WR trades reales</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Salud del Modelo</p><p>Estado ACTIVO/ENTRENANDO, AUC, Accuracy, muestras, último entreno</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Posiciones Abiertas</p><p>Cantidad y PnL no realizado en tiempo real</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Curva de Equity (60d)</p><p>PnL diario (barras) + acumulado (línea)</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Embudo de Señales (30d)</p><p>Generadas → Evaluadas → Aprobadas → Ejecutadas → Ganadas</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Win Rate Móvil (7d)</p><p>Evolución en ventana deslizante con referencia al 50%</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Matriz Tier × Status</p><p>WR por combinación. Verde ≥60%, Ámbar 45–60%, Rojo &lt;45%</p></div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2"><p className="font-semibold mb-1">Feature Importance</p><p>Ranking de features del ensemble híbrido (XGB+RF+LR)</p></div>
            </div>
            <p className="text-[11px] text-slate-400 dark:text-slate-500">
              <em>WR señales = backtest (TP1 vs SL en OHLCV) · WR real = trades ejecutados en exchange · AUC = ensemble híbrido (XGB+RF+LR+meta-learner) entrenado con señales etiquetadas. Trades reales reciben sample_weight 5×.</em>
            </p>
          </div>

          <div className="card p-4 border-l-4 border-pink-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Ranking de Activos IA</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Clasifica todos los activos de tu watchlist según rendimiento histórico. Herramienta de descubrimiento para decidir en qué pares activar bots.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead><tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300 w-32">Columna</th>
                  <th className="text-left py-2 font-semibold text-slate-700 dark:text-slate-300">Descripción</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {[
                    ['Par','Símbolo del activo (ej. BTCUSDT).'],
                    ['Score','Confluence Score promedio.'],
                    ['WR','Win Rate % de señales resueltas.'],
                    ['Avg P&L','Profit/Loss promedio por señal (%).'],
                    ['Avg Bars','Velas promedio hasta resolución.'],
                    ['Optimal Tier','Tier con mejor WR histórico.'],
                    ['Optimal Status','Status con mejor WR histórico.'],
                    ['Señales','Total generadas para ese par.'],
                  ].map(([col, desc]) => (
                    <tr key={col}><td className="py-2 pr-4 font-medium text-slate-700 dark:text-slate-300">{col}</td><td className="py-2 text-slate-600 dark:text-slate-400">{desc}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h4 className="font-semibold text-xs text-slate-700 dark:text-slate-300 mt-3 mb-1">Filtro de señales mínimas</h4>
            <ul className="list-disc list-inside space-y-0.5 text-xs text-slate-600 dark:text-slate-300">
              <li><strong>3:</strong> Muy permisivo. Usar con precaución.</li>
              <li><strong>5:</strong> Recomendado para watchlists nuevas.</li>
              <li><strong>10:</strong> Balance ideal entre cobertura y fiabilidad.</li>
              <li><strong>20:</strong> Muy conservador. Solo pares con historial largo.</li>
            </ul>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
              Los top 3 reciben 🥇 🥈 🥉 según la columna de ordenación activa.
            </p>
          </div>
        </div>
      )}

      {tab === 'configuracion' && (
        <div className="space-y-5">
          <div className="card p-4 border-l-4 border-blue-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Filtros del Bot IA</h3>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li><strong>Score mínimo:</strong> Umbral del Confluence Score (0-100). Default 60.</li>
              <li><strong>Máx. posiciones simultáneas:</strong> Cuántas operaciones abiertas permite. Default 1.</li>
              <li><strong>Tiers aceptados:</strong> STRONG, MODERATE, WEAK. Puedes activar varios.</li>
              <li><strong>Status aceptados:</strong> CLEAR, CAUTION. BLOCK nunca se incluye.</li>
            </ul>
          </div>

          <div className="card p-4 border-l-4 border-emerald-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Sizing Dinámico por Calidad</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Reduce el riesgo automáticamente según la calidad de la señal. Expresado como <strong>% del capital configurado</strong>.
            </p>
            <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-xs text-slate-600 dark:text-slate-300 space-y-1">
              <p><strong>Ejemplo conservador:</strong> STRONG=100% · MODERATE=50% · WEAK=0% · CLEAR=100% · CAUTION=25%</p>
              <p>Con capital de 100 USDT, una señal MODERATE+CLEAR abrirá con 50 USDT (100 × 0.5 × 1.0).</p>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-amber-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Circuit Breaker por Tier</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Seguro automático que bloquea un tier tras N stop losses consecutivos:
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li><strong>STRONG:</strong> 3 SL seguidos</li>
              <li><strong>MODERATE:</strong> 2 SL seguidos</li>
              <li><strong>WEAK:</strong> 1 SL seguido</li>
            </ul>
            <p className="text-sm text-slate-600 dark:text-slate-300 mt-2">
              Solo bloquea el tier afectado. El bot sigue operando otros tiers. Se <strong>auto-resetea a las 24h</strong>.
              Además, el bot se <strong>auto-reactiva</strong> si el WR rolling de las últimas 24h (≥3 señales) recupera ≥50%.
            </p>
          </div>

          <div className="card p-4 border-l-4 border-teal-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Config Óptima Automática</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Cuando <code>ai_optimal_config_enabled</code> está activo (default para bots AI), el activador consulta estadísticas históricas del ticker y aplica automáticamente:
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li><strong>min_score</strong> óptimo — umbral que maximiza win rate</li>
              <li><strong>allowed_tiers</strong> — solo tiers con ≥45% WR y ≥3 muestras</li>
              <li><strong>allowed_statuses</strong> — solo statuses con ≥45% WR y ≥3 muestras</li>
              <li><strong>sizing_multipliers</strong> — 1.0 si WR ≥55%, 0.5 si WR ≥45%, 0.0 si no</li>
              <li><strong>circuit_breaker_thresholds</strong> — conservadores para tiers con bajo WR</li>
              <li><strong>portfolio_limits</strong> — ajustadas al WR global del ticker</li>
            </ul>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
              Requiere ≥5 señales resueltas por ticker. Si no hay suficientes datos, no aplica cambios (safe fallback).
              Independiente del sistema de auto-optimización de parámetros (SL/leverage).
            </p>
          </div>

          <div className="card p-4 border-l-4 border-violet-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Auto-Configuración IA (✨ Auto)</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Botón <strong>✨ Auto</strong> en el editor de bots. Analiza el historial del par y rellena los filtros óptimos manualmente (one-shot, no automático per-signal).
            </p>
            <div className="space-y-2">
              <div className="card p-3 border-l-4 border-blue-500">
                <p className="font-semibold text-xs">Score mínimo</p>
                <p className="text-xs mt-1 text-slate-600 dark:text-slate-400">Umbral basado en score promedio de señales ganadoras históricas.</p>
              </div>
              <div className="card p-3 border-l-4 border-emerald-500">
                <p className="font-semibold text-xs">Tiers permitidos</p>
                <p className="text-xs mt-1 text-slate-600 dark:text-slate-400">Incluye tier solo si ≥3 señales resueltas y WR ≥45%.</p>
              </div>
              <div className="card p-3 border-l-4 border-yellow-500">
                <p className="font-semibold text-xs">Sizing dinámico</p>
                <p className="text-xs mt-1 text-slate-600 dark:text-slate-400">100% (WR≥55%), 50% (WR 45-55%), 0% (WR&lt;45%).</p>
              </div>
            </div>
            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
                <p className="font-semibold">✅ Ventajas</p>
                <ul className="list-disc list-inside mt-1 space-y-0.5">
                  <li>Ahorra tiempo en configuración.</li>
                  <li>Basado en datos reales del par.</li>
                  <li>Reduce riesgo descartando tiers débiles.</li>
                </ul>
              </div>
              <div className="bg-red-500/5 border border-red-500/20 rounded-lg px-3 py-2 text-xs text-red-700 dark:text-red-300">
                <p className="font-semibold">⚠️ Limitaciones</p>
                <ul className="list-disc list-inside mt-1 space-y-0.5">
                  <li>Requiere ≥3 señales resueltas por tier.</li>
                  <li>El pasado no garantiza el futuro.</li>
                  <li>Revisa antes de guardar.</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'autonomia' && (
        <div className="space-y-5">
          <div className="card p-4 border-l-4 border-violet-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Mecanismos Autónomos</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              El motor IA opera de forma autónoma con estos mecanismos de protección activos por defecto:
            </p>
            <table className="w-full text-xs text-left mt-2">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="py-1.5 pr-3">Mecanismo</th>
                  <th className="py-1.5">Comportamiento</th>
                </tr>
              </thead>
              <tbody className="text-slate-600 dark:text-slate-300">
                <tr><td className="py-1">Correlation gate</td><td className="py-1">Bloquea si activo correlacionado &gt;0.7 ya abierto misma dirección</td></tr>
                <tr><td className="py-1">Win rate histórico</td><td className="py-1">Rechaza si patrón (ticker+tier+status+dir) &lt;45% WR</td></tr>
                <tr><td className="py-1">TP split dinámico</td><td className="py-1">STRONG/CLEAR: 70/30 | Default: 60/40 | WEAK/CAUTION: 50/50</td></tr>
                <tr><td className="py-1">Leverage dinámico</td><td className="py-1">Reduce por ATR alto / funding alto / evento macro</td></tr>
                <tr><td className="py-1">Portfolio guard</td><td className="py-1">Límites: total &lt;50%, símbolo &lt;30%, direccional &lt;40%</td></tr>
                <tr><td className="py-1">Auto-reactivación</td><td className="py-1">Reactiva bot pausado si WR rolling 24h ≥50% (≥3 señales)</td></tr>
                <tr><td className="py-1">Watchlist coverage</td><td className="py-1">Alerta (log + Discord/Telegram) si bot activo no recibe señales &gt;1h por no estar en watchlist</td></tr>
                <tr><td className="py-1">Optimizer guard</td><td className="py-1">El optimizador general <strong>salta automáticamente</strong> bots con <code>ai_signal_mode=True</code>. Los bots IA usan <code>ai_optimal_config_enabled</code>, no el optimizador de parámetros.</td></tr>
              </tbody>
            </table>
          </div>

          <div className="card p-4 border-l-4 border-rose-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Separación Optimizador vs Bots IA</h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p>El <strong>optimizador general</strong> (<code>auto_optimize_enabled</code>) ajusta leverage, SL, TP y confirmación de señal basándose en el historial de trades del bot. Está diseñado para bots con indicadores externos/internos.</p>
              <p>Los <strong>bots IA</strong> (<code>ai_signal_mode=True</code>) usan un sistema separado:</p>
              <ul className="list-disc list-inside space-y-1 text-xs">
                <li><strong>AI Optimal Config</strong> ajusta filtros de señal (tiers, statuses, score mínimo, sizing) basándose en estadísticas históricas del ticker.</li>
                <li><strong>El ensemble</strong> califica cada señal individualmente con ML.</li>
                <li><strong>Los gates de riesgo</strong> (Kelly, drift, macro, portfolio, rolling beta) ajustan sizing y leverage por señal, no por bot.</li>
              </ul>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Si activas ambos sistemas en un bot IA, el optimizador general sería ignorado silenciosamente — el código lo detecta y salta automáticamente.
              </p>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-amber-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Leverage Dinámico (detalle)</h3>
            <table className="w-full text-xs mt-2">
              <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                <tr><th className="text-left px-2 py-1.5">Condición</th><th className="text-left px-2 py-1.5">Acción</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-600 dark:text-slate-300">
                <tr><td className="px-2 py-1.5">ATR &gt; 2× media histórica</td><td className="px-2 py-1.5">Leverage −50%</td></tr>
                <tr><td className="px-2 py-1.5">Funding rate &gt; 0.05%</td><td className="px-2 py-1.5">Leverage −50%</td></tr>
                <tr><td className="px-2 py-1.5">Evento macro bloqueado</td><td className="px-2 py-1.5">Leverage = 1×</td></tr>
                <tr><td className="px-2 py-1.5">Evento macro cercano</td><td className="px-2 py-1.5">Leverage cap = 3×</td></tr>
              </tbody>
            </table>
          </div>

          <div className="card p-4 border-l-4 border-emerald-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Trailing Stop + Breakeven + Post-TP1</h3>
            <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
              <div className="card p-3 border-l-4 border-emerald-500">
                <p className="font-semibold text-xs">Breakeven Auto</p>
                <p className="text-xs mt-1">A +1R, SL se mueve a entrada + 0.2%.</p>
              </div>
              <div className="card p-3 border-l-4 border-blue-500">
                <p className="font-semibold text-xs">Trailing Stop</p>
                <p className="text-xs mt-1">Activa a +1.5R. SL sigue al precio con callback 1% desde el máximo.</p>
              </div>
              <div className="card p-3 border-l-4 border-violet-500">
                <p className="font-semibold text-xs">Post-TP1 Trailing (40% libre)</p>
                <p className="text-xs mt-1">Al TP1 (60% cerrado), el 40% restante: cancela TP2, SL en breakeven, trailing 0.5%.</p>
              </div>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-sky-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Alertas Proactivas</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              El sistema notifica automáticamente por Telegram y Discord cuando:
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li>Un bot AI activo no está en la watchlist (no recibirá señales).</li>
              <li>Un bot no ha recibido señales ni abierto posiciones en &gt;1h.</li>
              <li>Un circuit breaker se activa o se resetea.</li>
              <li>Se aplica auto-optimización de parámetros.</li>
            </ul>
          </div>
        </div>
      )}
    </>
  )
}

const SECTIONS = [
  {
    id: 'bienvenida',
    title: 'Bienvenida',
    icon: BookOpen,
    content: (
      <>
        <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-3">Guía de Usuario — Trading Bot Platform</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed mb-4">
          Esta plataforma te permite operar en exchanges de criptomonedas de forma automatizada usando bots configurables,
          señales de inteligencia artificial (IA) basadas en análisis técnico ICT/SMC, webhooks desde TradingView y trading manual.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="card p-4">
            <Zap className="text-yellow-500 mb-2" size={20} />
            <h3 className="font-semibold text-sm">Automatización</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Crea bots que operan 24/7 sin intervención manual.</p>
          </div>
          <div className="card p-4">
            <Brain className="text-violet-500 mb-2" size={20} />
            <h3 className="font-semibold text-sm">Motor IA</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Scanner ICT+SMC con evaluación de calidad en tiempo real.</p>
          </div>
          <div className="card p-4">
            <TrendingUp className="text-emerald-500 mb-2" size={20} />
            <h3 className="font-semibold text-sm">Gestión de Riesgo</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Stop loss automático, circuit breaker y sizing dinámico.</p>
          </div>
          <div className="card p-4">
            <FileText className="text-blue-500 mb-2" size={20} />
            <h3 className="font-semibold text-sm">Paper Trading</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Prueba estrategias sin arriesgar dinero real.</p>
          </div>
        </div>
      </>
    ),
  },
  {
    id: 'ia-engine',
    title: 'IA ENGINE',
    icon: Brain,
    content: <IAEngineSection />,
  },
  {
    id: 'primeros-pasos',
    title: 'Primeros pasos',
    icon: CheckCircle2,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Primeros pasos</h2>
        <ol className="list-decimal list-inside space-y-4 text-sm text-slate-600 dark:text-slate-300">
          <li>
            <strong>Accede a tu cuenta:</strong> Usa las credenciales que te proporcionó el administrador.
            Si es tu primera vez, es posible que debas cambiar la contraseña.
          </li>
          <li>
            <strong>Revisa el Dashboard:</strong> Es tu centro de control. Muestra equity total, posiciones abiertas,
            bots activos y alertas del optimizador.
          </li>
          <li>
            <strong>Configura una cuenta de exchange o paper:</strong> Ve a <em>Exchanges</em> para añadir una cuenta real (API keys)
            o a <em>Paper</em> para crear una cuenta de simulación.
          </li>
          <li>
            <strong>Crea tu primer bot:</strong> Ve a <em>Bots → Nuevo bot</em>, elige el par (ej. BTCUSDT), timeframe y activa las fuentes de señal que quieras (Webhook, Indicador y/o IA).
          </li>
          <li>
            <strong>Activa el bot:</strong> Desde la lista de bots, pulsa el botón de activación. El bot empezará a escuchar señales.
          </li>
        </ol>

        <div className="mt-4 bg-amber-500/5 border border-amber-500/20 rounded-lg px-4 py-3 text-xs text-amber-700 dark:text-amber-300">
          <p className="font-semibold flex items-center gap-2"><AlertTriangle size={14}/> Recomendación inicial</p>
          <p className="mt-1">Siempre empieza con <strong>paper trading</strong>. Valida tu estrategia durante al menos una semana antes de usar dinero real.</p>
        </div>
      </>
    ),
  },
  {
    id: 'exchanges',
    title: 'Cuentas y Exchanges',
    icon: KeyRound,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Cuentas y Exchanges</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
          La plataforma se conecta a exchanges de criptomonedas mediante API keys. Actualmente soporta Binance, BingX y Bitunix.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Cómo añadir una cuenta real</h3>
        <ol className="list-decimal list-inside space-y-2 text-sm text-slate-600 dark:text-slate-300">
          <li>Ve a <strong>Exchanges</strong> en el menú lateral.</li>
          <li>Pulsa <strong>"Añadir cuenta"</strong>.</li>
          <li>Selecciona el exchange (Binance, BingX, Bitunix…).</li>
          <li>Introduce un <strong>label</strong> descriptivo (ej. "Mi cuenta Binance").</li>
          <li>Introduce la <strong>API Key</strong> y <strong>API Secret</strong> de tu exchange.</li>
          <li>Selecciona si la cuenta es de <strong>Futuros (USDⓈ-M)</strong>.</li>
          <li>Pulsa <strong>Guardar</strong>.</li>
        </ol>

        <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
          <p className="font-semibold">🔒 Seguridad</p>
          <p className="mt-1">Crea API keys con permisos de <strong>solo lectura y trading</strong>. No actives retiros (withdrawal). Guarda las keys de forma segura.</p>
        </div>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-5 mb-2">Problemas comunes</h3>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li><strong>"Invalid API key"</strong>: Verifica que no haya espacios al copiar/pegar.</li>
          <li><strong>"IP restriction"</strong>: Añade la IP del servidor de la plataforma en la configuración de tu exchange.</li>
          <li><strong>"No markets found"</strong>: La cuenta debe tener saldo o haber operado al menos una vez para que el exchange active los mercados.</li>
        </ul>
      </>
    ),
  },
  {
    id: 'paper-trading',
    title: 'Paper Trading',
    icon: FileText,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Paper Trading</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
          Paper trading es una simulación. El bot opera como si fuera real, pero no envía dinero al exchange.
          Es la forma más segura de probar estrategias nuevas.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Crear una cuenta paper</h3>
        <ol className="list-decimal list-inside space-y-2 text-sm text-slate-600 dark:text-slate-300">
          <li>Ve a <strong>Paper</strong> en el menú lateral.</li>
          <li>Pulsa <strong>"Crear cuenta paper"</strong>.</li>
          <li>Introduce un nombre (ej. "Test IA") y un balance inicial (ej. 10000 USDT).</li>
          <li>Selecciona el exchange de referencia (para precios y mercados).</li>
          <li>Pulsa <strong>Crear</strong>.</li>
        </ol>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-4 mb-2">Asignar paper a un bot</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Al crear o editar un bot, en <strong>Modo de trading</strong> selecciona <strong>📄 Paper</strong> y elige la cuenta creada.
          El bot operará en simulación hasta que cambies a una cuenta real.
        </p>

        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">✅ Ventajas</p>
            <ul className="list-disc list-inside text-xs text-emerald-600 dark:text-emerald-400 mt-1 space-y-0.5">
              <li>Sin riesgo de pérdida real</li>
              <li>Valida estrategias IA antes de poner dinero</li>
              <li>Testea configuraciones de circuit breaker</li>
              <li>Múltiples cuentas paper para diferentes estrategias</li>
            </ul>
          </div>
          <div className="bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-red-700 dark:text-red-300">⚠️ Limitaciones</p>
            <ul className="list-disc list-inside text-xs text-red-600 dark:text-red-400 mt-1 space-y-0.5">
              <li>No simula slippage ni lag del exchange</li>
              <li>No afecta el order book real</li>
              <li>Precios de ejecución pueden diferir ligeramente</li>
              <li>No garantiza resultados idénticos en real</li>
            </ul>
          </div>
        </div>
      </>
    ),
  },
  {
    id: 'bots',
    title: 'Bots y modos de activación',
    icon: Bot,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Bots y modos de activación</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
          Un bot es un operador automatizado que escucha señales y ejecuta órdenes según tu configuración.
          Cada bot opera un único par (símbolo) en un timeframe específico.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Crear un bot</h3>
        <ol className="list-decimal list-inside space-y-2 text-sm text-slate-600 dark:text-slate-300">
          <li>Ve a <strong>Bots</strong> y pulsa <strong>"Nuevo bot"</strong>.</li>
          <li>Rellena el <strong>Básico</strong>: nombre, símbolo, timeframe, apalancamiento.</li>
          <li>Configura <strong>Capital / SL</strong>: tipo de sizing (porcentaje o fijo USDT) y stop loss inicial.</li>
          <li>Define <strong>Take Profits</strong> (opcional pero recomendado).</li>
          <li>En la pestaña <strong>Activación</strong>, elige cómo se disparará.</li>
        </ol>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-5 mb-2">Fuentes de activación (independientes)</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-3">
          Cada bot puede tener una o varias fuentes activas simultáneamente. Ya no es necesario elegir solo una.
        </p>
        <div className="space-y-3">
          <div className="card p-4 border-l-4 border-blue-500">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">📡 Webhook externo</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              TradingView u otro sistema envía alertas JSON al endpoint del bot. Tú controlas cuándo se dispara desde fuera.
              Ideal si ya tienes indicadores propios en TradingView.
            </p>
          </div>
          <div className="card p-4 border-l-4 border-emerald-500">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">📊 Señal interna — Indicador</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              El sistema escanea usando el motor ICT / SMC interno. Dispara cuando detecta confluencia A/A+.
              Configurable: temporalidad del scan, tipos de señal, timing (cierre de vela o intracandle).
            </p>
          </div>
          <div className="card p-4 border-l-4 border-violet-500">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">🤖 Scanner IA</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              El motor IA evalúa confluencias ICT+SMC + anti-fake + confirmación HTF. El modo más avanzado.
              Ver la sección <strong>IA ENGINE</strong> para más detalle.
            </p>
          </div>
        </div>

        <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
          <p className="font-semibold">💡 Multi-fuente</p>
          <p className="mt-1">Puedes activar <strong>Webhook + Indicador + IA</strong> en el mismo bot. Cada fuente se evalúa de forma independiente y comparte la misma gestión de conflictos y capital por operación.</p>
        </div>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-5 mb-2">Estados del bot</h3>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li><strong>Activo:</strong> El bot está escuchando y ejecutando señales.</li>
          <li><strong>Pausado:</strong> El bot no ejecuta nuevas entradas, pero mantiene posiciones abiertas.</li>
          <li><strong>Deshabilitado:</strong> El bot no opera. Debes editarlo para cambiar configuración.</li>
        </ul>

        <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
          <p className="font-semibold">💡 Tip</p>
          <p className="mt-1">Puedes tener varios bots para el mismo par con diferentes configuraciones. Ejemplo: uno con scanner IA en paper (test) y otro con webhook en real (producción).</p>
        </div>
      </>
    ),
  },
  {
    id: 'indicadores',
    title: 'Indicadores internos',
    icon: Layers,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Indicadores internos — ICT / SMC</h2>
        <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
          La plataforma incluye el motor de señal ICT / SMC propio que puedes usar tanto para visualizar en el gráfico
          como para activar bots automáticamente. Tiene su propia configuración en dos lugares distintos.
        </p>

        <div className="rounded-lg bg-blue-500/8 border border-blue-500/20 px-4 py-3 mb-5 text-sm">
          <p className="font-semibold text-blue-400 mb-1">Configuración en gráfico vs. configuración del bot</p>
          <p className="text-slate-600 dark:text-slate-400">
            Son <strong>completamente independientes</strong>. Los parámetros del Panel del gráfico se guardan en tu navegador
            y solo afectan a la visualización. Los parámetros del bot se guardan en la base de datos y son los que usa
            el escáner Celery para generar señales reales. Puedes tener el gráfico en modo exploración con parámetros
            permisivos, y el bot con parámetros más conservadores.
          </p>
        </div>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-3">Cómo configurar el indicador en el gráfico</h3>
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-slate-600 dark:text-slate-400 mb-5">
          <li>Ve a <strong>Gráfico</strong> y selecciona el par y temporalidad.</li>
          <li>En la barra de indicadores (parte superior), activa <strong>ICT / SMC</strong> con el toggle.</li>
          <li>Haz clic en el icono <strong>⚙</strong> del badge del indicador (esquina superior izquierda del chart) para abrir el Panel.</li>
          <li>Ajusta los parámetros — los cambios se aplican en tiempo real sobre el gráfico.</li>
          <li>La configuración se guarda automáticamente en el navegador para esa sesión.</li>
        </ol>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-3">Cómo configurar el indicador en un bot</h3>
        <ol className="list-decimal list-inside space-y-1.5 text-sm text-slate-600 dark:text-slate-400 mb-5">
          <li>Ve a <strong>Bots → Editar bot</strong>.</li>
          <li>En la pestaña <strong>Activación</strong>, activa el toggle <strong>Indicador interno</strong>.</li>
          <li>Elige el indicador <strong>ICT / SMC</strong> en el desplegable.</li>
          <li>Aparecerá la sección <strong>Parámetros del indicador</strong> con todos los ajustes configurables.</li>
          <li>Guarda el bot — el escáner usará exactamente esos parámetros.</li>
        </ol>

        <div className="mb-6">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-3 flex items-center gap-2">
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400">ICT / SMC</span>
            Parámetros del motor ICT
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300 w-40">Parámetro</th>
                  <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300 w-16">Default</th>
                  <th className="text-left py-2 font-semibold text-slate-700 dark:text-slate-300">Descripción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {[
                  ['Pivot confirmación','5 velas','Número de velas a cada lado para confirmar un pivot alto/bajo. Más velas = pivots más robustos pero menos frecuentes.'],
                  ['Tamaño mín. pivot','× 0.3 ATR','El pivot debe tener un tamaño mínimo relativo al ATR. Valores bajos (0.1-0.5) generan más señales; valores altos (1-3) solo señales grandes.'],
                  ['Período ATR','14','Período para el cálculo del Average True Range. 14 es estándar; puedes reducirlo a 7 para mercados más volátiles.'],
                  ['Modo de entrada','OB o FVG','Define qué estructura de mercado confirma la entrada: Order Block, Fair Value Gap, o cualquiera de los dos. "OB o FVG" es el más permisivo.'],
                  ['Velas a analizar','200','Cantidad de velas históricas que el escáner procesa en cada ciclo. Más velas = análisis de estructura más completo pero mayor carga.'],
                ].map(([p, d, desc]) => (
                  <tr key={p}>
                    <td className="py-2 pr-4 font-medium text-slate-700 dark:text-slate-300">{p}</td>
                    <td className="py-2 pr-4 text-blue-500 font-mono">{d}</td>
                    <td className="py-2 text-slate-600 dark:text-slate-400">{desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 rounded-lg bg-slate-50 dark:bg-gray-800 px-3 py-2 text-xs text-slate-500 dark:text-slate-400">
            <strong>Grades ICT:</strong> A+ = BOS alcista (solo LONG) · A = CHoCH reversión (LONG o SHORT) · A- = BOS bajista (solo SHORT).
            El grade lo determina el tipo de ruptura de estructura, no la configuración.
          </div>
        </div>


      </>
    ),
  },
  {
    id: 'autonomia-avanzada',
    title: 'Autonomía Avanzada',
    icon: Gauge,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Autonomía Avanzada — Futuros Volátiles</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
          Estas features protegen tu capital en mercados de alta volatilidad. Actúan automáticamente sin intervención manual.
        </p>

        <div className="mb-6">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
            <AlertOctagon size={16} className="text-red-500" />
            Kill Switch Manual
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            Botón de emergencia que cierra <strong>TODAS</strong> las posiciones abiertas y pausa todos los bots en menos de 10 segundos.
            Disponible en el <strong>sidebar</strong> (footer) y en el <strong>Dashboard</strong>.
          </p>
          <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
            <li>Cancela SL y TP pendientes en el exchange.</li>
            <li>Cierra cada posición a <strong>mercado</strong> (market order).</li>
            <li>Pausa todos los bots activos del usuario.</li>
            <li>Notifica por Telegram/Discord con resumen: posiciones cerradas, PnL total, tiempo transcurrido.</li>
            <li>Requiere confirmación del navegador antes de ejecutar.</li>
          </ul>
          <div className="mt-2 bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 text-xs text-red-700 dark:text-red-300">
            <p className="font-semibold">⚠️ Uso recomendado</p>
            <p className="mt-1">Úsalo solo en emergencias (flash crash, noticia macro inesperada, comportamiento anómalo del exchange). No sustituye a una buena gestión de riesgo diaria.</p>
          </div>
        </div>

        <div className="mb-6">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
            <TrendingUp size={16} className="text-emerald-500" />
            Trailing Stop + Breakeven + Post-TP1 Libre
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            Los bots IA ahora traen configuración de riesgo por defecto. No necesitas configurar nada manualmente.
          </p>
          <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
            <div className="card p-3 border-l-4 border-emerald-500">
              <p className="font-semibold text-xs">Breakeven Auto</p>
              <p className="text-xs mt-1">Cuando el precio alcanza <strong>+1R</strong>, el SL se mueve automáticamente a entrada + 0.2%. Protege capital en trades que casi ganan pero revierten.</p>
            </div>
            <div className="card p-3 border-l-4 border-blue-500">
              <p className="font-semibold text-xs">Trailing Stop</p>
              <p className="text-xs mt-1">Se activa a <strong>+1.5R</strong>. El SL sigue al precio con un <strong>callback del 1%</strong> desde el máximo alcanzado. En futuros volátiles permite capturar extensiones de 5R-10R sin dejar dinero en la mesa.</p>
            </div>
            <div className="card p-3 border-l-4 border-violet-500">
              <p className="font-semibold text-xs">Post-TP1 Trailing (40% libre)</p>
              <p className="text-xs mt-1">Al ejecutar TP1 (60% cerrado), el 40% restante:</p>
              <ul className="list-disc list-inside text-xs mt-1 space-y-0.5">
                <li>Cancela TP2 automáticamente.</li>
                <li>Coloca nuevo SL en <strong>breakeven</strong>.</li>
                <li>Activa trailing con callback <strong>0.5%</strong> (más agresivo que el inicial).</li>
                <li>Corre libre hasta que el mercado revele su extensión máxima.</li>
              </ul>
            </div>
          </div>
        </div>

        <div className="mb-6">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
            <Activity size={16} className="text-blue-500" />
            Apalancamiento Dinámico
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            Antes de cada operación IA, el sistema ajusta el leverage automáticamente según las condiciones de mercado.
          </p>
          <table className="w-full text-xs mt-2">
            <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
              <tr><th className="text-left px-2 py-1.5">Condición</th><th className="text-left px-2 py-1.5">Acción</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-600 dark:text-slate-300">
              <tr><td className="px-2 py-1.5">ATR &gt; 2× media histórica</td><td className="px-2 py-1.5">Leverage −50%</td></tr>
              <tr><td className="px-2 py-1.5">Funding rate &gt; 0.05%</td><td className="px-2 py-1.5">Leverage −50%</td></tr>
              <tr><td className="px-2 py-1.5">Evento macro bloqueado</td><td className="px-2 py-1.5">Leverage = 1×</td></tr>
              <tr><td className="px-2 py-1.5">Evento macro cercano (caution)</td><td className="px-2 py-1.5">Leverage cap = 3×</td></tr>
            </tbody>
          </table>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
            El ATR y su historia se calculan en tiempo real desde las 200 velas del scanner. El funding rate se obtiene del exchange vía CCXT.
          </p>
        </div>

        <div className="mb-6">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
            <ShieldAlert size={16} className="text-amber-500" />
            Portfolio Manager v2
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            Protección agregada a nivel de cartera. Se evalúa <strong>antes</strong> de abrir cada nueva posición IA.
          </p>
          <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
            <div className="card p-3">
              <p className="font-semibold text-xs">Drawdown Guard</p>
              <p className="text-xs mt-1">Si el portfolio está en drawdown &gt; 10%, reduce sizing 50%. Si &gt; 5%, reduce 25%. El drawdown se calcula en tiempo real usando realized PnL (24h) + unrealized PnL (precios de Redis).</p>
            </div>
            <div className="card p-3">
              <p className="font-semibold text-xs">Correlación BTC-Alts</p>
              <p className="text-xs mt-1">Si BTC cae &gt; 3% en 24h y el bot quiere abrir LONG en una alt, el sizing se reduce 50% automáticamente. Evita acumular alts largas en correcciones de BTC.</p>
            </div>
            <div className="card p-3">
              <p className="font-semibold text-xs">Límites de exposición (existentes)</p>
              <p className="text-xs mt-1">Total &lt; 50%, símbolo &lt; 30%, direccional &lt; 40%, alt correlation threshold = 3 alts LONG con BTC bearish.</p>
            </div>
          </div>
        </div>

        <div className="mb-6">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
            <Zap size={16} className="text-yellow-500" />
            OCO Soft (One Cancels Other)
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            Los exchanges (BingX/Bitunix) no soportan OCO nativo. El sistema implementa OCO "soft" gestionando manualmente las órdenes:
          </p>
          <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
            <li><strong>Al ejecutar TP1:</strong> cancela TP2 + cancela SL original + coloca nuevo SL en BE para el remanente.</li>
            <li><strong>Al cerrar posición manualmente:</strong> cancela SL y todos los TPs pendientes antes del cierre.</li>
            <li><strong>Race condition protection:</strong> el TrailingWorker usa dedup Redis (30s TTL) para evitar doble ejecución.</li>
          </ul>
        </div>

        <div className="mb-6">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
            <Activity size={16} className="text-cyan-500" />
            Price Feed Dinámico
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            El monitor de precios ajusta su frecuencia según haya posiciones abiertas:
          </p>
          <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
            <li><strong>Con posiciones abiertas:</strong> polling cada <strong>0.5s</strong> → 4× más rápido que antes.</li>
            <li><strong>Sin posiciones:</strong> polling cada <strong>2s</strong> → ahorro de requests.</li>
            <li>Los precios se publican a Redis pub/sub y el TrailingWorker reacciona inmediatamente.</li>
          </ul>
        </div>

        <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
          <p className="font-semibold">💡 Todas estas features están activas por defecto</p>
          <p className="mt-1">No necesitas configurar nada. Solo el Kill Switch requiere acción manual (pulsa el botón rojo). El resto opera automáticamente en segundo plano.</p>
        </div>
      </>
    ),
  },
  {
    id: 'riesgo',
    title: 'Gestión de Riesgo',
    icon: ShieldAlert,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Gestión de Riesgo</h2>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Stop Loss automático</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          Cada bot configura un <strong>SL inicial</strong> como porcentaje desde el precio de entrada.
          El sistema coloca la orden de stop loss en el exchange automáticamente.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-4 mb-2">Take Profits</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          Puedes configurar múltiples niveles de take profit. Ejemplo:
        </p>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>TP1: +1.5% → cierra 60% de la posición</li>
          <li>TP2: +2.5% → cierra el 40% restante</li>
        </ul>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-4 mb-2">Trailing Stop</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Opcional. Activa un stop loss móvil que sigue el precio cuando alcanzas un beneficio determinado.
          Ej: Al llegar a +1% de profit, el trailing se activa y cierra si el precio retrocede un 0.5%.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-4 mb-2">Breakeven</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Opcional. Cuando el precio alcanza un % de beneficio, el SL se mueve automáticamente al precio de entrada
          (o ligeramente por encima) para asegurar que no pierdas.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-4 mb-2">Circuit breaker</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Además del circuit breaker por tier del modo IA, el sistema también tiene un circuit breaker global:
          si un bot acumula 3 stop losses consecutivos en <strong>cualquier modo</strong>, se pausa automáticamente.
        </p>

        <div className="mt-4 bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 text-xs text-red-700 dark:text-red-300">
          <p className="font-semibold flex items-center gap-2"><AlertTriangle size={14}/> Regla de oro</p>
          <p className="mt-1">Nunca arriesgues más del 2% de tu capital total por operación. Si usas sizing porcentaje, asegúrate de que el stop loss + apalancamiento no exceda ese límite.</p>
        </div>
      </>
    ),
  },
  {
    id: 'gestion-conflictos',
    title: 'Gestión de Conflictos',
    icon: AlertTriangle,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Gestión de Conflictos entre Bots</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
          El sistema gestiona automáticamente las interacciones entre posiciones abiertas en el mismo activo.
          Cada bot configura sus propias reglas en la pestaña <strong>Básico</strong>.
          Las reglas se aplican por <strong>fuente de señal</strong> (IA, Webhook, Indicador), no por tipo de bot.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Reglas principales</h3>
        <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300 mb-4">
          <p><span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-red-100 text-red-700 text-xs font-medium">Mismo sentido</span> Siempre se rechaza. Nunca se permiten dos posiciones LONG (o dos SHORT) en el mismo activo y cuenta, vengan de la fuente que vengan.</p>
          <p><span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-yellow-100 text-yellow-700 text-xs font-medium">Sentido contrario</span> Primero se evalúa si la posición existente está en profit y la tendencia de 15 min le favorece. Si es así, se rechaza automáticamente. Si no, se aplica la configuración específica de la fuente.</p>
          <p><span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 text-xs font-medium">Manual</span> Las operaciones manuales siempre pueden abrir (el frontend muestra confirmación si hay conflictos).</p>
        </div>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Configuración por fuente (sentido contrario)</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          Para cada fuente puedes elegir qué pasa cuando llega una señal contraria a una posición abierta:
        </p>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300 mb-4">
          <li><strong>Cerrar anterior y abrir nueva:</strong> Cierra la posición existente y abre la nueva. Opción por defecto.</li>
          <li><strong>Mantener ambas posiciones:</strong> No cierra nada. Tendrás LONG y SHORT abiertos simultáneamente en el mismo par (hedge).</li>
          <li><strong>Rechazar nueva señal:</strong> No abre nada. La posición existente se mantiene.</li>
        </ul>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Auto-evaluación de profit + tendencia</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          Cuando está activa (por defecto sí), el sistema analiza la posición existente antes de permitir una señal contraria:
        </p>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300 mb-4">
          <li>Obtiene el precio actual y calcula el PnL no realizado.</li>
          <li>Si la posición está en profit, mira las últimas velas de 15 minutos.</li>
          <li>Si la tendencia de 15 min favorece a la posición existente, rechaza la nueva señal automáticamente, independientemente de la configuración por fuente.</li>
          <li>Esto evita que una señal contraria cierre una operación que está yendo bien.</li>
        </ul>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Alerta visual</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          Cuando hay dos o más posiciones abiertas en el mismo símbolo, aparece un
          <AlertTriangle size={14} className="inline mx-1 text-yellow-500" />
          <strong>triángulo amarillo</strong> junto al símbolo en la página de Posiciones.
        </p>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Notificaciones Telegram</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Cada vez que un trade se rechaza por conflicto o una posición se cierra para dar paso a otra,
          recibirás un mensaje en Telegram con los detalles.
        </p>

        <div className="mt-4 bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-4 py-3 text-xs text-yellow-700 dark:text-yellow-300">
          <p className="font-semibold flex items-center gap-2"><AlertTriangle size={14}/> Configuración personalizada</p>
          <p className="mt-1">Puedes ajustar estas reglas desde la pestaña <strong>Básico</strong> de cada bot bajo tu propio riesgo. Las configuraciones por defecto son conservadoras para proteger tu capital.</p>
        </div>
      </>
    ),
  },
  {
    id: 'analytics',
    title: 'Analytics y Optimizer',
    icon: BarChart3,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Analytics y Optimizer</h2>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Analytics</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          La pestaña <strong>Analytics</strong> muestra métricas de rendimiento de todos tus bots:
        </p>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>P&L diario, semanal y mensual</li>
          <li>Win rate por bot y por símbolo</li>
          <li>Drawdown máximo</li>
          <li>Ratio riesgo/beneficio promedio</li>
          <li>Distribución de operaciones LONG vs SHORT</li>
        </ul>

        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-5 mb-2">Optimizer DB</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          El Optimizador analiza el histórico de tus bots y sugiere ajustes a los parámetros:
        </p>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>Ajuste de stop loss según volatilidad del par</li>
          <li>Take profits optimizados por win rate histórico</li>
          <li>Apalancamiento recomendado</li>
          <li>Auto-optimización: aplica cambios automáticamente tras N operaciones</li>
        </ul>

        <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
          <p className="font-semibold">💡 Tip</p>
          <p className="mt-1">Revisa el Optimizer DB al menos una vez por semana. Las sugerencias se basan en datos reales de tus operaciones, no en teoría.</p>
        </div>
      </>
    ),
  },
  {
    id: 'faq',
    title: 'FAQ y Solución de Problemas',
    icon: HelpCircle,
    content: (
      <>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Preguntas Frecuentes</h2>

        <div className="space-y-4">
          <div className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">¿Por qué mi bot no opera aunque tengo señales en el backtest?</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              El backtest muestra <strong>todas</strong> las señales generadas. El bot solo opera las que cumplan sus filtros configurados.
              Verifica: ¿el par está en la watchlist? ¿el tier/status está permitido en el bot? ¿el circuit breaker está abierto?
              ¿ya tiene el máximo de posiciones abiertas?
            </p>
          </div>

          <div className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">¿Puedo tener varios bots para el mismo par?</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Sí. También puedes tener <strong>un solo bot con múltiples fuentes activas</strong> (Webhook + Indicador + IA).
              Si prefieres separar estrategias, crea varios bots con diferentes configuraciones o cuentas.
              Solo asegúrate de no superar el capital disponible si operan en la misma cuenta real.
            </p>
          </div>

          <div className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">¿Qué diferencia hay entre pausar y deshabilitar un bot?</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              <strong>Pausar:</strong> El bot deja de abrir nuevas posiciones pero mantiene las abiertas.
              <strong>Deshabilitar:</strong> El bot no opera en absoluto. Debes pausarlo antes de editar su configuración.
            </p>
          </div>

          <div className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">¿Cómo reseteo un circuit breaker?</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Los circuit breakers se auto-resetean a las 24 horas. Si necesitas resetearlo manualmente,
              pausa el bot, edítalo (cualquier cambio mínimo) y guárdalo. Esto fuerza la recarga del estado.
            </p>
          </div>

          <div className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">¿Puedo operar manualmente mientras tengo bots activos?</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Sí, pero ten cuidado con el capital disponible. Los bots no saben de tus operaciones manuales
              y podrían abrir posiciones que superen tu margen si no gestionas el riesgo global.
            </p>
          </div>

          <div className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">¿El paper trading garantiza los mismos resultados en real?</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              No exactamente. Paper trading usa precios de mercado pero no simula slippage, lag ni liquidez real.
              Sirve para validar la lógica de la estrategia, no para prometer resultados idénticos.
            </p>
          </div>

          <div className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">¿Por qué no puedo incluir BLOCK en los filtros del bot?</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              BLOCK significa 2 o más red flags graves (spread excesivo, volumen anómalo, etc.).
              Es una protección de seguridad del sistema. Nunca se opera BLOCK, ni siquiera en paper trading.
            </p>
          </div>
        </div>

        <div className="mt-6 bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 text-center">
          <Mail className="mx-auto text-slate-400 mb-2" size={24} />
          <p className="text-sm text-slate-600 dark:text-slate-300 font-medium">¿No encuentras lo que buscas?</p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Contacta al administrador de la plataforma o revisa los logs del bot en la pestaña <strong>Actividad</strong>.
          </p>
        </div>
      </>
    ),
  },
]


/* ── Page component ───────────────────────────────────────────── */

export default function DocumentationPage() {
  const [active, setActive] = useState(SECTIONS[0].id)
  const contentRef = useRef(null)

  const activeSection = SECTIONS.find(s => s.id === active)

  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = 0
    }
  }, [active])

  return (
    <div className="flex flex-col md:flex-row gap-6 h-[calc(100vh-6rem)]">
      {/* Sidebar nav */}
      <aside className="md:w-64 shrink-0 flex flex-col gap-1 overflow-y-auto pr-2">
        <h1 className="text-sm font-bold text-slate-900 dark:text-white px-3 py-2">Documentación</h1>
        {SECTIONS.map(section => {
          const isActive = active === section.id
          const Icon = section.icon
          return (
            <button
              key={section.id}
              onClick={() => setActive(section.id)}
              className={cn(
                'flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-sm transition-colors',
                isActive
                  ? 'bg-blue-600/15 text-blue-600 dark:text-blue-400 font-medium'
                  : 'text-slate-600 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-gray-800'
              )}
            >
              <Icon size={16} className="shrink-0" />
              <span className="truncate">{section.title}</span>
              {isActive && <ChevronRight size={14} className="ml-auto shrink-0" />}
            </button>
          )
        })}
      </aside>

      {/* Content area */}
      <div
        ref={contentRef}
        className="flex-1 overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-5 md:p-6"
      >
        {activeSection?.content}
      </div>
    </div>
  )
}
