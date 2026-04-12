import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { createChart } from 'lightweight-charts'
import { analyticsService } from '@/services/analytics'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import { Sparkles, TrendingUp, TrendingDown, Minus, Download, RefreshCw } from 'lucide-react'

// ─── Helpers ──────────────────────────────────────────────────

function fmt(v, dec = 2) {
  return Number(v ?? 0).toFixed(dec)
}

function signed(v, dec = 2) {
  const n = Number(v ?? 0)
  return `${n >= 0 ? '+' : ''}${n.toFixed(dec)}`
}

function pct(v, dec = 1) {
  return `${(Number(v ?? 0) * 100).toFixed(dec)}%`
}

function formatCompact(num, dec = 2) {
  const n = Number(num ?? 0)
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(dec)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(dec)}k`
  return n.toFixed(dec)
}

const RANGES = [
  { label: '7d',  days: 7  },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: 'Todo', days: null },
]

function rangeFromDays(days) {
  if (!days) return { from: null, to: null }
  const to   = new Date()
  const from = new Date()
  from.setDate(from.getDate() - days)
  return {
    from: from.toISOString().slice(0, 10),
    to:   to.toISOString().slice(0, 10),
  }
}

// ─── Stat card ────────────────────────────────────────────────

function StatCard({ label, value, sub, color = 'default', icon }) {
  const colors = {
    default: 'text-slate-900 dark:text-gray-100',
    green:   'text-green-400',
    red:     'text-red-400',
    yellow:  'text-yellow-400',
    blue:    'text-blue-400',
  }
  return (
    <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl p-4 space-y-1">
      <p className="text-xs text-slate-500 dark:text-gray-400 flex items-center gap-1">
        {icon && icon}
        {label}
      </p>
      <p className={`text-xl font-bold font-mono ${colors[color]}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 dark:text-gray-500">{sub}</p>}
    </div>
  )
}

// ─── Win rate bar ─────────────────────────────────────────────

function WinRateBar({ rate }) {
  const pctNum = Math.round(rate * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-slate-200 dark:bg-gray-700 rounded-full h-1.5">
        <div
          className={`h-1.5 rounded-full ${pctNum >= 50 ? 'bg-green-400' : 'bg-red-400'}`}
          style={{ width: `${pctNum}%` }}
        />
      </div>
      <span className={`text-xs font-mono w-10 text-right ${pctNum >= 50 ? 'text-green-400' : 'text-red-400'}`}>
        {pctNum}%
      </span>
    </div>
  )
}

// ─── Streak badge ─────────────────────────────────────────────

function StreakBadge({ streak }) {
  if (streak === 0) return <span className="text-slate-400 text-xs">—</span>
  const isWin = streak > 0
  const n     = Math.abs(streak)
  return (
    <span className={`inline-flex items-center gap-1 text-sm font-bold px-2 py-0.5 rounded-lg ${
      isWin
        ? 'bg-green-500/10 text-green-400 border border-green-500/30'
        : 'bg-red-500/10 text-red-400 border border-red-500/30'
    }`}>
      {isWin ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
      {n} {isWin ? 'wins' : 'losses'} consecutivos
    </span>
  )
}

// ─── Equity chart (line) ──────────────────────────────────────

function EquityChart({ data, isDark }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || !data?.length) return

    const bg      = isDark ? '#030712' : '#ffffff'
    const text    = isDark ? '#9ca3af' : '#64748b'
    const grid    = isDark ? '#1f2937' : '#e2e8f0'

    const chart = createChart(ref.current, {
      layout:     { background: { color: bg }, textColor: text },
      grid:       { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale:  { borderColor: grid },
      rightPriceScale: { borderColor: grid },
      height: 220,
    })

    const series = chart.addLineSeries({
      color: '#3b82f6', lineWidth: 2,
      crosshairMarkerVisible: true,
      priceFormat: { type: 'custom', formatter: v => `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)} USDT` },
    })

    // Área bajo la línea
    const area = chart.addAreaSeries({
      topColor:    'rgba(59,130,246,0.15)',
      bottomColor: 'rgba(59,130,246,0)',
      lineColor:   'transparent',
      lineWidth:   0,
    })

    const points = data.map(p => ({
      time:  Math.floor(new Date(p.timestamp).getTime() / 1000),
      value: parseFloat(p.cumulative_pnl),
    }))

    series.setData(points)
    area.setData(points)
    chart.timeScale().fitContent()

    const obs = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    obs.observe(ref.current)

    return () => { chart.remove(); obs.disconnect() }
  }, [data, isDark])

  if (!data?.length) return (
    <div className="h-[220px] flex items-center justify-center text-slate-400 dark:text-gray-500 text-sm">
      Sin datos de equity
    </div>
  )

  return <div ref={ref} className="w-full" />
}

