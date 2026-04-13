import { useEffect, useRef, useCallback, useState } from 'react'
import { createChart, LineStyle } from 'lightweight-charts'
import api from '@/services/api'

// ── Helpers de fecha ──────────────────────────────────────────

function toISO(d) { return d.toISOString().slice(0, 10) }

function getPreset(key) {
  const today = new Date()
  const y = today.getFullYear()
  const m = today.getMonth()
  const d = today.getDate()
  const dow = today.getDay() // 0=dom

  switch (key) {
    case 'today':
      return { from: toISO(today), to: toISO(today) }
    case '7d': {
      const from = new Date(today); from.setDate(d - 6)
      return { from: toISO(from), to: toISO(today) }
    }
    case 'week': {
      const mon = new Date(today); mon.setDate(d - ((dow + 6) % 7))
      return { from: toISO(mon), to: toISO(today) }
    }
    case '30d': {
      const from = new Date(today); from.setDate(d - 29)
      return { from: toISO(from), to: toISO(today) }
    }
    case 'month':
      return { from: toISO(new Date(y, m, 1)), to: toISO(today) }
    case '3m': {
      const from = new Date(today); from.setDate(d - 89)
      return { from: toISO(from), to: toISO(today) }
    }
    case 'year':
      return { from: toISO(new Date(y, 0, 1)), to: toISO(today) }
    default:
      return { from: null, to: null }
  }
}

const PRESETS = [
  { key: 'today', label: 'Hoy'         },
  { key: '7d',    label: 'Últ. 7d'     },
  { key: 'week',  label: 'Semana'      },
  { key: '30d',   label: 'Últ. 30d'   },
  { key: 'month', label: 'Mes'         },
  { key: '3m',    label: 'Trim.'       },
  { key: 'year',  label: 'Año'         },
]

// ── Gráfico Acumulado (área) ───────────────────────────────────

function AreaChart({ data, height = 260, isDark }) {
  const containerRef = useRef(null)
  const chartRef     = useRef(null)
  const seriesRef    = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return
    const bgColor    = isDark ? '#111827' : '#ffffff'
    const textColor  = isDark ? '#9ca3af' : '#64748b'
    const gridColor  = isDark ? '#1f2937' : '#e2e8f0'
    const borderColor= isDark ? '#374151' : '#cbd5e1'

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
      layout: { background: { color: bgColor }, textColor },
      grid:   { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      rightPriceScale: { borderColor },
      timeScale: { borderColor, timeVisible: true },
    })

    const series = chart.addAreaSeries({
      lineColor:   '#3b82f6',
      topColor:    'rgba(59,130,246,0.28)',
      bottomColor: 'rgba(59,130,246,0.02)',
      lineWidth: 2,
      crosshairMarkerVisible: true,
    })

    series.createPriceLine({
      price: 0, color: isDark ? '#6b7280' : '#94a3b8',
      lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false,
    })

    chartRef.current  = chart
    seriesRef.current = series

    const ro = new ResizeObserver(entries => {
      chart.applyOptions({ width: entries[0].contentRect.width })
    })
    ro.observe(containerRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [height, isDark])

  useEffect(() => {
    if (!seriesRef.current || !data.length) return
    seriesRef.current.setData(
      data.map(p => ({ time: p.date, value: parseFloat(p.cumulative_pnl) }))
    )
    chartRef.current?.timeScale().fitContent()
  }, [data])

  return <div ref={containerRef} className="w-full" style={{ height }} />
}

// ── Gráfico Diario (barras) ────────────────────────────────────

function BarChart({ data, height = 260, isDark }) {
  const containerRef = useRef(null)
  const chartRef     = useRef(null)
  const seriesRef    = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return
    const bgColor    = isDark ? '#111827' : '#ffffff'
    const textColor  = isDark ? '#9ca3af' : '#64748b'
    const gridColor  = isDark ? '#1f2937' : '#e2e8f0'
    const borderColor= isDark ? '#374151' : '#cbd5e1'

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
      layout: { background: { color: bgColor }, textColor },
      grid:   { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      rightPriceScale: { borderColor },
      timeScale: { borderColor, timeVisible: true },
    })

    const series = chart.addHistogramSeries({
      color: 'rgba(74,222,128,0.8)',
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    })

    series.createPriceLine({
      price: 0, color: isDark ? '#6b7280' : '#94a3b8',
      lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false,
    })

    chartRef.current  = chart
    seriesRef.current = series

    const ro = new ResizeObserver(entries => {
      chart.applyOptions({ width: entries[0].contentRect.width })
    })
    ro.observe(containerRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [height, isDark])

  useEffect(() => {
    if (!seriesRef.current || !data.length) return
    seriesRef.current.setData(
      data.map(p => {
        const v = parseFloat(p.daily_pnl)
        return {
          time:  p.date,
          value: v,
          color: v >= 0 ? 'rgba(74,222,128,0.8)' : 'rgba(248,113,113,0.8)',
        }
      })
    )
    chartRef.current?.timeScale().fitContent()
  }, [data])

  return <div ref={containerRef} className="w-full" style={{ height }} />
}

