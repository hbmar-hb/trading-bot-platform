import { useState, useEffect, useRef } from 'react'
import {
  BookOpen, ChevronRight, Zap, Brain, Bot, ShieldAlert,
  TrendingUp, KeyRound, FileText, BarChart3,
  AlertTriangle, CheckCircle2, HelpCircle, Mail, Layers,
  Gauge, Sparkles, GitMerge, Scale, BrainCircuit, ShieldCheck,
  BarChart4, LineChart, Database, Workflow, Fingerprint, Radio,
  FlaskConical, Users, MessageSquare,
} from 'lucide-react'
import { cn } from '@/utils/cn'
import useAuthStore from '@/store/authStore'
import { isDeveloper, isAtLeastAdmin, isAtLeastModerator } from '@/constants/roles'

/* ── Componentes auxiliares ───────────────────────────────────── */

function ExpandableSection({ title, summary, children }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card p-4 border-l-4 border-blue-500 mb-4">
      <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-1 flex items-center gap-2">
        <ChevronRight
          size={16}
          className={cn(
            'text-blue-500 transition-transform',
            open && 'rotate-90'
          )}
        />
        {title}
      </h3>
      <p className="text-sm text-slate-600 dark:text-slate-300">{summary}</p>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="mt-2 text-xs text-blue-600 dark:text-blue-400 hover:underline"
      >
        {open ? 'Leer menos' : 'Leer más'}
      </button>
      {open && (
        <div className="mt-3 text-sm text-slate-600 dark:text-slate-300 space-y-2 border-t border-slate-200 dark:border-slate-700 pt-3">
          {children}
        </div>
      )}
    </div>
  )
}

function ReadMore({ children }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
      >
        {open ? 'Explicar menos' : 'Explicar más'}
      </button>
      {open && (
        <div className="mt-2 text-xs text-slate-500 dark:text-slate-400 space-y-2">
          {children}
        </div>
      )}
    </div>
  )
}

/* ── IA Engine Section (developer only) ───────────────────────── */

