import { useEffect, useRef, useCallback, useState, useMemo } from 'react'
import { createChart, LineStyle } from 'lightweight-charts'
import api from '@/services/api'
import useBalanceStore from '@/store/balanceStore'
import { getDateRange, toISODate } from '@/utils/dateRanges'

// ── Helpers de fecha ──────────────────────────────────────────

function getPreset(key) {
  const today = new Date()
  const y = today.getFullYear()
  const m = today.getMonth()
  const d = today.getDate()
  const dow = today.getDay() // 0=dom

  switch (key) {
    case 'today':
      return { from: toISODate(today), to: toISODate(today) }
    case '7d':
      return getDateRange(7)
    case 'week': {
      const mon = new Date(today); mon.setDate(d - ((dow + 6) % 7))
      return { from: toISODate(mon), to: toISODate(today) }
    }
    case '30d':
      return getDateRange(30)
    case 'month':
      return { from: toISODate(new Date(y, m, 1)), to: toISODate(today) }
    case '3m':
      return getDateRange(90)
    case 'year':
      return { from: toISODate(new Date(y, 0, 1)), to: toISODate(today) }
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

function formatTime(time, isHourly) {
  if (!time) return ''
  // lightweight-charts puede devolver un string ISO o un objeto { year, month, day, hour, minute }
  if (typeof time === 'string') {
    const [datePart, timePart] = time.split(' ')
    if (isHourly && timePart) return `${datePart} ${timePart}`
    return datePart
  }
  const { year, month, day, hour } = time
  const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  if (isHourly && hour !== undefined) {
    return `${dateStr} ${String(hour).padStart(2, '0')}:00`
  }
  return dateStr
}

function formatValue(value, valueMode) {
  const n = parseFloat(value)
  const suffix = valueMode === 'percent' ? ' %PnL' : ' USDT'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}${suffix}`
}

// ── Tooltip HTML flotante ─────────────────────────────────────

function Tooltip({ point, title, value, time, isDark, isHourly }) {
  if (!point || value === undefined || value === null) return null

  return (
    <div
      className="pointer-events-none absolute z-10 rounded-md border px-2.5 py-1.5 text-xs shadow-md"
      style={{
        left: point.x + 12,
        top: point.y - 12,
        backgroundColor: isDark ? '#1f2937' : '#ffffff',
        borderColor: isDark ? '#374151' : '#e2e8f0',
        color: isDark ? '#e5e7eb' : '#1f2937',
      }}
    >
      <div className="font-medium">{title}</div>
      <div className="text-[10px] opacity-80">{formatTime(time, isHourly)}</div>
      <div className={`font-mono font-semibold ${parseFloat(value) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
        {formatValue(value, 'usdt')}
      </div>
    </div>
  )
}

// ── Gráfico Acumulado (área) ───────────────────────────────────

function AreaChart({ data, height = 260, isDark, valueMode = 'usdt', isHourly = false }) {
  const containerRef = useRef(null)
  const chartRef     = useRef(null)
  const seriesRef    = useRef(null)
  const [tooltip, setTooltip] = useState(null)

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
      timeScale: { borderColor, timeVisible: isHourly },
      crosshair: { mode: 1, horzLine: { visible: true }, vertLine: { visible: true } },
      localization: {
        priceFormatter: (price) => formatValue(price, valueMode),
      },
    })

    const series = chart.addAreaSeries({
      lineColor:   '#3b82f6',
      topColor:    'rgba(59,130,246,0.28)',
      bottomColor: 'rgba(59,130,246,0.02)',
      lineWidth: 2,
      crosshairMarkerVisible: true,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      lastValueVisible: false,
      priceLineVisible: false,
    })

    series.createPriceLine({
      price: 0, color: isDark ? '#6b7280' : '#94a3b8',
      lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false,
    })

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined) {
        setTooltip(null)
        return
      }
      const seriesData = param.seriesData.get(series)
      if (!seriesData) {
        setTooltip(null)
        return
      }
      setTooltip({
        point: param.point,
        time: param.time,
        value: seriesData.value,
      })
    })

    chartRef.current  = chart
    seriesRef.current = series

    const ro = new ResizeObserver(entries => {
      chart.applyOptions({ width: entries[0].contentRect.width })
    })
    ro.observe(containerRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [height, isDark, valueMode, isHourly])

  useEffect(() => {
    if (!seriesRef.current || !data.length) return
    seriesRef.current.setData(
      data.map(p => ({ time: p.date, value: parseFloat(p.cumulative_pnl) }))
    )
    chartRef.current?.timeScale().fitContent()
  }, [data])

  return (
    <div ref={containerRef} className="relative w-full" style={{ height }}>
      <Tooltip
        point={tooltip?.point}
        time={tooltip?.time}
        value={tooltip?.value}
        title="PnL acumulado"
        isDark={isDark}
        isHourly={isHourly}
      />
    </div>
  )
}