// ─── PnL diario (barras) ──────────────────────────────────────

function DailyPnlChart({ data, isDark }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current) return

    const bg   = isDark ? '#030712' : '#ffffff'
    const text = isDark ? '#9ca3af' : '#64748b'
    const grid = isDark ? '#1f2937' : '#e2e8f0'

    const chart = createChart(ref.current, {
      layout:     { background: { color: bg }, textColor: text },
      grid:       { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale:  { borderColor: grid },
      rightPriceScale: { borderColor: grid },
      height: 180,
    })

    const series = chart.addHistogramSeries({
      priceFormat: { type: 'custom', formatter: v => `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}` },
    })

    series.setData(
      (data || []).map(p => ({
        time:  p.date,
        value: parseFloat(p.daily_pnl),
        color: parseFloat(p.daily_pnl) >= 0 ? '#22c55e' : '#ef4444',
      }))
    )

    chart.timeScale().fitContent()

    const obs = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    obs.observe(ref.current)

    return () => { chart.remove(); obs.disconnect() }
  }, [data, isDark])

  if (!data?.length) return (
    <div className="h-[180px] flex items-center justify-center text-slate-400 dark:text-gray-500 text-sm">
      Sin datos de PnL diario
    </div>
  )

  return <div ref={ref} className="w-full" />
}

// ─── Página principal ──────────────────────────────────────────

