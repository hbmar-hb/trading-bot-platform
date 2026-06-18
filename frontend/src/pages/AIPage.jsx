import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer, Legend,
  ComposedChart, Line,
} from 'recharts'
import {
  Ban, BarChart2, Bot, Brain, CheckCircle2, ChevronDown, ChevronUp, Clock, Database, Filter, Globe,
  Plus, RefreshCw, ScanLine, ShieldAlert, SlidersHorizontal, Sparkles, TrendingDown, TrendingUp, Trophy,
  X, XCircle, Zap,
} from 'lucide-react'
import { aiService }             from '@/services/aiService'
import { botsService }             from '@/services/bots'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import { cn } from '@/utils/cn'
const AIDashboardTab = lazy(() => import('./AIDashboardTab'))
const AIEngineControlTab = lazy(() => import('./AIEngineControlTab'))
const IALiveScannerTab = lazy(() => import('@/components/IAEngine/IALiveScannerTab'))
import SignalDiagnosisModal from '@/components/Analytics/SignalDiagnosisModal'
import useAuthStore from '@/store/authStore'
import IAMissionControlTab from '@/components/IAEngine/IAMissionControlTab'

// ── Constants ─────────────────────────────────────────────────────────────────

const TIMEFRAMES    = ['auto', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w']
const WATCHLIST_KEY  = 'ai_watchlist_v2'
const AUTO_KEY       = 'ai_autorefresh_v1'
const LAST_SCAN_KEY  = 'ai_last_scan_v1'
const AUTO_INTERVAL  = 5 * 60 * 1000

const DEFAULT_WATCHLIST = [
  { symbol: 'BTCUSDT',  timeframe: '1h' },
  { symbol: 'ETHUSDT',  timeframe: '1h' },
  { symbol: 'SOLUSDT',  timeframe: '4h' },
  { symbol: 'BNBUSDT',  timeframe: '4h' },
  { symbol: 'XRPUSDT',  timeframe: '1h' },
]

const loadLS = (k, fb) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fb } catch { return fb } }
const saveLS = (k, v)  => { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} }

const baseOf   = (sym) => sym.replace(/USDT$|USDC$/, '').replace(/^1000/, '')
const fmtPrice = (n)   => n == null ? '—' : n >= 1 ? n.toFixed(n >= 100 ? 2 : 4) : n.toPrecision(4)
const fmtQty   = (n)   => n == null ? '—' : n >= 1 ? n.toFixed(2) : n.toFixed(6).replace(/\.?0+$/, '')

// ── Small display components ──────────────────────────────────────────────────

function BiasTag({ bias }) {
  if (!bias) return null
  const bull = bias === 'bull'
  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide',
      bull
        ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400'
        : 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
    )}>
      {bull ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
      {bull ? 'Bull' : 'Bear'}
    </span>
  )
}

function ConfBadge({ confidence }) {
  const map = {
    HIGH:   'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400',
    MEDIUM: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400',
    LOW:    'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400',
  }
  return (
    <span className={cn(
      'text-[10px] font-bold px-1.5 py-0.5 rounded',
      map[confidence] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400',
    )}>
      {confidence}
    </span>
  )
}

function OutcomeBadge({ outcome }) {
  if (outcome === 'SUCCESS') return <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400"><CheckCircle2 size={11} />TP1</span>
  if (outcome === 'FAILURE') return <span className="flex items-center gap-1 text-xs text-red-600 dark:text-red-400"><XCircle size={11} />SL</span>
  if (outcome === 'EXPIRED') return <span className="flex items-center gap-1 text-xs text-slate-400"><Clock size={11} />Exp.</span>
  return <span className="flex items-center gap-1 text-xs text-blue-500 dark:text-blue-400"><Clock size={11} />Pdte.</span>
}

function ScoreMeter({ score }) {
  const pct = Math.min(100, Math.max(0, score ?? 0))
  const cls = pct >= 60
    ? 'text-green-600 dark:text-green-400'
    : pct >= 40
      ? 'text-yellow-600 dark:text-yellow-400'
      : 'text-orange-600 dark:text-orange-400'
  const bar = pct >= 60 ? '#16a34a' : pct >= 40 ? '#ca8a04' : '#ea580c'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: bar }} />
      </div>
      <span className={cn('text-xs font-bold tabular-nums w-10 text-right', cls)}>
        {pct.toFixed(0)}/100
      </span>
    </div>
  )
}

function QualityBadge({ tier, status, successProbability, mlStatus }) {
  const tierMap = {
    STRONG:   'bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-500/20 dark:text-emerald-400 dark:border-emerald-500/30',
    MODERATE: 'bg-yellow-100 text-yellow-700 border-yellow-300 dark:bg-yellow-500/20 dark:text-yellow-400 dark:border-yellow-500/30',
    WEAK:     'bg-orange-100 text-orange-700 border-orange-300 dark:bg-orange-500/20 dark:text-orange-400 dark:border-orange-500/30',
  }
  const effectiveStatus = mlStatus || status || 'CLEAR'
  const statusMap = {
    CLEAR:   'text-emerald-600 dark:text-emerald-400',
    CAUTION: 'text-amber-600 dark:text-amber-400',
    BLOCK:   'text-red-600 dark:text-red-400',
  }
  const statusLabel = { CLEAR: 'CLEAR', CAUTION: '⚠ CAUTION', BLOCK: '✕ BLOCK' }
  const hasML = successProbability != null
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {tier && (
        <span className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded border tracking-wide', tierMap[tier])}>
          {tier}
        </span>
      )}
      {effectiveStatus && (
        <span className={cn('text-[9px] font-semibold', statusMap[effectiveStatus])}>
          {hasML ? 'ML ' : ''}{statusLabel[effectiveStatus]}
          {hasML && (
            <span className="ml-1 opacity-70">({(successProbability * 100).toFixed(0)}% success)</span>
          )}
        </span>
      )}
    </div>
  )
}

// ── Signal day row (used inside SymbolModal) ──────────────────────────────────