// ── Gráfico Diario (barras) ────────────────────────────────────

function BarChart({ data, height = 260, isDark, valueMode = 'usdt', isHourly = false }) {
  const containerRef = useRef(null)
  const chartRef     = useRef(null)
  const seriesRef    = useRef(null)
  const [tooltip, setTooltip] = useState(null)

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
      timeScale: { borderColor, timeVisible: isHourly },
      crosshair: { mode: 1, horzLine: { visible: true }, vertLine: { visible: true } },
      localization: {
        priceFormatter: (price) => formatValue(price, valueMode),
      },
    })

    const series = chart.addHistogramSeries({
      color: 'rgba(74,222,128,0.8)',
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      lastValueVisible: false,
      priceLineVisible: false,
    })

    series.createPriceLine({
      price: 0, color: isDark ? '#6b7280' : '#94a3b8',
      lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false,
    })

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined) {
        setTooltip(null)
        return
      }
      const seriesData = param.seriesData.get(series)
      if (!seriesData) {
        setTooltip(null)
        return
      }
      setTooltip({
        point: param.point,
        time: param.time,
        value: seriesData.value,
      })
    })

    chartRef.current  = chart
    seriesRef.current = series

    const ro = new ResizeObserver(entries => {
      chart.applyOptions({ width: entries[0].contentRect.width })
    })
    ro.observe(containerRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [height, isDark, valueMode, isHourly])

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

  return (
    <div ref={containerRef} className="relative w-full" style={{ height }}>
      <Tooltip
        point={tooltip?.point}
        time={tooltip?.time}
        value={tooltip?.value}
        title={isHourly ? 'PnL horario' : 'PnL diario'}
        isDark={isDark}
        isHourly={isHourly}
      />
    </div>
  )
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
  const [valueMode, setValueMode] = useState('usdt') // 'usdt' | 'percent'

  // Detectar tema
  useEffect(() => {
    const checkDark = () => setIsDark(document.documentElement.classList.contains('dark'))
    checkDark()
    const observer = new MutationObserver(checkDark)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])

  const fetchData = useCallback(async (params, isHourly = false) => {
    setLoading(true)
    try {
      if (isHourly) {
        const qs = new URLSearchParams()
        if (params.from)   qs.set('from_date', params.from)
        if (params.to)     qs.set('to_date',   params.to)
        if (params.symbol) qs.set('symbol',    params.symbol)
        if (params.source) qs.set('source',    params.source)
        const res = await api.get(`/analytics/hourly-distribution?${qs}`)

        const baseDate = params.from || new Date().toISOString().slice(0, 10)
        let cumulative = 0
        const transformed = []
        for (let hour = 0; hour < 24; hour++) {
          const h = (res.data || []).find(d => d.hour === hour)
          const pnl = h ? parseFloat(h.pnl || 0) : 0
          const trades = h ? h.trades : 0
          cumulative += pnl
          transformed.push({
            date: `${baseDate} ${String(hour).padStart(2, '0')}:00`,
            daily_pnl: pnl,
            cumulative_pnl: cumulative,
            trade_count: trades,
          })
        }
        setData(transformed)
      } else {
        const qs = new URLSearchParams()
        if (params.from)   qs.set('from_date', params.from)
        if (params.to)     qs.set('to_date',   params.to)
        if (params.symbol) qs.set('symbol',    params.symbol)
        if (params.source) qs.set('source',    params.source)
        const res = await api.get(`/analytics/pnl-chart?${qs}`)
        setData(res.data)
      }
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
    fetchData({ ...p, symbol, source }, preset === 'today')
  }, []) // eslint-disable-line

  const applyPreset = (key) => {
    setPreset(key)
    setFrom(''); setTo('')
    const p = getPreset(key)
    fetchData({ ...p, symbol, source }, key === 'today')
  }

  const applyCustomRange = () => {
    setPreset(null)
    fetchData({ from, to, symbol, source }, false)
  }

  const applySymbol = (s) => {
    setSymbol(s)
    const p = preset ? getPreset(preset) : { from, to }
    fetchData({ ...p, symbol: s, source }, preset === 'today')
  }

  const applySource = (s) => {
    setSource(s)
    const p = preset ? getPreset(preset) : { from, to }
    fetchData({ ...p, symbol, source: s }, preset === 'today')
  }

  // Equity para cálculo de %
  const totalEquity = useBalanceStore(s => s.getTotalEquity())

  // Datos transformados según modo de visualización
  const displayData = useMemo(() => {
    if (valueMode === 'usdt' || totalEquity <= 0) return data
    return data.map(d => ({
      ...d,
      cumulative_pnl: (parseFloat(d.cumulative_pnl) / totalEquity) * 100,
      daily_pnl: (parseFloat(d.daily_pnl) / totalEquity) * 100,
    }))
  }, [data, valueMode, totalEquity])

  // ── Estadísticas del período ──────────────────────────────
  const totalPnl     = displayData.reduce((s, d) => s + parseFloat(d.daily_pnl), 0)
  const totalTrades  = data.reduce((s, d) => s + (d.trade_count || 0), 0)
  const winDays      = displayData.filter(d => parseFloat(d.daily_pnl) > 0).length
  const lossDays     = displayData.filter(d => parseFloat(d.daily_pnl) < 0).length
  const winDayRate   = (winDays + lossDays) > 0
    ? Math.round(winDays / (winDays + lossDays) * 100)
    : 0
  const bestDay      = displayData.length ? Math.max(...displayData.map(d => parseFloat(d.daily_pnl))) : 0
  const worstDay     = displayData.length ? Math.min(...displayData.map(d => parseFloat(d.daily_pnl))) : 0
  const isPos        = totalPnl >= 0
  const suffix       = valueMode === 'percent' ? ' %PnL' : ' USDT'
  const numFmt       = (n) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}${suffix}`

  const isHourly = preset === 'today'
  const STATS = [
    { label: 'PnL del período',  value: numFmt(totalPnl),              color: isPos ? 'text-green-400' : 'text-red-400' },
    { label: 'Trades cerrados',  value: totalTrades,                   color: 'text-slate-700 dark:text-white' },
    { label: isHourly ? 'Win rate (horas)' : 'Win rate (días)',  value: `${winDayRate}%`,              color: winDayRate >= 50 ? 'text-green-400' : 'text-red-400' },
    { label: isHourly ? 'Horas positivas' : 'Días positivos',   value: winDays,                       color: 'text-green-400' },
    { label: isHourly ? 'Horas negativas' : 'Días negativos',   value: lossDays,                      color: 'text-red-400' },
    { label: isHourly ? 'Mejor hora' : 'Mejor día',        value: numFmt(bestDay),               color: 'text-blue-400' },
    { label: isHourly ? 'Peor hora' : 'Peor día',         value: numFmt(worstDay),              color: worstDay >= 0 ? 'text-blue-400' : 'text-red-400' },
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
            { key: 'daily',      label: isHourly ? 'Horario' : 'Diario' },
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
        <div className="w-px h-4 bg-slate-300 dark:border-gray-700 shrink-0" />
        <select
          value={source} onChange={e => applySource(e.target.value)}
          className="bg-white dark:bg-gray-800 border border-slate-300 dark:border-gray-700 text-xs text-slate-700 dark:text-gray-300 rounded px-2 py-1"
        >
          <option value="">Todos</option>
          <option value="bot_int">Bot int. (señales internas)</option>
          <option value="bot_ext">Bot ext. (señales externas por webhook)</option>
          <option value="ai_bot">Bot IA</option>
          <option value="app_manual">Manual</option>
          <option value="paper">Paper</option>
          <option value="manual">BingX Manual</option>
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

      {/* Toggle USDT / % */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500 dark:text-gray-400">Mostrar en:</span>
        <div className="flex rounded-md overflow-hidden border border-slate-300 dark:border-gray-700">
          {[
            { key: 'usdt',    label: 'USDT' },
            { key: 'percent', label: '%PnL' },
          ].map(opt => (
            <button
              key={opt.key}
              onClick={() => setValueMode(opt.key)}
              className={`px-2.5 py-1 text-xs transition-colors ${
                valueMode === opt.key
                  ? 'bg-blue-600 text-white'
                  : 'bg-white dark:bg-gray-900 text-slate-600 dark:text-gray-400 hover:bg-slate-100 dark:hover:bg-gray-800'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

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
        <AreaChart key={`area-${isHourly ? 'hourly' : 'daily'}`} data={displayData} height={260} isDark={isDark} valueMode={valueMode} isHourly={isHourly} />
      ) : (
        <BarChart key={`bar-${isHourly ? 'hourly' : 'daily'}`} data={displayData} height={260} isDark={isDark} valueMode={valueMode} isHourly={isHourly} />
      )}

      {/* Nota UTC */}
      <p className="text-[10px] text-slate-400 dark:text-gray-600 text-right -mt-2">
        Fechas en UTC · datos de trades cerrados sincronizados
      </p>
    </div>
  )
}
