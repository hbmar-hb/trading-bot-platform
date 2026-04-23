import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { createChart } from 'lightweight-charts'
import { analyticsService } from '@/services/analytics'
import { botsService } from '@/services/bots'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import useBalanceStore from '@/store/balanceStore'
import { Sparkles, TrendingUp, TrendingDown, Minus, Download, RefreshCw, Filter, Clock, Calendar, Bot, User, ChevronDown, ChevronUp, Eye } from 'lucide-react'
import { getDateRange } from '@/utils/dateRanges'
import TradeDetailModal from '@/components/Analytics/TradeDetailModal'

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
  return getDateRange(days)
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

    const series = chart.addAreaSeries({
      lineColor:   '#3b82f6',
      lineWidth:   2,
      topColor:    'rgba(59,130,246,0.15)',
      bottomColor: 'rgba(59,130,246,0)',
      crosshairMarkerVisible: true,
      priceFormat: { type: 'custom', formatter: v => `${(v ?? 0) >= 0 ? '+' : ''}${Number(v ?? 0).toFixed(2)} USDT` },
    })

    const points = data
      .filter(p => p.timestamp && p.cumulative_pnl !== null && p.cumulative_pnl !== undefined)
      .map(p => {
        const time = Math.floor(new Date(p.timestamp).getTime() / 1000)
        const value = parseFloat(p.cumulative_pnl)
        return { 
          time: Number.isFinite(time) ? time : 0, 
          value: Number.isFinite(value) ? value : 0 
        }
      })
      .filter(p => p.time > 0)
    
    if (points.length === 0) {
      return () => { destroyed = true; obs.disconnect(); chart.remove() }
    }

    series.setData(points)
    chart.timeScale().fitContent()

    let destroyed = false
    const obs = new ResizeObserver(() => {
      if (!destroyed && ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    obs.observe(ref.current)

    return () => { destroyed = true; obs.disconnect(); chart.remove() }
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

    const validData = (data || [])
      .filter(p => p.date && p.daily_pnl !== null && p.daily_pnl !== undefined)
      .map(p => {
        const value = parseFloat(p.daily_pnl)
        return {
          time: p.date,
          value: Number.isFinite(value) ? value : 0,
          color: value >= 0 ? '#22c55e' : '#ef4444',
        }
      })
    
    if (validData.length > 0) {
      series.setData(validData)
    }

    chart.timeScale().fitContent()

    let destroyed = false
    const obs = new ResizeObserver(() => {
      if (!destroyed && ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    obs.observe(ref.current)

    return () => { destroyed = true; obs.disconnect(); chart.remove() }
  }, [data, isDark])

  if (!data?.length) return (
    <div className="h-[180px] flex items-center justify-center text-slate-400 dark:text-gray-500 text-sm">
      Sin datos de PnL diario
    </div>
  )

  return <div ref={ref} className="w-full" />
}

// ─── Activity Chart (Barras NARANJAS) ─────────────────────────

function ActivityHeatmap({ data, isDark }) {
  const ref = useRef(null)
  const safeData = Array.isArray(data) ? data : []
  
  useEffect(() => {
    if (!ref.current || safeData.length === 0) return

    const bg   = isDark ? '#030712' : '#ffffff'
    const text = isDark ? '#9ca3af' : '#64748b'
    const grid = isDark ? '#1f2937' : '#e2e8f0'

    const chart = createChart(ref.current, {
      layout:     { background: { color: bg }, textColor: text },
      grid:       { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale:  { 
        borderColor: grid,
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: grid },
      height: 180,
    })

    // Serie de trades (barras NARANJAS) - visible
    const tradesSeries = chart.addHistogramSeries({
      color: 'rgba(249, 115, 22, 0.7)',  // Naranja
      priceFormat: { type: 'volume' },
      priceScaleId: 'right',
    })

    // Serie de PnL (línea AZUL) - secundaria
    const pnlSeries = chart.addLineSeries({
      color: '#3b82f6',  // Azul
      lineWidth: 2,
      priceFormat: { type: 'custom', formatter: v => `${signed(v)} USDT` },
      priceScaleId: 'left',
    })

    // Preparar datos ordenados por fecha
    const sortedData = [...safeData].sort((a, b) => (a.date || '').localeCompare(b.date || ''))
    
    const points = sortedData.map(d => ({
      time: d.date,
      trades: d.count || 0,
      pnl: parseFloat(d.pnl || 0),
    }))

    tradesSeries.setData(points.filter(p => p.time).map(p => ({
      time: p.time,
      value: p.trades || 0,
      color: (p.trades || 0) > 0 ? 'rgba(249, 115, 22, 0.7)' : 'rgba(249, 115, 22, 0.2)',
    })))

    pnlSeries.setData(points.filter(p => p.time && !isNaN(p.pnl)).map(p => ({
      time: p.time,
      value: p.pnl,
    })))

    // Tooltip
    const toolTip = document.createElement('div')
    toolTip.style.cssText = `
      position: absolute;
      display: none;
      padding: 8px 12px;
      box-sizing: border-box;
      font-size: 12px;
      text-align: left;
      z-index: 1000;
      pointer-events: none;
      border-radius: 6px;
      background: ${isDark ? '#1f2937' : '#ffffff'};
      color: ${isDark ? '#e5e7eb' : '#1f2937'};
      border: 1px solid ${isDark ? '#374151' : '#e5e7eb'};
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    `
    ref.current.appendChild(toolTip)

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined) {
        toolTip.style.display = 'none'
        return
      }

      const dayData = sortedData.find(d => d.date === param.time)
      if (!dayData) {
        toolTip.style.display = 'none'
        return
      }

      const pnl = parseFloat(dayData.pnl || 0)
      const pnlColor = pnl >= 0 ? '#22c55e' : '#ef4444'
      
      toolTip.innerHTML = `
        <div style="font-weight: 600; margin-bottom: 4px;">${param.time}</div>
        <div>Trades: <span style="font-weight: 600; color: #f97316;">${dayData.count || 0}</span></div>
        <div>PnL: <span style="font-weight: 600; color: ${pnlColor}">${signed(pnl)} USDT</span></div>
      `

      const rect = ref.current.getBoundingClientRect()
      toolTip.style.left = `${param.point.x + 10}px`
      toolTip.style.top = `${param.point.y - 10}px`
      toolTip.style.display = 'block'
    })

    chart.timeScale().fitContent()

    let destroyed = false
    const obs = new ResizeObserver(() => {
      if (!destroyed && ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    obs.observe(ref.current)

    return () => {
      destroyed = true
      obs.disconnect()
      toolTip.remove()
      chart.remove()
    }
  }, [safeData, isDark])

  if (safeData.length === 0) {
    return (
      <div className="h-[180px] flex items-center justify-center text-slate-400 dark:text-gray-500 text-sm">
        Sin datos de actividad
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div ref={ref} className="w-full" />
      
      {/* Leyenda */}
      <div className="flex items-center justify-center gap-6 text-xs">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-orange-500/70" />
          <span className="text-slate-500 dark:text-gray-400">📅 Trades por día</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 bg-blue-500" />
          <span className="text-slate-500 dark:text-gray-400">PnL</span>
        </div>
      </div>
    </div>
  )
}

// ─── Hourly Distribution Chart (Lineal con MEDIA) ─────────────

function HourlyChart({ data, isDark }) {
  const ref = useRef(null)
  const safeData = Array.isArray(data) ? data : []

  useEffect(() => {
    if (!ref.current || safeData.length === 0) return

    const bg   = isDark ? '#030712' : '#ffffff'
    const text = isDark ? '#9ca3af' : '#64748b'
    const grid = isDark ? '#1f2937' : '#e2e8f0'

    const chart = createChart(ref.current, {
      layout:     { background: { color: bg }, textColor: text },
      grid:       { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale:  { 
        borderColor: grid,
        tickMarkFormatter: (time) => `${time}:00`,
      },
      rightPriceScale: { borderColor: grid },
      leftPriceScale:  { visible: true, borderColor: grid },
      height: 200,
    })

    // Calcular la MEDIA de PnL por hora (solo horas con trades)
    const hoursWithTrades = safeData.filter(d => (d.trades || 0) > 0)
    const avgPnl = hoursWithTrades.length > 0
      ? hoursWithTrades.reduce((sum, d) => sum + parseFloat(d.pnl || 0), 0) / hoursWithTrades.length
      : 0

    // Serie de PnL (línea MORADA)
    const pnlSeries = chart.addLineSeries({
      color: '#a855f7',  // Morado
      lineWidth: 2,
      title: 'PnL',
      priceFormat: { type: 'custom', formatter: v => `${signed(v)} USDT` },
      priceScaleId: 'right',
    })

    // Serie de MEDIA (línea punteada GRIS)
    const avgSeries = chart.addLineSeries({
      color: '#6b7280',  // Gris
      lineWidth: 1,
      lineStyle: 2,  // Punteada
      title: 'Media',
      priceFormat: { type: 'custom', formatter: v => `${signed(v)} USDT` },
      priceScaleId: 'right',
    })

    // Serie de trades (barras ROSAS)
    const tradesSeries = chart.addHistogramSeries({
      color: 'rgba(236, 72, 153, 0.5)',  // Rosa
      priceFormat: { type: 'volume' },
      priceScaleId: 'left',
    })

    // Preparar datos para las 24 horas
    const hourlyPoints = Array.from({ length: 24 }, (_, hour) => {
      const hourData = safeData.find(d => d.hour === hour)
      return {
        time: hour,
        pnl: parseFloat(hourData?.pnl || 0),
        trades: hourData?.trades || 0,
        winRate: hourData?.win_rate || 0,
      }
    })

    pnlSeries.setData(hourlyPoints.map(p => ({
      time: p.time,
      value: p.pnl,
    })))

    // Línea de media (mismo valor para todas las horas)
    avgSeries.setData(hourlyPoints.map(p => ({
      time: p.time,
      value: avgPnl,
    })))

    tradesSeries.setData(hourlyPoints.map(p => ({
      time: p.time,
      value: p.trades,
      color: p.trades > 0 ? 'rgba(236, 72, 153, 0.5)' : 'transparent',
    })))

    // Tooltip personalizado
    const toolTip = document.createElement('div')
    toolTip.style.cssText = `
      position: absolute;
      display: none;
      padding: 8px 12px;
      box-sizing: border-box;
      font-size: 12px;
      text-align: left;
      z-index: 1000;
      pointer-events: none;
      border-radius: 6px;
      background: ${isDark ? '#1f2937' : '#ffffff'};
      color: ${isDark ? '#e5e7eb' : '#1f2937'};
      border: 1px solid ${isDark ? '#374151' : '#e5e7eb'};
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    `
    ref.current.appendChild(toolTip)

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined) {
        toolTip.style.display = 'none'
        return
      }

      const hourData = hourlyPoints.find(p => p.time === param.time)
      if (!hourData) {
        toolTip.style.display = 'none'
        return
      }

      const pnlColor = hourData.pnl >= 0 ? '#22c55e' : '#ef4444'
      const vsAvg = hourData.pnl > avgPnl ? '↑' : hourData.pnl < avgPnl ? '↓' : '='
      const vsAvgColor = hourData.pnl > avgPnl ? '#22c55e' : hourData.pnl < avgPnl ? '#ef4444' : '#6b7280'
      
      toolTip.innerHTML = `
        <div style="font-weight: 600; margin-bottom: 4px;">${param.time}:00 - ${param.time}:59</div>
        <div>Trades: <span style="font-weight: 600;">${hourData.trades}</span></div>
        <div>Win Rate: <span style="font-weight: 600;">${(hourData.winRate * 100).toFixed(1)}%</span></div>
        <div>PnL: <span style="font-weight: 600; color: ${pnlColor}">${signed(hourData.pnl)} USDT</span></div>
        <div style="margin-top: 4px; padding-top: 4px; border-top: 1px solid ${isDark ? '#374151' : '#e5e7eb'};">
          vs Media: <span style="font-weight: 600; color: ${vsAvgColor}">${vsAvg} ${signed(avgPnl)}</span>
        </div>
      `

      const rect = ref.current.getBoundingClientRect()
      toolTip.style.left = `${param.point.x + 10}px`
      toolTip.style.top = `${param.point.y - 10}px`
      toolTip.style.display = 'block'
    })

    chart.timeScale().fitContent()

    let destroyed = false
    const obs = new ResizeObserver(() => {
      if (!destroyed && ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    obs.observe(ref.current)

    return () => {
      destroyed = true
      obs.disconnect()
      toolTip.remove()
      chart.remove()
    }
  }, [safeData, isDark])

  if (safeData.length === 0) {
    return (
      <div className="h-[200px] flex items-center justify-center text-slate-400 dark:text-gray-500 text-sm">
        Sin datos horarios
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div ref={ref} className="w-full" />
      
      {/* Leyenda */}
      <div className="flex items-center justify-center gap-4 text-xs flex-wrap">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-pink-500/50" />
          <span className="text-slate-500 dark:text-gray-400">⏰ Trades</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 bg-purple-500" />
          <span className="text-slate-500 dark:text-gray-400">PnL</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 bg-gray-500" style={{borderStyle: 'dashed'}} />
          <span className="text-slate-500 dark:text-gray-400">Media PnL</span>
        </div>
      </div>

      {/* Top 3 horas */}
      {(() => {
        const topHours = safeData
          .filter(d => (d.trades || 0) > 0)
          .sort((a, b) => (b.trades || 0) - (a.trades || 0))
          .slice(0, 3)
        
        if (topHours.length === 0) return null
        
        return (
          <div className="grid grid-cols-3 gap-2 text-xs pt-2 border-t border-slate-200 dark:border-gray-700">
            {topHours.map(hour => (
              <div key={hour.hour} className="text-center">
                <p className="text-slate-400 text-[10px]">{hour.hour}:00 - {hour.hour}:59</p>
                <p className="font-mono font-semibold">{hour.trades} trades</p>
                <p className={`font-mono ${parseFloat(hour.pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {signed(hour.pnl)}
                </p>
              </div>
            ))}
          </div>
        )
      })()}
    </div>
  )
}

// ─── Period Comparison ────────────────────────────────────────

function PeriodComparison({ summary }) {
  const [periodData, setPeriodData] = useState({})
  const [loading, setLoading] = useState(false)
  const totalEquity = useBalanceStore(s => s.getTotalEquity())

  useEffect(() => {
    const fetchPeriods = async () => {
      setLoading(true)
      const periods = [
        { label: '7d', days: 7 },
        { label: '30d', days: 30 },
      ]
      const data = {}
      for (const period of periods) {
        const { from, to } = rangeFromDays(period.days)
        try {
          const res = await analyticsService.pnlChart({ from_date: from, to_date: to })
          const pnlData = res.data || []
          const totalPnl = pnlData.reduce((acc, d) => acc + parseFloat(d.daily_pnl || 0), 0)
          const positive = pnlData.filter(d => parseFloat(d.daily_pnl || 0) > 0).length
          data[period.label] = {
            pnl: totalPnl,
            days: pnlData.length,
            positive,
            negative: pnlData.length - positive,
          }
        } catch {
          data[period.label] = null
        }
      }
      setPeriodData(data)
      setLoading(false)
    }

    fetchPeriods()
  }, [])

  if (loading) {
    return (
      <div className="h-[100px] flex items-center justify-center">
        <LoadingSpinner size="sm" />
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-4">
      {['7d', '30d'].map(periodLabel => {
        const d = periodData[periodLabel]
        if (!d) return null
        const pct = totalEquity > 0 ? (d.pnl / totalEquity * 100).toFixed(2) : null
        
        return (
          <div key={periodLabel} className="bg-slate-50 dark:bg-gray-800/40 rounded-lg p-3">
            <p className="text-xs text-slate-400 mb-2">Últimos {periodLabel}</p>
            <p className={`text-lg font-bold font-mono ${d.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {signed(d.pnl)} USDT
              {pct && <span className="text-sm ml-1 opacity-80">({signed(pct)}%)</span>}
            </p>
            <div className="flex gap-2 text-xs text-slate-400 mt-1">
              <span className="text-green-400">{d.positive}d ↑</span>
              <span className="text-red-400">{d.negative}d ↓</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Página principal ──────────────────────────────────────────

const SOURCE_OPTIONS = [
  { value: '', label: 'Todos' },
  { value: 'bot', label: 'Bots' },
  { value: 'manual', label: 'Manual' },
]

export default function AnalyticsPage() {
  const [summary, setSummary]     = useState(null)
  const [dailyPnl, setDailyPnl]   = useState([])
  const [heatmapData, setHeatmapData] = useState([])
  const [hourlyData, setHourlyData] = useState([])
  const [bots, setBots]           = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [range, setRange]         = useState(RANGES[1])
  const [selectedBot, setSelectedBot] = useState('')
  const [selectedSource, setSelectedSource] = useState('')
  const [isDark, setIsDark]       = useState(false)
  
  // Estado para modal de detalle de trades
  const [selectedBotDetail, setSelectedBotDetail] = useState(null)
  const [showTradeModal, setShowTradeModal] = useState(false)

  // Hook SIEMPRE antes de cualquier return condicional
  const totalEquity = useBalanceStore(s => s.getTotalEquity())

  useEffect(() => {
    const check = () => setIsDark(document.documentElement.classList.contains('dark'))
    check()
    const obs = new MutationObserver(check)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    botsService.list().then(res => setBots(res.data || [])).catch(() => setBots([]))
  }, [])

  const load = useCallback(async (selectedRange, botId, source) => {
    setLoading(true)
    setError(null)
    try {
      const { from, to } = rangeFromDays(selectedRange.days)
      const params = {}
      if (from) params.from_date = from
      if (to) params.to_date = to
      if (botId) params.bot_id = botId
      if (source) params.source = source

      const [summaryRes, pnlRes, heatmapRes, hourlyRes] = await Promise.all([
        analyticsService.summary(params),
        analyticsService.pnlChart(params),
        analyticsService.activityHeatmap(params),
        analyticsService.hourlyDistribution(params),
      ])
      
      setSummary(summaryRes.data)
      setDailyPnl(pnlRes.data || [])
      setHeatmapData(heatmapRes.data || [])
      setHourlyData(hourlyRes.data || [])
    } catch (err) {
      console.error('Error cargando analytics:', err)
      setError('No se pudieron cargar las estadísticas')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(range, selectedBot, selectedSource)
  }, [range, selectedBot, selectedSource, load])

  const exportToCSV = useCallback(() => {
    if (!dailyPnl?.length) return
    const headers = ['Fecha', 'PnL Diario', 'PnL Acumulado']
    const rows = dailyPnl.map(d => [d.date, d.daily_pnl, d.cumulative_pnl])
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `analytics_${range.label}_${selectedBot || 'all'}_${new Date().toISOString().slice(0,10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [dailyPnl, range.label, selectedBot])

  // Calcular estadísticas diarias
  const dailyStats = useMemo(() => {
    if (!Array.isArray(dailyPnl) || dailyPnl.length === 0) return null
    try {
      const positive = dailyPnl.filter(d => parseFloat(d.daily_pnl || 0) > 0).length
      const negative = dailyPnl.filter(d => parseFloat(d.daily_pnl || 0) < 0).length
      const pnls = dailyPnl.map(d => parseFloat(d.daily_pnl || 0))
      const best = Math.max(...pnls)
      const worst = Math.min(...pnls)
      return { positive, negative, best, worst }
    } catch (e) {
      return null
    }
  }, [dailyPnl])

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner />
      </div>
    )
  }

  if (error || !summary) {
    return (
      <div className="text-center py-20">
        <p className="text-slate-400 mb-4">{error || 'No se pudieron cargar las estadísticas'}</p>
        <button
          onClick={() => load(range, selectedBot)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2 mx-auto"
        >
          <RefreshCw size={16} /> Reintentar
        </button>
      </div>
    )
  }

  const g = summary.global_stats
  const pnlColor = parseFloat(g.total_pnl) >= 0 ? 'green' : 'red'
  const ddColor = parseFloat(g.max_drawdown) > 0 ? 'red' : 'default'

  // % ROI sobre equity total (totalEquity declarado arriba, antes de returns)
  const pnlPct = (pnl) => {
    if (!totalEquity || totalEquity <= 0) return null
    return (Number(pnl ?? 0) / totalEquity * 100).toFixed(2)
  }

  return (
    <div className="space-y-6">

      {/* Header + filtros */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Analytics</h1>
        
        <div className="flex flex-wrap items-center gap-2">
          {/* Selector de fuente */}
          <div className="relative">
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="px-3 py-1.5 text-xs bg-slate-100 dark:bg-gray-800 border-none rounded-lg text-slate-700 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 cursor-pointer"
            >
              {SOURCE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Selector de bot */}
          <div className="relative">
            <Filter size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
            <select
              value={selectedBot}
              onChange={(e) => setSelectedBot(e.target.value)}
              disabled={selectedSource === 'manual'}
              className="pl-8 pr-3 py-1.5 text-xs bg-slate-100 dark:bg-gray-800 border-none rounded-lg text-slate-700 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <option value="">Todos los bots</option>
              {bots.map(bot => (
                <option key={bot.id} value={bot.id}>{bot.bot_name}</option>
              ))}
            </select>
          </div>

          {/* Selector de rango */}
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
      </div>

      {/* Comparación de períodos */}
      <div className="card space-y-3">
        <div className="flex items-center gap-2">
          <Calendar size={14} className="text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200">Comparación de períodos</h2>
        </div>
        <PeriodComparison summary={summary} />
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
            sub={pnlPct(g.total_pnl) ? `Media ${signed(g.average_pnl)} · ${signed(pnlPct(g.total_pnl))}%` : `Media ${signed(g.average_pnl)} / trade`}
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
            sub={pnlPct(-g.max_drawdown) ? `${signed(pnlPct(-g.max_drawdown))}% del equity` : 'caída máx. desde pico'}
            color={ddColor} />
        </div>
      </div>

      {/* Fila 2: detalles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Mejor trade"  value={`+${fmt(g.best_trade)} USDT`}
          sub={pnlPct(g.best_trade) ? `${signed(pnlPct(g.best_trade))}%` : null}
          color="green" />
        <StatCard label="Peor trade"   value={`${signed(g.worst_trade)} USDT`}
          sub={pnlPct(g.worst_trade) ? `${signed(pnlPct(g.worst_trade))}%` : null}
          color="red" />
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
              {pnlPct(g.long_pnl) && <span className="text-sm ml-1 opacity-80">({signed(pnlPct(g.long_pnl))}%)</span>}
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
              {pnlPct(g.short_pnl) && <span className="text-sm ml-1 opacity-80">({signed(pnlPct(g.short_pnl))}%)</span>}
            </p>
            <WinRateBar rate={g.short_win_rate} />
          </div>
        </div>
      )}

      {/* Heatmap de actividad */}
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock size={14} className="text-slate-400" />
            <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200">Actividad</h2>
          </div>
          <span className="text-xs text-slate-400">{heatmapData.length} días activos</span>
        </div>
        <ActivityHeatmap data={heatmapData} isDark={isDark} />
      </div>

      {/* Distribución horaria */}
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock size={14} className="text-slate-400" />
            <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200">Rendimiento por hora</h2>
          </div>
        </div>
        <HourlyChart data={hourlyData} isDark={isDark} />
      </div>

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
              {pnlPct(dailyStats.best) && <span className="opacity-70 ml-1">({signed(pnlPct(dailyStats.best))}%)</span>}
            </span>
            {dailyStats.worst < 0 && (
              <span>
                Peor día: <span className="text-red-400 font-medium">{signed(dailyStats.worst)} USDT</span>
                {pnlPct(dailyStats.worst) && <span className="opacity-70 ml-1">({signed(pnlPct(dailyStats.worst))}%)</span>}
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
                      {pnlPct(bot.total_pnl) && <span className="text-xs ml-1 opacity-80">({signed(pnlPct(bot.total_pnl))}%)</span>}
                    </span>
                    <button
                      onClick={() => {
                        setSelectedBotDetail(bot)
                        setShowTradeModal(true)
                      }}
                      className="p-1.5 text-slate-400 hover:text-blue-400 rounded" 
                      title="Ver trades">
                      <Eye size={14} />
                    </button>
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
      
      {/* Modal de detalle de trades */}
      {showTradeModal && (
        <TradeDetailModal
          botId={selectedBotDetail?.bot_id}
          botName={selectedBotDetail?.bot_name}
          fromDate={rangeFromDays(range.days).from}
          toDate={rangeFromDays(range.days).to}
          source={selectedSource}
          onClose={() => {
            setShowTradeModal(false)
            setSelectedBotDetail(null)
          }}
        />
      )}
    </div>
  )
}