function SignalDayRow({ sig, onViewDiagnosis }) {
  const isLong = sig.direction === 'long'
  const time   = new Date(sig.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const confs  = sig.components ? Object.values(sig.components) : []
  const showDiagnosis = sig.anti_fake_status === 'BLOCK' || sig.anti_fake_status === 'CAUTION'
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'

  return (
    <div className="flex items-start gap-3 bg-white dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 rounded-lg px-3 py-2 text-xs">
      <span className="text-slate-500 dark:text-slate-500 tabular-nums shrink-0 mt-0.5">{time}</span>
      <span className={cn(
        'flex items-center gap-0.5 font-bold shrink-0 mt-0.5',
        isLong ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400',
      )}>
        {isLong ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
        {sig.direction.toUpperCase()}
      </span>
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="w-24 shrink-0"><ScoreMeter score={sig.score} /></div>
          {sig.quality_tier && (
            <span className={cn(
              'text-[9px] font-bold px-1 py-0.5 rounded border shrink-0',
              sig.quality_tier === 'STRONG'   ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
              sig.quality_tier === 'MODERATE' ? 'bg-yellow-500/20  text-yellow-400  border-yellow-500/30' :
                                               'bg-orange-500/20  text-orange-400  border-orange-500/30',
            )}>
              {sig.quality_tier}
            </span>
          )}
          {(sig.ml_status || sig.anti_fake_status) && (
            <span className={cn(
              'text-[9px] font-semibold shrink-0',
              (sig.ml_status || sig.anti_fake_status) === 'CLEAR'   ? 'text-emerald-600 dark:text-emerald-400' :
              (sig.ml_status || sig.anti_fake_status) === 'CAUTION' ? 'text-yellow-600 dark:text-yellow-400'  :
                                                   'text-red-600 dark:text-red-400',
            )}>
              {sig.success_probability != null ? 'ML ' : 'XGB '}{(sig.ml_status || sig.anti_fake_status)}
              {sig.success_probability != null && (
                <span className="opacity-70"> ({(sig.success_probability * 100).toFixed(0)}%)</span>
              )}
            </span>
          )}
        </div>
        {confs.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {confs.map((c, i) => (
              <span key={i} className="text-[10px] bg-blue-100 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 px-1.5 py-0.5 rounded">
                {c}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="shrink-0 mt-0.5 flex items-center gap-2">
        {showDiagnosis && onViewDiagnosis && (
          <button
            onClick={(e) => { e.stopPropagation(); onViewDiagnosis(sig) }}
            className="text-[10px] text-blue-500 hover:text-blue-400 font-medium transition-colors"
            title={isAdmin ? "Ver diagnóstico IA" : "Ver contexto del par"}
          >
            {isAdmin ? 'IA' : 'Ctx'}
          </button>
        )}
        {sig.pnl_pct != null ? (
          <span className={cn('font-bold text-xs', sig.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400')}>
            {sig.pnl_pct >= 0 ? '+' : ''}{sig.pnl_pct.toFixed(2)}%
          </span>
        ) : (
          <OutcomeBadge outcome={sig.outcome} />
        )}
      </div>
    </div>
  )
}

// ── Symbol recommendation (AI config advice + Apply) ──────────────────────────

function SymbolRecommendation({ symbol, timeframe, aiBots }) {
  const [rec, setRec] = useState(null)
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    aiService.optimalConfig(symbol, timeframe)
      .then(r => {
        if (cancelled) return
        setRec(r.data ?? null)
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [symbol, timeframe])

  const bot = useMemo(() => {
    // Normalize symbol "XRPUSDT" → match bot.symbol "XRP/USDT:USDT"
    const normalized = symbol.replace(/\/([^:]+):[^:]+$/, '$1').replace('/', '')
    return aiBots.find(b => {
      const botNorm = b.symbol.replace(/\/([^:]+):[^:]+$/, '$1').replace('/', '')
      return botNorm === normalized
    })
  }, [aiBots, symbol])

  const handleApply = async () => {
    if (!bot || !rec?.config) return
    setApplying(true)
    try {
      const cfg = rec.config
      const payload = {
        ai_signal_config: {
          min_score: cfg.min_score,
          max_concurrent: cfg.max_concurrent,
          allowed_tiers: cfg.allowed_tiers,
          allowed_statuses: cfg.allowed_statuses,
          sizing_multipliers: cfg.sizing_multipliers,
          circuit_breaker_thresholds: cfg.circuit_breaker_thresholds,
          portfolio_limits: cfg.portfolio_limits,
        },
        leverage: rec.recommendations?.recommended_leverage ?? bot.leverage,
      }
      await botsService.update(bot.id, payload)
      setToast({ type: 'success', msg: `Config aplicada a ${bot.bot_name}` })
    } catch (err) {
      setToast({ type: 'error', msg: err?.response?.data?.detail || 'Error al aplicar config' })
    } finally {
      setApplying(false)
      setTimeout(() => setToast(null), 4000)
    }
  }

  if (loading) {
    return <div className="py-10 text-center text-sm text-slate-400">Analizando estadísticas…</div>
  }

  if (!rec) {
    return <div className="py-10 text-center text-sm text-slate-400">Sin datos suficientes para recomendar</div>
  }

  const cfg = rec.config
  const recs = rec.recommendations || {}
  const sizing = cfg.sizing_multipliers || {}

  return (
    <div className="space-y-4">
      {/* Toast */}
      {toast && (
        <div className={cn(
          'px-4 py-2 rounded text-xs font-medium',
          toast.type === 'success' ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20' : 'bg-red-500/10 text-red-600 border border-red-500/20'
        )}>
          {toast.msg}
        </div>
      )}

      {/* Rationale */}
      <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3">
        <p className="text-xs text-blue-700 dark:text-blue-300">
          <span className="font-semibold">🧠 Análisis:</span> {recs.rationale || 'Configuración basada en estadísticas históricas'}
        </p>
      </div>

      {/* Cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Capital suggestion */}
        <div className="card p-3">
          <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">% Capital sugerido</h4>
          <div className="space-y-1.5 text-xs">
            {['STRONG','MODERATE','WEAK'].map(tier => {
              const val = Math.round((sizing[tier] ?? 0) * 100)
              return (
                <div key={tier} className="flex justify-between items-center">
                  <span className="text-slate-600 dark:text-slate-300">{tier}</span>
                  <span className={cn('font-bold', val >= 80 ? 'text-emerald-500' : val >= 40 ? 'text-yellow-500' : 'text-red-500')}>
                    {val}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        {/* Leverage */}
        <div className="card p-3">
          <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">Apalancamiento sugerido</h4>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold text-slate-800 dark:text-white">{recs.recommended_leverage ?? '—'}x</span>
            {recs.recommended_leverage && (
              <span className={cn(
                'text-[10px] px-1.5 py-0.5 rounded font-bold',
                recs.recommended_leverage >= 7 ? 'bg-red-500/10 text-red-600' :
                recs.recommended_leverage >= 5 ? 'bg-yellow-500/10 text-yellow-600' :
                'bg-emerald-500/10 text-emerald-600'
              )}>
                {recs.recommended_leverage >= 7 ? 'ALTO' : recs.recommended_leverage >= 5 ? 'MEDIO' : 'CONSERVADOR'}
              </span>
            )}
          </div>
          <p className="text-[10px] text-slate-400 mt-1">Basado en volatilidad (ATR) del par</p>
        </div>

        {/* Timeframe */}
        <div className="card p-3">
          <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">Timeframe óptimo</h4>
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-slate-800 dark:text-white">{recs.recommended_timeframe ?? timeframe}</span>
            {recs.recommended_timeframe && recs.recommended_timeframe !== timeframe && (
              <span className="text-[10px] bg-yellow-500/10 text-yellow-600 px-1.5 py-0.5 rounded font-bold">
                Cambiar desde {timeframe}
              </span>
            )}
          </div>
          <p className="text-[10px] text-slate-400 mt-1">Mayor ratio WR × volumen de señales</p>
        </div>

        {/* HTF */}
        <div className="card p-3">
          <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">HTF sugerido</h4>
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-slate-800 dark:text-white">{recs.recommended_htf ?? '—'}</span>
          </div>
          <p className="text-[10px] text-slate-400 mt-1">Confirmación de sesgo en timeframe superior</p>
        </div>

        {/* Score */}
        <div className="card p-3">
          <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">Score mínimo sugerido</h4>
          <span className="text-lg font-bold text-slate-800 dark:text-white">{cfg.min_score}</span>
          <p className="text-[10px] text-slate-400 mt-1">Umbral que maximiza win rate histórico</p>
        </div>

        {/* Tiers / Status */}
        <div className="card p-3">
          <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">Tiers / Status recomendados</h4>
          <div className="flex flex-wrap gap-1 mt-1">
            {(cfg.allowed_tiers || []).map(t => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-600 font-medium">{t}</span>
            ))}
            {(cfg.allowed_statuses || []).map(s => (
              <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 font-medium">{s}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Apply section */}
      <div className="border-t border-slate-200 dark:border-slate-700 pt-3">
        {bot ? (
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-slate-500 dark:text-slate-400">
              Bot detectado: <strong className="text-slate-700 dark:text-slate-200">{bot.bot_name}</strong>
            </div>
            <button
              onClick={handleApply}
              disabled={applying}
              className={cn(
                'flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold transition-colors',
                applying
                  ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                  : 'bg-violet-600 text-white hover:bg-violet-700'
              )}
            >
              <Sparkles size={14} />
              {applying ? 'Aplicando…' : 'Apply to Bot'}
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-slate-500 dark:text-slate-400">
              No hay bot IA configurado para {symbol}. Crea uno primero para aplicar esta config.
            </div>
            <a
              href="/bots/new"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-slate-200 text-slate-700 hover:bg-slate-300 transition-colors"
            >
              <Plus size={14} /> Crear bot
            </a>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Symbol rejections (detailed list + summary) ───────────────────────────────

function SymbolRejections({ symbol }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)
  const [timeframeFilter, setTimeframeFilter] = useState('')
  const [reasonFilter, setReasonFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const limit = 25

  const load = useCallback(() => {
    setLoading(true)
    const params = { days, limit, offset }
    if (timeframeFilter) params.timeframe = timeframeFilter
    if (reasonFilter) params.reason = reasonFilter
    aiService.symbolRejections(symbol, params)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [symbol, days, timeframeFilter, reasonFilter, offset])

  useEffect(() => {
    setOffset(0)
  }, [symbol, days, timeframeFilter, reasonFilter])

  useEffect(() => {
    load()
  }, [load])

  if (loading) {
    return <div className="py-10 text-center text-sm text-slate-400">Cargando rechazos…</div>
  }

  if (!data || !data.summary || data.summary.total === 0) {
    return (
      <div className="py-10 text-center text-sm text-slate-400">
        No hay señales rechazadas para {baseOf(symbol)} en los últimos {days} días
      </div>
    )
  }

  const summary = data.summary || {}
  const detail = data.detail || {}
  const items = detail.items || []
  const totalItems = detail.total || 0
  const byReason = summary.by_reason || {}

  const reasonLabels = {
    stale: 'Señal caducada',
    tier: 'Tier no permitido',
    status: 'Status anti-fake',
    score: 'Score bajo',
    concurrent: 'Máx. posiciones',
    stacking: 'No apilar',
    slippage: 'Slippage alto',
    macro: 'Contexto macro',
    regime: 'Régimen de mercado',
    drift: 'Drift estadístico',
    kelly: 'Kelly sizing',
    portfolio: 'Límite portfolio',
    look_ahead: 'Look-ahead bias',
    wf_rejected: 'WFV rechazado',
    optimal_config_missing: 'Sin config óptima',
    paper_divergence: 'Divergencia paper',
    oi_cvd: 'OI/CVD contrario',
    session_funding: 'Funding/sesión',
    rolling_beta: 'Beta rolling',
    unknown: 'Desconocido',
  }

  const maxCount = Math.max(...Object.values(byReason).map(r => r.count), 1)

  return (
    <div className="space-y-5">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-slate-500 dark:text-slate-400">Período:</span>
        {[7, 30, 90].map(d => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={cn(
              'text-[11px] px-2 py-1 rounded border font-medium transition-colors',
              days === d
                ? 'bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-500/20 dark:text-blue-400 dark:border-blue-700'
                : 'bg-white text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
            )}
          >
            {d}d
          </button>
        ))}
        <span className="text-xs text-slate-500 dark:text-slate-400 ml-2">Timeframe:</span>
        <select
          value={timeframeFilter}
          onChange={e => setTimeframeFilter(e.target.value)}
          className="text-[11px] px-2 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
        >
          <option value="">Todos</option>
          {TIMEFRAMES.filter(t => t !== 'auto').map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <span className="text-xs text-slate-500 dark:text-slate-400">Razón:</span>
        <select
          value={reasonFilter}
          onChange={e => setReasonFilter(e.target.value)}
          className="text-[11px] px-2 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
        >
          <option value="">Todas</option>
          {Object.entries(reasonLabels).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <span className="ml-auto text-xs text-slate-400">
          {summary.total} rechazos / {items.length} mostrados
        </span>
      </div>

      {/* Summary card */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
          <Ban size={14} className="text-red-500" />
          Resumen de rechazos ({days}d)
          {summary.top_filters?.length > 0 && (
            <span className="ml-auto text-[10px] bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400 px-2 py-0.5 rounded-full">
              {summary.top_filters.length} filtro(s) agresivo(s)
            </span>
          )}
        </h4>
        <div className="space-y-2">
          {Object.entries(byReason).sort((a, b) => b[1].count - a[1].count).map(([reason, info]) => {
            const pct = Math.round((info.count / maxCount) * 100)
            const winPct = info.would_win_pct
            return (
              <div key={reason} className="flex items-center gap-3">
                <div className="w-32 text-[11px] text-slate-600 dark:text-slate-400 truncate">
                  {reasonLabels[reason] || reason}
                </div>
                <div className="flex-1 h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={cn(
                      'h-full rounded-full',
                      winPct != null && winPct > 60 ? 'bg-amber-500' : 'bg-red-400',
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <div className="w-8 text-[11px] font-medium text-slate-700 dark:text-slate-300 text-right">
                  {info.count}
                </div>
                {winPct != null && (
                  <div className={cn(
                    'w-14 text-[10px] text-right',
                    winPct > 60 ? 'text-amber-600 dark:text-amber-400 font-semibold' : 'text-slate-500 dark:text-slate-500',
                  )}>
                    {winPct}% gan.
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Detail table */}
      {items.length > 0 && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
            <h4 className="text-xs font-semibold text-slate-600 dark:text-slate-300">
              Detalle de rechazos
            </h4>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400">
                  <th className="px-3 py-2 text-left font-medium">Fecha</th>
                  <th className="px-3 py-2 text-left font-medium">TF</th>
                  <th className="px-3 py-2 text-left font-medium">Dir</th>
                  <th className="px-3 py-2 text-left font-medium">Score</th>
                  <th className="px-3 py-2 text-left font-medium">Tier</th>
                  <th className="px-3 py-2 text-left font-medium">Anti-fake</th>
                  <th className="px-3 py-2 text-left font-medium">Razón</th>
                  <th className="px-3 py-2 text-left font-medium">¿Habría ganado?</th>
                  <th className="px-3 py-2 text-left font-medium">Similar (+24h)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.map(item => (
                  <tr key={item.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-400 whitespace-nowrap">
                      {item.rejected_at ? new Date(item.rejected_at).toLocaleString('es-ES', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-400">{item.timeframe}</td>
                    <td className={cn(
                      'px-3 py-2 font-medium uppercase',
                      item.direction === 'long' ? 'text-green-600' : 'text-red-600',
                    )}>
                      {item.direction}
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-400">{item.score?.toFixed(1) ?? '—'}</td>
                    <td className="px-3 py-2">
                      <span className={cn(
                        'px-1.5 py-0.5 rounded text-[10px] font-medium',
                        item.quality_tier === 'STRONG' ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400' :
                        item.quality_tier === 'MODERATE' ? 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400' :
                        'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400',
                      )}>
                        {item.quality_tier || '—'}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={cn(
                        'px-1.5 py-0.5 rounded text-[10px] font-medium',
                        item.anti_fake_status === 'CLEAR' ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400' :
                        item.anti_fake_status === 'CAUTION' ? 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400' :
                        item.anti_fake_status === 'BLOCK' ? 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400' :
                        'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400',
                      )}>
                        {item.anti_fake_status || '—'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-400">
                      {reasonLabels[item.rejection_reason] || item.rejection_reason}
                    </td>
                    <td className="px-3 py-2">
                      {item.would_have_been_winner === null ? (
                        <span className="text-slate-400">Pendiente</span>
                      ) : item.would_have_been_winner ? (
                        <span className="text-green-600 font-medium">Sí</span>
                      ) : (
                        <span className="text-red-500 font-medium">No</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {item.similar_signal_outcome ? (
                        <span className={cn(
                          item.similar_signal_outcome === 'SUCCESS' ? 'text-green-600' : 'text-red-500',
                        )}>
                          {item.similar_signal_outcome} ({item.similar_signal_pnl_pct?.toFixed(2) ?? '—'}%)
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalItems > limit && (
            <div className="flex items-center justify-between px-4 py-2 border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                className="text-[11px] px-2 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 disabled:opacity-40"
              >
                ← Anterior
              </button>
              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                {offset + 1} – {Math.min(offset + limit, totalItems)} de {totalItems}
              </span>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= totalItems}
                className="text-[11px] px-2 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 disabled:opacity-40"
              >
                Siguiente →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Symbol real stats (executed IA trades) ────────────────────────────────────

function SymbolRealStats({ symbol }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState('total')

  useEffect(() => {
    setLoading(true)
    aiService.symbolRealStats(symbol, mode)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [symbol, mode])

  if (loading) {
    return <div className="py-10 text-center text-sm text-slate-400">Cargando métricas…</div>
  }

  if (!data) {
    return <div className="py-10 text-center text-sm text-slate-400">Sin datos de trades para {baseOf(symbol)}</div>
  }

  const rt = data.real_trades || {}
  const sig = data.ai_signals || {}
  const openPos = data.open_positions || []

  const modeLabels = {
    real: 'reales',
    paper: 'paper',
    total: 'totales',
  }

  const Stat = ({ label, value, color }) => {
    const colorCls =
      color === 'green' ? 'text-green-600 dark:text-green-400' :
      color === 'red'   ? 'text-red-600 dark:text-red-400' :
      'text-slate-800 dark:text-white'
    return (
      <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
        <div className={cn('text-lg font-bold', colorCls)}>{value}</div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</div>
      </div>
    )
  }

  const hasData = rt.total > 0 || openPos.length > 0

  return (
    <div className="space-y-4">
      {/* Mode selector */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500 dark:text-slate-400">Modo:</span>
        {['total', 'real', 'paper'].map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              'text-[11px] px-2 py-1 rounded border font-medium transition-colors',
              mode === m
                ? 'bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-500/20 dark:text-blue-400 dark:border-blue-700'
                : 'bg-white text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
            )}
          >
            {m === 'total' ? 'Total' : m === 'real' ? 'Real' : 'Paper'}
          </button>
        ))}
      </div>

      {!hasData && (
        <div className="py-8 text-center">
          <p className="text-sm text-slate-500 dark:text-slate-400">Aún no hay trades IA {modeLabels[mode]} ejecutados para <strong>{baseOf(symbol)}</strong></p>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">Las operaciones aparecerán aquí cuando el bot IA ejecute señales en este par.</p>
        </div>
      )}

      {/* Open positions */}
      {openPos.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-2 flex items-center gap-2">
            <Zap size={14} className="text-amber-500" />
            Posiciones IA abiertas ({openPos.length})
          </h4>
          <div className="space-y-2">
            {openPos.map(p => (
              <div key={p.id} className="flex items-center justify-between bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 rounded-lg px-3 py-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className={cn('font-bold uppercase', p.side === 'long' ? 'text-green-600' : 'text-red-600')}>{p.side}</span>
                  <span className="text-slate-500">@ ${p.entry_price?.toFixed(4) ?? '—'}</span>
                  <span className="text-slate-400">qty {fmtQty(p.quantity)}</span>
                  {p.is_paper && (
                    <span className="text-[9px] bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400 px-1 rounded">PAPER</span>
                  )}
                </div>
                <span className={cn('font-bold', (p.unrealized_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600')}>
                  {p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl?.toFixed(4) ?? '0.0000'} USDT
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trades stats */}
      {rt.total > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-2 flex items-center gap-2">
            <Trophy size={14} className="text-violet-500" />
            Trades IA {modeLabels[mode]}
          </h4>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
            <Stat label="Total trades" value={rt.total ?? 0} />
            <Stat label="Win Rate" value={`${rt.win_rate ?? 0}%`} color={rt.win_rate >= 50 ? 'green' : 'red'} />
            <Stat label="Ganados" value={rt.winners ?? 0} color="green" />
            <Stat label="Perdidos" value={rt.losers ?? 0} color="red" />
            <Stat label="PnL total" value={`${rt.total_pnl >= 0 ? '+' : ''}${rt.total_pnl?.toFixed(2) ?? '0.00'}`} color={rt.total_pnl >= 0 ? 'green' : 'red'} />
            <Stat label="Avg PnL" value={`${rt.avg_pnl >= 0 ? '+' : ''}${rt.avg_pnl?.toFixed(2) ?? '0.00'}`} color={rt.avg_pnl >= 0 ? 'green' : 'red'} />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-3">
            <Stat label="Mejor trade" value={`+${rt.best_trade?.toFixed(4) ?? '0.0000'}`} color="green" />
            <Stat label="Peor trade" value={`${rt.worst_trade?.toFixed(4) ?? '0.0000'}`} color="red" />
            <Stat label="Duración media" value={rt.avg_duration_minutes != null ? `${Math.round(rt.avg_duration_minutes)}m` : '—'} />
          </div>
        </div>
      )}

      {/* AI signals — visually separated as backtest/simulated data */}
      {sig.total > 0 && (
        <div className="bg-slate-50/60 dark:bg-slate-800/30 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-2 flex items-center gap-2">
            <Brain size={14} className="text-blue-400" />
            Señales AI (backtest / simulado)
            <span className="text-[10px] font-normal text-slate-400 dark:text-slate-500 ml-auto">
              No son trades reales ejecutados
            </span>
          </h4>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
            <Stat label="Total señales" value={sig.total ?? 0} />
            <Stat label="Resueltas" value={sig.resolved ?? 0} />
            <Stat label="WR señales" value={`${sig.win_rate ?? 0}%`} color={sig.win_rate >= 50 ? 'green' : 'red'} />
            <Stat label="Score medio" value={sig.avg_score?.toFixed(1) ?? '—'} />
            <Stat label="Bars medio" value={sig.avg_bars?.toFixed(1) ?? '—'} />
            <Stat label="Mejor señal" value={`${sig.best_signal_pnl_pct >= 0 ? '+' : ''}${sig.best_signal_pnl_pct?.toFixed(2) ?? '0.00'}%`} color="green" />
          </div>
        </div>
      )}
    </div>
  )
}

// ── Symbol detail panel (expanded below grid) ─────────────────────────────────

function SymbolDetailPanel({ symbol, timeframe, onClose, aiBots }) {
  const [tab, setTab] = useState('detail')
  const [chartData, setChartData] = useState(null)
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)
  const chartRef = useRef(null)

  // Load data
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setChartData(null)
    setSignals([])

    Promise.all([
      aiService.ictAnalysis(symbol, timeframe),
      aiService.listSignals(100, symbol),
    ])
      .then(([ictRes, sigRes]) => {
        if (cancelled) return
        setChartData(ictRes.data ?? null)
        setSignals(Array.isArray(sigRes.data) ? sigRes.data : [])
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [symbol, timeframe])

  // Render chart
  useEffect(() => {
    if (!chartData?.candles?.length || !chartRef.current) return
    let chart
    let raf
    const el = chartRef.current

    const init = () => {
      if (!el.offsetWidth || !el.offsetHeight) {
        raf = requestAnimationFrame(init)
        return
      }
      try {
        chart = createChart(el, {
        width: el.offsetWidth || 600,
        height: el.offsetHeight || 400,
        layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
        grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
        crosshair: { mode: 1 },
        timeScale: { timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#1e293b' },
      })
      const series = chart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
      })
      series.setData(chartData.candles)
      const ctx = chartData.context ?? {}
      if (ctx.break_level) {
        try { series.createPriceLine({ price: ctx.break_level, color: '#3b82f6', lineWidth: 1, lineStyle: 2, title: ctx.last_break ?? 'Break' }) } catch {}
      }
      if (ctx.active_ob) {
        try { series.createPriceLine({ price: ctx.active_ob.top, color: '#a855f7', lineWidth: 1, lineStyle: 0, title: 'OB↑' }) } catch {}
        try { series.createPriceLine({ price: ctx.active_ob.bottom, color: '#a855f7', lineWidth: 1, lineStyle: 0, title: 'OB↓' }) } catch {}
      }
      ;(ctx.fvg_zones ?? []).forEach((fvg) => {
        const color = fvg.kind === 'bull' ? '#22c55e' : '#ef4444'
        try { series.createPriceLine({ price: fvg.top, color, lineWidth: 1, lineStyle: 3, title: '' }) } catch {}
        try { series.createPriceLine({ price: fvg.bottom, color, lineWidth: 1, lineStyle: 3, title: '' }) } catch {}
      })
      ;(ctx.eq_highs ?? []).forEach((p) => {
        try { series.createPriceLine({ price: p, color: '#f59e0b', lineWidth: 1, lineStyle: 3, title: '' }) } catch {}
      })
      ;(ctx.eq_lows ?? []).forEach((p) => {
        try { series.createPriceLine({ price: p, color: '#06b6d4', lineWidth: 1, lineStyle: 3, title: '' }) } catch {}
      })
      } catch {}
    }

    raf = requestAnimationFrame(init)
    return () => {
      if (raf) cancelAnimationFrame(raf)
      try { chart?.remove() } catch {}
    }
  }, [chartData])

  return (
    <div className="mt-4 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
        <div className="flex items-center gap-3">
          <span className="font-bold text-slate-900 dark:text-white">{baseOf(symbol)}</span>
          <span className="text-xs text-slate-500 dark:text-slate-400">{timeframe}</span>
        </div>
        <div className="flex items-center gap-1">
          {[
            { id: 'detail', label: 'Detalle', icon: <BarChart2 size={13} /> },
            { id: 'backtest', label: 'Backtest', icon: <TrendingUp size={13} /> },
            { id: 'validation', label: 'Validación', icon: <ShieldAlert size={13} /> },
            { id: 'real', label: 'Real', icon: <Trophy size={13} /> },
            { id: 'rejections', label: 'Rechazos', icon: <Ban size={13} /> },
            { id: 'recommendation', label: 'Recomendación', icon: <Sparkles size={13} /> },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded transition-colors',
              tab === t.id
                ? 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400'
                : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800',
            )}>
              {t.icon} {t.label}
            </button>
          ))}
          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-red-500 ml-2">
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        <div className={tab !== 'detail' ? 'hidden' : ''}>
          {loading ? (
            <div className="py-10 text-center text-sm text-slate-400">Cargando análisis…</div>
          ) : !chartData?.candles?.length ? (
            <div className="py-10 text-center text-sm text-slate-400">Sin datos de velas</div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2">
                <div ref={chartRef} className="w-full h-80 bg-slate-950 rounded" />
              </div>
              <div className="space-y-3">
                <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Contexto ICT</h4>
                {chartData.context && Object.entries(chartData.context).map(([k, v]) => (
                  <div key={k} className="text-xs">
                    <span className="text-slate-500 dark:text-slate-400 capitalize">{k.replace(/_/g, ' ')}:</span>{' '}
                    <span className="text-slate-700 dark:text-slate-200">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className={tab !== 'backtest' ? 'hidden' : ''}>
          <SymbolBacktest symbol={symbol} />
        </div>

        <div className={tab !== 'validation' ? 'hidden' : ''}>
          <SymbolValidation symbol={symbol} />
        </div>

        <div className={tab !== 'real' ? 'hidden' : ''}>
          <SymbolRealStats symbol={symbol} />
        </div>

        <div className={tab !== 'rejections' ? 'hidden' : ''}>
          <SymbolRejections symbol={symbol} />
        </div>

        <div className={tab !== 'recommendation' ? 'hidden' : ''}>
          <SymbolRecommendation symbol={symbol} timeframe={timeframe} aiBots={aiBots} />
        </div>
      </div>
    </div>
  )
}

// ── Symbol backtest (filtered by symbol, collapsible with totals) ─────────────

function SymbolBacktest({ symbol }) {
  const [signals, setSignals] = useState([])
  const [comparisonData, setComparisonData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      aiService.listSignals(200, symbol).then(r => Array.isArray(r.data) ? r.data : []),
      aiService.symbolBacktestComparison(symbol).then(r => r.data).catch(() => null),
    ])
      .then(([sigData, compData]) => {
        setSignals(sigData)
        setComparisonData(compData)
      })
      .catch(() => {
        setSignals([])
        setComparisonData(null)
      })
      .finally(() => setLoading(false))
  }, [symbol])

  if (loading) return <div className="py-10 text-center text-sm text-slate-400">Cargando señales…</div>
  if (!signals.length) return <div className="py-10 text-center text-sm text-slate-400">Sin señales históricas para {baseOf(symbol)}</div>

  const total = signals.length
  const resolved = signals.filter(s => s.outcome && s.outcome !== 'PENDING')
  const wins = resolved.filter(s => s.outcome === 'SUCCESS')
  const losses = resolved.filter(s => s.outcome === 'FAILURE')
  const winRate = resolved.length ? Math.round((wins.length / resolved.length) * 100) : 0
  const avgPnL = resolved.length
    ? (resolved.reduce((sum, s) => sum + (s.pnl_pct || 0), 0) / resolved.length).toFixed(2)
    : '—'

  const hasComparison = comparisonData?.signal_curve?.length && comparisonData?.trade_curve?.length

  // Merge curves for Recharts
  // Backtest = realistic equity curve with slippage/fees/gaps modeled
  // Ideal = ideal equity curve (reference only)
  // Ejecución = normalized % from $10k reference capital (comparable scale)
  const chartData = hasComparison
    ? comparisonData.signal_curve.map((d, i) => ({
        date: d.date,
        backtest: d.cumulative_pnl,
        ideal: comparisonData.ideal_curve?.[i]?.cumulative_pnl ?? d.cumulative_pnl,
        ejecucion: comparisonData.trade_curve[i]?.cumulative_pnl_pct ?? 0,
        ejecucion_usdt: comparisonData.trade_curve[i]?.cumulative_pnl ?? 0,
      }))
    : []

  const ComparisonTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    const tradePoint = chartData.find(d => d.date === label)
    return (
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-2 text-xs shadow-lg">
        <p className="font-semibold text-slate-600 dark:text-slate-300 mb-1">{label}</p>
        {payload.map((p, i) => (
          <p key={i} className="tabular-nums" style={{ color: p.color }}>
            {p.dataKey === 'backtest'
              ? `${p.name}: ${p.value >= 0 ? '+' : ''}${p.value?.toFixed(2)}%`
              : `${p.name}: ${p.value >= 0 ? '+' : ''}${p.value?.toFixed(2)}% (${tradePoint?.ejecucion_usdt >= 0 ? '+' : ''}${tradePoint?.ejecucion_usdt?.toFixed(0)} USDT)`
            }
          </p>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Comparison chart */}
      {hasComparison && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
            <TrendingUp size={14} className="text-violet-500" />
            Backtest vs Ejecución (real + paper)
          </h4>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
              <defs>
                <linearGradient id="gradBacktest" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradEjecucion" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradRealistic" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={d => d?.slice(5)} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={v => `${v.toFixed(0)}`} width={48} />
              <ReTooltip content={<ComparisonTooltip />} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Area type="monotone" dataKey="backtest" name="Backtest" stroke="#3b82f6" strokeWidth={2} fill="url(#gradBacktest)" dot={false} activeDot={{ r: 3 }} />
              <Area type="monotone" dataKey="ideal" name="Ideal (referencia)" stroke="#8b5cf6" strokeWidth={2} fill="url(#gradRealistic)" dot={false} activeDot={{ r: 3 }} />
              <Area type="monotone" dataKey="ejecucion" name="Ejecución (real+paper)" stroke="#f59e0b" strokeWidth={2} fill="url(#gradEjecucion)" dot={false} activeDot={{ r: 3 }} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-800 dark:text-white">{total}</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Total señales</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-blue-600 dark:text-blue-400">{resolved.length}</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Resueltas</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
          <div className={cn('text-lg font-bold', winRate >= 50 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>{winRate}%</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Win rate</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-800 dark:text-white">{avgPnL}%</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Avg PnL</div>
        </div>
      </div>

      {/* Toggle detail */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="flex items-center gap-2 text-xs font-medium text-blue-600 dark:text-blue-400 mb-2 hover:underline"
      >
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        {expanded ? 'Ocultar detalle' : `Ver detalle (${total} señales)`}
      </button>

      {expanded && (
        <div className="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-lg">
          <table className="w-full text-xs">
            <thead className="text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
              <tr>
                <th className="text-left py-2 px-2">Fecha</th>
                <th className="text-left py-2 px-2">Dir</th>
                <th className="text-left py-2 px-2">Score</th>
                <th className="text-left py-2 px-2">Tier</th>
                <th className="text-left py-2 px-2">Entrada</th>
                <th className="text-left py-2 px-2">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {signals.map(s => (
                <tr key={s.id} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/30">
                  <td className="py-2 px-2 text-slate-600 dark:text-slate-300">{new Date(s.signal_time).toLocaleDateString()}</td>
                  <td className="py-2 px-2">
                    <span className={cn(
                      'font-bold',
                      s.direction === 'long' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                    )}>{s.direction?.toUpperCase()}</span>
                  </td>
                  <td className="py-2 px-2 text-slate-600 dark:text-slate-300">{s.score}</td>
                  <td className="py-2 px-2"><QualityBadge tier={s.quality_tier} status={s.anti_fake_status} successProbability={s.success_probability} mlStatus={s.ml_status} /></td>
                  <td className="py-2 px-2 text-slate-600 dark:text-slate-300">${fmtPrice(s.entry_price)}</td>
                  <td className="py-2 px-2"><OutcomeBadge outcome={s.outcome} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Symbol validation (filtered by symbol, correct API structure) ─────────────

function SymbolValidation({ symbol }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)

  useEffect(() => {
    setLoading(true)
    aiService.heuristicValidation({ days, ticker: symbol })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [symbol, days])

  if (loading) return <div className="py-10 text-center text-sm text-slate-500">Cargando validación…</div>
  if (!data) return <div className="py-10 text-center text-sm text-red-400">Sin datos de validación.</div>

  const summary = data.summary || {}
  const rows = data.by_tier_status || []

  return (
    <div>
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-800 dark:text-white">{summary.total_signals ?? 0}</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Total señales</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-blue-600 dark:text-blue-400">{summary.resolved ?? 0}</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Resueltas</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-800 dark:text-white">{summary.total_signals ? Math.round((summary.resolved / summary.total_signals) * 100) : 0}%</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Tasa resolución</div>
        </div>
      </div>

      {/* Days filter */}
      <div className="flex items-center gap-3 mb-4">
        <span className="text-xs text-slate-500">Días:</span>
        {[7, 30, 90].map(d => (
          <button key={d} onClick={() => setDays(d)} className={cn(
            'text-xs px-2 py-1 rounded border',
            days === d
              ? 'bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-500/20 dark:text-blue-400 dark:border-blue-700'
              : 'bg-white text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
          )}>{d}d</button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-lg">
        <table className="w-full text-xs">
          <thead className="text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="text-left py-2 px-2">Tier</th>
              <th className="text-left py-2 px-2">Status</th>
              <th className="text-right py-2 px-2">Señales</th>
              <th className="text-right py-2 px-2">Resueltas</th>
              <th className="text-right py-2 px-2">Win Rate</th>
              <th className="text-right py-2 px-2">Avg PnL</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/30">
                <td className="py-2 px-2 text-slate-700 dark:text-slate-200 font-medium">{r.tier}</td>
                <td className="py-2 px-2"><QualityBadge tier={r.tier} status={r.status} /></td>
                <td className="py-2 px-2 text-right text-slate-600 dark:text-slate-300">{r.count}</td>
                <td className="py-2 px-2 text-right text-slate-600 dark:text-slate-300">{r.resolved}</td>
                <td className="py-2 px-2 text-right">
                  <span className={cn(r.win_rate > 50 ? 'text-green-600 dark:text-green-400' : r.win_rate > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-slate-500 dark:text-slate-400')}>
                    {r.win_rate != null ? r.win_rate.toFixed(1) : '—'}%
                  </span>
                </td>
                <td className="py-2 px-2 text-right text-slate-600 dark:text-slate-300">{r.avg_pnl_pct != null ? r.avg_pnl_pct.toFixed(2) + '%' : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Symbol detail modal ───────────────────────────────────────────────────────

function SymbolModal({ symbol, timeframe, onClose }) {
  const [chartData, setChartData] = useState(null)
  const [signals,   setSignals]   = useState([])
  const [loading,   setLoading]   = useState(true)
  const [diagnosisSignal, setDiagnosisSignal] = useState(null)
  const chartRef = useRef(null)

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setChartData(null)
    setSignals([])

    Promise.all([
      aiService.ictAnalysis(symbol, timeframe),
      aiService.listSignals(100, symbol),
    ])
      .then(([ictRes, sigRes]) => {
        if (cancelled) return
        setChartData(ictRes.data ?? null)
        setSignals(Array.isArray(sigRes.data) ? sigRes.data : [])
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [symbol, timeframe])

  useEffect(() => {
    if (!chartData?.candles?.length || !chartRef.current) return

    let chart
    const el = chartRef.current
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      try { chart?.applyOptions({ width: Math.floor(width), height: Math.floor(height) }) } catch {}
    })

    try {
      chart = createChart(el, {
        width:  el.offsetWidth  || 600,
        height: el.offsetHeight || 400,
        layout: {
          background: { color: '#0f172a' },
          textColor:  '#94a3b8',
        },
        grid: {
          vertLines: { color: '#1e293b' },
          horzLines: { color: '#1e293b' },
        },
        crosshair: { mode: 1 },
        timeScale: { timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#1e293b' },
      })

      const series = chart.addCandlestickSeries({
        upColor:       '#22c55e',
        downColor:     '#ef4444',
        borderVisible: false,
        wickUpColor:   '#22c55e',
        wickDownColor: '#ef4444',
      })
      series.setData(chartData.candles)

      const ctx = chartData.context ?? {}

      if (ctx.break_level) {
        try {
          series.createPriceLine({
            price: ctx.break_level, color: '#3b82f6',
            lineWidth: 1, lineStyle: 2,
            title: ctx.last_break ?? 'Break',
          })
        } catch {}
      }

      if (ctx.active_ob) {
        try {
          series.createPriceLine({ price: ctx.active_ob.top,    color: '#a855f7', lineWidth: 1, lineStyle: 0, title: `OB↑` })
          series.createPriceLine({ price: ctx.active_ob.bottom, color: '#a855f7', lineWidth: 1, lineStyle: 0, title: `OB↓` })
        } catch {}
      }

      ;(ctx.fvg_zones ?? []).forEach((fvg, i) => {
        const color = fvg.kind === 'bull' ? '#22c55e' : '#ef4444'
        try {
          series.createPriceLine({ price: fvg.top,    color, lineWidth: 1, lineStyle: 3, title: i === 0 ? 'FVG' : '' })
          series.createPriceLine({ price: fvg.bottom, color, lineWidth: 1, lineStyle: 3, title: '' })
        } catch {}
      })

      ;(ctx.eq_highs ?? []).forEach((p, i) => {
        try {
          series.createPriceLine({ price: p, color: '#f59e0b', lineWidth: 1, lineStyle: 3, title: i === 0 ? 'EQH' : '' })
        } catch {}
      })

      ;(ctx.eq_lows ?? []).forEach((p, i) => {
        try {
          series.createPriceLine({ price: p, color: '#06b6d4', lineWidth: 1, lineStyle: 3, title: i === 0 ? 'EQL' : '' })
        } catch {}
      })

      chart.timeScale().fitContent()
    } catch {}

    ro.observe(el)
    return () => {
      ro.disconnect()
      try { chart?.remove() } catch {}
    }
  }, [chartData])

  const byDay = useMemo(() => {
    const groups = {}
    signals.forEach(s => {
      const d = new Date(s.created_at).toLocaleDateString('es-ES', {
        day: '2-digit', month: '2-digit', year: 'numeric',
      })
      if (!groups[d]) groups[d] = []
      groups[d].push(s)
    })
    return Object.entries(groups)
  }, [signals])

  const ctx = chartData?.context ?? {}

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-white dark:bg-slate-950">
      {/* Header bar */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-slate-200 dark:border-slate-800 shrink-0 bg-white dark:bg-slate-950">
        <Brain size={18} className="text-blue-500 dark:text-blue-400 shrink-0" />
        <span className="font-bold text-slate-900 dark:text-white text-lg">{symbol}</span>
        <span className="text-sm text-slate-500 dark:text-slate-400 font-medium">{timeframe}</span>
        {ctx.bias && <BiasTag bias={ctx.bias} />}
        {ctx.last_break && (
          <span className="text-xs font-bold text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 px-2 py-0.5 rounded">
            {ctx.last_break}
          </span>
        )}
        {ctx.trigger && (
          <span className="text-xs font-semibold text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-500/10 px-2 py-0.5 rounded">
            {ctx.trigger.toUpperCase()}
          </span>
        )}
        {ctx.last_close && (
          <span className="text-sm font-mono text-slate-600 dark:text-slate-300">
            ${fmtPrice(ctx.last_close)}
          </span>
        )}
        <span className="ml-auto text-xs text-slate-400 dark:text-slate-600 hidden sm:block">ICT · SMC</span>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors ml-1"
        >
          <X size={20} />
        </button>
      </div>

      {/* Two-column layout below header */}
      <div className="flex-1 overflow-hidden flex flex-col lg:flex-row min-h-0">

        {/* Chart column */}
        <div className="lg:w-3/5 flex flex-col border-b lg:border-b-0 lg:border-r border-slate-200 dark:border-slate-800 bg-slate-950 shrink-0 lg:shrink" style={{ minHeight: 0 }}>
          {loading ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center space-y-2">
                <RefreshCw size={24} className="animate-spin text-blue-500 mx-auto" />
                <p className="text-sm text-slate-400">Cargando análisis ICT…</p>
              </div>
            </div>
          ) : !chartData?.candles?.length ? (
            <div className="flex-1 flex items-center justify-center px-8">
              <div className="text-center space-y-3 max-w-xs">
                <ScanLine size={32} className="text-slate-600 mx-auto" />
                <p className="text-sm text-slate-400">No se pudieron obtener velas del exchange para este par.</p>
                <p className="text-xs text-slate-600">Comprueba que {symbol} cotiza activamente en Binance Perps.</p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col h-full">
              {/* ICT overlay legend */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-3 pb-2 text-[11px] shrink-0">
                {ctx.last_break && ctx.break_level && (
                  <span className="flex items-center gap-1.5 text-blue-400">
                    <span className="w-5 border-t-2 border-dashed border-blue-500 inline-block shrink-0" />
                    {ctx.last_break} @ {fmtPrice(ctx.break_level)}
                  </span>
                )}
                {ctx.active_ob && (
                  <span className="flex items-center gap-1.5 text-purple-400">
                    <span className="w-5 border-t-2 border-purple-500 inline-block shrink-0" />
                    OB {ctx.active_ob.kind} ({fmtPrice(ctx.active_ob.bottom)}–{fmtPrice(ctx.active_ob.top)})
                  </span>
                )}
                {(ctx.fvg_zones?.length ?? 0) > 0 && (
                  <span className="flex items-center gap-1.5 text-green-400">
                    <span className="w-5 border-t-2 border-dotted border-green-500 inline-block shrink-0" />
                    FVG ({ctx.fvg_zones.length})
                  </span>
                )}
                {(ctx.eq_highs?.length ?? 0) > 0 && (
                  <span className="flex items-center gap-1.5 text-amber-400">
                    <span className="w-5 border-t-2 border-dotted border-amber-500 inline-block shrink-0" />
                    EQH ({ctx.eq_highs.length})
                  </span>
                )}
                {(ctx.eq_lows?.length ?? 0) > 0 && (
                  <span className="flex items-center gap-1.5 text-cyan-400">
                    <span className="w-5 border-t-2 border-dotted border-cyan-500 inline-block shrink-0" />
                    EQL ({ctx.eq_lows.length})
                  </span>
                )}
              </div>
              {/* Chart container — fills remaining space */}
              <div ref={chartRef} className="flex-1 w-full min-h-0" />
            </div>
          )}
        </div>

        {/* History column */}
        <div className="lg:w-2/5 flex flex-col overflow-hidden min-h-0">
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-800 shrink-0 bg-white dark:bg-slate-950">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Historial de señales</h3>
            {!loading && (
              <span className="text-xs text-slate-400 dark:text-slate-500">{signals.length} registradas</span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 bg-slate-50 dark:bg-slate-900/50">
            {loading && (
              <div className="space-y-2 animate-pulse pt-2">
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className="h-14 bg-slate-200 dark:bg-slate-800 rounded-lg" />
                ))}
              </div>
            )}

            {!loading && signals.length === 0 && (
              <div className="flex flex-col items-center justify-center h-48 text-center">
                <Clock size={28} className="text-slate-300 dark:text-slate-600 mb-3" />
                <p className="text-sm text-slate-500 dark:text-slate-500">Sin señales registradas aún</p>
                <p className="text-xs text-slate-400 dark:text-slate-600 mt-1">
                  Las señales se guardan automáticamente al escanear
                </p>
              </div>
            )}

            {!loading && byDay.map(([day, sigs]) => {
              const resolved = sigs.filter(s => s.outcome !== 'PENDING')
              const wins     = resolved.filter(s => s.outcome === 'SUCCESS').length
              const wr       = resolved.length > 0 ? Math.round(wins / resolved.length * 100) : null
              return (
                <div key={day}>
                  <div className="flex items-center gap-3 mb-2 sticky top-0 bg-slate-50 dark:bg-slate-900/50 py-1">
                    <span className="text-[11px] font-bold text-slate-500 dark:text-slate-500 uppercase tracking-widest">{day}</span>
                    <span className="text-[11px] text-slate-400 dark:text-slate-600">{sigs.length} señal{sigs.length !== 1 ? 'es' : ''}</span>
                    {wr !== null && (
                      <span className={cn('text-[11px] font-bold', wr >= 50 ? 'text-green-600 dark:text-green-500' : 'text-red-500')}>
                        WR {wr}%
                      </span>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    {sigs.map(sig => <SignalDayRow key={sig.id} sig={sig} onViewDiagnosis={setDiagnosisSignal} />)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {diagnosisSignal && (
        <SignalDiagnosisModal
          signal={diagnosisSignal}
          onClose={() => setDiagnosisSignal(null)}
        />
      )}
    </div>
  )
}

// ── Symbol Slot Card ──────────────────────────────────────────────────────────

function SlotCard({ entry, result, scanning, tickerStats, aiBotNames, onRemove, onChangeTimeframe, onScanOne, onSelect, isSelected }) {
  const { symbol, timeframe, resolved_timeframe } = entry
  const status   = result?.status
  const isSignal = status === 'SIGNAL'
  const hasAiBot = aiBotNames?.length > 0

  return (
    <div
      onClick={() => { if (!scanning) onSelect(symbol, timeframe) }}
      className={cn(
        'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3',
        'cursor-pointer select-none transition-shadow relative',
        !scanning && 'hover:shadow-md hover:border-slate-300 dark:hover:border-slate-600',
        scanning && 'opacity-70 cursor-wait',
        isSignal && result.direction === 'long'  && 'ring-1 ring-green-500/40',
        isSignal && result.direction === 'short' && 'ring-1 ring-red-500/40',
        hasAiBot && 'ring-1 ring-blue-400/30',
        isSelected && 'ring-2 ring-blue-500 dark:ring-blue-400',
      )}
    >
      {/* Selection checkmark */}
      {isSelected && (
        <div className="absolute -top-2 -right-2 z-10">
          <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white shadow-md">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          </span>
        </div>
      )}

      {/* Header — stop propagation so controls work */}
      <div className="flex items-center gap-2 mb-3" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <span className="font-bold text-slate-900 dark:text-white text-sm truncate">{baseOf(symbol)}</span>
          <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0">USDT</span>
          {hasAiBot && (
            <span
              title={`Bot IA activo: ${aiBotNames.join(', ')}`}
              className="flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400 shrink-0"
            >
              <Bot size={8} />IA
            </span>
          )}
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <select
            value={timeframe}
            onChange={e => onChangeTimeframe(symbol, e.target.value)}
            className={cn(
              'text-xs border rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500',
              'bg-slate-100 text-slate-700 border-slate-300',
              'dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600',
            )}
          >
            {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
          </select>
          {timeframe === 'auto' && resolved_timeframe && (
            <span className="text-[9px] font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 px-1 rounded">
              → {resolved_timeframe}
            </span>
          )}
        </div>
        <button
          onClick={() => onScanOne(symbol, timeframe)}
          disabled={scanning}
          title="Re-escanear"
          className="p-1 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 disabled:opacity-30 transition-colors"
        >
          <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
        </button>
        <button
          onClick={() => onRemove(symbol)}
          title="Eliminar"
          className="p-1 text-slate-400 hover:text-red-500 transition-colors"
        >
          <X size={12} />
        </button>
      </div>

      {/* Timestamp */}
      {result?.scannedAt && !scanning && (
        <div className="text-[10px] text-slate-400 dark:text-slate-600 mb-2 tabular-nums">
          {new Date(result.scannedAt).toLocaleTimeString()}
        </div>
      )}

      {/* Scanning */}
      {scanning && (
        <div className="text-xs text-slate-400 dark:text-slate-500 animate-pulse py-2">Analizando…</div>
      )}

      {/* Not scanned yet */}
      {!scanning && !result && (
        <div className="text-xs text-blue-500 dark:text-blue-400 flex items-center gap-1.5 py-1">
          <ScanLine size={12} />
          Sin datos — pulsa para ver gráfico
        </div>
      )}

      {/* Error */}
      {!scanning && status === 'ERROR' && (
        <div className="text-xs text-red-500 dark:text-red-400 py-1">Error al obtener datos del exchange</div>
      )}

      {/* NO_SIGNAL — ICT summary */}
      {!scanning && status === 'NO_SIGNAL' && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            {result.context?.bias && <BiasTag bias={result.context.bias} />}
            {result.context?.last_break && (
              <span className="text-[11px] font-bold text-blue-600 dark:text-blue-400">
                {result.context.last_break}
              </span>
            )}
            {result.context?.active_ob && (
              <span className="text-[11px] font-semibold text-purple-600 dark:text-purple-400">OB</span>
            )}
            {result.context?.active_fvgs > 0 && (
              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                {result.context.active_fvgs} FVG
              </span>
            )}
          </div>
          <div className="text-[11px] leading-snug text-slate-400 dark:text-slate-500 line-clamp-2">
            {result.context?.reason ?? 'Sin confluencia ICT'}
          </div>
          {result.context?.last_close && (
            <div className="font-mono text-[10px] text-slate-400">${fmtPrice(result.context.last_close)}</div>
          )}
        </div>
      )}

      {/* SIGNAL */}
      {!scanning && isSignal && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className={cn(
              'flex items-center gap-1.5 text-sm font-bold',
              result.direction === 'long'
                ? 'text-green-600 dark:text-green-400'
                : 'text-red-600 dark:text-red-400',
            )}>
              {result.direction === 'long' ? <TrendingUp size={15} /> : <TrendingDown size={15} />}
              {result.direction?.toUpperCase()}
            </span>
            <OutcomeBadge outcome={result.outcome} />
          </div>
          <ScoreMeter score={result.score} />
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <ConfBadge confidence={result.confidence} />
            {result.quality_tier && (
              <QualityBadge tier={result.quality_tier} status={result.anti_fake_status} successProbability={result.success_probability} mlStatus={result.ml_status} />
            )}
          </div>
          <div className="text-[10px] text-slate-400 font-mono">
            SL {fmtPrice(result.stop_loss)} · TP1 {fmtPrice(result.take_profit_1)}
          </div>
        </div>
      )}

      {/* Per-symbol stats footer */}
      <div className="mt-2.5 pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center gap-3 text-[10px] flex-wrap">
        {tickerStats ? (
          <>
            <span className="text-slate-400">
              <span className="font-bold text-slate-600 dark:text-slate-300">{tickerStats.total}</span>
              {' '}señal{tickerStats.total !== 1 ? 'es' : ''}
              <span className="ml-1 text-[9px] text-slate-400 dark:text-slate-500">(backtest)</span>
            </span>
            <span className="text-slate-400">
              Win{' '}
              <span className="text-[9px] text-slate-400 dark:text-slate-500">sim:</span>{' '}
              <span className={cn(
                'font-bold',
                tickerStats.win_rate == null ? 'text-slate-500' :
                tickerStats.win_rate >= 55   ? 'text-green-600 dark:text-green-400' :
                                               'text-red-500 dark:text-red-400',
              )}>
                {tickerStats.win_rate != null ? `${tickerStats.win_rate}%` : '—'}
              </span>
            </span>
            <span className="text-slate-400">
              Score: <span className="font-bold text-slate-600 dark:text-slate-300">{tickerStats.avg_score ?? '—'}</span>
            </span>
          </>
        ) : (
          <span className="text-slate-400 dark:text-slate-600">Sin señales aún</span>
        )}
        {(result?.ml_status || result?.anti_fake_status) ? (
          <span className={cn(
            'ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded',
            (result.ml_status || result.anti_fake_status) === 'CLEAR'   ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400' :
            (result.ml_status || result.anti_fake_status) === 'CAUTION' ? 'bg-yellow-500/20 text-yellow-600 dark:text-yellow-400' :
                                                    'bg-red-500/20 text-red-600 dark:text-red-400',
          )}>
            {result.success_probability != null ? 'ML ' : 'XGB '}{(result.ml_status || result.anti_fake_status)}
            {result.success_probability != null && (
              <span className="opacity-70"> ({(result.success_probability * 100).toFixed(0)}%)</span>
            )}
          </span>
        ) : (
          <span className="ml-auto text-[9px] text-slate-400 dark:text-slate-600">→ ver gráfico</span>
        )}
      </div>
    </div>
  )
}

// ── P&L Chart (SVG) ───────────────────────────────────────────────────────────

function PnlChart({ points }) {
  const W = 600, H = 96, PAD = 8
  const vals  = points.map(p => p.cum)
  const minV  = Math.min(0, ...vals)
  const maxV  = Math.max(0, ...vals)
  const range = Math.max(Math.abs(maxV - minV), 0.5)
  const toX   = (i) => PAD + (i / (points.length - 1)) * (W - PAD * 2)
  const toY   = (v) => H - PAD - ((v - minV) / range) * (H - PAD * 2)
  const pts   = points.map((p, i) => `${toX(i).toFixed(1)},${toY(p.cum).toFixed(1)}`).join(' ')
  const zeroY = toY(0).toFixed(1)
  const lastV = vals[vals.length - 1]
  const color = lastV >= 0 ? '#22c55e' : '#ef4444'
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-600 dark:text-slate-400">Curva de P&amp;L simulada</span>
        <span className={cn('text-xs font-bold tabular-nums', lastV >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
          {lastV >= 0 ? '+' : ''}{lastV.toFixed(2)}R &bull; {points.length} señales
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-20" preserveAspectRatio="none">
        <line x1={PAD} y1={zeroY} x2={W - PAD} y2={zeroY} stroke="#94a3b8" strokeWidth="1" strokeDasharray="4 4" opacity="0.5" />
        <polyline
          points={`${toX(0).toFixed(1)},${zeroY} ${pts} ${toX(points.length - 1).toFixed(1)},${zeroY}`}
          fill={color} fillOpacity={0.12} stroke="none"
        />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        <circle cx={toX(points.length - 1).toFixed(1)} cy={toY(lastV).toFixed(1)} r="3.5" fill={color} />
      </svg>
    </div>
  )
}

// ── Validation Tab ────────────────────────────────────────────────────────────

function ValidationTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)

  useEffect(() => {
    setLoading(true)
    aiService.heuristicValidation({ days })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="py-10 text-center text-sm text-slate-500">Cargando validación heurística…</div>
  if (!data) return <div className="py-10 text-center text-sm text-red-400">Error cargando datos de validación.</div>

  const { summary, by_tier_status, by_tier, by_status } = data

  const TierBadge = ({ tier }) => (
    <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded',
      tier === 'STRONG'   ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400' :
      tier === 'MODERATE' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400' :
      tier === 'WEAK'     ? 'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400' :
      'bg-slate-100 text-slate-700 dark:bg-slate-500/20 dark:text-slate-400'
    )}>{tier}</span>
  )

  const StatusBadge = ({ status }) => (
    <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded',
      status === 'CLEAR'   ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400' :
      status === 'CAUTION' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400' :
      'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400'
    )}>{status}</span>
  )

  const WinRateBar = ({ wr }) => {
    if (wr == null) return <span className="text-xs text-slate-400">—</span>
    const color = wr >= 60 ? 'bg-emerald-500' : wr >= 45 ? 'bg-yellow-500' : 'bg-red-500'
    return (
      <div className="flex items-center gap-2">
        <div className="w-16 h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
          <div className={cn('h-full rounded-full', color)} style={{ width: `${Math.min(100, wr)}%` }} />
        </div>
        <span className={cn('text-xs font-bold tabular-nums',
          wr >= 60 ? 'text-emerald-400' : wr >= 45 ? 'text-yellow-400' : 'text-red-400'
        )}>{wr}%</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-sm font-bold text-slate-800 dark:text-slate-200">Validación Heurística</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {summary.total_signals} señales · {summary.resolved} resueltas · últimos {days} días
          </p>
        </div>
        <select value={days} onChange={e => setDays(parseInt(e.target.value))}
          className="input text-xs py-1 w-32"
        >
          {[7, 14, 30, 60, 90, 180, 365].map(d => (
            <option key={d} value={d}>Últimos {d} días</option>
          ))}
        </select>
      </div>

      {/* By tier + status matrix */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
          <h3 className="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wide">Matriz Tier × Status</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400">
                <th className="text-left px-3 py-2 font-medium">Tier</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-right px-3 py-2 font-medium">Total</th>
                <th className="text-right px-3 py-2 font-medium">Resueltas</th>
                <th className="text-right px-3 py-2 font-medium">✓ SUCCESS</th>
                <th className="text-right px-3 py-2 font-medium">✗ FAILURE</th>
                <th className="text-right px-3 py-2 font-medium">⏱ EXPIRED</th>
                <th className="text-left px-3 py-2 font-medium">Win Rate</th>
                <th className="text-right px-3 py-2 font-medium">Avg PnL %</th>
              </tr>
            </thead>
            <tbody>
              {by_tier_status.map((row, i) => (
                <tr key={i} className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/30">
                  <td className="px-3 py-2"><TierBadge tier={row.tier} /></td>
                  <td className="px-3 py-2"><StatusBadge status={row.status} /></td>
                  <td className="px-3 py-2 text-right font-mono">{row.count}</td>
                  <td className="px-3 py-2 text-right font-mono text-slate-500">{row.resolved}</td>
                  <td className="px-3 py-2 text-right font-mono text-emerald-600">{row.success}</td>
                  <td className="px-3 py-2 text-right font-mono text-red-600">{row.failure}</td>
                  <td className="px-3 py-2 text-right font-mono text-slate-400">{row.expired}</td>
                  <td className="px-3 py-2"><WinRateBar wr={row.win_rate} /></td>
                  <td className="px-3 py-2 text-right font-mono">
                    {row.avg_pnl_pct != null ? (
                      <span className={row.avg_pnl_pct >= 0 ? 'text-emerald-600' : 'text-red-600'}>
                        {row.avg_pnl_pct > 0 ? '+' : ''}{row.avg_pnl_pct}%
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
              {by_tier_status.length === 0 && (
                <tr><td colSpan={9} className="px-3 py-6 text-center text-slate-400">No hay señales resueltas en este periodo</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Roll-ups */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* By tier */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
            <h3 className="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wide">Por Tier</h3>
          </div>
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {by_tier.map(t => (
              <div key={t.key} className="flex items-center gap-3 px-4 py-3">
                <TierBadge tier={t.key} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">{t.count} señales · {t.resolved} resueltas</span>
                    <WinRateBar wr={t.win_rate} />
                  </div>
                </div>
              </div>
            ))}
            {by_tier.length === 0 && (
              <div className="px-4 py-6 text-center text-xs text-slate-400">Sin datos</div>
            )}
          </div>
        </div>

        {/* By status */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
            <h3 className="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wide">Por Anti-Fake Status</h3>
          </div>
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {by_status.map(s => (
              <div key={s.key} className="flex items-center gap-3 px-4 py-3">
                <StatusBadge status={s.key} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">{s.count} señales · {s.resolved} resueltas</span>
                    <WinRateBar wr={s.win_rate} />
                  </div>
                </div>
              </div>
            ))}
            {by_status.length === 0 && (
              <div className="px-4 py-6 text-center text-xs text-slate-400">Sin datos</div>
            )}
          </div>
        </div>
      </div>

      {/* Guidance */}
      <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg px-4 py-3 text-xs text-amber-700 dark:text-amber-300 space-y-1">
        <p className="font-semibold">💡 Cómo interpretar estos datos</p>
        <ul className="list-disc list-inside space-y-0.5 text-amber-600/80 dark:text-amber-400/80">
          <li>Si <strong>CAUTION</strong> tiene win rate similar a <strong>CLEAR</strong>, el heurístico de red flags está siendo demasiado conservador.</li>
          <li>Si <strong>MODERATE</strong> tiene win rate &gt;50% y avg PnL positivo, puede valer la pena activarlo con sizing reducido.</li>
          <li>Si <strong>WEAK</strong> tiene win rate &lt;40%, mantenlo desactivado o solo en paper trading.</li>
        </ul>
      </div>
    </div>
  )
}

// ── Real Performance Tab (global IA trades) ──────────────────────────────────

function RealPerformanceTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState('total')

  useEffect(() => {
    setLoading(true)
    aiService.realPerformance(mode)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [mode])

  if (loading) {
    return <div className="py-20 text-center text-sm text-slate-400">Cargando rendimiento real…</div>
  }

  if (!data) {
    return <div className="py-20 text-center text-sm text-slate-400">Sin datos de rendimiento real</div>
  }

  const summary = data.summary || {}
  const trades = data.trades || []
  const openPos = data.open_positions || []

  const Stat = ({ label, value, color }) => {
    const colorCls =
      color === 'green' ? 'text-green-600 dark:text-green-400' :
      color === 'red'   ? 'text-red-600 dark:text-red-400' :
      'text-slate-800 dark:text-white'
    return (
      <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 text-center">
        <div className={cn('text-2xl font-bold', colorCls)}>{value}</div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wide mt-1">{label}</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Mode selector */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500 dark:text-slate-400">Modo:</span>
        {['total', 'real', 'paper'].map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              'text-[11px] px-2 py-1 rounded border font-medium transition-colors',
              mode === m
                ? 'bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-500/20 dark:text-blue-400 dark:border-blue-700'
                : 'bg-white text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
            )}
          >
            {m === 'total' ? 'Total' : m === 'real' ? 'Real' : 'Paper'}
          </button>
        ))}
      </div>

      {/* Summary */}
      <div>
        <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
          <Trophy size={16} className="text-violet-500" />
          Rendimiento IA global
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-3">
          <Stat label="Trades" value={summary.total_trades ?? 0} />
          <Stat label="Win Rate" value={`${summary.win_rate ?? 0}%`} color={summary.win_rate >= 50 ? 'green' : 'red'} />
          <Stat label="Ganados" value={summary.winning_trades ?? 0} color="green" />
          <Stat label="Perdidos" value={summary.losing_trades ?? 0} color="red" />
          <Stat label="PnL total" value={`${summary.total_pnl >= 0 ? '+' : ''}${summary.total_pnl?.toFixed(2) ?? '0.00'}`} color={summary.total_pnl >= 0 ? 'green' : 'red'} />
          <Stat label="Avg PnL" value={`${summary.avg_pnl >= 0 ? '+' : ''}${summary.avg_pnl?.toFixed(2) ?? '0.00'}`} />
          <Stat label="Mejor" value={`+${summary.best_trade?.toFixed(2) ?? '0.00'}`} color="green" />
          <Stat label="Peor" value={`${summary.worst_trade?.toFixed(2) ?? '0.00'}`} color="red" />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
          <Stat label="Longs" value={summary.long_trades ?? 0} />
          <Stat label="Shorts" value={summary.short_trades ?? 0} />
        </div>
      </div>

      {/* Open positions */}
      {openPos.length > 0 && (
        <div>
          <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
            <Zap size={16} className="text-amber-500" />
            Posiciones IA abiertas ({openPos.length})
          </h3>
          <div className="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-lg">
            <table className="w-full text-xs">
              <thead className="text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                <tr>
                  <th className="text-left py-2 px-3">Símbolo</th>
                  <th className="text-left py-2 px-3">Dirección</th>
                  <th className="text-right py-2 px-3">Entrada</th>
                  <th className="text-right py-2 px-3">Cantidad</th>
                  <th className="text-right py-2 px-3">Palanca</th>
                  <th className="text-right py-2 px-3">PnL no realizado</th>
                  <th className="text-right py-2 px-3">Abierta</th>
                </tr>
              </thead>
              <tbody>
                {openPos.map(p => (
                  <tr key={p.id} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/30">
                    <td className="py-2 px-3 font-medium text-slate-700 dark:text-slate-200">{p.symbol}</td>
                    <td className="py-2 px-3">
                      <span className={cn('font-bold uppercase', p.side === 'long' ? 'text-green-600' : 'text-red-600')}>{p.side}</span>
                    </td>
                    <td className="py-2 px-3 text-right text-slate-600 dark:text-slate-300">${p.entry_price?.toFixed(4) ?? '—'}</td>
                    <td className="py-2 px-3 text-right text-slate-600 dark:text-slate-300">{fmtQty(p.quantity)}</td>
                    <td className="py-2 px-3 text-right text-slate-600 dark:text-slate-300">{p.leverage ?? '—'}x</td>
                    <td className="py-2 px-3 text-right font-bold">
                      <span className={p.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-600'}>
                        {p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl?.toFixed(4) ?? '0.0000'}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right text-slate-400">{p.opened_at ? new Date(p.opened_at).toLocaleDateString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Trade history */}
      {trades.length > 0 && (
        <div>
          <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
            <BarChart2 size={16} className="text-blue-500" />
            Historial de trades IA ({trades.length})
          </h3>
          <div className="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-lg">
            <table className="w-full text-xs">
              <thead className="text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                <tr>
                  <th className="text-left py-2 px-3">Fecha cierre</th>
                  <th className="text-left py-2 px-3">Símbolo</th>
                  <th className="text-left py-2 px-3">Dir</th>
                  <th className="text-right py-2 px-3">Entrada</th>
                  <th className="text-right py-2 px-3">Salida</th>
                  <th className="text-right py-2 px-3">Cantidad</th>
                  <th className="text-right py-2 px-3">PnL</th>
                  <th className="text-right py-2 px-3">Fee</th>
                </tr>
              </thead>
              <tbody>
                {trades.map(t => (
                  <tr key={t.id} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/30">
                    <td className="py-2 px-3 text-slate-500">{t.closed_at ? new Date(t.closed_at).toLocaleDateString() : '—'}</td>
                    <td className="py-2 px-3 font-medium text-slate-700 dark:text-slate-200">{t.symbol}</td>
                    <td className="py-2 px-3">
                      <span className={cn('font-bold uppercase', t.side === 'long' ? 'text-green-600' : 'text-red-600')}>{t.side}</span>
                    </td>
                    <td className="py-2 px-3 text-right text-slate-600">${t.entry_price?.toFixed(4) ?? '—'}</td>
                    <td className="py-2 px-3 text-right text-slate-600">${t.exit_price?.toFixed(4) ?? '—'}</td>
                    <td className="py-2 px-3 text-right text-slate-600">{fmtQty(t.quantity)}</td>
                    <td className="py-2 px-3 text-right font-bold">
                      <span className={t.realized_pnl >= 0 ? 'text-green-600' : 'text-red-600'}>
                        {t.realized_pnl >= 0 ? '+' : ''}{t.realized_pnl?.toFixed(4) ?? '0.0000'}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right text-slate-400">{t.fee?.toFixed(4) ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {trades.length === 0 && openPos.length === 0 && (
        <div className="py-16 text-center">
          <Trophy size={32} className="text-slate-300 dark:text-slate-600 mx-auto mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">Aún no hay trades IA ejecutados</p>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">Las operaciones aparecerán aquí cuando el bot IA ejecute señales reales.</p>
        </div>
      )}
    </div>
  )
}

// ── Ranking Tab ───────────────────────────────────────────────────────────────

function RankingTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sortBy, setSortBy] = useState('win_rate')
  const [minSignals, setMinSignals] = useState(5)

  useEffect(() => {
    setLoading(true)
    aiService.statsByTicker()
      .then(r => {
        const obj = r.data && typeof r.data === 'object' ? r.data : {}
        setData(obj)
      })
      .catch(() => setData({}))
      .finally(() => setLoading(false))
  }, [])

  const rows = useMemo(() => {
    if (!data) return []
    const arr = Object.entries(data).map(([ticker, stats]) => ({ ticker, ...stats }))
      .filter(r => r.total >= minSignals)
    // Sort: nulls last, descending for numeric metrics
    const sortOrder = ['win_rate', 'avg_pnl_pct', 'avg_score', 'total'].includes(sortBy) ? -1 : 1
    arr.sort((a, b) => {
      const av = a[sortBy]
      const bv = b[sortBy]
      if (av == null && bv == null) return b.total - a.total
      if (av == null) return 1
      if (bv == null) return -1
      return (av > bv ? 1 : av < bv ? -1 : 0) * sortOrder
    })
    return arr
  }, [data, sortBy, minSignals])

  if (loading) return <div className="py-10 text-center text-sm text-slate-500">Cargando ranking…</div>
  if (!rows.length) return <div className="py-10 text-center text-sm text-slate-400">Sin datos suficientes. Necesitas al menos {minSignals} señales por símbolo.</div>

  const SortHeader = ({ id, label, right = false }) => (
    <th
      onClick={() => setSortBy(id)}
      className={cn(
        'px-3 py-2 font-medium cursor-pointer select-none hover:text-slate-700 dark:hover:text-slate-200 transition-colors',
        right ? 'text-right' : 'text-left',
        sortBy === id ? 'text-blue-600 dark:text-blue-400' : 'text-slate-500 dark:text-slate-400'
      )}
    >
      <span className="flex items-center gap-1" style={{ justifyContent: right ? 'flex-end' : 'flex-start' }}>
        {label}
        {sortBy === id && <ChevronDown size={12} className="shrink-0" />}
      </span>
    </th>
  )

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-sm font-bold text-slate-800 dark:text-slate-200">Ranking de Activos</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Ordenado por rendimiento histórico. Usa el score medio como referencia para ajustar el bot.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Mín. señales:</span>
          {[3, 5, 10, 20].map(n => (
            <button key={n} onClick={() => setMinSignals(n)} className={cn(
              'text-xs px-2 py-1 rounded border font-medium transition-colors',
              minSignals === n
                ? 'bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-500/20 dark:border-blue-500/40 dark:text-blue-400'
                : 'bg-white text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
            )}>{n}</button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700">
              <tr>
                <SortHeader id="ticker" label="Símbolo" />
                <SortHeader id="total" label="Señales" right />
                <SortHeader id="win_rate" label="Win Rate" right />
                <SortHeader id="avg_score" label="Score Medio" right />
                <SortHeader id="avg_pnl_pct" label="P&L Sim." right />
                <SortHeader id="avg_bars" label="Bars Ø" right />
                <th className="px-3 py-2 text-left font-medium text-slate-500 dark:text-slate-400">Óptimo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {rows.map((r, i) => {
                const wr = r.win_rate
                const pnl = r.avg_pnl_pct
                const tierStatus = r.best_tier && r.best_status ? `${r.best_tier} + ${r.best_status}` : r.best_tier || r.best_status || '—'
                return (
                  <tr key={r.ticker} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className={cn(
                          'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0',
                          i === 0 ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400' :
                          i === 1 ? 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300' :
                          i === 2 ? 'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400' :
                          'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500'
                        )}>
                          {i + 1}
                        </span>
                        <span className="font-bold text-slate-800 dark:text-slate-200">{baseOf(r.ticker)}</span>
                        <span className="text-[10px] text-slate-400">USDT</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-slate-600 dark:text-slate-300">{r.total}</td>
                    <td className="px-3 py-2 text-right">
                      {wr != null ? (
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-12 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                            <div className={cn('h-full rounded-full', wr >= 55 ? 'bg-green-500' : wr >= 45 ? 'bg-yellow-500' : 'bg-red-500')} style={{ width: `${Math.min(100, wr)}%` }} />
                          </div>
                          <span className={cn('font-bold tabular-nums', wr >= 55 ? 'text-green-600 dark:text-green-400' : wr >= 45 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-500')}>
                            {wr}%
                          </span>
                        </div>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-slate-600 dark:text-slate-300">{r.avg_score}</td>
                    <td className="px-3 py-2 text-right">
                      {pnl != null ? (
                        <span className={cn('font-mono font-medium', pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                          {pnl >= 0 ? '+' : ''}{pnl}%
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-slate-600 dark:text-slate-300">
                      {r.avg_bars != null ? `${r.avg_bars}` : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {r.best_direction && (
                          <span className={cn(
                            'text-[10px] font-bold px-1.5 py-0.5 rounded',
                            r.best_direction === 'long'
                              ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400'
                              : 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400'
                          )}>
                            {r.best_direction.toUpperCase()}
                          </span>
                        )}
                        {tierStatus !== '—' && (
                          <span className="text-[10px] font-medium text-slate-600 dark:text-slate-300">
                            {tierStatus}
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {rows.length === 0 && (
          <div className="px-4 py-8 text-center text-xs text-slate-400 dark:text-slate-600">
            Ningún símbolo cumple el filtro de {minSignals} señales mínimas.
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg px-4 py-3 text-xs text-blue-700 dark:text-blue-300 space-y-1">
        <p className="font-semibold">💡 Cómo usar este ranking</p>
        <ul className="list-disc list-inside space-y-0.5 text-blue-600/80 dark:text-blue-400/80">
          <li><strong>Score Medio:</strong> Usa este valor como referencia para el <em>min_score</em> de tu bot en ese par.</li>
          <li><strong>Win Rate &gt;55% + P&L positivo:</strong> Candidato ideal para trading automático.</li>
          <li><strong>Bars Ø:</strong> Tiempo promedio de resolución. Útil para ajustar el timeframe o la paciencia del bot.</li>
          <li><strong>Óptimo:</strong> Dirección y combinación Tier+Status con mejor rendimiento histórico.</li>
        </ul>
      </div>
    </div>
  )
}

// ── Backtest Tab ──────────────────────────────────────────────────────────────

function BacktestTab() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter,  setFilter]  = useState('ALL')
  const [diagnosisSignal, setDiagnosisSignal] = useState(null)
  const [comparisonData, setComparisonData] = useState(null)
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'

  useEffect(() => {
    setLoading(true)
    Promise.all([
      aiService.listSignals(200)
        .then(r => Array.isArray(r.data) ? r.data : [])
        .catch(() => []),
      aiService.backtestComparison()
        .then(r => r.data)
        .catch(() => null),
    ])
      .then(([sigData, compData]) => {
        setSignals(sigData)
        setComparisonData(compData)
      })
      .catch(() => {
        setSignals([])
        setComparisonData(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() =>
    filter === 'ALL' ? signals : signals.filter(s => s.quality_tier === filter),
  [signals, filter])

  const resolved = useMemo(() => filtered.filter(s => s.outcome !== 'PENDING' && s.outcome !== 'INVALID'), [filtered])
  const wins     = useMemo(() => resolved.filter(s => s.outcome === 'SUCCESS').length, [resolved])
  const winRate  = resolved.length > 0 ? Math.round(wins / resolved.length * 100) : null

  const pnlPoints = useMemo(() => {
    const sorted = [...filtered]
      .filter(s => s.outcome !== 'PENDING' && s.outcome !== 'EXPIRED' && s.outcome !== 'INVALID')
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    let cum = 0
    return sorted.map(s => {
      // Prefer realistic P&L (models slippage/fees/gaps), fallback to ideal
      const pnl = s.realistic_pnl_pct != null ? s.realistic_pnl_pct
        : s.pnl_pct != null ? s.pnl_pct
        : (s.outcome === 'SUCCESS' ? 1.5 : -1.0)
      cum += pnl
      return { cum }
    })
  }, [filtered])

  const finalPnl = pnlPoints.length > 0 ? pnlPoints[pnlPoints.length - 1].cum : 0

  const avgBars = useMemo(() => {
    const wb = resolved.filter(s => s.outcome_bars != null)
    return wb.length > 0 ? Math.round(wb.reduce((a, s) => a + s.outcome_bars, 0) / wb.length) : null
  }, [resolved])

  const byTier = useMemo(() => ['STRONG', 'MODERATE', 'WEAK'].map(tier => {
    const sub = signals.filter(s => s.quality_tier === tier)
    const res = sub.filter(s => s.outcome !== 'PENDING' && s.outcome !== 'INVALID')
    const w   = res.filter(s => s.outcome === 'SUCCESS').length
    return { tier, total: sub.length, resolved: res.length, win_rate: res.length > 0 ? Math.round(w / res.length * 100) : null }
  }), [signals])

  return (
    <div className="space-y-5">
      {/* Filter */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter size={13} className="text-slate-400 shrink-0" />
        {['ALL', 'STRONG', 'MODERATE', 'WEAK'].map(t => (
          <button key={t} onClick={() => setFilter(t)} className={cn(
            'text-xs px-2.5 py-1 rounded-lg border font-medium transition-colors',
            filter === t
              ? 'bg-blue-100 border-blue-300 text-blue-700 dark:bg-blue-500/20 dark:border-blue-500/40 dark:text-blue-400'
              : 'bg-slate-100 border-slate-200 text-slate-600 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-400',
          )}>{t}</button>
        ))}
        <span className="ml-auto text-xs text-slate-400">{filtered.length} señales</span>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Resueltas',     value: resolved.length,  color: '' },
          { label: 'Win Rate',      value: winRate != null ? `${winRate}%` : '—',
            color: winRate == null ? '' : winRate >= 55 ? 'text-green-600 dark:text-green-400' : 'text-red-500' },
          { label: 'P&L simulado',  value: `${finalPnl >= 0 ? '+' : ''}${finalPnl.toFixed(1)}R`,
            color: finalPnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500' },
          { label: 'Bars promedio', value: avgBars != null ? `${avgBars}` : '—', color: '' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3 text-center">
            <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">{label}</div>
            <div className={cn('text-lg font-bold', color || 'text-slate-900 dark:text-slate-100')}>{value}</div>
          </div>
        ))}
      </div>

      {/* Global comparison chart: Backtest vs Execution */}
      {comparisonData?.signal_curve?.length > 0 && comparisonData?.trade_curve?.length > 0 && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
            <TrendingUp size={14} className="text-violet-500" />
            Backtest vs Ejecución (global)
          </h4>
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart
              data={comparisonData.signal_curve.map((d, i) => ({
                date: d.date,
                backtest: d.cumulative_pnl,
                ideal: comparisonData.ideal_curve?.[i]?.cumulative_pnl ?? d.cumulative_pnl,
                ejecucion: comparisonData.trade_curve[i]?.cumulative_pnl ?? 0,
              }))}
              margin={{ top: 4, right: 4, left: 4, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 10 }}
                tickFormatter={v => `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`}
                label={{ value: 'Backtest (%)', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#3b82f6' }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fontSize: 10 }}
                tickFormatter={v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}`}
                label={{ value: 'Ejecución (USDT)', angle: 90, position: 'insideRight', fontSize: 10, fill: '#f59e0b' }}
              />
              <ReTooltip
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
                formatter={(value, name) => {
                  const suffix = name === 'Backtest' || name === 'Ideal (referencia)' ? '%' : ' USDT'
                  return [`${value >= 0 ? '+' : ''}${value?.toFixed(2)}${suffix}`, name]
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area yAxisId="left" type="monotone" dataKey="backtest" name="Backtest" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.1} strokeWidth={2} />
              <Area yAxisId="left" type="monotone" dataKey="ideal" name="Ideal (referencia)" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.1} strokeWidth={2} />
              <Line yAxisId="right" type="monotone" dataKey="ejecucion" name="Ejecución" stroke="#f59e0b" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* P&L curve */}
      {pnlPoints.length >= 2 ? (
        <PnlChart points={pnlPoints} />
      ) : !loading && (
        <div className="text-center py-8 text-slate-400 dark:text-slate-600 text-sm border border-dashed border-slate-200 dark:border-slate-700 rounded-lg">
          Necesitas al menos 2 señales resueltas para ver la curva de P&amp;L.
          <br />
          <span className="text-xs">Los outcomes se marcan automáticamente cada 15 minutos.</span>
        </div>
      )}

      {/* Win rate by tier */}
      {signals.length > 0 && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">Win Rate por Tier</h3>
          <div className="space-y-2.5">
            {byTier.map(({ tier, total, resolved: res, win_rate: wr }) => (
              <div key={tier} className="flex items-center gap-3 text-sm">
                <span className={cn(
                  'text-[10px] font-bold px-2 py-0.5 rounded w-20 text-center shrink-0',
                  tier === 'STRONG'   ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400' :
                  tier === 'MODERATE' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400' :
                                        'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
                )}>{tier}</span>
                <span className="text-xs text-slate-500 dark:text-slate-400">{total} señales &bull; {res} resueltas</span>
                {wr != null ? (
                  <div className="ml-auto flex items-center gap-2">
                    <div className="w-20 h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                      <div className={cn('h-full rounded-full', wr >= 55 ? 'bg-green-500' : 'bg-red-500')} style={{ width: `${wr}%` }} />
                    </div>
                    <span className={cn('text-xs font-bold tabular-nums w-10 text-right', wr >= 55 ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                      {wr}%
                    </span>
                  </div>
                ) : (
                  <span className="ml-auto text-xs text-slate-400">Sin datos</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Signal table */}
      {loading && <div className="text-center py-8 text-slate-400 text-sm animate-pulse">Cargando señales…</div>}
      {!loading && filtered.length > 0 && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                  {['Fecha', 'Par', 'TF', 'Dir.', 'Score', 'ADX', 'Tier', 'HTF', 'Outcome', 'P&L', 'IA'].map(h => (
                    <th key={h} className={cn('px-3 py-2 text-slate-500 font-medium', h === 'Score' || h === 'ADX' || h === 'P&L' ? 'text-right' : 'text-left')}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.slice(0, 100).map(sig => {
                  const isLong = sig.direction === 'long'
                  const outcome = sig.outcome
                  const isSuccess = outcome === 'SUCCESS'
                  const isFailure = outcome === 'FAILURE'
                  const pnl = sig.pnl_pct
                  const adx = sig.features?.adx
                  const htfBias = sig.features?.htf_bias
                  const regime = sig.features?.market_regime
                  const dt = new Date(sig.created_at)
                  return (
                    <tr key={sig.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                      <td className="px-3 py-2 text-slate-400 tabular-nums whitespace-nowrap">
                        {dt.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' })}{' '}
                        <span className="text-slate-300 dark:text-slate-600">{dt.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}</span>
                      </td>
                      <td className="px-3 py-2 font-medium text-slate-700 dark:text-slate-300">{baseOf(sig.ticker)}</td>
                      <td className="px-3 py-2 text-slate-400">{sig.timeframe}</td>
                      <td className="px-3 py-2">
                        <span className={cn('font-bold', isLong ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                          {isLong ? '↑L' : '↓S'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-600 dark:text-slate-400">{sig.score}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {adx != null ? (
                          <span className={cn('text-[10px] font-medium', adx < 25 ? 'text-yellow-600 dark:text-yellow-400' : 'text-slate-500')}>
                            {adx.toFixed(0)}{adx < 25 ? ' ≈R' : ''}
                          </span>
                        ) : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-3 py-2">
                        <span className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded',
                          sig.quality_tier === 'STRONG'   ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400' :
                          sig.quality_tier === 'MODERATE' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400' :
                                                            'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
                        )}>{sig.quality_tier}</span>
                      </td>
                      <td className="px-3 py-2">
                        {htfBias ? (
                          <span className={cn('text-[10px] font-bold', htfBias === 'bull' ? 'text-green-500' : 'text-red-400')}>
                            {htfBias === 'bull' ? '↑' : '↓'}
                          </span>
                        ) : <span className="text-slate-300 text-[10px]">—</span>}
                      </td>
                      <td className="px-3 py-2">
                        <span className={cn('text-[10px] font-bold',
                          isSuccess ? 'text-green-600 dark:text-green-400' :
                          isFailure ? 'text-red-500' : 'text-slate-400',
                        )}>
                          {outcome === 'PENDING' ? '·' : outcome === 'EXPIRED' ? 'EXP' : outcome}
                        </span>
                      </td>
                      <td className={cn('px-3 py-2 text-right tabular-nums font-medium',
                        pnl == null ? 'text-slate-400' : pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500',
                      )}>
                        {pnl != null ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%` : '—'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {(sig.anti_fake_status === 'BLOCK' || sig.anti_fake_status === 'CAUTION') && (
                          <button
                            onClick={() => setDiagnosisSignal(sig)}
                            className="text-[10px] text-blue-500 hover:text-blue-400 font-medium transition-colors"
                            title={isAdmin ? "Ver diagnóstico IA" : "Ver contexto del par"}
                          >
                            {isAdmin ? 'IA' : 'Ctx'}
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {filtered.length > 100 && (
            <div className="text-center py-2 text-xs text-slate-400 dark:text-slate-600 border-t border-slate-100 dark:border-slate-800">
              Mostrando 100 de {filtered.length} señales
            </div>
          )}
        </div>
      )}
      {!loading && filtered.length === 0 && (
        <div className="text-center py-12 text-slate-400 dark:text-slate-600 text-sm">
          Sin señales registradas aún.
        </div>
      )}

      {diagnosisSignal && (
        <SignalDiagnosisModal
          signal={diagnosisSignal}
          onClose={() => setDiagnosisSignal(null)}
        />
      )}
    </div>
  )
}

// ── Symbol Picker ─────────────────────────────────────────────────────────────

function SymbolPicker({ watchlist, onAdd }) {
  const [open,       setOpen]    = useState(false)
  const [query,      setQuery]   = useState('')
  const [allSymbols, setAll]     = useState([])
  const [loading,    setLoading] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  useEffect(() => {
    if (!open || allSymbols.length > 0) return
    setLoading(true)
    exchangeAccountsService.marketsByExchange('bingx')
      .then(res => {
        const raw = Array.isArray(res.data) ? res.data : []
        setAll(raw.map(s => s.replace('/', '').replace(/:.*$/, '')).filter(Boolean))
      })
      .catch(() => setAll(['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT']))
      .finally(() => setLoading(false))
  }, [open, allSymbols.length])

  const existing = useMemo(() => new Set(watchlist.map(e => e.symbol)), [watchlist])

  const options = useMemo(() => {
    const q = query.toUpperCase()
    return allSymbols
      .filter(s => !existing.has(s) && (!q || s.toUpperCase().includes(q)))
      .slice(0, 60)
  }, [allSymbols, query, existing])

  const pick = (sym) => { onAdd(sym); setOpen(false); setQuery('') }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        className={cn(
          'flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors font-medium',
          'bg-slate-100 text-slate-700 border-slate-300 hover:bg-slate-200',
          'dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600 dark:hover:bg-slate-700',
        )}
      >
        <Plus size={13} /> Añadir par
      </button>

      {open && (
        <div className={cn(
          'absolute top-full mt-1 right-0 z-30 w-64 rounded-xl shadow-xl border',
          'bg-white border-slate-200',
          'dark:bg-slate-900 dark:border-slate-700',
        )}>
          <div className="p-2">
            <input
              autoFocus
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Buscar par (ej: SOL, PEPE…)"
              className="input text-sm"
            />
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {loading && (
              <div className="text-xs text-slate-400 dark:text-slate-500 px-3 py-2 animate-pulse">
                Cargando pares del exchange…
              </div>
            )}
            {!loading && options.length === 0 && (
              <div className="text-xs text-slate-400 dark:text-slate-500 px-3 py-2">Sin resultados</div>
            )}
            {options.map(sym => (
              <button
                key={sym}
                onClick={() => pick(sym)}
                className={cn(
                  'flex items-center justify-between w-full px-3 py-2 text-sm transition-colors',
                  'text-slate-700 hover:bg-slate-100',
                  'dark:text-slate-300 dark:hover:bg-slate-800',
                )}
              >
                <span className="font-semibold">{baseOf(sym)}</span>
                <span className="text-xs text-slate-400">{sym}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Laboratorio / Simulado tab ────────────────────────────────────────────────

function LaboratorioTab({ stats, lastScan }) {
  const [sub, setSub] = useState('dashboard')

  return (
    <div className="space-y-4">
      <div className="text-sm text-slate-600 dark:text-slate-300 bg-amber-50 dark:bg-amber-500/10 border border-amber-100 dark:border-amber-500/20 rounded-lg px-4 py-3 flex items-start gap-2">
        <span className="text-amber-500">⚠️</span>
        <p>
          Esta sección muestra métricas <strong>teóricas y de backtest/simulación</strong>.
          No representan trades reales ejecutados: sirven para auditar el motor,
          comparar escenarios y validar el modelo, pero el rendimiento real está en
          la pestaña <strong>Rendimiento real</strong>.
        </p>
      </div>

      <div className="flex gap-0 border-b border-slate-200 dark:border-slate-800 -mb-1">
        {[
          { id: 'dashboard',  label: 'Dashboard',  icon: <Brain size={13} /> },
          { id: 'ranking',    label: 'Ranking',    icon: <Trophy size={13} /> },
          { id: 'backtest',   label: 'Backtest',   icon: <BarChart2 size={13} /> },
          { id: 'validation', label: 'Validación', icon: <ShieldAlert size={13} /> },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setSub(t.id)}
            className={cn(
              'flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              sub === t.id
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300',
            )}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      <StatsBar stats={stats} lastScan={lastScan} />

      {sub === 'dashboard' && (
        <Suspense fallback={
          <div className="py-20 text-center">
            <div className="animate-spin inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full" />
            <p className="text-sm text-slate-400 mt-3">Cargando Dashboard IA…</p>
          </div>
        }>
          <AIDashboardTab />
        </Suspense>
      )}

      {sub === 'ranking'    && <RankingTab />}
      {sub === 'backtest'   && <BacktestTab />}
      {sub === 'validation' && <ValidationTab />}
    </div>
  )
}

// ── Stats Bar ─────────────────────────────────────────────────────────────────

function StatsBar({ stats, lastScan }) {
  if (!stats) return null

  // DB health: how stale is the last background scan?
  // Use the most recent timestamp between the DB metric and the local manual scan,
  // so a scan just triggered by the user is immediately reflected.
  const dbLastScan   = stats.last_scan_at ? new Date(stats.last_scan_at) : null
  const localLastScan = lastScan instanceof Date ? lastScan : null
  const lastScanAt   = dbLastScan && localLastScan
    ? (dbLastScan > localLastScan ? dbLastScan : localLastScan)
    : (dbLastScan || localLastScan)
  const ageMin       = lastScanAt ? Math.floor((Date.now() - lastScanAt.getTime()) / 60000) : null
  const scanHealth   = ageMin == null ? 'unknown' : ageMin <= 7 ? 'ok' : ageMin <= 20 ? 'warn' : 'stale'
  const healthColor  = { ok: 'bg-green-500', warn: 'bg-yellow-400', stale: 'bg-red-500', unknown: 'bg-slate-400' }
  const healthLabel  = { ok: `hace ${ageMin}m`, warn: `hace ${ageMin}m`, stale: `hace ${ageMin}m`, unknown: '—' }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Señales totales (backtest)', value: stats.total ?? 0 },
          { label: 'Win rate (backtest)',        value: stats.win_rate != null ? `${stats.win_rate}%` : '—' },
          { label: 'Score promedio',             value: stats.avg_score ?? '—' },
          { label: 'Datos Ensemble',             value: stats.model_ready ? '✓ Listo' : `${stats.resolved ?? 0} / 50` },
        ].map(({ label, value }) => (
          <div key={label} className={cn(
            'bg-white dark:bg-slate-900 border rounded-lg p-3 text-center',
            label.includes('backtest')
              ? 'border-dashed border-slate-300 dark:border-slate-600'
              : 'border-slate-200 dark:border-slate-700'
          )}>
            <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">{label}</div>
            <div className="text-lg font-bold text-slate-900 dark:text-slate-100">{value}</div>
          </div>
        ))}
      </div>

      {/* DB health row */}
      <div className="flex items-center gap-3 px-3 py-2 bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 rounded-lg text-xs flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className={cn('w-2 h-2 rounded-full shrink-0', healthColor[scanHealth], scanHealth === 'ok' && 'animate-pulse')} />
          <span className="font-semibold text-slate-600 dark:text-slate-400">BD activa</span>
        </div>
        <span className="text-slate-400 dark:text-slate-500">
          Último scan: <span className="font-medium text-slate-600 dark:text-slate-300">
            {lastScanAt
              ? `${lastScanAt.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })} (${healthLabel[scanHealth]})`
              : '—'}
          </span>
        </span>
        <span className="text-slate-400 dark:text-slate-500">
          Símbolos vigilados: <span className="font-medium text-slate-600 dark:text-slate-300">{stats.latest_scans_count ?? '—'}</span>
        </span>
        <span className="text-slate-400 dark:text-slate-500">
          Señales en BD: <span className="font-medium text-slate-600 dark:text-slate-300">{stats.total ?? 0}</span>
          {(stats.pending ?? 0) > 0 && (
            <span className="ml-1 text-yellow-600 dark:text-yellow-400">({stats.pending} pendientes)</span>
          )}
        </span>
        {scanHealth === 'stale' && (
          <span className="ml-auto text-red-500 font-semibold">⚠ Scanner sin actividad reciente</span>
        )}
        {scanHealth === 'warn' && (
          <span className="ml-auto text-yellow-600 dark:text-yellow-400 font-medium">Scanner tardando más de lo normal</span>
        )}
      </div>
    </div>
  )
}

// ── XGBoost Card ─────────────────────────────────────────────────────────────

function XGBoostCard({ modelStatus, stats }) {
  const [open,     setOpen]     = useState(false)
  const [training, setTraining] = useState(false)
  const [trained,  setTrained]  = useState(false)

  const triggerTrain = async () => {
    setTraining(true)
    try {
      await aiService.trainModel()
      setTrained(true)
    } catch {}
    finally { setTraining(false) }
  }

  const byConf = stats?.by_confidence ?? {}

  return (
    <div className="border-t border-slate-200 dark:border-slate-800 pt-4">
      <div
        onClick={() => setOpen(v => !v)}
        className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4 cursor-pointer hover:border-violet-300 dark:hover:border-violet-500/40 transition-colors"
      >
        {/* Header */}
        <div className="flex items-center gap-2">
          <Database size={15} className="text-violet-500 shrink-0" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Ensemble Híbrido</span>
          {modelStatus?.model_ready
            ? <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/20 px-1.5 py-0.5 rounded">ACTIVO</span>
            : modelStatus && <span className="text-[10px] text-slate-400">{modelStatus.progress_pct}% entrenado</span>
          }
          <span className="ml-auto text-[11px] text-slate-400">{open ? '▲ cerrar' : '▼ ver detalle'}</span>
        </div>

        {/* Compact bar */}
        {modelStatus && (
          <div className="mt-3">
            <div className="flex justify-between text-xs mb-1">
              <span className="text-slate-500 dark:text-slate-400">Señales resueltas</span>
              <span className="font-mono font-semibold text-slate-600 dark:text-slate-300">{modelStatus.resolved_signals} / 50</span>
            </div>
            <div className="h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full transition-all', modelStatus.model_ready ? 'bg-emerald-500' : 'bg-violet-500')}
                style={{ width: `${modelStatus.progress_pct}%` }}
              />
            </div>
          </div>
        )}

        {/* Expanded detail */}
        {open && (
          <div className="mt-4 space-y-4 border-t border-slate-100 dark:border-slate-800 pt-4" onClick={e => e.stopPropagation()}>

            {/* What it does */}
            <div className="text-[11px] text-slate-500 dark:text-slate-400 space-y-1.5 leading-relaxed">
              <p><strong className="text-slate-600 dark:text-slate-300">¿Qué hace?</strong> Analiza cada señal ICT/SMC con un ensemble de 3 modelos (XGBoost + RandomForest + LogisticRegression) + meta-learner LR. Clasifica en:</p>
              <div className="flex flex-wrap gap-2 pt-0.5">
                {[
                  { label: 'CLEAR',   color: 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400', desc: 'alta probabilidad real' },
                  { label: 'CAUTION', color: 'bg-yellow-500/20 text-yellow-600 dark:text-yellow-400',   desc: 'dudosa, operar con cuidado' },
                  { label: 'BLOCK',   color: 'bg-red-500/20 text-red-600 dark:text-red-400',            desc: 'patrón de falsa ruptura' },
                ].map(({ label, color, desc }) => (
                  <span key={label} className={cn('text-[10px] font-bold px-2 py-1 rounded', color)}>
                    {label} <span className="font-normal opacity-80">— {desc}</span>
                  </span>
                ))}
              </div>
              <p className="pt-1">El modelo aprende de <strong className="text-slate-600 dark:text-slate-300">todos los pares</strong> — los features son estructurales (score, ADX, HTF bias, killzone, etc.), no dependen del símbolo. Cuantas más señales resueltas, mejor clasifica.</p>
            </div>

            {/* Metrics if ready */}
            {modelStatus?.model_ready && modelStatus.metrics && (
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'AUC-ROC', value: modelStatus.metrics.ensemble_auc ?? modelStatus.metrics.oof_auc ?? modelStatus.metrics.auc ?? '—' },
                  { label: 'Accuracy', value: (modelStatus.metrics.ensemble_accuracy ?? modelStatus.metrics.oof_accuracy ?? modelStatus.metrics.accuracy) != null ? `${((modelStatus.metrics.ensemble_accuracy ?? modelStatus.metrics.oof_accuracy ?? modelStatus.metrics.accuracy) * 100).toFixed(1)}%` : '—' },
                  { label: 'F1-Score', value: modelStatus.metrics.f1 ?? '—' },
                ].map(({ label, value }) => (
                  <div key={label} className="text-center bg-violet-50 dark:bg-violet-500/10 rounded-lg p-2">
                    <div className="text-[10px] text-slate-400 mb-0.5">{label}</div>
                    <div className="text-sm font-bold text-violet-700 dark:text-violet-400 font-mono">{value}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Win rate by confidence from stats */}
            {Object.keys(byConf).length > 0 && (
              <div>
                <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">Win Rate por clasificación Ensemble</div>
                <div className="space-y-2">
                  {[
                    { key: 'HIGH',   label: 'HIGH conf.',   color: 'bg-green-500' },
                    { key: 'MEDIUM', label: 'MEDIUM conf.', color: 'bg-yellow-500' },
                    { key: 'LOW',    label: 'LOW conf.',    color: 'bg-orange-500' },
                  ].map(({ key, label, color }) => {
                    const d = byConf[key] ?? {}
                    return (
                      <div key={key} className="flex items-center gap-3 text-xs">
                        <span className="w-24 text-slate-500 dark:text-slate-400 shrink-0">{label}</span>
                        <span className="text-slate-400 w-16 shrink-0">{d.total ?? 0} señales</span>
                        {d.win_rate != null ? (
                          <>
                            <div className="flex-1 h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                              <div className={cn('h-full rounded-full', color)} style={{ width: `${d.win_rate}%` }} />
                            </div>
                            <span className="font-bold tabular-nums w-10 text-right text-slate-600 dark:text-slate-300">{d.win_rate}%</span>
                          </>
                        ) : (
                          <span className="text-slate-400 text-[10px]">sin datos aún</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Train button */}
            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={triggerTrain}
                disabled={training || trained}
                className={cn(
                  'text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors',
                  trained
                    ? 'bg-emerald-100 border-emerald-300 text-emerald-700 dark:bg-emerald-500/20 dark:border-emerald-500/40 dark:text-emerald-400'
                    : 'bg-violet-100 border-violet-300 text-violet-700 hover:bg-violet-200 dark:bg-violet-500/20 dark:border-violet-500/40 dark:text-violet-400 dark:hover:bg-violet-500/30 disabled:opacity-50',
                )}
              >
                {training ? 'Encolando…' : trained ? '✓ Entrenamiento encolado' : 'Reentrenar ahora'}
              </button>
              <span className="text-[10px] text-slate-400">El entreno semanal es automático (dom. 03:00 UTC)</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Bot Activator Card ────────────────────────────────────────────────────────

function BotActivatorCard({ aiBots, tickerStats }) {
  const [open,    setOpen]    = useState(false)
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || signals.length > 0) return
    setLoading(true)
    aiService.listSignals(100)
      .then(r => setSignals(Array.isArray(r.data) ? r.data : []))
      .catch(() => setSignals([]))
      .finally(() => setLoading(false))
  }, [open, signals.length])

  // Stats for symbols covered by AI bots
  const botSymbols = useMemo(() => new Set(aiBots.map(b => {
    const s = b.symbol.replace('/USDT:USDT', 'USDT').replace('/USDC:USDC', 'USDC')
    return s
  })), [aiBots])

  const botSignals = useMemo(() =>
    signals.filter(s => botSymbols.has(s.ticker)),
  [signals, botSymbols])

  const resolved  = useMemo(() => botSignals.filter(s => s.outcome !== 'PENDING'), [botSignals])
  const wins      = useMemo(() => resolved.filter(s => s.outcome === 'SUCCESS').length, [resolved])
  const winRate   = resolved.length > 0 ? Math.round(wins / resolved.length * 100) : null
  const avgScore  = botSignals.length > 0 ? Math.round(botSignals.reduce((a, s) => a + s.score, 0) / botSignals.length) : null

  // Per-bot breakdown using tickerStats
  const botBreakdown = useMemo(() => aiBots.map(b => {
    const sym = b.symbol.replace('/USDT:USDT', 'USDT').replace('/USDC:USDC', 'USDC')
    const ts  = tickerStats[sym] ?? null
    return { ...b, ts }
  }), [aiBots, tickerStats])

  // Last 8 recent signals for these bots
  const recent = useMemo(() => botSignals.slice(0, 8), [botSignals])

  return (
    <div>
      <div
        onClick={() => setOpen(v => !v)}
        className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4 cursor-pointer hover:border-blue-300 dark:hover:border-blue-500/40 transition-colors"
      >
        {/* Header */}
        <div className="flex items-center gap-2">
          <Bot size={15} className="text-blue-500 shrink-0" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Bot Activator</span>
          {aiBots.length > 0
            ? <span className="text-[10px] font-bold text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-500/20 px-1.5 py-0.5 rounded">
                {aiBots.length} bot{aiBots.length > 1 ? 's' : ''} conectado{aiBots.length > 1 ? 's' : ''}
              </span>
            : null
          }
          <span className="ml-auto text-[11px] text-slate-400">{open ? '▲ cerrar' : '▼ ver historial'}</span>
        </div>

        {/* Compact bot list */}
        {aiBots.length === 0 ? (
          <p className="text-[11px] text-slate-400 dark:text-slate-500 leading-relaxed mt-2">
            Ningún bot configurado para auto-ejecutar señales IA.
            En <strong className="text-slate-500">Configuración de bot</strong> activa
            {' '}<em>Modo señal IA</em> para que las señales del scanner disparen órdenes reales.
          </p>
        ) : (
          <div className="mt-2 space-y-1">
            {aiBots.map(b => (
              <div key={b.id} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', b.status === 'active' ? 'bg-green-500' : 'bg-slate-400')} />
                  <span className="font-semibold text-slate-700 dark:text-slate-300 truncate">{b.bot_name}</span>
                  <span className="text-slate-400 shrink-0 text-[10px]">{baseOf(b.symbol.split('/')[0] ?? b.symbol)}</span>
                </div>
                <span className="text-[10px] text-slate-400 shrink-0 ml-2">{b.is_paper ? '📄 paper' : '🏦 live'}</span>
              </div>
            ))}
          </div>
        )}

        {/* Expanded historial */}
        {open && aiBots.length > 0 && (
          <div className="mt-4 space-y-4 border-t border-slate-100 dark:border-slate-800 pt-4" onClick={e => e.stopPropagation()}>

            {/* Cómo funciona */}
            <div className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed space-y-1">
              <p><strong className="text-slate-600 dark:text-slate-300">¿Qué busca?</strong> Señales ICT/SMC cuyo tier y status estén dentro de los filtros configurados en el bot (por defecto STRONG+CLEAR) + score ≥ min_score. La señal debe coincidir exactamente con el par configurado en el bot.</p>
              <p><strong className="text-slate-600 dark:text-slate-300">Riesgo:</strong> SL automático en el precio calculado por el ICT engine · TP1 60% de qty · TP2 40% · Circuit breaker: 3 SL seguidos → pausa automática.</p>
              <p><strong className="text-slate-600 dark:text-slate-300">Importante:</strong> El par debe estar en tu watchlist para que el scanner lo analice. Sin watchlist → sin señales → bot nunca se activa.</p>
            </div>

            {/* Summary stats */}
            {botSignals.length > 0 && (
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Señales IA',  value: botSignals.length },
                  { label: 'Win Rate',    value: winRate != null ? `${winRate}%` : '—',
                    color: winRate == null ? '' : winRate >= 55 ? 'text-green-600 dark:text-green-400' : 'text-red-500' },
                  { label: 'Score medio', value: avgScore ?? '—' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="text-center bg-blue-50 dark:bg-blue-500/10 rounded-lg p-2">
                    <div className="text-[10px] text-slate-400 mb-0.5">{label}</div>
                    <div className={cn('text-sm font-bold font-mono', color || 'text-blue-700 dark:text-blue-400')}>{value}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Per-bot breakdown */}
            {botBreakdown.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">Por bot</div>
                <div className="space-y-2">
                  {botBreakdown.map(b => {
                    const sym = b.symbol.replace('/USDT:USDT', 'USDT').replace('/USDC:USDC', 'USDC')
                    return (
                      <div key={b.id} className="flex items-center gap-3 text-xs bg-slate-50 dark:bg-slate-800/50 rounded-lg px-3 py-2">
                        <span className={cn('w-2 h-2 rounded-full shrink-0', b.status === 'active' ? 'bg-green-500' : 'bg-slate-400')} />
                        <div className="flex-1 min-w-0">
                          <span className="font-semibold text-slate-700 dark:text-slate-300 truncate block">{b.bot_name}</span>
                          <span className="text-[10px] text-slate-400">{sym} · {b.is_paper ? 'paper' : 'live'}</span>
                        </div>
                        {b.ts ? (
                          <div className="text-right shrink-0 space-y-0.5">
                            <div className="font-mono text-slate-600 dark:text-slate-300">{b.ts.total} señales</div>
                            <div className={cn('text-[10px] font-bold',
                              b.ts.win_rate == null ? 'text-slate-400' :
                              b.ts.win_rate >= 55 ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                              WR {b.ts.win_rate != null ? `${b.ts.win_rate}%` : '—'}
                            </div>
                          </div>
                        ) : (
                          <span className="text-[10px] text-slate-400 shrink-0">sin historial</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Recent signal log */}
            {loading && <div className="text-xs text-slate-400 animate-pulse text-center py-2">Cargando historial…</div>}
            {!loading && recent.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">Últimas señales IA para estos pares</div>
                <div className="space-y-1.5">
                  {recent.map(sig => {
                    const isLong = sig.direction === 'long'
                    const dt = new Date(sig.created_at)
                    return (
                      <div key={sig.id} className="flex items-center gap-2 text-xs bg-slate-50 dark:bg-slate-800/40 rounded-lg px-3 py-1.5">
                        <span className="text-slate-400 tabular-nums w-10 shrink-0">
                          {dt.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}
                        </span>
                        <span className="text-[10px] text-slate-400 shrink-0">
                          {dt.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' })}
                        </span>
                        <span className={cn('font-bold shrink-0', isLong ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                          {isLong ? '↑L' : '↓S'}
                        </span>
                        <span className="font-semibold text-slate-700 dark:text-slate-300 shrink-0">{baseOf(sig.ticker)}</span>
                        <span className="text-slate-400 shrink-0">{sig.timeframe}</span>
                        <span className="text-slate-500 tabular-nums shrink-0">{sig.score}</span>
                        <span className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0',
                          sig.quality_tier === 'STRONG' ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400' :
                          sig.quality_tier === 'MODERATE' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400' :
                          'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400'
                        )}>{sig.quality_tier}</span>
                        <div className="ml-auto shrink-0">
                          <OutcomeBadge outcome={sig.outcome} />
                        </div>
                      </div>
                    )
                  })}
                </div>
                {!loading && botSignals.length === 0 && (
                  <p className="text-[11px] text-slate-400 text-center py-3">Aún no hay señales registradas para estos pares.</p>
                )}
              </div>
            )}
            {!loading && botSignals.length === 0 && (
              <p className="text-[11px] text-slate-400 dark:text-slate-500 text-center py-2">
                Aún no hay señales registradas para los pares de estos bots.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Macro Context Bar ─────────────────────────────────────────────────────────

function MacroContextBar({ watchlist }) {
  const [alerts, setAlerts] = useState([])
  const [currentIndex, setCurrentIndex] = useState(0)

  // Carga macro context de toda la watchlist y filtra solo alertas
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!watchlist?.length) return
      const results = await Promise.allSettled(
        watchlist.map(item =>
          aiService.macroContext(item.symbol)
            .then(r => ({ symbol: item.symbol, data: r.data }))
            .catch(() => null)
        )
      )
      if (cancelled) return
      const newAlerts = results
        .filter(r => r.status === 'fulfilled' && r.value && r.value.data)
        .map(r => r.value)
        .filter(({ data }) => {
          const funding = data.funding || {}
          const events = data.high_impact_soon || []
          const rec = data.recommendation
          return (
            rec === 'avoid' ||
            rec === 'caution' ||
            funding.signal === 'extreme' ||
            funding.signal === 'high' ||
            events.length > 0
          )
        })
      setAlerts(newAlerts)
      setCurrentIndex(prev => (newAlerts.length ? 0 : prev))
    }

    load()
    const interval = setInterval(load, 60000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [watchlist])

  // Rotación automática tipo cartel cada 5 segundos
  useEffect(() => {
    if (alerts.length <= 1) return
    const interval = setInterval(() => {
      setCurrentIndex(prev => (prev + 1) % alerts.length)
    }, 5000)
    return () => clearInterval(interval)
  }, [alerts.length])

  if (alerts.length === 0) return null

  const current = alerts[currentIndex]
  const ctx = current.data
  const funding = ctx.funding || {}
  const events = ctx.high_impact_soon || []
  const rec = ctx.recommendation

  const borderColor = rec === 'avoid'
    ? 'border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/10'
    : rec === 'caution' || funding.signal === 'high' || events.length > 0
    ? 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/10'
    : 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/30'

  return (
    <div className={`rounded-lg border px-4 py-2.5 text-xs ${borderColor}`}>
      <div className="flex items-center gap-3 flex-wrap">
        <Globe size={14} className={
          rec === 'avoid' ? 'text-red-500' : 'text-amber-500'
        } />
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-700 dark:text-slate-200">Macro {current.symbol}</span>
          {funding.annualized_pct != null && (
            <span className={cn('font-mono',
              funding.signal === 'extreme' ? 'text-red-600 dark:text-red-400 font-bold' :
              funding.signal === 'high' ? 'text-amber-600 dark:text-amber-400' :
              'text-slate-500 dark:text-slate-400'
            )}>
              Funding {funding.annualized_pct > 0 ? '+' : ''}{funding.annualized_pct}%/año
            </span>
          )}
        </div>
        {events.length > 0 && (
          <div className="flex items-center gap-1.5 ml-auto">
            <span className="text-amber-600 dark:text-amber-400 font-medium">⚠ Eventos próximos:</span>
            {events.map(e => (
              <span key={e.title} className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-1.5 py-0.5">
                {e.title} ({e.minutes_until}min)
              </span>
            ))}
          </div>
        )}
        {alerts.length > 1 && (
          <span className="ml-auto text-[10px] text-slate-400 dark:text-slate-500 tabular-nums">
            {currentIndex + 1}/{alerts.length}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AIPage() {
  const [tab,              setTab]           = useState('operativa')
  const [watchlist,        setWatchlistRaw]  = useState(() => loadLS(WATCHLIST_KEY, DEFAULT_WATCHLIST))
  const [autoRefresh,      setAutoRefresh]   = useState(() => loadLS(AUTO_KEY, false))
  const [scanning,         setScanning]      = useState({})
  const [results,          setResults]       = useState({})
  const [selected,         setSelected]      = useState(null)   // { symbol, timeframe } | null
  const [stats,            setStats]         = useState(null)
  const [tickerStats,      setTickerStats]   = useState({})
  const [lastScan,         setLastScan]      = useState(() => {
    const ts = loadLS(LAST_SCAN_KEY, null)
    return ts ? new Date(ts) : null
  })
  const [nextScan,         setNextScan]      = useState(null)
  const [countdown,        setCountdown]     = useState(null)
  const [scanLog,          setScanLog]       = useState([])
  const [modelStatus,      setModelStatus]   = useState(null)
  const [aiBots,           setAiBots]        = useState([])
  const [loadingPersisted, setLoadingPersisted] = useState(true)
  const intervalRef = useRef(null)
  const syncRef     = useRef(null)

  const setWatchlist = useCallback((updater) => {
    setWatchlistRaw(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      saveLS(WATCHLIST_KEY, next)
      if (syncRef.current) clearTimeout(syncRef.current)
      syncRef.current = setTimeout(() => {
        aiService.syncWatchlist(next).catch(() => {})
      }, 500)
      return next
    })
  }, [])

  useEffect(() => { saveLS(AUTO_KEY, autoRefresh) }, [autoRefresh])

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      // 1. Preferir watchlist del backend; solo usar localStorage como fallback
      let watchlistItems = []
      try {
        const res = await aiService.getWatchlist()
        if (res?.data && Array.isArray(res.data) && res.data.length > 0) {
          watchlistItems = res.data.map(e => ({ symbol: e.symbol, timeframe: e.timeframe }))
          saveLS(WATCHLIST_KEY, watchlistItems)
        }
      } catch {}

      // Si backend vacío o falló, usar localStorage / default
      if (watchlistItems.length === 0) {
        watchlistItems = loadLS(WATCHLIST_KEY, DEFAULT_WATCHLIST)
        // Sync al backend para que la próxima vez esté persistido
        aiService.syncWatchlist(watchlistItems).catch(() => {})
      }

      if (!cancelled) setWatchlistRaw(watchlistItems)

      const syms = watchlistItems.map(e => e.symbol)
      if (syms.length > 0) {
        try {
          const scanRes = await aiService.latestScans(syms)
          const data = scanRes?.data
          if (!cancelled && data && typeof data === 'object' && !Array.isArray(data)) {
            const newResults = {}
            Object.entries(data).forEach(([sym, d]) => {
              newResults[sym] = {
                ...d,
                symbol:    sym,
                timeframe: d.timeframe ?? watchlistItems.find(e => e.symbol === sym)?.timeframe ?? '1h',
                scannedAt: d.scanned_at ? new Date(d.scanned_at) : null,
              }
            })
            if (!cancelled) setResults(newResults)
          }
        } catch {}
      }

      if (!cancelled) setLoadingPersisted(false)

      aiService.stats()
        .then(r => { if (!cancelled) setStats(!Array.isArray(r.data) ? r.data : null) })
        .catch(() => {})
      aiService.statsByTicker()
        .then(r => { if (!cancelled && r.data && typeof r.data === 'object') setTickerStats(r.data) })
        .catch(() => {})
      aiService.modelStatus()
        .then(r => { if (!cancelled) setModelStatus(r.data) })
        .catch(() => {})
      aiService.listAiBots()
        .then(r => { if (!cancelled) setAiBots(Array.isArray(r.data) ? r.data : []) })
        .catch(() => {})
    }

    bootstrap()
    return () => { cancelled = true }
  }, [])

  const refreshStats = useCallback(() => {
    aiService.stats()
      .then(r => {
        const s = !Array.isArray(r.data) ? r.data : null
        setStats(s)
        if (s?.last_scan_at) {
          const d = new Date(s.last_scan_at)
          setLastScan(d)
          saveLS(LAST_SCAN_KEY, d.toISOString())
        }
      })
      .catch(() => {})
    aiService.statsByTicker()
      .then(r => { if (r.data && typeof r.data === 'object') setTickerStats(r.data) })
      .catch(() => {})
  }, [])

  // Refrescar stats (y la hora del último scan de Celery) cada minuto
  useEffect(() => {
    refreshStats()
    const id = setInterval(refreshStats, 60000)
    return () => clearInterval(id)
  }, [refreshStats])

  useEffect(() => {
    if (!autoRefresh || !nextScan) { setCountdown(null); return }
    const tick = setInterval(() => {
      setCountdown(Math.max(0, Math.ceil((nextScan.getTime() - Date.now()) / 1000)))
    }, 1000)
    return () => clearInterval(tick)
  }, [autoRefresh, nextScan])

  const scanOne = useCallback(async (symbol, timeframe) => {
    setScanning(s => ({ ...s, [symbol]: true }))
    try {
      const res  = await aiService.analyze(symbol, timeframe)
      const data = res.data ?? {}
      const now = new Date()
      setResults(r => ({ ...r, [symbol]: { ...data, symbol, timeframe, scannedAt: now } }))
      setLastScan(now)
      saveLS(LAST_SCAN_KEY, now.toISOString())
      refreshStats()
    } catch {
      setResults(r => ({ ...r, [symbol]: { symbol, timeframe, status: 'ERROR', scannedAt: new Date() } }))
    } finally {
      setScanning(s => { const n = { ...s }; delete n[symbol]; return n })
    }
  }, [refreshStats])

  const scanAll = useCallback(async (type = 'manual') => {
    if (!watchlist.length) return
    setScanning(Object.fromEntries(watchlist.map(e => [e.symbol, true])))
    let signalCount = 0

    // Limit concurrent scans to avoid overwhelming the backend / exchange rate limits
    const asyncPool = async (poolLimit, array, iteratorFn) => {
      const ret = []
      const executing = []
      for (const item of array) {
        const p = Promise.resolve().then(() => iteratorFn(item))
        ret.push(p)
        if (array.length >= poolLimit) {
          const e = p.then(() => executing.splice(executing.indexOf(e), 1))
          executing.push(e)
          if (executing.length >= poolLimit) await Promise.race(executing)
        }
      }
      return Promise.all(ret)
    }

    await asyncPool(
      4,
      watchlist,
      ({ symbol, timeframe }) =>
        aiService.analyze(symbol, timeframe)
          .then(res => {
            const data = res.data ?? {}
            if (data.status === 'SIGNAL') signalCount++
            setResults(r => ({ ...r, [symbol]: { ...data, symbol, timeframe, scannedAt: new Date() } }))
          })
          .catch(() => {
            setResults(r => ({ ...r, [symbol]: { symbol, timeframe, status: 'ERROR', scannedAt: new Date() } }))
          })
          .finally(() => {
            setScanning(s => { const n = { ...s }; delete n[symbol]; return n })
          })
    )
    const now = new Date()
    setLastScan(now)
    saveLS(LAST_SCAN_KEY, now.toISOString())
    setScanLog(log => [{ time: now, type, symbols: watchlist.length, signals: signalCount }, ...log].slice(0, 8))
    refreshStats()
  }, [watchlist, refreshStats])

  useEffect(() => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    if (autoRefresh) {
      setNextScan(new Date(Date.now() + AUTO_INTERVAL))
      intervalRef.current = setInterval(() => {
        scanAll('auto')
        setNextScan(new Date(Date.now() + AUTO_INTERVAL))
      }, AUTO_INTERVAL)
    } else {
      setNextScan(null)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [autoRefresh, scanAll])

  const addSymbol = (sym) => {
    if (!watchlist.some(e => e.symbol === sym) && watchlist.length < 15)
      setWatchlist(w => [...w, { symbol: sym, timeframe: '1h' }])
  }
  const removeSymbol = (sym) => {
    setWatchlist(w => w.filter(e => e.symbol !== sym))
    setResults(r => { const n = { ...r }; delete n[sym]; return n })
    setScanning(s => { const n = { ...s }; delete n[sym]; return n })
  }
  const changeTimeframe = (sym, tf) => {
    setWatchlist(w => w.map(e => e.symbol === sym ? { ...e, timeframe: tf } : e))
    setResults(r => { const n = { ...r }; delete n[sym]; return n })
  }

  const isAnyScanning = Object.keys(scanning).length > 0
  const signalCount   = watchlist.filter(e => results[e.symbol]?.status === 'SIGNAL').length

  // Map watchlist symbol (e.g. "XRPUSDT") → bot names that have ai_signal_mode for it
  const aiBotsBySymbol = useMemo(() => {
    const map = {}
    aiBots.forEach(b => {
      // Normalize ccxt symbol "XRP/USDT:USDT" → "XRPUSDT"
      const normalized = b.symbol
        .replace(/\/([^:]+):[^:]+$/, '$1')  // "XRP/USDT:USDT" → "XRPUSDT"
        .replace('/', '')
      if (!map[normalized]) map[normalized] = []
      map[normalized].push(b.bot_name)
    })
    return map
  }, [aiBots])

  return (
    <div className="space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <Brain size={20} className="text-blue-500 shrink-0" />
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">IA Confluence Scanner</h1>
            <span className="text-xs bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400 px-2 py-0.5 rounded font-semibold">
              ICT + SMC
            </span>
            {signalCount > 0 && (
              <span className="flex items-center gap-1 text-xs bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400 px-2 py-0.5 rounded font-bold">
                <Zap size={11} /> {signalCount} señal{signalCount > 1 ? 'es' : ''}
              </span>
            )}
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-xl">
            Añade los pares que quieras vigilar, asigna la temporalidad y pulsa{' '}
            <strong className="text-slate-700 dark:text-slate-300">Escanear todo</strong>. Haz clic en
            cualquier caja para ver el gráfico con overlays ICT+SMC y el historial de señales.
          </p>
        </div>
        <div className="ml-auto">
          <SymbolPicker watchlist={watchlist} onAdd={addSymbol} />
        </div>
        {lastScan && (
          <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0 self-start pt-1">
            Último: {lastScan.toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Main tab toggle */}
      <div className="flex gap-0 border-b border-slate-200 dark:border-slate-800 -mb-1">
        {[
          { id: 'operativa',   label: 'Operativa',            icon: <Zap size={13} /> },
          { id: 'real',        label: 'Rendimiento real',     icon: <TrendingUp size={13} /> },
          { id: 'laboratorio', label: 'Laboratorio / Simulado', icon: <BarChart2 size={13} /> },
          { id: 'live',        label: 'Scanner Live',         icon: <ScanLine size={13} /> },
          { id: 'control',     label: 'Control del motor',    icon: <SlidersHorizontal size={13} /> },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} className={cn(
            'flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
            tab === t.id
              ? 'border-blue-500 text-blue-600 dark:text-blue-400'
              : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300',
          )}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === 'laboratorio' && <LaboratorioTab stats={stats} lastScan={lastScan} />}

      {tab === 'real'       && <RealPerformanceTab />}

      {tab === 'control' && (
        <Suspense fallback={
          <div className="py-20 text-center">
            <div className="animate-spin inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full" />
            <p className="text-sm text-slate-400 mt-3">Cargando Control del Motor IA…</p>
          </div>
        }>
          <AIEngineControlTab />
        </Suspense>
      )}

      {tab === 'live' && (
        <Suspense fallback={
          <div className="py-20 text-center">
            <div className="animate-spin inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full" />
            <p className="text-sm text-slate-400 mt-3">Cargando Scanner Live…</p>
          </div>
        }>
          <IALiveScannerTab />
        </Suspense>
      )}

      {tab === 'operativa' && (
        <IAMissionControlTab
          watchlist={watchlist}
          results={results}
          scanning={scanning}
          tickerStats={tickerStats}
          aiBots={aiBots}
          selected={selected}
          autoRefresh={autoRefresh}
          lastScan={lastScan}
          countdown={countdown}
          isAnyScanning={isAnyScanning}
          onSelect={(sym, tf) => setSelected({ symbol: sym, timeframe: tf })}
          onRemove={removeSymbol}
          onChangeTimeframe={changeTimeframe}
          onScanOne={scanOne}
          onScanAll={() => scanAll('manual')}
          onToggleAutoRefresh={() => setAutoRefresh((v) => !v)}
        />
      )}


      {/* Symbol detail panel */}
      {selected && (
        <SymbolDetailPanel
          symbol={selected.symbol}
          timeframe={selected.timeframe}
          onClose={() => setSelected(null)}
          aiBots={aiBots}
        />
      )}
    </div>
  )
}