export default function AnalyticsPage() {
  const [summary, setSummary]     = useState(null)
  const [dailyPnl, setDailyPnl]   = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [range, setRange]         = useState(RANGES[1])   // 30d por defecto
  const [isDark, setIsDark]       = useState(false)

  useEffect(() => {
    const check = () => setIsDark(document.documentElement.classList.contains('dark'))
    check()
    const obs = new MutationObserver(check)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])

  const load = useCallback(async (selectedRange) => {
    setLoading(true)
    try {
      const { from, to } = rangeFromDays(selectedRange.days)
      const [summaryRes, pnlRes] = await Promise.all([
        analyticsService.summary(),
        analyticsService.pnlChart({ from_date: from, to_date: to }),
      ])
      setSummary(summaryRes.data)
      setDailyPnl(pnlRes.data)
    } catch (err) {
      console.error('Error cargando analytics:', err)
      setError('No se pudieron cargar las estadísticas')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(range) }, [range, load])

  // Exportar datos a CSV
  const exportToCSV = useCallback(() => {
    if (!dailyPnl?.length) return
    const headers = ['Fecha', 'PnL Diario', 'PnL Acumulado']
    const rows = dailyPnl.map(d => [d.date, d.daily_pnl, d.cumulative_pnl])
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `analytics_${range.label}_${new Date().toISOString().slice(0,10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [dailyPnl, range.label])

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>
  if (error || !summary) return (
    <div className="text-center py-20">
      <p className="text-slate-400 mb-4">{error || 'No se pudieron cargar las estadísticas'}</p>
      <button
        onClick={() => load(range)}
        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2 mx-auto"
      >
        <RefreshCw size={16} /> Reintentar
      </button>
    </div>
  )

  const g = summary.global_stats

  // Optimizar cálculos de estadísticas diarias
  const dailyStats = useMemo(() => {
    if (!dailyPnl?.length) return null
    const positive = dailyPnl.filter(d => parseFloat(d.daily_pnl) > 0).length
    const negative = dailyPnl.filter(d => parseFloat(d.daily_pnl) < 0).length
    const best = Math.max(...dailyPnl.map(d => parseFloat(d.daily_pnl)))
    const worst = Math.min(...dailyPnl.map(d => parseFloat(d.daily_pnl)))
    return { positive, negative, best, worst }
  }, [dailyPnl])

  const pnlColor  = parseFloat(g.total_pnl) >= 0 ? 'green' : 'red'
  const ddColor   = parseFloat(g.max_drawdown) > 0 ? 'red' : 'default'

  return (
    <div className="space-y-6">

      {/* Header + rango */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Analytics</h1>
        <div className="flex gap-1 bg-slate-100 dark:bg-gray-800 rounded-lg p-1">
          {RANGES.map(r => (
            <button
              key={r.label}
              onClick={() => setRange(r)}
              aria-pressed={range.label === r.label}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                range.label === r.label
                  ? 'bg-white dark:bg-gray-700 text-slate-900 dark:text-white shadow-sm'
                  : 'text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-200'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Racha actual */}
      {g.current_streak !== 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-gray-400">Racha actual:</span>
          <StreakBadge streak={g.current_streak} />
        </div>
      )}

      {/* Fila 1: resultados principales */}
      <div>
        <p className="text-xs font-semibold text-slate-400 dark:text-gray-500 uppercase tracking-wide mb-3">
          Rendimiento global · {g.total_trades} trades
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="PnL total" value={`${signed(g.total_pnl)} USDT`}
            sub={`Media ${signed(g.average_pnl)} / trade`}
            color={pnlColor} />
          <StatCard label="Win rate"
            value={pct(g.win_rate)}
            sub={`${g.winning_trades}W · ${g.losing_trades}L`}
            color={g.win_rate >= 0.5 ? 'green' : 'red'} />
          <StatCard label="Profit factor"
            value={g.profit_factor != null ? fmt(g.profit_factor) : '—'}
            sub="ganancia / pérdida"
            color={g.profit_factor >= 1.5 ? 'green' : g.profit_factor >= 1 ? 'yellow' : 'red'} />
          <StatCard label="Max drawdown"
            value={`-${fmt(g.max_drawdown)} USDT`}
            sub="caída máx. desde pico"
            color={ddColor} />
        </div>
      </div>

      {/* Fila 2: detalles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Mejor trade"  value={`+${fmt(g.best_trade)} USDT`}  color="green" />
        <StatCard label="Peor trade"   value={`${signed(g.worst_trade)} USDT`} color="red" />
        <StatCard label="Duración media" value={`${fmt(g.avg_duration_hours, 1)}h`} sub="por operación" />
        <StatCard label="Trades totales" value={g.total_trades}
          sub={`${g.long_trades} longs · ${g.short_trades} shorts`} />
      </div>

      {/* Fila 3: Long vs Short */}
      {(g.long_trades > 0 || g.short_trades > 0) && (
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl p-4 space-y-2">
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-green-400" />
              <p className="text-xs font-semibold text-slate-600 dark:text-gray-300">LONG</p>
              <span className="text-xs text-slate-400">{g.long_trades} trades</span>
            </div>
            <p className={`text-lg font-bold font-mono ${parseFloat(g.long_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {signed(g.long_pnl)} USDT
            </p>
            <WinRateBar rate={g.long_win_rate} />
          </div>
          <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl p-4 space-y-2">
            <div className="flex items-center gap-2">
              <TrendingDown size={14} className="text-red-400" />
              <p className="text-xs font-semibold text-slate-600 dark:text-gray-300">SHORT</p>
              <span className="text-xs text-slate-400">{g.short_trades} trades</span>
            </div>
            <p className={`text-lg font-bold font-mono ${parseFloat(g.short_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {signed(g.short_pnl)} USDT
            </p>
            <WinRateBar rate={g.short_win_rate} />
          </div>
        </div>
      )}

      {/* Curva de equity */}
      <div className="card space-y-3">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200">Curva de equity</h2>
        <EquityChart data={summary.equity_curve} isDark={isDark} />
      </div>

      {/* PnL diario */}
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200">PnL diario</h2>
          <div className="flex items-center gap-2">
            {dailyPnl.length > 0 && (
              <button
                onClick={exportToCSV}
                className="flex items-center gap-1 text-xs px-2 py-1 text-slate-500 hover:text-slate-700 dark:text-gray-400 dark:hover:text-gray-200 bg-slate-100 dark:bg-gray-800 rounded-lg transition-colors"
                title="Exportar a CSV"
              >
                <Download size={12} /> CSV
              </button>
            )}
            <span className="text-xs text-slate-400 dark:text-gray-500">{range.label}</span>
          </div>
        </div>
        <DailyPnlChart data={dailyPnl} isDark={isDark} />
        {dailyStats && (
          <div className="flex flex-wrap gap-4 text-xs text-slate-500 dark:text-gray-400 pt-1 border-t border-slate-200 dark:border-gray-700">
            <span>
              Días positivos: <span className="text-green-400 font-medium">{dailyStats.positive}</span>
            </span>
            <span>
              Días negativos: <span className="text-red-400 font-medium">{dailyStats.negative}</span>
            </span>
            <span>
              Mejor día: <span className="text-green-400 font-medium">+{fmt(dailyStats.best)} USDT</span>
            </span>
            {dailyStats.worst < 0 && (
              <span>
                Peor día: <span className="text-red-400 font-medium">{signed(dailyStats.worst)} USDT</span>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Por bot */}
      <div className="card space-y-4">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200">Por bot</h2>

        {summary.by_bot.filter(b => b.total_trades > 0).length === 0 ? (
          <p className="text-slate-500 dark:text-gray-400 text-sm">Sin trades registrados</p>
        ) : (
          <div className="space-y-3">
            {summary.by_bot.filter(b => b.total_trades > 0).map(bot => (
              <div key={bot.bot_id}
                className="border border-slate-200 dark:border-gray-700 rounded-xl p-4 space-y-3">

                {/* Header del bot */}
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-gray-100">{bot.bot_name}</p>
                    <p className="text-xs text-slate-400 dark:text-gray-500">{bot.symbol} · {bot.total_trades} trades</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-bold font-mono ${parseFloat(bot.total_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {signed(bot.total_pnl)} USDT
                    </span>
                    <Link to={`/bots/${bot.bot_id}/optimizer`}
                      className="p-1.5 text-slate-400 hover:text-blue-400 rounded" title="Optimizador">
                      <Sparkles size={14} />
                    </Link>
                  </div>
                </div>

                {/* Métricas del bot */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <div>
                    <p className="text-slate-400 dark:text-gray-500 mb-1">Win rate</p>
                    <WinRateBar rate={bot.win_rate} />
                  </div>
                  <div>
                    <p className="text-slate-400 dark:text-gray-500 mb-1">Profit factor</p>
                    <span className={`font-mono font-semibold ${
                      bot.profit_factor >= 1.5 ? 'text-green-400'
                      : bot.profit_factor >= 1  ? 'text-yellow-400'
                      : 'text-red-400'
                    }`}>
                      {bot.profit_factor != null ? fmt(bot.profit_factor) : '—'}
                    </span>
                  </div>
                  <div>
                    <p className="text-slate-400 dark:text-gray-500 mb-1">Mejor trade</p>
                    <span className="text-green-400 font-mono">+{fmt(bot.best_trade)}</span>
                  </div>
                  <div>
                    <p className="text-slate-400 dark:text-gray-500 mb-1">Peor trade</p>
                    <span className="text-red-400 font-mono">{signed(bot.worst_trade)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Bots sin trades */}
        {summary.by_bot.filter(b => b.total_trades === 0).length > 0 && (
          <div className="border-t border-slate-200 dark:border-gray-700 pt-3">
            <p className="text-xs text-slate-400 dark:text-gray-500 mb-2">Sin trades aún:</p>
            <div className="flex flex-wrap gap-2">
              {summary.by_bot.filter(b => b.total_trades === 0).map(bot => (
                <span key={bot.bot_id}
                  className="text-xs px-2 py-1 bg-slate-100 dark:bg-gray-800 rounded-lg text-slate-500 dark:text-gray-400">
                  {bot.bot_name} · {bot.symbol}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
