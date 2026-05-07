import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import {
  BarChart2, Bot, Brain, CheckCircle2, Clock, Database, Filter,
  Plus, RefreshCw, ScanLine, TrendingDown, TrendingUp,
  X, XCircle, Zap,
} from 'lucide-react'
import { aiService }             from '@/services/aiService'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import { cn } from '@/utils/cn'

// ── Constants ─────────────────────────────────────────────────────────────────

const TIMEFRAMES    = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d']
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
  const cls = pct >= 75
    ? 'text-green-600 dark:text-green-400'
    : pct >= 55
      ? 'text-yellow-600 dark:text-yellow-400'
      : 'text-orange-600 dark:text-orange-400'
  const bar = pct >= 75 ? '#16a34a' : pct >= 55 ? '#ca8a04' : '#ea580c'
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

function QualityBadge({ tier, status }) {
  const tierMap = {
    STRONG:   'bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-500/20 dark:text-emerald-400 dark:border-emerald-500/30',
    MODERATE: 'bg-yellow-100 text-yellow-700 border-yellow-300 dark:bg-yellow-500/20 dark:text-yellow-400 dark:border-yellow-500/30',
    WEAK:     'bg-orange-100 text-orange-700 border-orange-300 dark:bg-orange-500/20 dark:text-orange-400 dark:border-orange-500/30',
  }
  const statusMap = {
    CLEAR:   'text-emerald-600 dark:text-emerald-400',
    CAUTION: 'text-amber-600 dark:text-amber-400',
    BLOCK:   'text-red-600 dark:text-red-400',
  }
  const statusLabel = { CLEAR: 'CLEAR', CAUTION: '⚠ CAUTION', BLOCK: '✕ BLOCK' }
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {tier && (
        <span className={cn('text-[9px] font-bold px-1.5 py-0.5 rounded border tracking-wide', tierMap[tier])}>
          {tier}
        </span>
      )}
      {status && (
        <span className={cn('text-[9px] font-semibold', statusMap[status])}>
          {statusLabel[status]}
        </span>
      )}
    </div>
  )
}

// ── Signal day row (used inside SymbolModal) ──────────────────────────────────