// ── PnlChart principal ────────────────────────────────────────

export default function PnlChart() {
  const [preset,    setPreset]    = useState('30d')
  const [from,      setFrom]      = useState('')
  const [to,        setTo]        = useState('')
  const [symbol,    setSymbol]    = useState('')
  const [source,    setSource]    = useState('')
  const [symbols,   setSymbols]   = useState([])
  const [data,      setData]      = useState([])
  const [loading,   setLoading]   = useState(false)
  const [isDark,    setIsDark]    = useState(false)
  const [chartMode, setChartMode] = useState('cumulative') // 'cumulative' | 'daily'

  // Detectar tema
  useEffect(() => {
    const checkDark = () => setIsDark(document.documentElement.classList.contains('dark'))
    checkDark()
    const observer = new MutationObserver(checkDark)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])

  const fetchData = useCallback(async (params) => {
    setLoading(true)
    try {
      const qs = new URLSearchParams()
      if (params.from)   qs.set('from_date', params.from)
      if (params.to)     qs.set('to_date',   params.to)
      if (params.symbol) qs.set('symbol',    params.symbol)
      if (params.source) qs.set('source',    params.source)
      const res = await api.get(`/analytics/pnl-chart?${qs}`)
      setData(res.data)
    } catch {
      setData([])
    } finally {
      setLoading(false)
    }
  }, [])

  // Cargar símbolos disponibles
  useEffect(() => {
    api.get('/analytics/symbols').then(r => setSymbols(r.data.symbols || [])).catch(() => {})
  }, [])

  // Carga inicial
  useEffect(() => {
    const p = getPreset(preset)
    fetchData({ ...p, symbol, source })
  }, []) // eslint-disable-line

  const applyPreset = (key) => {
    setPreset(key)
    setFrom(''); setTo('')
    const p = getPreset(key)
    fetchData({ ...p, symbol, source })
  }

  const applyCustomRange = () => {
    setPreset(null)
    fetchData({ from, to, symbol, source })
  }

  const applySymbol = (s) => {
    setSymbol(s)
    const p = preset ? getPreset(preset) : { from, to }
    fetchData({ ...p, symbol: s, source })
  }

  const applySource = (s) => {
    setSource(s)
    const p = preset ? getPreset(preset) : { from, to }
    fetchData({ ...p, symbol, source: s })
  }

  // ── Estadísticas del período ──────────────────────────────
  const totalPnl     = data.reduce((s, d) => s + parseFloat(d.daily_pnl), 0)
  const totalTrades  = data.reduce((s, d) => s + (d.trade_count || 0), 0)
  const winDays      = data.filter(d => parseFloat(d.daily_pnl) > 0).length
  const lossDays     = data.filter(d => parseFloat(d.daily_pnl) < 0).length
  const winDayRate   = (winDays + lossDays) > 0
    ? Math.round(winDays / (winDays + lossDays) * 100)
    : 0
  const bestDay      = data.length ? Math.max(...data.map(d => parseFloat(d.daily_pnl))) : 0
  const worstDay     = data.length ? Math.min(...data.map(d => parseFloat(d.daily_pnl))) : 0
  const isPos        = totalPnl >= 0

  const STATS = [
    { label: 'PnL del período',  value: `${isPos ? '+' : ''}${totalPnl.toFixed(2)} USDT`, color: isPos ? 'text-green-400' : 'text-red-400' },
    { label: 'Trades cerrados',  value: totalTrades,                                        color: 'text-slate-700 dark:text-white' },
    { label: 'Win rate (días)',  value: `${winDayRate}%`,                                   color: winDayRate >= 50 ? 'text-green-400' : 'text-red-400' },
    { label: 'Días positivos',   value: winDays,                                            color: 'text-green-400' },
    { label: 'Días negativos',   value: lossDays,                                           color: 'text-red-400' },
    { label: 'Mejor día',        value: `${bestDay >= 0 ? '+' : ''}${bestDay.toFixed(2)}`, color: 'text-blue-400' },
    { label: 'Peor día',         value: `${worstDay >= 0 ? '+' : ''}${worstDay.toFixed(2)}`, color: worstDay >= 0 ? 'text-blue-400' : 'text-red-400' },
  ]

  return (
    <div className="card space-y-4">
      {/* ── Cabecera: título + toggle modo ── */}
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold text-slate-900 dark:text-white shrink-0">PnL</h2>

        {/* Toggle Acumulado / Diario */}
        <div className="flex rounded-md overflow-hidden border border-slate-300 dark:border-gray-700 shrink-0">
          {[
            { key: 'cumulative', label: 'Acumulado' },
            { key: 'daily',      label: 'Diario'    },
          ].map(opt => (
            <button
              key={opt.key}
              onClick={() => setChartMode(opt.key)}
              className={`px-2.5 py-1 text-xs transition-colors ${
                chartMode === opt.key
                  ? 'bg-blue-600 text-white'
                  : 'bg-white dark:bg-gray-900 text-slate-600 dark:text-gray-400 hover:bg-slate-100 dark:hover:bg-gray-800'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="w-px h-4 bg-slate-300 dark:bg-gray-700 shrink-0" />

        {/* Presets */}
        {PRESETS.map(p => (
          <button
            key={p.key}
            onClick={() => applyPreset(p.key)}
            className={`px-2.5 py-1 text-xs rounded transition-colors shrink-0 ${
              preset === p.key
                ? 'bg-blue-600 text-white'
                : 'bg-slate-100 dark:bg-gray-800 text-slate-600 dark:text-gray-400 hover:bg-slate-200 dark:hover:bg-gray-700'
            }`}
          >
            {p.label}
          </button>
        ))}

        <div className="w-px h-4 bg-slate-300 dark:bg-gray-700 shrink-0" />

        {/* Rango personalizado */}
        <input
          type="date" value={from} onChange={e => setFrom(e.target.value)}
          className="bg-white dark:bg-gray-800 border border-slate-300 dark:border-gray-700 text-xs text-slate-700 dark:text-gray-300 rounded px-2 py-1"
        />
        <span className="text-slate-500 dark:text-gray-500 text-xs shrink-0">→</span>
        <input
          type="date" value={to} onChange={e => setTo(e.target.value)}
          className="bg-white dark:bg-gray-800 border border-slate-300 dark:border-gray-700 text-xs text-slate-700 dark:text-gray-300 rounded px-2 py-1"
        />
        <button
          onClick={applyCustomRange}
          disabled={!from && !to}
          className="px-2.5 py-1 text-xs bg-slate-200 dark:bg-gray-700 hover:bg-slate-300 dark:hover:bg-gray-600 text-slate-800 dark:text-white rounded disabled:opacity-40 transition-colors shrink-0"
        >
          Aplicar
        </button>

        {/* Símbolo */}
        {symbols.length > 0 && (
          <>
            <div className="w-px h-4 bg-slate-300 dark:bg-gray-700 shrink-0" />
            <select
              value={symbol} onChange={e => applySymbol(e.target.value)}
              className="bg-white dark:bg-gray-800 border border-slate-300 dark:border-gray-700 text-xs text-slate-700 dark:text-gray-300 rounded px-2 py-1"
            >
              <option value="">Todos los pares</option>
              {[...new Set(symbols)].sort().map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </>
        )}

        {/* Fuente */}
        <div className="w-px h-4 bg-slate-300 dark:bg-gray-700 shrink-0" />
        <select
          value={source} onChange={e => applySource(e.target.value)}
          className="bg-white dark:bg-gray-800 border border-slate-300 dark:border-gray-700 text-xs text-slate-700 dark:text-gray-300 rounded px-2 py-1"
        >
          <option value="">Todos</option>
          <option value="bots">Solo bots</option>
          <option value="manual">Solo manuales</option>
        </select>
      </div>

      {/* ── Stats del período ── */}
      {data.length > 0 && (
        <div className="grid grid-cols-4 sm:grid-cols-7 gap-2">
          {STATS.map(s => (
            <div key={s.label} className="bg-slate-100 dark:bg-gray-800/60 rounded-lg px-2 py-2 text-center">
              <p className={`text-sm font-bold font-mono ${s.color}`}>{s.value}</p>
              <p className="text-[10px] text-slate-500 dark:text-gray-400 mt-0.5 leading-tight">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* ── Gráfico ── */}
      {loading ? (
        <div className="flex items-center justify-center h-[260px] text-slate-500 dark:text-gray-400 text-sm">
          Cargando…
        </div>
      ) : data.length === 0 ? (
        <div className="flex items-center justify-center h-[260px] text-slate-600 dark:text-gray-500 text-sm">
          Sin trades en este período
        </div>
      ) : chartMode === 'cumulative' ? (
        <AreaChart data={data} height={260} isDark={isDark} />
      ) : (
        <BarChart data={data} height={260} isDark={isDark} />
      )}

      {/* Nota UTC */}
      <p className="text-[10px] text-slate-400 dark:text-gray-600 text-right -mt-2">
        Fechas en UTC · datos de trades cerrados sincronizados
      </p>
    </div>
  )
}