function IAEngineSection() {
  const [tab, setTab] = useState('arquitectura')

  const tabs = [
    { id: 'arquitectura',   label: 'Arquitectura' },
    { id: 'scanner',        label: 'Scanner & Señales' },
    { id: 'live',           label: 'Scanner Live' },
    { id: 'dashboard',      label: 'Dashboard & Ranking' },
    { id: 'metricas',       label: 'Métricas' },
    { id: 'configuracion',  label: 'Configuración' },
    { id: 'autonomia',      label: 'Autonomía' },
  ]

  return (
    <>
      <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-3">IA ENGINE</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed mb-4">
        Motor de trading autónomo que combina análisis técnico ICT/SMC con Machine Learning
        para generar, evaluar y ejecutar señales de forma inteligente.
        <span className="block mt-2 p-2 rounded bg-violet-500/10 border border-violet-500/20 text-violet-700 dark:text-violet-300 text-xs">
          <strong>Perfil desarrollador:</strong> esta funcionalidad es experimental y está en desarrollo activo.
          Solo está disponible para el rol <code>developer</code> porque incluye entrenamiento de modelos,
          gates de riesgo avanzados y mecanismos de autonomía que aún no se exponen a usuarios estándar.
        </span>
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
          {/* ── Pipeline de Señales ── */}
          <div className="card p-4 border-l-4 border-violet-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <Workflow size={16} className="text-violet-500" />
              Pipeline de Señales — Ecosistema Completo
            </h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 space-y-2">
              <p><strong>1. Datos OHLCV</strong> (cada 5 min) → Análisis ICT/SMC (<code>confluence_engine.py</code>)</p>
              <p><strong>2. Scoring de confluencia</strong> (0-100 pts) — CHoCH, BOS, OB, FVG, sweep, P/D, killzone. <strong>Pesos adaptativos</strong> por feature importance del ensemble</p>
              <p><strong>3. Calidad heurística</strong> — red flags, volume, spread, sweep, FVGs, RSI/Stoch + Volume Profile POC</p>
              <p><strong>4. Ensemble Híbrido Anti-Fake</strong> — XGBoost + RandomForest + RidgeClassifier + meta-learner LR que asigna <code>ensemble_success_prob</code></p>
              <p><strong>5. Bot Activator</strong> → múltiples gates de riesgo (Kelly, drift, macro, portfolio, rolling beta) → Exchange</p>
              <p><strong>6. Outcome Tracker</strong> — cada 15 min evalúa TP1/SL. El resultado real alimenta el próximo retrain con <strong>sample_weight 5×</strong></p>
            </div>
            <ReadMore>
              <p>
                El pipeline se ejecuta de forma continua en workers Celery. Cada par de la watchlist genera un ciclo
                de análisis que, si supera todos los filtros, persiste la señal en base de datos y notifica a los bots
                suscritos. La clave del sistema es la retroalimentación: cualquier señal ejecutada en el exchange queda
                vinculada a su outcome real, que luego se usa para reentrenar el ensemble.
              </p>
            </ReadMore>
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
            <ReadMore>
              <p>
                El stacking OOF (out-of-fold) es clave para evitar optimismo en las métricas. Cada modelo base genera
                predicciones sobre particiones que no ha visto durante su entrenamiento, y el meta-learner aprende a
                combinar esas predicciones. Esto imita la forma en que el sistema se enfrentará a datos futuros.
              </p>
            </ReadMore>
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

      {tab === 'live' && (
        <div className="space-y-5">
          <div className="card p-4 border-l-4 border-cyan-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <Radio size={16} className="text-cyan-500" />
              Scanner Live — Escaneo en tiempo real
            </h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              La pestaña <strong>Live</strong> muestra qué está haciendo el motor IA ahora mismo.
              Es útil para verificar que el sistema escanea tu watchlist y para entender por qué una señal esperada no llega.
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li><strong>Eventos en vivo:</strong> cada análisis de par publica un evento con el resultado y el motivo de rechazo si aplica.</li>
              <li><strong>KPIs 24h:</strong> pares escaneados, señales generadas, rechazos y tiempo desde el último scan.</li>
              <li><strong>Tips del LLM:</strong> si tienes Ollama configurado, verás consejos breves sobre el estado del mercado.</li>
            </ul>
          </div>

          <div className="card p-4 border-l-4 border-amber-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Cómo interpretar los rechazos</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead><tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300 w-40">Motivo</th>
                  <th className="text-left py-2 font-semibold text-slate-700 dark:text-slate-300">Significado</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {[
                    ['Score insuficiente','La señal no alcanzó el umbral de Confluence Score configurado.'],
                    ['Tier/status no permitido','El bot no acepta ese tier o status.'],
                    ['Circuit breaker abierto','Ese tier está bloqueado temporalmente por pérdidas recientes.'],
                    ['Deployment gate PAUSED','El par/timeframe está pausado por malas métricas.'],
                    ['Macro context','Funding extremo o evento económico cercano bloquea la operativa.'],
                    ['Portfolio guard','La cartera ya está muy expuesta; se reduce o rechaza la posición.'],
                  ].map(([m, s]) => (
                    <tr key={m}><td className="py-2 pr-4 font-medium text-slate-700 dark:text-slate-300">{m}</td><td className="py-2 text-slate-600 dark:text-slate-400">{s}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-emerald-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Flujo recomendado</h3>
            <ol className="list-decimal list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li>Abre <strong>IA → Live</strong>.</li>
              <li>Comprueba que los pares de tu watchlist aparecen escaneados cada ~5 minutos.</li>
              <li>Si no llega una señal esperada, revisa el motivo de rechazo.</li>
              <li>Antes de cambiar la configuración del bot, consulta el Dashboard y Validación.</li>
            </ol>
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

      {tab === 'metricas' && (
        <div className="space-y-5">
          <div className="card p-4 border-l-4 border-violet-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2 flex items-center gap-2">
              <BarChart4 size={16} className="text-violet-500" />
              Métricas del modelo
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead><tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300 w-32">Métrica</th>
                  <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300">Qué mide</th>
                  <th className="text-left py-2 font-semibold text-slate-700 dark:text-slate-300">Qué hacer si baja</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {[
                    ['AUC-ROC','Capacidad de separar señales buenas de malas.','Si cae cerca de 0.50, revisa feature drift o espera más datos.'],
                    ['Accuracy','% de señales clasificadas correctamente.','Úsala junto a AUC; valores muy altos con pocos datos pueden ser sobreajuste.'],
                    ['Muestras','Señales resueltas usadas para entrenar.','Por debajo de 200 el modelo no está activo; se usa el heurístico.'],
                  ].map(([m, d, a]) => (
                    <tr key={m}><td className="py-2 pr-4 font-medium text-slate-700 dark:text-slate-300">{m}</td><td className="py-2 pr-4 text-slate-600 dark:text-slate-400">{d}</td><td className="py-2 text-slate-600 dark:text-slate-400">{a}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-emerald-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Métricas de rendimiento</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead><tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300 w-32">Métrica</th>
                  <th className="text-left py-2 font-semibold text-slate-700 dark:text-slate-300">Interpretación</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {[
                    ['Win Rate señales','% de señales de backtest que tocaron TP1 primero.'],
                    ['Win Rate trades reales','% de trades ejecutados por IA que ganaron. Puede diferir del backtest por slippage y gaps.'],
                    ['PnL acumulado IA real','Beneficio/pérdida de trades reales ejecutados por IA.'],
                    ['Sharpe','Rentabilidad ajustada por volatilidad. >1 aceptable, >2 bueno.'],
                    ['Profit Factor','Ganancias / pérdidas. >1.5 es saludable.'],
                    ['Expectancy','Ganancia esperada por trade. >0 indica expectativa positiva.'],
                    ['Max Drawdown','Caída máxima desde el pico. Si supera tu límite, reduce sizing.'],
                  ].map(([m, i]) => (
                    <tr key={m}><td className="py-2 pr-4 font-medium text-slate-700 dark:text-slate-300">{m}</td><td className="py-2 text-slate-600 dark:text-slate-400">{i}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-amber-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Métricas de salud y calibración</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-600 dark:text-slate-300">
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
                <p className="font-semibold mb-1">Feature Drift</p>
                <p className="text-slate-500 dark:text-slate-400">Indica si el mercado actual se parece poco al de entrenamiento. Valores altos sugieren recalibración.</p>
              </div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
                <p className="font-semibold mb-1">Confidence Decay</p>
                <p className="text-slate-500 dark:text-slate-400">Diferencia entre confianza predicha y win rate real. Alerta de sobreconfianza.</p>
              </div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
                <p className="font-semibold mb-1">Shadow Mode</p>
                <p className="text-slate-500 dark:text-slate-400">Compara modelo live vs candidato. Si el candidato supera en Sharpe, puede promocionarse.</p>
              </div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
                <p className="font-semibold mb-1">Deployment Gate</p>
                <p className="text-slate-500 dark:text-slate-400">HEALTHY = operable; CAUTION = reducir sizing; PAUSED = bloqueado para real.</p>
              </div>
            </div>
          </div>

          <div className="card p-4 border-l-4 border-rose-500">
            <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Embudo de señales</h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
              Representa el recorrido de las señales en 30 días:
            </p>
            <p className="text-sm font-mono text-slate-700 dark:text-slate-300 mb-2">
              Generadas → Evaluadas → Aprobadas → Ejecutadas → Ganadas
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
              <li>Mucha pérdida en <strong>Aprobadas</strong>: filtros o gates muy restrictivos.</li>
              <li>Mucha pérdida en <strong>Ejecutadas</strong>: revisa bots, cuentas de exchange o saldo.</li>
            </ul>
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

/* ── Section builders ─────────────────────────────────────────── */

function BienvenidaSection() {
  return (
    <>
      <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-3">Guía de Usuario — Trading Bot Platform</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed mb-4">
        Esta plataforma te permite operar en exchanges de criptomonedas de forma automatizada usando bots configurables,
        señales de inteligencia artificial (IA) basadas en análisis técnico ICT/SMC, webhooks desde TradingView, trading manual,
        <strong> gráfico avanzado</strong> con indicadores técnicos e <strong>indicadores internos</strong> propietarios.
        Todos estos módulos forman un ecosistema: los indicadores internos y el motor IA son visibles solo para el perfil
        <code>developer</code>, mientras que usuarios estándar pueden aprovechar webhooks, paper trading y gestión de riesgo.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-4 border-l-4 border-yellow-400">
          <Zap className="text-yellow-500 mb-2" size={20} />
          <h3 className="font-semibold text-sm">Automatización</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Crea bots que operan 24/7 sin intervención manual.</p>
          <ReadMore>
            Los bots escuchan señales, evalúan riesgo y ejecutan órdenes en el exchange. Puedes combinar paper trading
            y cuentas reales, y tener varios bots simultáneos con diferentes estrategias.
          </ReadMore>
        </div>
        <div className="card p-4 border-l-4 border-violet-400">
          <Brain className="text-violet-500 mb-2" size={20} />
          <h3 className="font-semibold text-sm">Motor IA</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Scanner ICT+SMC con evaluación de calidad en tiempo real.</p>
          <ReadMore>
            El motor IA es experimental y exclusivo del rol <code>developer</code>. Combina análisis de estructura de mercado
            con un ensemble híbrido de machine learning que aprende de cada trade real.
          </ReadMore>
        </div>
        <div className="card p-4 border-l-4 border-emerald-400">
          <TrendingUp className="text-emerald-500 mb-2" size={20} />
          <h3 className="font-semibold text-sm">Gestión de Riesgo</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Stop loss automático, circuit breaker y sizing dinámico.</p>
          <ReadMore>
            Define cuánto capital arriesgar por operación, activa trailing stop, breakeven y circuit breakers por tier
            o globales. El sistema protege el capital incluso cuando no estás conectado.
          </ReadMore>
        </div>
        <div className="card p-4 border-l-4 border-blue-400">
          <FileText className="text-blue-500 mb-2" size={20} />
          <h3 className="font-semibold text-sm">Paper Trading</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Prueba estrategias sin arriesgar dinero real.</p>
          <ReadMore>
            Las cuentas paper simulan ejecución sobre precios reales. Son ideales para validar configuraciones de bots,
            circuit breakers y webhooks antes de pasar a una cuenta real.
          </ReadMore>
        </div>
        <div className="card p-4 border-l-4 border-cyan-400">
          <LineChart className="text-cyan-500 mb-2" size={20} />
          <h3 className="font-semibold text-sm">Gráfico avanzado</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Visualiza precios, indicadores y estructura de mercado.</p>
          <ReadMore>
            El gráfico permite dibujar herramientas de análisis técnico, superponer zonas de entrada y salida, y
            visualizar señales históricas. Es independiente de la operativa automática.
          </ReadMore>
        </div>
        <div className="card p-4 border-l-4 border-amber-400">
          <Layers className="text-amber-500 mb-2" size={20} />
          <h3 className="font-semibold text-sm">Indicadores internos</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Motores ICT y Quantum Gold propietarios.</p>
          <ReadMore>
            Los indicadores internos son visibles y configurables únicamente por el rol <code>developer</code>. Pueden
            usarse tanto en el gráfico como para activar bots automáticamente.
          </ReadMore>
        </div>
      </div>
    </>
  )
}

function PrimerosPasosSection({ user }) {
  const isDev = isDeveloper(user)
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Primeros pasos</h2>

      <ExpandableSection
        title="1. Accede a tu cuenta por primera vez"
        summary="Usa las credenciales que te proporcionó el administrador y completa el onboarding de seguridad."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Abre la URL de la plataforma e introduce tu email y contraseña temporal.</li>
          <li>Si el administrador activó el cambio forzado, se te pedirá una nueva contraseña inmediatamente. Usa al menos 12 caracteres, mayúsculas, minúsculas y números.</li>
          <li>Configura el 2FA si tu organización lo exige. Ve a <strong>Perfil → Seguridad</strong>, escanea el QR con tu app de autenticación y guarda los códigos de respaldo.</li>
          <li>Revisa las notificaciones Telegram: si hay un bot de alertas configurado, vincula tu usuario siguiendo el enlace del admin.</li>
        </ol>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          No compartas tu contraseña ni tus API keys. El soporte nunca te las pedirá.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="2. Tour del dashboard"
        summary="Conoce las secciones principales antes de crear tu primer bot."
      >
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Dashboard:</strong> equity total, posiciones abiertas, bots activos y alertas del optimizador.</li>
          <li><strong>Bots:</strong> crea, edita, activa o pausa tus estrategias automatizadas.</li>
          <li><strong>Posiciones:</strong> seguimiento en tiempo real de trades abiertos y cerrados.</li>
          <li><strong>Analytics:</strong> métricas de rendimiento, win rate, drawdown y optimizador.</li>
          <li><strong>Exchanges / Paper:</strong> gestión de cuentas reales y cuentas de simulación.</li>
          {isDev && <li><strong>IA Engine:</strong> scanner, backtest, dashboard y ranking (exclusivo developer).</li>}
        </ul>
      </ExpandableSection>

      <ExpandableSection
        title="3. Configura notificaciones Telegram"
        summary="Recibe alertas de trades, conflictos y circuit breakers en tu móvil."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Perfil → Notificaciones</strong>.</li>
          <li>Introduce tu <code>chat_id</code> de Telegram. Si no lo conoces, escribe <code>/start</code> al bot de la plataforma y te lo devolverá.</li>
          <li>Selecciona qué eventos quieres recibir: apertura/cierre de posiciones, rechazos por conflictos, circuit breakers, errores de exchange.</li>
          <li>Pulsa <strong>Probar</strong> para enviar un mensaje de prueba.</li>
        </ol>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Telegram es útil para estar informado sin tener la app abierta. No sustituye la revisión periódica del dashboard.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="4. Crea una cuenta paper paso a paso"
        summary="Practica sin riesgo antes de conectar dinero real."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Paper</strong> en el menú lateral.</li>
          <li>Pulsa <strong>Crear cuenta paper</strong>.</li>
          <li>Introduce un nombre descriptivo (ej. "Prueba Webhook BTC").</li>
          <li>Elige un balance inicial realista (ej. 1,000 USDT).</li>
          <li>Selecciona el exchange de referencia (BingX, Bitunix o Binance) para precios y mercados.</li>
          <li>Guarda y verifica que aparece en la lista con saldo disponible.</li>
        </ol>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Puedes tener varias cuentas paper. Úsalas para separar estrategias y comparar resultados antes de pasar a real.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="5. Crea tu primer bot con webhook de TradingView"
        summary="La forma más directa para usuarios estándar: recibe alertas de TradingView y ejecuta en la plataforma."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Bots → Nuevo bot</strong>.</li>
          <li>En <strong>Básico</strong>: nombre, símbolo (ej. BTCUSDT), timeframe y apalancamiento.</li>
          <li>En <strong>Capital / SL</strong>: elige la cuenta paper recién creada, tipo de sizing y stop loss inicial.</li>
          <li>En <strong>Take Profits</strong>: añade al menos TP1 (recomendado 1.5R).</li>
          <li>En <strong>Activación</strong>: activa solo <strong>Webhook externo</strong>. Copia la URL del endpoint.</li>
          <li>En TradingView, crea una alerta, pega la URL en el campo de webhook y configura el mensaje JSON.</li>
          <li>Guarda el bot y actívalo. Desde ese momento, las alertas de TradingView dispararán el bot.</li>
        </ol>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Empieza en paper al menos una semana. Cuando veas resultados estables y entiendas la gestión de conflictos,
          considera cambiar a una cuenta real con capital reducido.
        </p>
      </ExpandableSection>

      <div className="mt-4 bg-amber-500/5 border border-amber-500/20 rounded-lg px-4 py-3 text-xs text-amber-700 dark:text-amber-300">
        <p className="font-semibold flex items-center gap-2"><AlertTriangle size={14}/> Recomendación inicial</p>
        <p className="mt-1">Siempre empieza con <strong>paper trading</strong>. Valida tu estrategia durante al menos una semana antes de usar dinero real. No copies configuraciones de otros usuarios sin entender el riesgo.</p>
      </div>
    </>
  )
}

function ExchangesSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Cuentas y Exchanges</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        La plataforma se conecta a exchanges de criptomonedas mediante API keys. Actualmente soporta <strong>BingX</strong>, <strong>Bitunix</strong> y <strong>Binance</strong>.
        Todas las operaciones se ejecutan en mercados de futuros perpetuos (USDⓈ-M) salvo configuración explícita de spot.
      </p>

      <ExpandableSection
        title="Guía BingX"
        summary="Cómo crear y configurar una API key en BingX de forma segura."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Inicia sesión en BingX y ve a <strong>Account → API Management</strong> (ruta textual: <em>Mi cuenta &gt; Gestión de API</em>).</li>
          <li>Pulsa <strong>Crear API Key</strong>. Dale un nombre descriptivo, por ejemplo "TradingBot_Plataforma".</li>
          <li>Activa permisos de <strong>lectura</strong> y <strong>trading de futuros</strong>. <span className="text-red-500 font-medium">NO actives retiros (withdrawal).</span></li>
          <li>Activa la restricción por IP y añade la IP pública del servidor donde corre la plataforma. Pregúntale al administrador si no la conoces.</li>
          <li>Completa la verificación 2FA de BingX y copia la <strong>API Key</strong> y el <strong>API Secret</strong>.</li>
          <li>En la plataforma, ve a <strong>Exchanges → Añadir cuenta</strong>, selecciona BingX, pega ambos valores y guarda.</li>
        </ol>
      </ExpandableSection>

      <ExpandableSection
        title="Guía Bitunix"
        summary="Cómo crear y configurar una API key en Bitunix de forma segura."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Inicia sesión en Bitunix y ve a <strong>User Center → API Management</strong>.</li>
          <li>Crea una nueva API key con nombre identificativo (ej. "TradingBot_Plataforma").</li>
          <li>Marca permisos <strong>Read</strong> y <strong>Trade</strong> para futuros. <span className="text-red-500 font-medium">NO actives Withdraw.</span></li>
          <li>Configura la whitelist de IPs con la IP del servidor de la plataforma.</li>
          <li>Verifica por email/SMS y copia la <strong>API Key</strong> y el <strong>API Secret</strong>.</li>
          <li>En la plataforma, selecciona Bitunix, pega los valores, elige futuros y guarda.</li>
        </ol>
      </ExpandableSection>

      <ExpandableSection
        title="Guía Binance"
        summary="Cómo crear y configurar una API key en Binance de forma segura."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Inicia sesión en Binance y ve a <strong>Account → API Management</strong>.</li>
          <li>Pulsa <strong>Create API</strong> y elige <strong>System-generated</strong>.</li>
          <li>Dale un nombre (ej. "TradingBot_Plataforma") y completa la seguridad 2FA.</li>
          <li>En permisos, activa <strong>Enable Reading</strong> y <strong>Enable Futures</strong>. <span className="text-red-500 font-medium">NO actives Withdrawal ni Sub-account.</span></li>
          <li>Restringe por IP: introduce la IP del servidor de la plataforma.</li>
          <li>Copia la <strong>API Key</strong> y el <strong>Secret Key</strong> y pégalos en la plataforma seleccionando Binance.</li>
        </ol>
      </ExpandableSection>

      <div className="card p-4 border-l-4 border-blue-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Tabla comparativa de exchanges</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left py-2 pr-4">Exchange</th>
                <th className="text-left py-2 pr-4">Futuros</th>
                <th className="text-left py-2 pr-4">Liquidez</th>
                <th className="text-left py-2 pr-4">Comisiones (maker/taker)</th>
                <th className="text-left py-2">Notas</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-600 dark:text-slate-300">
              <tr>
                <td className="py-2 pr-4 font-medium">Binance</td>
                <td className="py-2 pr-4">Sí</td>
                <td className="py-2 pr-4">Alta</td>
                <td className="py-2 pr-4">~0.02% / 0.05%</td>
                <td className="py-2">Mayor liquidez y estabilidad API.</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium">BingX</td>
                <td className="py-2 pr-4">Sí</td>
                <td className="py-2 pr-4">Media-Alta</td>
                <td className="py-2 pr-4">~0.02% / 0.05%</td>
                <td className="py-2">Buena para usuarios retail; verifica restricciones regionales.</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium">Bitunix</td>
                <td className="py-2 pr-4">Sí</td>
                <td className="py-2 pr-4">Media</td>
                <td className="py-2 pr-4">~0.02% / 0.06%</td>
                <td className="py-2">Revisar disponibilidad de pares y documentación API.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Las comisiones son aproximadas y dependen de tu nivel de volumen. Revisa siempre la página oficial del exchange.
        </p>
      </div>

      <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
        <p className="font-semibold">🔒 Seguridad</p>
        <p className="mt-1">Crea API keys con permisos de <strong>solo lectura y trading</strong>. No actives retiros (withdrawal). Guarda las keys de forma segura y nunca las compartas. Restringe siempre por IP del servidor.</p>
      </div>

      <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mt-5 mb-2">Problemas comunes</h3>
      <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
        <li><strong>"Invalid API key"</strong>: Verifica que no haya espacios al copiar/pegar.</li>
        <li><strong>"IP restriction"</strong>: Añade la IP del servidor de la plataforma en la configuración de tu exchange.</li>
        <li><strong>"No markets found"</strong>: La cuenta debe tener saldo o haber operado al menos una vez para que el exchange active los mercados.</li>
        <li><strong>"Permiso denegado"</strong>: Revisa que la API key tenga habilitados futuros y trading, no solo lectura.</li>
      </ul>
    </>
  )
}

function PaperTradingSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Paper Trading</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        Paper trading es una simulación. El bot opera como si fuera real, pero no envía dinero al exchange.
        Es la forma más segura de probar estrategias nuevas antes de arriesgar capital.
      </p>

      <ExpandableSection
        title="Crear una cuenta paper"
        summary="Pasos para crear una cuenta de práctica con balance virtual."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Paper</strong> en el menú lateral.</li>
          <li>Pulsa <strong>Crear cuenta paper</strong>.</li>
          <li>Introduce un nombre (ej. "Test IA") y un balance inicial (ej. 10,000 USDT).</li>
          <li>Selecciona el exchange de referencia (para precios y mercados).</li>
          <li>Pulsa <strong>Crear</strong>.</li>
        </ol>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          El balance inicial es virtual. Puedes recargarlo o crear nuevas cuentas desde el panel de Paper.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Asignar paper a un bot"
        summary="Cómo hacer que un bot opere en simulación."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Abre el editor del bot o crea uno nuevo.</li>
          <li>En <strong>Capital / Cuenta</strong> selecciona <strong>📄 Paper</strong>.</li>
          <li>Elige la cuenta paper creada.</li>
          <li>Guarda el bot. Todas las operaciones se registrarán contra el saldo virtual.</li>
        </ol>
      </ExpandableSection>

      <ExpandableSection
        title="Limitaciones del paper trading"
        summary="Entiende qué sí y qué no simula una cuenta paper."
      >
        <ul className="list-disc list-inside space-y-2">
          <li>No simula slippage ni lag del exchange.</li>
          <li>No afecta el order book real.</li>
          <li>Los precios de ejecución pueden diferir ligeramente del real.</li>
          <li>Liquidez y funding no se reproducen exactamente.</li>
        </ul>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Paper trading valida la lógica de la estrategia, no promete resultados idénticos en real. Úsalo para calibrar
          configuraciones y familiarizarte con la plataforma.
        </p>
      </ExpandableSection>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg px-4 py-3">
          <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">✅ Ventajas</p>
          <ul className="list-disc list-inside text-xs text-emerald-600 dark:text-emerald-400 mt-1 space-y-0.5">
            <li>Sin riesgo de pérdida real</li>
            <li>Valida estrategias antes de poner dinero</li>
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
  )
}

function BotsSection({ user }) {
  const isDev = isDeveloper(user)
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Bots y modos de activación</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        Un bot es un operador automatizado que escucha señales y ejecuta órdenes según tu configuración.
        Cada bot opera un único par (símbolo) en un timeframe específico.
      </p>

      <ExpandableSection
        title="Crear un bot"
        summary="Flujo inicial para configurar un nuevo bot."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Bots</strong> y pulsa <strong>Nuevo bot</strong>.</li>
          <li>Rellena el <strong>Básico</strong>: nombre, símbolo, timeframe, apalancamiento.</li>
          <li>Configura <strong>Capital / SL</strong>: tipo de sizing (porcentaje o fijo USDT) y stop loss inicial.</li>
          <li>Define <strong>Take Profits</strong> (opcional pero recomendado).</li>
          <li>En la pestaña <strong>Activación</strong>, elige cómo se disparará.</li>
          <li>Guarda y activa el bot.</li>
        </ol>
      </ExpandableSection>

      <ExpandableSection
        title="Fuentes de activación"
        summary="Cómo puede dispararse un bot."
      >
        <p className="mb-2">
          Cada bot puede tener una o varias fuentes activas simultáneamente. Para usuarios estándar solo está disponible
          la opción de webhook externo.
        </p>
        <div className="space-y-3">
          <div className="card p-4 border-l-4 border-blue-500">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">📡 Webhook externo</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              TradingView u otro sistema envía alertas JSON al endpoint del bot. Tú controlas cuándo se dispara desde fuera.
              Ideal si ya tienes indicadores propios en TradingView.
            </p>
            <ReadMore>
              <ol className="list-decimal list-inside space-y-1">
                <li>En la pestaña <strong>Activación</strong> del bot, copia la URL del webhook.</li>
                <li>En TradingView, crea una alerta sobre tu indicador o condición de precio.</li>
                <li>Pega la URL en el campo <strong>Webhook URL</strong> de la alerta.</li>
                <li>En el mensaje de alerta incluye un JSON con los campos obligatorios.</li>
              </ol>
              <p className="mt-2 font-semibold">Campos obligatorios del JSON:</p>
              <ul className="list-disc list-inside space-y-1">
                <li><code>symbol</code>: debe coincidir con el símbolo del bot (ej. BTCUSDT).</li>
                <li><code>side</code>: <code>buy</code> / <code>sell</code> o <code>long</code> / <code>short</code>.</li>
              </ul>
              <p className="mt-2 font-semibold">Ejemplo de mensaje:</p>
              <pre className="bg-slate-100 dark:bg-slate-800 p-2 rounded text-[10px] overflow-x-auto">
{`{
  "symbol": "BTCUSDT",
  "side": "buy",
  "entry": 65000,
  "sl": 63500,
  "tp1": 68000,
  "comment": "Alerta de ejemplo"
}`}
              </pre>
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                Si no envías <code>entry</code>, <code>sl</code> o <code>tp1</code>, el bot usará los valores configurados en su interfaz.
              </p>
            </ReadMore>
          </div>

          {isDev && (
            <>
              <div className="card p-4 border-l-4 border-emerald-500">
                <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">📊 Señal interna — Indicador</h4>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  El sistema escanea usando el motor ICT o Quantum Gold interno. Dispara cuando detecta confluencia A/A+.
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
            </>
          )}
        </div>
      </ExpandableSection>

      <ExpandableSection
        title="Estados del bot"
        summary="Activo, pausado, deshabilitado y qué significa cada uno."
      >
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Activo:</strong> el bot escucha señales y ejecuta nuevas entradas.</li>
          <li><strong>Pausado:</strong> no abre nuevas posiciones, pero mantiene las abiertas y gestiona SL/TP.</li>
          <li><strong>Deshabilitado:</strong> el bot no opera. Debes editarlo para cambiar configuración.</li>
        </ul>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Pausa un bot antes de editar parámetros críticos. Recuerda que las posiciones abiertas siguen gestionándose
          aunque el bot esté pausado.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Capital y sizing"
        summary="Cómo define el bot cuánto capital usa por operación."
      >
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Porcentaje del balance:</strong> usa un % del balance disponible de la cuenta. Ej. 10% con 1,000 USDT = 100 USDT.</li>
          <li><strong>Cantidad fija (USDT):</strong> usa siempre la misma cantidad nominal. Útil para mantener riesgo constante.</li>
          <li><strong>Apalancamiento:</strong> multiplica la exposición. Un leverage mayor amplifica tanto ganancias como pérdidas.</li>
        </ul>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Regla general: no arriesgar más del 1-2% del capital total por operación. Comprueba que sizing + leverage + SL
          cumplen ese límite.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Take profits y trailing stop"
        summary="Cómo configurar salidas parciales y proteger beneficios."
      >
        <ul className="list-disc list-inside space-y-2">
          <li><strong>TP1:</strong> primer objetivo, suele cerrar 50-70% de la posición.</li>
          <li><strong>TP2:</strong> segundo objetivo para el remanente.</li>
          <li><strong>Breakeven:</strong> al alcanzar +1R, el SL se mueve a entrada + pequeño margen.</li>
          <li><strong>Trailing stop:</strong> sigue el precio favorable y cierra si retrocede un % configurable.</li>
        </ul>
      </ExpandableSection>

      <ExpandableSection
        title="Circuit breaker"
        summary="Seguro automático ante rachas de pérdidas."
      >
        <p className="mb-2">
          Si un bot acumula N stop losses consecutivos, se pausa automáticamente para evitar que una racha negativa
          consuma demasiado capital. El umbral y el tiempo de reset dependen de la configuración del bot.
        </p>
        <ul className="list-disc list-inside space-y-1 text-xs text-slate-500 dark:text-slate-400">
          <li>Los circuit breakers se auto-resetean tras un período configurable (por defecto 24h).</li>
          <li>También puedes forzar el reset editando y guardando el bot.</li>
        </ul>
      </ExpandableSection>

      <ExpandableSection
        title="Gestión de conflictos"
        summary="Cómo se resuelven señales contradictorias en el mismo par."
      >
        <p className="mb-2">
          El sistema no permite dos posiciones del mismo sentido en el mismo activo y cuenta. Para señales contrarias,
          aplica la regla configurada en el bot:
        </p>
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Cerrar anterior y abrir nueva:</strong> cierra la posición existente y abre la opuesta.</li>
          <li><strong>Mantener ambas:</strong> permite hedge (LONG y SHORT simultáneos).</li>
          <li><strong>Rechazar nueva:</strong> conserva la posición existente.</li>
        </ul>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Para la mayoría de usuarios, la gestión de conflictos se aplica principalmente a señales contradictorias
          provenientes de indicadores externos (webhooks). El rol <code>developer</code> tiene acceso a la lógica completa
          incluyendo señales internas e IA.
        </p>
      </ExpandableSection>

      <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
        <p className="font-semibold">💡 Tip</p>
        <p className="mt-1">Puedes tener varios bots para el mismo par con diferentes configuraciones. Ejemplo: uno con webhook en paper (test) y otro en real (producción), siempre que cuides el capital total.</p>
      </div>
    </>
  )
}

function IndicadoresSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Indicadores internos — ICT &amp; Quantum Gold</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
        La plataforma incluye dos motores de señal propios que puedes usar tanto para visualizar en el gráfico
        como para activar bots automáticamente. Esta sección es exclusiva del rol <code>developer</code>.
      </p>

      <div className="rounded-lg bg-blue-500/8 border border-blue-500/20 px-4 py-3 mb-5 text-sm">
        <p className="font-semibold text-blue-400 mb-1">Configuración en gráfico vs. configuración del bot</p>
        <p className="text-slate-600 dark:text-slate-400">
          Son <strong>completamente independientes</strong>. Los parámetros del Panel del gráfico se guardan en tu navegador
          y solo afectan a la visualización. Los parámetros del bot se guardan en la base de datos y son los que usa
          el escáner Celery para generar señales reales.
        </p>
      </div>

      <ExpandableSection
        title="Cómo configurar el indicador en el gráfico"
        summary="Pasos para visualizar ICT o Quantum Gold en el chart."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Gráfico</strong> y selecciona el par y temporalidad.</li>
          <li>En la barra de indicadores (parte superior), activa <strong>ICT</strong> o <strong>⚡ Quantum Gold</strong> con el toggle.</li>
          <li>Haz clic en el icono <strong>⚙</strong> del badge del indicador para abrir el Panel.</li>
          <li>Ajusta los parámetros — los cambios se aplican en tiempo real sobre el gráfico.</li>
          <li>La configuración se guarda automáticamente en el navegador para esa sesión.</li>
        </ol>
      </ExpandableSection>

      <ExpandableSection
        title="Cómo configurar el indicador en un bot"
        summary="Pasos para que un bot use el motor interno como fuente de señal."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Bots → Editar bot</strong>.</li>
          <li>En la pestaña <strong>Activación</strong>, activa el toggle <strong>Indicador interno</strong>.</li>
          <li>Elige el indicador (ICT o Quantum Gold) en el desplegable.</li>
          <li>Aparecerá la sección <strong>Parámetros del indicador</strong> con todos los ajustes configurables.</li>
          <li>Guarda el bot — el escáner usará exactamente esos parámetros.</li>
        </ol>
      </ExpandableSection>

      <ExpandableSection
        title="Parámetros del motor ICT"
        summary="Cómo se calculan las señales ICT y qué ajusta cada parámetro."
      >
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
                ['Tamaño mín. pivot','× 0.3 ATR','El pivot debe tener un tamaño mínimo relativo al ATR. Valores bajos generan más señales; valores altos solo señales grandes.'],
                ['Período ATR','14','Período para el cálculo del Average True Range. 14 es estándar.'],
                ['Modo de entrada','OB o FVG','Define qué estructura confirma la entrada: Order Block, Fair Value Gap, o ambos.'],
                ['Velas a analizar','200','Cantidad de velas históricas que el escáner procesa en cada ciclo.'],
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
          El grade lo determina el tipo de ruptura de estructura.
        </div>
        <ReadMore>
          <p>
            El motor ICT detecta cambios de estructura de mercado (CHoCH/BOS), Order Blocks y Fair Value Gaps. Cuando
            varios de estos elementos se alinean en la misma zona, se genera una señal con un grade que refleja la fuerza
            de la confluencia. El timing de disparo puede ser al cierre de vela o intracandle, según la configuración del bot.
          </p>
        </ReadMore>
      </ExpandableSection>

      <ExpandableSection
        title="Parámetros del motor Quantum Gold"
        summary="Motor multi-indicador porteado desde Pine Script v5."
      >
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
          Requiere la confluencia de <strong>todos</strong> los filtros simultáneamente: tendencia macro, ribbon EMA alineado,
          Supertrend, RSI en zona, y un trigger de entrada. Optimizado para 1h+ en XAUUSD.
        </p>
        <div className="space-y-4">
          <div>
            <p className="text-[11px] font-bold text-slate-500 dark:text-gray-400 uppercase tracking-wide mb-2">EMA Ribbon</p>
            <table className="w-full text-xs border-collapse">
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {[
                  ['EMA Rápida (fast)','9','EMA de corto plazo.'],
                  ['EMA Media (mid)','21','EMA de medio plazo.'],
                  ['EMA Lenta (slow)','50','Para señal LONG se necesita E9 > E21 > E50.'],
                  ['EMA Tendencia (trend)','200','Define la tendencia macro.'],
                ].map(([p,d,desc]) => (
                  <tr key={p}><td className="py-1.5 pr-4 font-medium text-slate-700 dark:text-slate-300 w-44">{p}</td><td className="py-1.5 pr-4 text-blue-500 font-mono w-12">{d}</td><td className="py-1.5 text-slate-500 dark:text-slate-400">{desc}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <p className="text-[11px] font-bold text-slate-500 dark:text-gray-400 uppercase tracking-wide mb-2">RSI — Zonas de señal</p>
            <table className="w-full text-xs border-collapse">
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {[
                  ['RSI zona LONG (mín–máx)','45–75','El RSI debe estar en esta franja para activar señales largas.'],
                  ['RSI zona SHORT (mín–máx)','25–55','Franja RSI para señales cortas.'],
                ].map(([p,d,desc]) => (
                  <tr key={p}><td className="py-1.5 pr-4 font-medium text-slate-700 dark:text-slate-300 w-44">{p}</td><td className="py-1.5 pr-4 text-blue-500 font-mono w-16">{d}</td><td className="py-1.5 text-slate-500 dark:text-slate-400">{desc}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <p className="text-[11px] font-bold text-slate-500 dark:text-gray-400 uppercase tracking-wide mb-2">Supertrend</p>
            <table className="w-full text-xs border-collapse">
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {[
                  ['Período ATR','10','ATR para calcular las bandas del Supertrend.'],
                  ['Factor','3.0','Multiplicador de ATR para las bandas.'],
                ].map(([p,d,desc]) => (
                  <tr key={p}><td className="py-1.5 pr-4 font-medium text-slate-700 dark:text-slate-300 w-44">{p}</td><td className="py-1.5 pr-4 text-blue-500 font-mono w-12">{d}</td><td className="py-1.5 text-slate-500 dark:text-slate-400">{desc}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rounded-lg bg-yellow-900/20 border border-yellow-700/30 px-3 py-2.5 text-xs space-y-1">
            <p className="font-semibold text-yellow-400">Grades Quantum Gold:</p>
            <p className="text-slate-400"><strong className="text-yellow-300">A+</strong> — BB squeeze breakout.</p>
            <p className="text-slate-400"><strong className="text-yellow-300">A</strong> — Cruce EMA 9/21.</p>
            <p className="text-slate-400"><strong className="text-yellow-300">A-</strong> — Cruce RSI 50.</p>
          </div>
        </div>
        <ReadMore>
          <p>
            Quantum Gold exige que todos los filtros estén alineados antes de generar una señal. Esto reduce la frecuencia
            pero mejora la calidad. En timeframes bajos puedes relajar algunos filtros; en timeframes altos es recomendable
            mantener la configuración conservadora.
          </p>
        </ReadMore>
      </ExpandableSection>
    </>
  )
}

function AutonomiaAvanzadaSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Autonomía Avanzada — Futuros Volátiles</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        Estas features protegen tu capital en mercados de alta volatilidad. Actúan automáticamente sin intervención manual.
        Esta sección es exclusiva del rol <code>developer</code>.
      </p>

      <ExpandableSection
        title="Kill Switch Manual"
        summary="Botón de emergencia para cerrar todo en segundos."
      >
        <p className="mb-2">
          Botón de emergencia que cierra <strong>TODAS</strong> las posiciones abiertas y pausa todos los bots en menos de 10 segundos.
          Disponible en el <strong>sidebar</strong> (footer) y en el <strong>Dashboard</strong>.
        </p>
        <ul className="list-disc list-inside space-y-2">
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
      </ExpandableSection>

      <ExpandableSection
        title="Trailing Stop + Breakeven + Post-TP1 Libre"
        summary="Gestión automática del trade una vez abierto."
      >
        <p className="mb-2">
          Los bots IA traen configuración de riesgo por defecto. No necesitas configurar nada manualmente.
        </p>
        <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
          <div className="card p-3 border-l-4 border-emerald-500">
            <p className="font-semibold text-xs">Breakeven Auto</p>
            <p className="text-xs mt-1">Cuando el precio alcanza <strong>+1R</strong>, el SL se mueve automáticamente a entrada + 0.2%. Protege capital en trades que casi ganan pero revierten.</p>
          </div>
          <div className="card p-3 border-l-4 border-blue-500">
            <p className="font-semibold text-xs">Trailing Stop</p>
            <p className="text-xs mt-1">Se activa a <strong>+1.5R</strong>. El SL sigue al precio con un <strong>callback del 1%</strong> desde el máximo alcanzado.</p>
          </div>
          <div className="card p-3 border-l-4 border-violet-500">
            <p className="font-semibold text-xs">Post-TP1 Trailing (40% libre)</p>
            <p className="text-xs mt-1">Al ejecutar TP1 (60% cerrado), el 40% restante cancela TP2, coloca SL en breakeven y activa trailing 0.5%.</p>
          </div>
        </div>
        <ReadMore>
          <p>
            Este mecanismo busca capturar extensiones de 5R-10R sin dejar dinero en la mesa. La parte libre tras TP1
            permite que las ganancias corran mientras se protege el capital inicial.
          </p>
        </ReadMore>
      </ExpandableSection>

      <ExpandableSection
        title="Apalancamiento Dinámico"
        summary="Ajuste automático de leverage según condiciones de mercado."
      >
        <p className="mb-2">
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
            <tr><td className="px-2 py-1.5">Evento macro cercano</td><td className="px-2 py-1.5">Leverage cap = 3×</td></tr>
          </tbody>
        </table>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          El ATR y su historia se calculan en tiempo real desde las 200 velas del scanner. El funding rate se obtiene del exchange vía CCXT.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Portfolio Manager v2"
        summary="Protección agregada a nivel de cartera."
      >
        <p className="mb-2">
          Se evalúa <strong>antes</strong> de abrir cada nueva posición IA.
        </p>
        <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
          <div className="card p-3">
            <p className="font-semibold text-xs">Drawdown Guard</p>
            <p className="text-xs mt-1">Si el portfolio está en drawdown &gt; 10%, reduce sizing 50%. Si &gt; 5%, reduce 25%.</p>
          </div>
          <div className="card p-3">
            <p className="font-semibold text-xs">Correlación BTC-Alts</p>
            <p className="text-xs mt-1">Si BTC cae &gt; 3% en 24h y el bot quiere abrir LONG en una alt, el sizing se reduce 50% automáticamente.</p>
          </div>
          <div className="card p-3">
            <p className="font-semibold text-xs">Límites de exposición</p>
            <p className="text-xs mt-1">Total &lt; 50%, símbolo &lt; 30%, direccional &lt; 40%, alt correlation threshold = 3 alts LONG con BTC bearish.</p>
          </div>
        </div>
      </ExpandableSection>

      <ExpandableSection
        title="OCO Soft y Price Feed Dinámico"
        summary="Gestión manual de OCO y frecuencia de precios adaptativa."
      >
        <p className="mb-2">
          Los exchanges (BingX/Bitunix) no soportan OCO nativo. El sistema implementa OCO "soft" gestionando manualmente las órdenes:
        </p>
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Al ejecutar TP1:</strong> cancela TP2 + cancela SL original + coloca nuevo SL en BE para el remanente.</li>
          <li><strong>Al cerrar posición manualmente:</strong> cancela SL y todos los TPs pendientes antes del cierre.</li>
          <li><strong>Race condition protection:</strong> el TrailingWorker usa dedup Redis (30s TTL) para evitar doble ejecución.</li>
        </ul>
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          El monitor de precios ajusta su frecuencia: <strong>0.5s</strong> con posiciones abiertas y <strong>2s</strong> sin posiciones,
          ahorrando requests y reaccionando rápido cuando es necesario.
        </p>
      </ExpandableSection>

      <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
        <p className="font-semibold">💡 Todas estas features están activas por defecto</p>
        <p className="mt-1">No necesitas configurar nada. Solo el Kill Switch requiere acción manual (pulsa el botón rojo). El resto opera automáticamente en segundo plano.</p>
      </div>
    </>
  )
}

function RiesgoSection({ user }) {
  const isDev = isDeveloper(user)
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Gestión de Riesgo</h2>

      <ExpandableSection
        title="Stop Loss automático"
        summary="Cómo configura el bot su nivel de pérdida máxima por operación."
      >
        <p>
          Cada bot configura un <strong>SL inicial</strong> como porcentaje desde el precio de entrada.
          El sistema coloca la orden de stop loss en el exchange automáticamente. Para LONG, el SL está por debajo de la entrada;
          para SHORT, por encima.
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Un SL demasiado ajustado aumenta la probabilidad de ser tocado por ruido de mercado. Un SL demasiado amplio
          aumenta la pérdida por operación. Ajusta según la volatilidad del par.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Take Profits"
        summary="Salidas parciales para asegurar beneficios."
      >
        <p className="mb-2">
          Puedes configurar múltiples niveles de take profit. Ejemplo:
        </p>
        <ul className="list-disc list-inside space-y-2">
          <li>TP1: +1.5% → cierra 60% de la posición</li>
          <li>TP2: +2.5% → cierra el 40% restante</li>
        </ul>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Las salidas parciales reducen el riesgo de que un trade rentable se revierta completamente.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Trailing Stop"
        summary="Stop loss móvil que sigue el precio favorable."
      >
        <p>
          Opcional. Activa un stop loss móvil que sigue el precio cuando alcanzas un beneficio determinado.
          Ej: Al llegar a +1% de profit, el trailing se activa y cierra si el precio retrocede un 0.5%.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Breakeven"
        summary="Protege el capital cuando el trade se mueve a favor."
      >
        <p>
          Opcional. Cuando el precio alcanza un % de beneficio, el SL se mueve automáticamente al precio de entrada
          (o ligeramente por encima) para asegurar que no pierdas.
        </p>
      </ExpandableSection>

      <ExpandableSection
        title="Circuit breaker"
        summary="Seguro ante rachas de pérdidas."
      >
        <p className="mb-2">
          {isDev ? (
            <>
              Además del circuit breaker por tier del modo IA, el sistema también tiene un circuit breaker global:
              si un bot acumula 3 stop losses consecutivos en <strong>cualquier modo</strong>, se pausa automáticamente.
            </>
          ) : (
            <>
              El sistema incluye un circuit breaker global: si un bot acumula 3 stop losses consecutivos,
              se pausa automáticamente. En tu perfil, la gestión de conflictos se aplica principalmente a
              señales contradictorias provenientes de indicadores externos (webhooks), ya que no tienes acceso
              a bots IA ni señales internas.
            </>
          )}
        </p>
      </ExpandableSection>

      <div className="mt-4 bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 text-xs text-red-700 dark:text-red-300">
        <p className="font-semibold flex items-center gap-2"><AlertTriangle size={14}/> Regla de oro</p>
        <p className="mt-1">Nunca arriesgues más del 2% de tu capital total por operación. Si usas sizing porcentaje, asegúrate de que el stop loss + apalancamiento no exceda ese límite.</p>
      </div>
    </>
  )
}

function GestionConflictosSection({ user }) {
  const isDev = isDeveloper(user)
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Gestión de Conflictos entre Bots</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        El sistema gestiona automáticamente las interacciones entre posiciones abiertas en el mismo activo.
        Cada bot configura sus propias reglas en la pestaña <strong>Básico</strong>.
      </p>

      {!isDev && (
        <div className="mb-4 p-3 rounded bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-300">
          En tu perfil, la gestión de conflictos está configurada principalmente para señales contradictorias
          provenientes de indicadores externos (TradingView/webhooks), ya que no tienes acceso a bots IA ni señales internas.
        </div>
      )}

      <ExpandableSection
        title="Reglas principales"
        summary="Sentido igual, contrario y operaciones manuales."
      >
        <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
          <p><span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-red-100 text-red-700 text-xs font-medium">Mismo sentido</span> Siempre se rechaza. Nunca se permiten dos posiciones LONG (o dos SHORT) en el mismo activo y cuenta.</p>
          <p><span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-yellow-100 text-yellow-700 text-xs font-medium">Sentido contrario</span> Primero se evalúa si la posición existente está en profit y la tendencia de 15 min le favorece. Si es así, se rechaza automáticamente.</p>
          <p><span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 text-xs font-medium">Manual</span> Las operaciones manuales siempre pueden abrir (el frontend muestra confirmación si hay conflictos).</p>
        </div>
      </ExpandableSection>

      <ExpandableSection
        title="Configuración por fuente (sentido contrario)"
        summary="Qué hacer cuando llega una señal contraria a una posición abierta."
      >
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Cerrar anterior y abrir nueva:</strong> Cierra la posición existente y abre la nueva. Opción por defecto.</li>
          <li><strong>Mantener ambas posiciones:</strong> No cierra nada. Tendrás LONG y SHORT abiertos simultáneamente en el mismo par (hedge).</li>
          <li><strong>Rechazar nueva señal:</strong> No abre nada. La posición existente se mantiene.</li>
        </ul>
      </ExpandableSection>

      <ExpandableSection
        title="Auto-evaluación de profit + tendencia"
        summary="El sistema analiza la posición existente antes de permitir una señal contraria."
      >
        <ul className="list-disc list-inside space-y-2">
          <li>Obtiene el precio actual y calcula el PnL no realizado.</li>
          <li>Si la posición está en profit, mira las últimas velas de 15 minutos.</li>
          <li>Si la tendencia de 15 min favorece a la posición existente, rechaza la nueva señal automáticamente.</li>
          <li>Esto evita que una señal contraria cierre una operación que está yendo bien.</li>
        </ul>
      </ExpandableSection>

      <ExpandableSection
        title="Alerta visual y notificaciones"
        summary="Cómo detectar conflictos en la interfaz."
      >
        <p className="mb-2">
          Cuando hay dos o más posiciones abiertas en el mismo símbolo, aparece un
          <AlertTriangle size={14} className="inline mx-1 text-yellow-500" />
          <strong>triángulo amarillo</strong> junto al símbolo en la página de Posiciones.
        </p>
        <p>
          Cada vez que un trade se rechaza por conflicto o una posición se cierra para dar paso a otra,
          recibirás un mensaje en Telegram con los detalles.
        </p>
      </ExpandableSection>

      <div className="mt-4 bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-4 py-3 text-xs text-yellow-700 dark:text-yellow-300">
        <p className="font-semibold flex items-center gap-2"><AlertTriangle size={14}/> Configuración personalizada</p>
        <p className="mt-1">Puedes ajustar estas reglas desde la pestaña <strong>Básico</strong> de cada bot bajo tu propio riesgo. Las configuraciones por defecto son conservadoras para proteger tu capital.</p>
      </div>
    </>
  )
}

function AnalyticsSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Analytics</h2>

      <ExpandableSection
        title="Métricas de Analytics"
        summary="Qué mide cada KPI y cómo interpretarlo."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left py-2 pr-4 font-semibold text-slate-700 dark:text-slate-300 w-32">Métrica</th>
                <th className="text-left py-2 font-semibold text-slate-700 dark:text-slate-300">Descripción</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-600 dark:text-slate-400">
              {[
                ['P&L','Profit & Loss: ganancias o pérdidas acumuladas en un período. Positivo = rentable.'],
                ['Win Rate','% de operaciones ganadoras sobre el total. Alto WR no garantiza rentabilidad si las pérdidas son grandes.'],
                ['Max Drawdown','Caída máxima desde el pico de equity. Mide el riesgo de la estrategia.'],
                ['R/R promedio','Ratio riesgo/beneficio medio de las operaciones. >1 indica que las ganancias superan las pérdidas.'],
                ['LONG/SHORT','Distribución de operaciones por dirección. Ayuda a detectar sesgos de mercado.'],
                ['Profit Factor','Ganancias brutas / pérdidas brutas. >1.5 suele considerarse saludable.'],
                ['Expectancy','Ganancia/pérdida esperada por trade. >0 indica expectativa positiva.'],
                ['Sharpe','Rentabilidad ajustada por volatilidad. >1 aceptable, >2 bueno.'],
              ].map(([m, d]) => (
                <tr key={m}><td className="py-2 pr-4 font-medium text-slate-700 dark:text-slate-300">{m}</td><td className="py-2">{d}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </ExpandableSection>

      <ExpandableSection
        title="Cómo usar Analytics para mejorar"
        summary="Flujo recomendado de revisión semanal."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Revisa el P&L diario y busca días anómalos (noticias, errores de configuración).</li>
          <li>Compara win rate por bot y por símbolo para detectar qué estrategias funcionan mejor.</li>
          <li>Identifica si el drawdown supera tu límite personal de riesgo.</li>
          <li>Revisa la distribución LONG/SHORT para detectar sesgos direccionales.</li>
          <li>Documenta los cambios que hagas en la configuración para poder revertirlos.</li>
        </ol>
      </ExpandableSection>

      <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
        <p className="font-semibold">💡 Tip</p>
        <p className="mt-1">Revisa Analytics al menos una vez por semana. Las métricas se basan en datos reales de tus operaciones.</p>
      </div>
    </>
  )
}

function OptimizerDBSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Optimizer DB</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        El Optimizador analiza el histórico de tus bots y sugiere ajustes a los parámetros. Esta funcionalidad es exclusiva del rol <code>developer</code>.
      </p>

      <ExpandableSection
        title="Qué analiza el Optimizer"
        summary="Sugerencias basadas en datos reales."
      >
        <ul className="list-disc list-inside space-y-2">
          <li><strong>Ajuste de stop loss:</strong> sugiere ampliar o reducir el SL según la volatilidad histórica del par.</li>
          <li><strong>Take profits optimizados:</strong> recomienda niveles de TP basados en el win rate histórico.</li>
          <li><strong>Apalancamiento recomendado:</strong> ajusta el leverage según el drawdown y la volatilidad.</li>
          <li><strong>Auto-optimización:</strong> aplica cambios automáticamente tras N operaciones si está habilitada.</li>
        </ul>
      </ExpandableSection>

      <ExpandableSection
        title="Flujo recomendado"
        summary="Cómo usar el Optimizer de forma segura."
      >
        <ol className="list-decimal list-inside space-y-2">
          <li>Ve a <strong>Optimizer DB</strong> en el menú lateral.</li>
          <li>Selecciona el bot y el período de análisis (mínimo recomendado 30 días).</li>
          <li>Revisa las sugerencias: cambios de SL, TP, leverage y confirmación.</li>
          <li>Si activas auto-optimización, el sistema aplicará cambios graduales y te notificará por Telegram.</li>
          <li>Después de cada cambio, monitoriza el comportamiento durante al menos una semana.</li>
        </ol>
      </ExpandableSection>

      <ExpandableSection
        title="Riesgos de la auto-optimización"
        summary="Por qué revisar antes de aplicar."
      >
        <p className="mb-2">
          La auto-optimización tiene riesgos: un mercado en cambio de régimen puede hacer que parámetros óptimos en el
          pasado sean perjudiciales en el futuro.
        </p>
        <ul className="list-disc list-inside space-y-2">
          <li>No apliques sugerencias que no entiendas.</li>
          <li>Empieza con bots en paper trading antes de aplicar a real.</li>
          <li>Mantén un registro de los cambios para poder revertirlos.</li>
        </ul>
      </ExpandableSection>

      <div className="mt-4 bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
        <p className="font-semibold">💡 Tip</p>
        <p className="mt-1">Revisa el Optimizer DB al menos una vez por semana. Las sugerencias se basan en datos reales de tus operaciones, no en teoría.</p>
      </div>
    </>
  )
}

function MonteCarloSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Monte Carlo</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        El módulo Monte Carlo te permite diseñar estrategias propias, backtestearlas y evaluar su robustez
        mediante simulaciones estadísticas. Esta sección es exclusiva del rol <code>developer</code>; para otros perfiles
        el módulo está desactivado/oculto.
      </p>

      <div className="card p-4 border-l-4 border-violet-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Crear una estrategia</h3>
        <ol className="list-decimal list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>Ve a <strong>Monte Carlo</strong> en el menú lateral.</li>
          <li>Pulsa <strong>Nueva estrategia</strong>.</li>
          <li>Configura par, timeframe, condiciones de entrada/salida, stop loss, take profits y sizing.</li>
          <li>Guarda la estrategia.</li>
        </ol>
      </div>

      <div className="card p-4 border-l-4 border-emerald-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Backtest</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          El backtest ejecuta la estrategia sobre datos históricos y genera:
        </p>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>Curva de equity.</li>
          <li>Lista de trades con entrada, salida, PnL y duración.</li>
          <li>Métricas: win rate, profit factor, Sharpe, max drawdown y expectancy.</li>
        </ul>
      </div>

      <div className="card p-4 border-l-4 border-blue-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Simulaciones</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-600 dark:text-slate-300">
          <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
            <p className="font-semibold mb-1">Return shuffle</p>
            <p className="text-slate-500 dark:text-slate-400">Reordena los retornos para comprobar si el resultado depende de un orden concreto.</p>
          </div>
          <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
            <p className="font-semibold mb-1">Bootstrap</p>
            <p className="text-slate-500 dark:text-slate-400">Remuestrea trades para estimar intervalos de confianza.</p>
          </div>
          <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
            <p className="font-semibold mb-1">Perturbación de parámetros</p>
            <p className="text-slate-500 dark:text-slate-400">Cambia ligeramente los parámetros para detectar fragilidad.</p>
          </div>
          <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-3">
            <p className="font-semibold mb-1">Equity path</p>
            <p className="text-slate-500 dark:text-slate-400">Genera múltiples caminos posibles del capital.</p>
          </div>
        </div>
      </div>

      <div className="card p-4 border-l-4 border-amber-500">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Score de Monte Carlo</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          El score resume rentabilidad, riesgo y robustez en un solo valor. No garantiza resultados futuros,
          pero ayuda a descartar estrategias frágiles antes de arriesgar capital real.
        </p>
        <div className="bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 text-xs text-red-700 dark:text-red-300">
          <p className="font-semibold">⚠️ Recomendación</p>
          <p className="mt-1">Pasa siempre la estrategia a paper trading después de Monte Carlo, incluso si el backtest y las simulaciones son muy positivos.</p>
        </div>
      </div>
    </>
  )
}

function ChatSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Chat interno</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        La plataforma incluye un chat para comunicarte con otros usuarios del sistema en tiempo real.
        Actualmente es una funcionalidad interna/exclusiva de desarrollo.
      </p>

      <div className="card p-4 border-l-4 border-blue-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Salas</h3>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>Salas públicas por tema (operativa, alertas, soporte).</li>
          <li>Salas privadas entre dos usuarios.</li>
          <li>Mensajes en tiempo real mediante WebSocket.</li>
        </ul>
      </div>

      <div className="card p-4 border-l-4 border-violet-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Menciones y reacciones</h3>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>Usa <strong>@usuario</strong> para llamar la atención de alguien.</li>
          <li>Reacciona a mensajes con emojis.</li>
          <li>Personaliza el color de tu fuente y usa GIFs.</li>
        </ul>
      </div>

      <div className="bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-4 py-3 text-xs text-yellow-700 dark:text-yellow-300">
        <p className="font-semibold">💡 Tip</p>
        <p className="mt-1">El chat es una herramienta de comunicación, no un canal de señales de trading. Las decisiones de operativa deben basarse en tus bots y análisis.</p>
      </div>
    </>
  )
}

function RolesSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Roles y permisos</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        La plataforma distingue cuatro roles. Actualmente <strong>rol1</strong>, <strong>moderator</strong> y <strong>admin</strong>
        comparten el mismo acceso al menú y funcionalidades; la distinción queda reservada para el rol <code>developer</code>,
        que puede ver las secciones experimentales y de administración técnica.
      </p>

      <div className="space-y-3">
        <div className="card p-4 border-l-4 border-slate-400">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-1">rol1, moderator y admin — Acceso estándar</h3>
          <ul className="list-disc list-inside text-xs text-slate-600 dark:text-slate-300">
            <li>Dashboard, bots con webhook externo (TradingView), trading manual.</li>
            <li>Gestión de cuentas de exchange y posiciones.</li>
            <li>Analytics básico.</li>
            <li>Documentación pública y FAQ.</li>
            <li>No pueden usar el motor IA, indicadores internos, Monte Carlo, Optimizer DB, Paper Trading, Chat, gestión de usuarios, administración del sistema ni el asistente IA.</li>
          </ul>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
            <em>Nota: por el momento, moderator y admin comparten el mismo acceso que rol1.</em>
          </p>
        </div>
        <div className="card p-4 border-l-4 border-violet-500">
          <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-1">developer — Desarrollador / Superadmin</h3>
          <ul className="list-disc list-inside text-xs text-slate-600 dark:text-slate-300">
            <li>Todo lo de <strong>admin</strong>.</li>
            <li>IA Engine, indicadores internos, autonomía avanzada, Monte Carlo.</li>
            <li>Administración del sistema y asistente de IA con Ollama.</li>
            <li>Acceso a documentación técnica extendida y funcionalidades experimentales.</li>
          </ul>
        </div>
      </div>
    </>
  )
}

function AdminSystemSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Administración del Sistema</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        Panel exclusivo para el rol <code>developer</code> que permite revisar la salud general de la plataforma y generar diagnósticos.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-slate-600 dark:text-slate-300 mb-4">
        <div className="card p-3 border-l-4 border-emerald-500">
          <p className="font-semibold text-xs mb-1">Infraestructura</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">Estado de Docker, PostgreSQL, Redis, Nginx y uso de recursos.</p>
        </div>
        <div className="card p-3 border-l-4 border-blue-500">
          <p className="font-semibold text-xs mb-1">Celery</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">Workers activos, tareas en cola y latencia del broker.</p>
        </div>
        <div className="card p-3 border-l-4 border-violet-500">
          <p className="font-semibold text-xs mb-1">Modelos ML</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">Último entrenamiento, AUC, accuracy, muestras y shadow mode.</p>
        </div>
        <div className="card p-3 border-l-4 border-amber-500">
          <p className="font-semibold text-xs mb-1">Exchange</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">Conectividad y salud de las cuentas de exchange configuradas.</p>
        </div>
      </div>

      <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
        <p className="font-semibold">💡 Uso</p>
        <p className="mt-1">Puedes ejecutar checks individuales, descargar logs compartibles y revisar el historial del monitor de shadow mode. Úsalo ante cualquier comportamiento anómalo de la plataforma.</p>
      </div>
    </>
  )
}

function AsistenteSection() {
  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Asistente de IA</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
        El Asistente es un widget flotante que responde preguntas sobre el uso de la plataforma mediante un modelo de lenguaje local.
        Es exclusivo del perfil <code>developer</code> y requiere Ollama.
      </p>

      <div className="card p-4 border-l-4 border-violet-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Qué puede hacer</h3>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>Explicar conceptos: tiers, circuit breaker, R, backtest, deployment gate.</li>
          <li>Guiarte en la creación de bots y configuración del motor IA.</li>
          <li>Responder dudas sobre métricas y paneles.</li>
        </ul>
      </div>

      <div className="card p-4 border-l-4 border-amber-500 mb-4">
        <h3 className="font-semibold text-sm text-slate-800 dark:text-slate-200 mb-2">Requisitos</h3>
        <ul className="list-disc list-inside space-y-1 text-sm text-slate-600 dark:text-slate-300">
          <li>Una instancia de <strong>Ollama</strong> accesible desde los contenedores.</li>
          <li>El servicio opcional <strong>ollama-bridge</strong> configurado en <code>docker-compose.yml</code>.</li>
          <li>Si Ollama no está disponible, el widget no responde o muestra error.</li>
        </ul>
      </div>

      <div className="bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 text-xs text-red-700 dark:text-red-300">
        <p className="font-semibold">⚠️ Limitaciones</p>
        <p className="mt-1">El asistente no tiene acceso a tus posiciones, balances ni datos de mercado en tiempo real. No proporciona recomendaciones de inversión. Verifica siempre la configuración antes de operar.</p>
      </div>
    </>
  )
}

function FAQSection({ user }) {
  const isDev = isDeveloper(user)

  const allQuestions = [
    {
      q: '¿Cómo conecto TradingView con la plataforma?',
      a: 'Copia la URL de webhook de tu bot (pestaña Activación), crea una alerta en TradingView, pega la URL en el campo Webhook URL y usa un JSON con symbol y side. Empieza en paper trading para validar.',
      devOnly: false,
    },
    {
      q: '¿Cómo configuro API keys de forma segura?',
      a: 'Crea la API key en tu exchange con permisos de lectura y trading de futuros, NUNCA retiros. Restringe por IP del servidor de la plataforma y pega key/secret en Exchanges → Añadir cuenta.',
      devOnly: false,
    },
    {
      q: '¿Qué es el paper trading y por qué empezar ahí?',
      a: 'Paper trading simula operaciones con precios reales pero sin arriesgar dinero. Es la forma más segura de validar una estrategia antes de pasar a una cuenta real.',
      devOnly: false,
    },
    {
      q: '¿Por qué mi bot no opera aunque tengo señales en el backtest?',
      a: 'El backtest muestra todas las señales generadas. El bot solo opera las que cumplan sus filtros configurados. Verifica: ¿el par está en la watchlist? ¿el tier/status está permitido en el bot? ¿el circuit breaker está abierto? ¿ya tiene el máximo de posiciones abiertas?',
      devOnly: false,
    },
    {
      q: '¿Puedo tener varios bots para el mismo par?',
      a: 'Sí. También puedes tener un solo bot con múltiples fuentes activas. Si prefieres separar estrategias, crea varios bots con diferentes configuraciones o cuentas. Solo asegúrate de no superar el capital disponible si operan en la misma cuenta real.',
      devOnly: false,
    },
    {
      q: '¿Qué diferencia hay entre pausar y deshabilitar un bot?',
      a: 'Pausar: el bot deja de abrir nuevas posiciones pero mantiene las abiertas. Deshabilitar: el bot no opera en absoluto. Debes pausarlo antes de editar su configuración.',
      devOnly: false,
    },
    {
      q: '¿Cómo reseteo un circuit breaker?',
      a: 'Los circuit breakers se auto-resetean a las 24 horas. Si necesitas resetearlo manualmente, pausa el bot, edítalo (cualquier cambio mínimo) y guárdalo. Esto fuerza la recarga del estado.',
      devOnly: false,
    },
    {
      q: '¿Puedo operar manualmente mientras tengo bots activos?',
      a: 'Sí, pero ten cuidado con el capital disponible. Los bots no saben de tus operaciones manuales y podrían abrir posiciones que superen tu margen si no gestionas el riesgo global.',
      devOnly: false,
    },
    {
      q: '¿El paper trading garantiza los mismos resultados en real?',
      a: 'No exactamente. Paper trading usa precios de mercado pero no simula slippage, lag ni liquidez real. Sirve para validar la lógica de la estrategia, no para prometer resultados idénticos.',
      devOnly: false,
    },
    {
      q: '¿Por qué no puedo incluir BLOCK en los filtros del bot?',
      a: 'BLOCK significa 2 o más red flags graves (spread excesivo, volumen anómalo, etc.). Es una protección de seguridad del sistema. Nunca se opera BLOCK, ni siquiera en paper trading.',
      devOnly: true,
    },
    {
      q: '¿Qué es Scanner Live?',
      a: 'Es una pestaña de IA Engine que muestra el escaneo del mercado en tiempo real: pares analizados, señales generadas, rechazos y KPIs de las últimas 24h. Úsala para entender por qué no llegan señales.',
      devOnly: true,
    },
    {
      q: '¿Por qué un par aparece como PAUSED?',
      a: 'El Deployment Gate pausa un par/timeframe cuando sus métricas son muy malas (win rate bajo, drawdown alto o feature drift). Es una protección automática para bots reales.',
      devOnly: true,
    },
    {
      q: '¿Qué significa un AUC de 0.5?',
      a: 'Que el modelo no distingue mejor que el azar. Suele pasar con pocas muestras o tras un cambio de régimen de mercado. Revisa el feature drift y espera más señales antes de confiar ciegamente.',
      devOnly: true,
    },
    {
      q: '¿Quién puede usar Monte Carlo?',
      a: 'El módulo Monte Carlo es exclusivo del rol developer. Otros perfiles no tienen acceso.',
      devOnly: true,
    },
    {
      q: '¿El asistente de IA puede ver mis posiciones?',
      a: 'No. Responde preguntas generales sobre el uso de la plataforma, pero no accede a posiciones, balances ni datos de mercado en tiempo real. No da recomendaciones de inversión.',
      devOnly: true,
    },
    {
      q: '¿Por qué no veo el menú de IA Engine?',
      a: 'El motor IA, los indicadores internos, Monte Carlo y el asistente están restringidos al rol developer. Los perfiles estándar usan webhooks, paper trading y gestión de riesgo.',
      devOnly: true,
    },
  ]

  const visibleQuestions = allQuestions.filter(q => !q.devOnly || isDev)

  return (
    <>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-3">Preguntas Frecuentes</h2>

      <div className="space-y-4">
        {visibleQuestions.map((item, idx) => (
          <div key={idx} className="card p-4">
            <h4 className="font-semibold text-sm text-slate-800 dark:text-slate-200">{item.q}</h4>
            <ReadMore>
              <p>{item.a}</p>
            </ReadMore>
          </div>
        ))}
      </div>

      <div className="mt-6 bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 text-center">
        <Mail className="mx-auto text-slate-400 mb-2" size={24} />
        <p className="text-sm text-slate-600 dark:text-slate-300 font-medium">¿No encuentras lo que buscas?</p>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Contacta al administrador de la plataforma o revisa los logs del bot en la pestaña <strong>Actividad</strong>.
        </p>
      </div>
    </>
  )
}

/* ── Section data (role-aware) ────────────────────────────────── */

function getSections(user) {
  const always = [
    {
      id: 'bienvenida',
      title: 'Bienvenida',
      icon: BookOpen,
      content: <BienvenidaSection />,
    },
    {
      id: 'primeros-pasos',
      title: 'Primeros pasos',
      icon: CheckCircle2,
      content: <PrimerosPasosSection user={user} />,
    },
    {
      id: 'exchanges',
      title: 'Cuentas y Exchanges',
      icon: KeyRound,
      content: <ExchangesSection />,
    },
    {
      id: 'bots',
      title: 'Bots y modos de activación',
      icon: Bot,
      content: <BotsSection user={user} />,
    },
    {
      id: 'riesgo',
      title: 'Gestión de Riesgo',
      icon: ShieldAlert,
      content: <RiesgoSection user={user} />,
    },
    {
      id: 'gestion-conflictos',
      title: 'Gestión de Conflictos',
      icon: AlertTriangle,
      content: <GestionConflictosSection user={user} />,
    },
    {
      id: 'analytics',
      title: 'Analytics',
      icon: BarChart3,
      content: <AnalyticsSection />,
    },
    {
      id: 'faq',
      title: 'FAQ y Solución de Problemas',
      icon: HelpCircle,
      content: <FAQSection user={user} />,
    },
  ]

  if (!isDeveloper(user)) {
    return always
  }

  return [
    ...always,
    {
      id: 'paper-trading',
      title: 'Paper Trading',
      icon: FileText,
      content: <PaperTradingSection />,
    },
    {
      id: 'optimizer-db',
      title: 'Optimizer DB',
      icon: Zap,
      content: <OptimizerDBSection />,
    },
    {
      id: 'ia-engine',
      title: 'IA ENGINE',
      icon: Brain,
      content: <IAEngineSection />,
    },
    {
      id: 'indicadores',
      title: 'Indicadores internos',
      icon: Layers,
      content: <IndicadoresSection />,
    },
    {
      id: 'autonomia-avanzada',
      title: 'Autonomía Avanzada',
      icon: Gauge,
      content: <AutonomiaAvanzadaSection />,
    },
    {
      id: 'monte-carlo',
      title: 'Monte Carlo',
      icon: FlaskConical,
      content: <MonteCarloSection />,
    },
    {
      id: 'chat',
      title: 'Chat',
      icon: MessageSquare,
      content: <ChatSection />,
    },
    {
      id: 'roles',
      title: 'Roles y permisos',
      icon: Users,
      content: <RolesSection />,
    },
    {
      id: 'admin-system',
      title: 'Administración del Sistema',
      icon: ShieldCheck,
      content: <AdminSystemSection />,
    },
    {
      id: 'asistente',
      title: 'Asistente de IA',
      icon: Sparkles,
      content: <AsistenteSection />,
    },
  ]
}


/* ── Page component ───────────────────────────────────────────── */

export default function DocumentationPage() {
  const user = useAuthStore(s => s.user)
  const sections = getSections(user)
  const [active, setActive] = useState(sections[0].id)
  const contentRef = useRef(null)

  const activeSection = sections.find(s => s.id === active)

  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = 0
    }
  }, [active])

  // Si cambia el usuario y la sección activa ya no existe, volver a la primera
  useEffect(() => {
    if (!sections.find(s => s.id === active)) {
      setActive(sections[0].id)
    }
  }, [user, sections, active])

  return (
    <div className="flex flex-col md:flex-row gap-6 h-[calc(100vh-6rem)]">
      {/* Sidebar nav */}
      <aside className="md:w-64 shrink-0 flex flex-col gap-1 overflow-y-auto pr-2">
        <h1 className="text-sm font-bold text-slate-900 dark:text-white px-3 py-2">Documentación</h1>
        {sections.map(section => {
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