function SignalDayRow({ sig }) {
  const isLong = sig.direction === 'long'
  const time   = new Date(sig.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const confs  = sig.components ? Object.values(sig.components) : []

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
          {sig.anti_fake_status && (
            <span className={cn(
              'text-[9px] font-semibold shrink-0',
              sig.anti_fake_status === 'CLEAR'   ? 'text-emerald-600 dark:text-emerald-400' :
              sig.anti_fake_status === 'CAUTION' ? 'text-yellow-600 dark:text-yellow-400'  :
                                                   'text-red-600 dark:text-red-400',
            )}>
              XGB {sig.anti_fake_status}
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
      <div className="shrink-0 mt-0.5">
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

// ── Symbol detail modal ───────────────────────────────────────────────────────

function SymbolModal({ symbol, timeframe, onClose }) {
  const [chartData, setChartData] = useState(null)
  const [signals,   setSignals]   = useState([])
  const [loading,   setLoading]   = useState(true)
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
                    {sigs.map(sig => <SignalDayRow key={sig.id} sig={sig} />)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Symbol Slot Card ──────────────────────────────────────────────────────────

function SlotCard({ entry, result, scanning, tickerStats, aiBotNames, onRemove, onChangeTimeframe, onScanOne, onSelect }) {
  const { symbol, timeframe } = entry
  const status   = result?.status
  const isSignal = status === 'SIGNAL'
  const hasAiBot = aiBotNames?.length > 0

  return (
    <div
      onClick={() => { if (!scanning) onSelect(symbol, timeframe) }}
      className={cn(
        'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3',
        'cursor-pointer select-none transition-shadow',
        !scanning && 'hover:shadow-md hover:border-slate-300 dark:hover:border-slate-600',
        scanning && 'opacity-70 cursor-wait',
        isSignal && result.direction === 'long'  && 'ring-1 ring-green-500/40',
        isSignal && result.direction === 'short' && 'ring-1 ring-red-500/40',
        hasAiBot && 'ring-1 ring-blue-400/30',
      )}
    >
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
              {result.direction.toUpperCase()}
            </span>
            <OutcomeBadge outcome={result.outcome} />
          </div>
          <ScoreMeter score={result.score} />
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <ConfBadge confidence={result.confidence} />
            {result.quality_tier && (
              <QualityBadge tier={result.quality_tier} status={result.anti_fake_status} />
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
            </span>
            <span className="text-slate-400">
              Win:{' '}
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
        {result?.anti_fake_status ? (
          <span className={cn(
            'ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded',
            result.anti_fake_status === 'CLEAR'   ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400' :
            result.anti_fake_status === 'CAUTION' ? 'bg-yellow-500/20 text-yellow-600 dark:text-yellow-400' :
                                                    'bg-red-500/20 text-red-600 dark:text-red-400',
          )}>
            XGB {result.anti_fake_status}
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

// ── Backtest Tab ──────────────────────────────────────────────────────────────

function BacktestTab() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter,  setFilter]  = useState('ALL')

  useEffect(() => {
    aiService.listSignals(200)
      .then(r => setSignals(Array.isArray(r.data) ? r.data : []))
      .catch(() => setSignals([]))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() =>
    filter === 'ALL' ? signals : signals.filter(s => s.quality_tier === filter),
  [signals, filter])

  const resolved = useMemo(() => filtered.filter(s => s.outcome !== 'PENDING'), [filtered])
  const wins     = useMemo(() => resolved.filter(s => s.outcome === 'SUCCESS').length, [resolved])
  const winRate  = resolved.length > 0 ? Math.round(wins / resolved.length * 100) : null

  const pnlPoints = useMemo(() => {
    const sorted = [...filtered]
      .filter(s => s.outcome !== 'PENDING' && s.outcome !== 'EXPIRED')
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    let cum = 0
    return sorted.map(s => {
      const pnl = s.pnl_pct != null ? s.pnl_pct : (s.outcome === 'SUCCESS' ? 1.5 : -1.0)
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
    const res = sub.filter(s => s.outcome !== 'PENDING')
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
                  {['Fecha', 'Par', 'TF', 'Dir.', 'Score', 'ADX', 'Tier', 'HTF', 'Outcome', 'P&L'].map(h => (
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

// ── Stats Bar ─────────────────────────────────────────────────────────────────

function StatsBar({ stats }) {
  if (!stats) return null

  // DB health: how stale is the last background scan?
  const lastScanAt   = stats.last_scan_at ? new Date(stats.last_scan_at) : null
  const ageMin       = lastScanAt ? Math.floor((Date.now() - lastScanAt.getTime()) / 60000) : null
  const scanHealth   = ageMin == null ? 'unknown' : ageMin <= 7 ? 'ok' : ageMin <= 20 ? 'warn' : 'stale'
  const healthColor  = { ok: 'bg-green-500', warn: 'bg-yellow-400', stale: 'bg-red-500', unknown: 'bg-slate-400' }
  const healthLabel  = { ok: `hace ${ageMin}m`, warn: `hace ${ageMin}m`, stale: `hace ${ageMin}m`, unknown: '—' }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Señales totales', value: stats.total ?? 0 },
          { label: 'Win rate',        value: stats.win_rate != null ? `${stats.win_rate}%` : '—' },
          { label: 'Score promedio',  value: stats.avg_score ?? '—' },
          { label: 'Datos XGBoost',   value: stats.model_ready ? '✓ Listo' : `${stats.resolved ?? 0} / 200` },
        ].map(({ label, value }) => (
          <div key={label} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3 text-center">
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
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Anti-Fake XGBoost</span>
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
              <span className="font-mono font-semibold text-slate-600 dark:text-slate-300">{modelStatus.resolved_signals} / 200</span>
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
              <p><strong className="text-slate-600 dark:text-slate-300">¿Qué hace?</strong> Analiza cada señal ICT/SMC y la puntúa con un modelo XGBoost entrenado con el historial de señales pasadas. Clasifica en:</p>
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
                  { label: 'AUC-ROC', value: modelStatus.metrics.auc },
                  { label: 'Accuracy', value: `${(modelStatus.metrics.accuracy * 100).toFixed(1)}%` },
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
                <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">Win Rate por clasificación XGBoost</div>
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
            {' '}<em>Modo señal IA</em> para que las señales STRONG+CLEAR disparen órdenes reales.
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
              <p><strong className="text-slate-600 dark:text-slate-300">¿Qué busca?</strong> Señales ICT/SMC con tier <strong>STRONG</strong> + XGBoost <strong>CLEAR</strong> + score ≥ min_score. La señal debe coincidir exactamente con el par configurado en el bot.</p>
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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AIPage() {
  const [tab,              setTab]           = useState('scanner')
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
      const localWL = loadLS(WATCHLIST_KEY, DEFAULT_WATCHLIST)
      aiService.syncWatchlist(localWL).catch(() => {})

      const syms = localWL.map(e => e.symbol)
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
                timeframe: d.timeframe ?? localWL.find(e => e.symbol === sym)?.timeframe ?? '1h',
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
      .then(r => setStats(!Array.isArray(r.data) ? r.data : null))
      .catch(() => {})
    aiService.statsByTicker()
      .then(r => { if (r.data && typeof r.data === 'object') setTickerStats(r.data) })
      .catch(() => {})
  }, [])

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
      setResults(r => ({ ...r, [symbol]: { ...data, symbol, timeframe, scannedAt: new Date() } }))
      if (data.status === 'SIGNAL') refreshStats()
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
    await Promise.all(
      watchlist.map(({ symbol, timeframe }) =>
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
        {lastScan && (
          <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0 self-start pt-1">
            Último: {lastScan.toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Tab toggle */}
      <div className="flex gap-0 border-b border-slate-200 dark:border-slate-800 -mb-1">
        {[
          { id: 'scanner',  label: 'Scanner',  icon: <ScanLine size={13} /> },
          { id: 'backtest', label: 'Backtest', icon: <BarChart2 size={13} /> },
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

      {/* Global stats */}
      <StatsBar stats={stats} />

      {tab === 'backtest' && <BacktestTab />}

      {tab === 'scanner' && (<>
      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={() => scanAll('manual')}
          disabled={isAnyScanning || !watchlist.length}
          className="btn-primary flex items-center gap-2 text-sm"
        >
          {isAnyScanning
            ? <><RefreshCw size={14} className="animate-spin" />Escaneando…</>
            : <><ScanLine size={14} />Escanear todo ({watchlist.length})</>}
        </button>

        <button
          onClick={() => setAutoRefresh(v => !v)}
          title="Repite el scan automáticamente cada 5 minutos"
          className={cn(
            'flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border transition-colors',
            autoRefresh
              ? 'bg-blue-100 border-blue-300 text-blue-700 dark:bg-blue-600/20 dark:border-blue-500/40 dark:text-blue-400'
              : 'bg-slate-100 border-slate-300 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-700',
          )}
        >
          <Clock size={13} />
          Auto-scan {autoRefresh ? 'ON · 5 min' : 'OFF'}
        </button>

        <div className="ml-auto">
          <SymbolPicker watchlist={watchlist} onAdd={addSymbol} />
        </div>
      </div>

      {/* Auto-scan status bar */}
      {autoRefresh && (
        <div className={cn(
          'flex items-center gap-4 px-4 py-2.5 rounded-lg border text-xs flex-wrap',
          isAnyScanning
            ? 'bg-blue-50 border-blue-200 dark:bg-blue-500/10 dark:border-blue-500/30'
            : 'bg-slate-50 border-slate-200 dark:bg-slate-800/50 dark:border-slate-700',
        )}>
          <div className="flex items-center gap-2">
            <span className={cn(
              'w-2 h-2 rounded-full shrink-0',
              isAnyScanning ? 'bg-blue-500 animate-ping' : 'bg-green-500 animate-pulse',
            )} />
            <span className={cn(
              'font-semibold',
              isAnyScanning ? 'text-blue-700 dark:text-blue-400' : 'text-slate-700 dark:text-slate-300',
            )}>
              {isAnyScanning ? 'Escaneando mercado…' : 'Auto-scan activo'}
            </span>
          </div>
          {!isAnyScanning && countdown !== null && (
            <span className="text-slate-500 dark:text-slate-400">
              Próximo en{' '}
              <strong className="text-slate-700 dark:text-slate-200 tabular-nums">
                {Math.floor(countdown / 60)}:{String(countdown % 60).padStart(2, '0')}
              </strong>
            </span>
          )}
          {lastScan && !isAnyScanning && (
            <span className="text-slate-400 dark:text-slate-500">Último: {lastScan.toLocaleTimeString()}</span>
          )}
          {!isAnyScanning && countdown !== null && (
            <div className="flex-1 min-w-16 max-w-32 ml-auto">
              <div className="h-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-400 dark:bg-blue-500 rounded-full transition-all duration-1000"
                  style={{ width: `${((AUTO_INTERVAL / 1000 - countdown) / (AUTO_INTERVAL / 1000)) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Symbol grid */}
      {loadingPersisted ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {watchlist.map(entry => (
            <div key={entry.symbol} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3 space-y-2 animate-pulse">
              <div className="flex items-center gap-2">
                <div className="h-4 w-12 bg-slate-200 dark:bg-slate-700 rounded" />
                <div className="h-3 w-8 bg-slate-100 dark:bg-slate-800 rounded ml-auto" />
              </div>
              <div className="h-3 w-full bg-slate-100 dark:bg-slate-800 rounded" />
              <div className="h-3 w-3/4 bg-slate-100 dark:bg-slate-800 rounded" />
            </div>
          ))}
        </div>
      ) : watchlist.length === 0 ? (
        <div className="text-center py-16 text-slate-400 dark:text-slate-600">
          <ScanLine size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Usa <strong className="text-slate-500 dark:text-slate-500">Añadir par</strong> para construir tu watchlist</p>
          <p className="text-xs mt-1">Máximo 15 pares simultáneos</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {watchlist.map(entry => (
            <SlotCard
              key={entry.symbol}
              entry={entry}
              result={results[entry.symbol]}
              scanning={!!scanning[entry.symbol]}
              tickerStats={tickerStats[entry.symbol] ?? null}
              aiBotNames={aiBotsBySymbol[entry.symbol] ?? null}
              onRemove={removeSymbol}
              onChangeTimeframe={changeTimeframe}
              onScanOne={scanOne}
              onSelect={(sym, tf) => setSelected({ symbol: sym, timeframe: tf })}
            />
          ))}
        </div>
      )}

      {/* Scan activity log */}
      {scanLog.length > 0 && (
        <div className="border-t border-slate-200 dark:border-slate-800 pt-4">
          <div className="text-xs font-semibold text-slate-400 dark:text-slate-500 mb-2 uppercase tracking-wide">
            Actividad del scanner
          </div>
          <div className="space-y-1">
            {scanLog.map((entry, i) => (
              <div key={i} className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-500">
                <span className="tabular-nums text-slate-400 dark:text-slate-600 w-16 shrink-0">
                  {entry.time.toLocaleTimeString()}
                </span>
                <span className={cn(
                  'px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0',
                  entry.type === 'auto'
                    ? 'bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400'
                    : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
                )}>
                  {entry.type === 'auto' ? 'AUTO' : 'MANUAL'}
                </span>
                <span>{entry.symbols} par{entry.symbols !== 1 ? 'es' : ''} analizados</span>
                {entry.signals > 0
                  ? <span className="text-yellow-600 dark:text-yellow-400 font-semibold">
                      {entry.signals} señal{entry.signals !== 1 ? 'es' : ''} detectada{entry.signals !== 1 ? 's' : ''}
                    </span>
                  : <span className="text-slate-400 dark:text-slate-600">sin señales</span>
                }
              </div>
            ))}
          </div>
        </div>
      )}

      {/* XGBoost + Bot Activator */}
      <XGBoostCard modelStatus={modelStatus} stats={stats} />
      <BotActivatorCard aiBots={aiBots} tickerStats={tickerStats} />
      </>)}

      {/* Symbol detail modal */}
      {selected && (
        <SymbolModal
          symbol={selected.symbol}
          timeframe={selected.timeframe}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
