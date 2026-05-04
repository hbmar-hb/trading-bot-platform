import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { createChart } from 'lightweight-charts'
import { positionsService } from '@/services/positions'
import { botsService } from '@/services/bots'
import { tradingSignalsService } from '@/services/tradingSignals'
import { chartingService } from '@/services/charting'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import usePositionStore from '@/store/positionStore'
import useUiStore from '@/store/uiStore'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import { useIndicatorConfig } from '@/hooks/useIndicatorConfig'
import { indicators, getIndicator } from '@/indicators/registry'
import {
  TrendingUp, TrendingDown, AlertTriangle, Activity, Clock,
  BarChart3, ChevronDown, Eye, EyeOff, LineChart, X,
  Maximize2, Minimize2, CandlestickChart, AreaChart,
} from 'lucide-react'

// ─── Timeframes ───────────────────────────────────────────────────────────────
const TIMEFRAMES = [
  { label: '1m',  value: '1m',  seconds: 3  * 24 * 3600 },
  { label: '5m',  value: '5m',  seconds: 7  * 24 * 3600 },
  { label: '10m', value: '10m', seconds: 14 * 24 * 3600 },
  { label: '15m', value: '15m', seconds: 30 * 24 * 3600 },
  { label: '30m', value: '30m', seconds: 60 * 24 * 3600 },
  { label: '1h',  value: '1h',  seconds: 90 * 24 * 3600 },
  { label: '2h',  value: '2h',  seconds: 180 * 24 * 3600 },
  { label: '4h',  value: '4h',  seconds: 365 * 24 * 3600 },
  { label: '1D',  value: '1d',  seconds: 730 * 24 * 3600 },
  { label: '1S',  value: '1w',  seconds: 730 * 24 * 3600 },
  { label: '1M',  value: '1M',  seconds: 1825 * 24 * 3600 },
]

// ─── Paletas de color ─────────────────────────────────────────────────────────
const PALETTES = {
  classic: { label: 'Classic',   up: '#22c55e', down: '#ef4444' },
  tv:      { label: 'TradingView', up: '#26a69a', down: '#ef5350' },
  blue:    { label: 'Blue/Red',  up: '#3b82f6', down: '#ef4444' },
  mono:    { label: 'Mono',      up: '#94a3b8', down: '#475569' },
  warm:    { label: 'Gold/Violet', up: '#f59e0b', down: '#7c3aed' },
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function formatPrice(price) {
  if (price === null || price === undefined) return '—'
  const num = Number(price)
  if (num >= 1000) return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return num.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 })
}

function formatTime(dateString) {
  if (!dateString) return '—'
  const date = new Date(dateString)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleString('es-ES', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function calculatePositionRoi(pos, currentPrice) {
  const entry = parseFloat(pos.entry_price)
  const qty   = parseFloat(pos.quantity)
  const lev   = parseFloat(pos.leverage || 1)
  let pnl = parseFloat(pos.unrealized_pnl || 0)
  if (currentPrice && entry > 0 && qty > 0) {
    pnl = pos.side === 'long' ? (currentPrice - entry) * qty : (entry - currentPrice) * qty
  }
  const margin = entry > 0 && qty > 0 ? (entry * qty) / lev : 0
  return margin > 0 ? (pnl / margin) * 100 : 0
}

const normalizeSymbol = (s) =>
  s?.replace(':USDT','').replace(':USDC','').replace('/USDT','').replace('/USDC','').toUpperCase()

function toCcxtSymbol(raw) {
  if (!raw) return raw
  if (raw.includes('/')) return raw
  let s = raw.replace(/\.P$/i, '').replace(/_/g, '-')
  if (s.includes('-')) {
    const [base, quote] = s.split('-')
    return `${base}/${quote}:${quote}`
  }
  const m = s.match(/^(.*?)(USDT|USDC|BTC|ETH|USD)$/i)
  if (m) return `${m[1]}/${m[2]}:${m[2]}`
  return raw
}

// ─── Indicadores técnicos ─────────────────────────────────────────────────────
function sma(data, period) {
  return data.map((_, i) => {
    if (i < period - 1) return null
    const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b.close, 0)
    return { time: data[i].time, value: sum / period }
  })
}

function ema(data, period) {
  const k = 2 / (period + 1)
  let prev = null
  return data.map((c, i) => {
    if (i < period - 1) return null
    if (i === period - 1) prev = data.slice(0, period).reduce((a, b) => a + b.close, 0) / period
    else prev = c.close * k + prev * (1 - k)
    return { time: c.time, value: prev }
  })
}

function rsi(data, period = 14) {
  const result = []
  let avgGain = 0, avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const c = data[i].close - data[i - 1].close
    if (c > 0) avgGain += c; else avgLoss -= c
  }
  avgGain /= period; avgLoss /= period
  for (let i = 0; i < data.length; i++) {
    if (i < period) { result.push(null); continue }
    const c = data[i].close - data[i - 1].close
    avgGain = (avgGain * (period - 1) + Math.max(c, 0)) / period
    avgLoss = (avgLoss * (period - 1) + Math.max(-c, 0)) / period
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
    result.push({ time: data[i].time, value: 100 - (100 / (1 + rs)) })
  }
  return result
}

function calculateIndicators(candles) {
  if (!candles || candles.length < 200) return null
  return {
    ema20:  ema(candles, 20),
    ema50:  ema(candles, 50),
    sma200: sma(candles, 200),
    rsi14:  rsi(candles, 14),
    volume: candles.map(c => ({ time: c.time, value: c.volume || 0 })),
  }
}

// ─── ICT Engine importado desde frontend/src/core/ictEngine.js ─────────────
// ─── Sub-componentes ──────────────────────────────────────────────────────────
function IndicatorToggle({ active, onChange, color, label }) {
  return (
    <button
      onClick={() => onChange(!active)}
      className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-slate-50 dark:hover:bg-gray-700/60 transition-colors text-left"
    >
      <div className="w-4 h-1 rounded-full flex-shrink-0" style={{ backgroundColor: active ? color : '#64748b' }} />
      <span className={`text-sm flex-1 ${active ? 'text-slate-800 dark:text-gray-100' : 'text-slate-400 dark:text-gray-500'}`}>
        {label}
      </span>
      {active
        ? <Eye size={12} className="text-slate-400 dark:text-gray-500 flex-shrink-0" />
        : <EyeOff size={12} className="text-slate-300 dark:text-gray-700 flex-shrink-0" />}
    </button>
  )
}

function IndicatorBadge({ name, value, color = 'blue' }) {
  const colors = {
    blue:   'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    purple: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  }
  if (value === null || value === undefined) return null
  return (
    <div className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium ${colors[color]}`}>
      <span className="opacity-70">{name}:</span>
      <span>{typeof value === 'number' ? value.toFixed(2) : value}</span>
    </div>
  )
}

// ─── Componente principal ─────────────────────────────────────────────────────
export default function ChartPage() {
  // Refs
  const chartContainerRef  = useRef(null)
  const chartRef           = useRef(null)
  const candleSeriesRef    = useRef(null)
  const indicatorSeriesRef = useRef({ ema20: null, ema50: null, sma200: null, rsi: null, volume: null })
  const overlayPriceLinesRef = useRef([])
  const overlaySeriesRef     = useRef([])
  const overlayMarkersRef    = useRef([])
  const posMarkersRef        = useRef([])
  const positionPriceLinesRef = useRef([])
  const positionLineSeriesRef = useRef(null)
  const indicatorsMenuRef  = useRef(null)
  const tfMenuRef          = useRef(null)
  const paletteMenuRef     = useRef(null)

  // State
  const [loading, setLoading]               = useState(true)
  const [loadingCandles, setLoadingCandles] = useState(false)
  const [availableSymbols, setAvailableSymbols] = useState([])
  const [selectedSymbol, setSelectedSymbol] = useState('BTC/USDT:USDT')
  const [timeframe, setTimeframe]           = useState('1h')
  const [positions, setPositions]           = useState([])
  const [signals, setSignals]               = useState([])
  const [bots, setBots]                     = useState([])

  // Indicators
  const [showEma20, setShowEma20]   = useState(true)
  const [showEma50, setShowEma50]   = useState(true)
  const [showSma200, setShowSma200] = useState(true)
  const [showRsi, setShowRsi]       = useState(false)
  const [showVolume, setShowVolume] = useState(true)

  // Indicators system
  const { configs, getConfig, setConfig } = useIndicatorConfig()
  const [activeIndicators, setActiveIndicators] = useState({})
  const [openPanels, setOpenPanels] = useState({})

  // Chart appearance
  const [chartType, setChartType] = useState('candles')  // 'candles' | 'line' | 'area'
  const [palette, setPalette]     = useState('classic')

  // UI toggles
  const [candleData, setCandleData]         = useState([])
  const [symbolSearch, setSymbolSearch]     = useState('')
  const [showSymbolDropdown, setShowSymbolDropdown] = useState(false)
  const [showIndicatorsMenu, setShowIndicatorsMenu] = useState(false)
  const [showTfMenu, setShowTfMenu]         = useState(false)
  const [showPaletteMenu, setShowPaletteMenu] = useState(false)
  const [selectedPosition, setSelectedPosition] = useState(null)
  const [chartError, setChartError]         = useState(null)
  const [isFullscreen, setIsFullscreen]     = useState(false)

  const prices      = usePositionStore(s => s.prices)
  const sidebarOpen = useUiStore(s => s.sidebarOpen)

  const selectedSymbolNorm = useMemo(() => normalizeSymbol(selectedSymbol), [selectedSymbol])
  const currentTf = useMemo(() => TIMEFRAMES.find(t => t.value === timeframe) || TIMEFRAMES[5], [timeframe])
  const pal = PALETTES[palette] || PALETTES.classic

  // ─── Close dropdowns on outside click ───────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (indicatorsMenuRef.current && !indicatorsMenuRef.current.contains(e.target))
        setShowIndicatorsMenu(false)
      if (tfMenuRef.current && !tfMenuRef.current.contains(e.target))
        setShowTfMenu(false)
      if (paletteMenuRef.current && !paletteMenuRef.current.contains(e.target))
        setShowPaletteMenu(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // ─── Load symbols ────────────────────────────────────────────────────────────
  const loadSymbols = useCallback(async (search = '') => {
    try {
      const res = await exchangeAccountsService.marketsByExchange('bingx')
      let symbols = (Array.isArray(res.data) ? res.data : []).map(s => ({
        symbol: s,
        description: s.replace('/USDT:USDT', '').replace('/USDC:USDC', ''),
      }))
      if (search) {
        const q = search.toUpperCase()
        symbols = symbols.filter(s => s.symbol.toUpperCase().includes(q))
      }
      setAvailableSymbols(symbols)
    } catch {
      setAvailableSymbols([
        { symbol: 'BTC/USDT:USDT', description: 'BTC' },
        { symbol: 'ETH/USDT:USDT', description: 'ETH' },
      ])
    }
  }, [])

  // ─── Initial load ────────────────────────────────────────────────────────────
  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [posRes, botsRes, closedRes] = await Promise.all([
          positionsService.unified(true),
          botsService.list(),
          positionsService.list({ status: 'closed', limit: 500 }),
        ])
        const open   = Array.isArray(posRes?.data)    ? posRes.data    : Array.isArray(posRes)    ? posRes    : []
        const closed = Array.isArray(closedRes?.data) ? closedRes.data : Array.isArray(closedRes) ? closedRes : []
        const botsData = Array.isArray(botsRes?.data) ? botsRes.data   : Array.isArray(botsRes)   ? botsRes   : []
        setPositions([...open, ...closed])
        setBots(botsData)
        await loadSymbols('')
        try {
          const sigRes = await tradingSignalsService.list({ symbol: selectedSymbol, days: 7, limit: 100 })
          setSignals(sigRes.data?.signals || [])
        } catch { setSignals([]) }
      } catch (e) { console.error('Chart load error:', e) }
      finally { setLoading(false) }
    }
    load()
  }, [])

  // ─── Load candles ────────────────────────────────────────────────────────────
  const loadCandleData = useCallback(async () => {
    if (!selectedSymbol) return
    setChartError(null)
    setLoadingCandles(true)
    try {
      const to   = Math.floor(Date.now() / 1000)
      const from = to - (currentTf.seconds ?? 90 * 24 * 3600)
      const res  = await chartingService.getHistory({
        symbol:     toCcxtSymbol(selectedSymbol),
        resolution: timeframe,
        from_time:  from,
        to_time:    to,
      })
      if (res.data?.s === 'ok' && res.data.t?.length > 0) {
        setCandleData(res.data.t.map((time, i) => ({
          time,
          open:   res.data.o[i],
          high:   res.data.h[i],
          low:    res.data.l[i],
          close:  res.data.c[i],
          volume: res.data.v?.[i] ?? 0,
        })))
      } else {
        setChartError(res.data?.errmsg || 'No data returned')
        setCandleData([])
      }
    } catch (e) {
      setChartError(e.response?.data?.detail || e.message || 'Failed to load data')
      setCandleData([])
    } finally { setLoadingCandles(false) }
  }, [selectedSymbol, timeframe, currentTf.seconds])

  useEffect(() => { loadCandleData() }, [loadCandleData])

  // ─── Merge markers helper ────────────────────────────────────────────────────
  const syncMarkers = useCallback(() => {
    if (!candleSeriesRef.current) return
    const combined = [...posMarkersRef.current, ...overlayMarkersRef.current]
      .sort((a, b) => a.time - b.time)
    candleSeriesRef.current.setMarkers(combined)
  }, [])

  // ─── EFFECT A: Create chart on data / appearance change ───────────────────
  useEffect(() => {
    if (!chartContainerRef.current || loading || candleData.length === 0) {
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
        candleSeriesRef.current = null
        indicatorSeriesRef.current = { ema20: null, ema50: null, sma200: null, rsi: null, volume: null }
        overlayPriceLinesRef.current = []
        overlaySeriesRef.current = []
      }
      return
    }
    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null }
    candleSeriesRef.current = null
    indicatorSeriesRef.current = { ema20: null, ema50: null, sma200: null, rsi: null, volume: null }
    overlayPriceLinesRef.current = []
    overlaySeriesRef.current = []
    posMarkersRef.current = []
    overlayMarkersRef.current = []

    const isDark = document.documentElement.classList.contains('dark')
    const bg   = isDark ? '#111827' : '#ffffff'
    const text = isDark ? '#94a3b8' : '#64748b'
    const grid = isDark ? '#1f2937' : '#f1f5f9'

    const container = chartContainerRef.current
    const chart = createChart(container, {
      layout:  { background: { color: bg }, textColor: text, fontSize: 11 },
      grid:    { vertLines: { color: grid, style: 2 }, horzLines: { color: grid, style: 2 } },
      crosshair: {
        mode: 1,
        vertLine: { color: isDark ? '#475569' : '#94a3b8', labelBackgroundColor: isDark ? '#374151' : '#94a3b8' },
        horzLine: { color: isDark ? '#475569' : '#94a3b8', labelBackgroundColor: isDark ? '#374151' : '#94a3b8' },
      },
      timeScale: { borderColor: grid, timeVisible: true, secondsVisible: false, barSpacing: 8, minBarSpacing: 3 },
      rightPriceScale: { borderColor: grid },
      handleScroll: { vertTouchDrag: false },
      width:  container.offsetWidth  || 800,
      height: container.offsetHeight || 500,
    })
    chartRef.current = chart

    // ── Main series by chart type ─────────────────────────────────────────────
    let mainSeries
    if (chartType === 'line') {
      mainSeries = chart.addLineSeries({
        color: pal.up, lineWidth: 2, lastValueVisible: true, priceLineVisible: true,
      })
      mainSeries.setData(candleData.map(c => ({ time: c.time, value: c.close })))
    } else if (chartType === 'area') {
      mainSeries = chart.addAreaSeries({
        topColor: pal.up + '55', bottomColor: pal.up + '11', lineColor: pal.up, lineWidth: 2,
        lastValueVisible: true, priceLineVisible: true,
      })
      mainSeries.setData(candleData.map(c => ({ time: c.time, value: c.close })))
    } else {
      mainSeries = chart.addCandlestickSeries({
        upColor: pal.up, downColor: pal.down,
        borderUpColor: pal.up, borderDownColor: pal.down,
        wickUpColor: pal.up, wickDownColor: pal.down,
      })
      mainSeries.setData(candleData)
    }
    candleSeriesRef.current = mainSeries
    positionPriceLinesRef.current = []

    // ── Position overlay ──────────────────────────────────────────────────────
    const allMarkers = []
    if (selectedPosition && normalizeSymbol(toCcxtSymbol(selectedPosition.symbol)) === selectedSymbolNorm) {
      const pos        = selectedPosition
      const entryTime  = Math.floor(new Date(pos.opened_at).getTime() / 1000)
      const closeTime  = pos.closed_at ? Math.floor(new Date(pos.closed_at).getTime() / 1000) : null
      const entryPrice = parseFloat(pos.entry_price)
      const isLong     = pos.side === 'long'
      const posColor   = isLong ? '#22c55e' : '#ef4444'

      const posOpenedMs  = new Date(pos.opened_at).getTime()
      let relatedSignal  = signals.find(s => s.position_id === pos.id)
      if (!relatedSignal) {
        relatedSignal = signals
          .filter(s => normalizeSymbol(toCcxtSymbol(s.symbol)) === selectedSymbolNorm && s.action === pos.side)
          .map(s => ({ ...s, _delta: Math.abs(new Date(s.received_at).getTime() - posOpenedMs) }))
          .filter(s => s._delta < 2 * 60 * 1000)
          .sort((a, b) => a._delta - b._delta)[0]
      }

      if (relatedSignal) {
        const snapTime = candleData.find(c => c.time === Math.floor(new Date(relatedSignal.received_at).getTime() / 1000))?.time
          ?? Math.floor(new Date(relatedSignal.received_at).getTime() / 1000)
        allMarkers.push({ time: snapTime, position: relatedSignal.action === 'long' ? 'belowBar' : 'aboveBar', color: relatedSignal.action === 'long' ? '#22c55e' : '#ef4444', shape: relatedSignal.action === 'long' ? 'arrowUp' : 'arrowDown', text: relatedSignal.action === 'long' ? 'LONG' : 'SHORT', size: 2 })
        if (relatedSignal.price) positionPriceLinesRef.current.push(
          mainSeries.createPriceLine({ price: parseFloat(relatedSignal.price), color: isLong ? '#16a34a' : '#dc2626', lineWidth: 1, lineStyle: 3, axisLabelVisible: true, title: `Señal ${pos.side.toUpperCase()}` })
        )
      }

      allMarkers.push({ time: entryTime, position: isLong ? 'belowBar' : 'aboveBar', color: posColor, shape: isLong ? 'arrowUp' : 'arrowDown', text: 'Entry', size: 2 })
      positionPriceLinesRef.current.push(
        mainSeries.createPriceLine({ price: entryPrice, color: posColor, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: `Entry ${pos.side.toUpperCase()}` })
      )
      if (closeTime) {
        const pnl = parseFloat(pos.realized_pnl || 0)
        allMarkers.push({ time: closeTime, position: isLong ? 'aboveBar' : 'belowBar', color: pnl >= 0 ? '#22c55e' : '#ef4444', shape: 'circle', text: `${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}`, size: 2 })
      }
      if (pos.current_sl_price) positionPriceLinesRef.current.push(
        mainSeries.createPriceLine({ price: parseFloat(pos.current_sl_price), color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' })
      )
      if (pos.current_tp_prices?.length > 0) pos.current_tp_prices.forEach((tp, idx) =>
        positionPriceLinesRef.current.push(
          mainSeries.createPriceLine({ price: parseFloat(tp), color: '#22c55e', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `TP${idx + 1}` })
        )
      )

      const bot = bots.find(b => b.id === pos.bot_id)
      const currentSl = parseFloat(pos.current_sl_price || 0)
      if (bot?.initial_sl_percentage && currentSl > 0) {
        const initSl = isLong
          ? entryPrice * (1 - parseFloat(bot.initial_sl_percentage) / 100)
          : entryPrice * (1 + parseFloat(bot.initial_sl_percentage) / 100)
        const improved = isLong ? currentSl > initSl : currentSl < initSl
        if (improved) {
          const nearEntry = Math.abs(currentSl - entryPrice) / entryPrice < 0.005
          positionPriceLinesRef.current.push(
            mainSeries.createPriceLine({ price: currentSl, color: nearEntry ? '#f59e0b' : '#a855f7', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: nearEntry ? 'BE' : 'TS' })
          )
        }
      }

      const endTime = closeTime || candleData[candleData.length - 1]?.time || entryTime
      if (endTime > entryTime) {
        const durSeries = chart.addLineSeries({ color: posColor, lineWidth: 3, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
        durSeries.setData([{ time: entryTime, value: entryPrice }, { time: endTime, value: entryPrice }])
        positionLineSeriesRef.current = durSeries
        const bandSeries = chart.addAreaSeries({ topColor: isLong ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)', bottomColor: 'rgba(0,0,0,0)', lineColor: 'rgba(0,0,0,0)', lineWidth: 0, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
        bandSeries.setData([{ time: entryTime, value: entryPrice }, { time: endTime, value: entryPrice }])
        if (!positionLineSeriesRef._aux) positionLineSeriesRef._aux = []
        positionLineSeriesRef._aux.push(bandSeries)
      }

      try {
        const ei = candleData.findIndex(c => c.time >= entryTime)
        const ci = closeTime ? candleData.findIndex(c => c.time >= closeTime) : candleData.length - 1
        if (ei >= 0 && ci >= 0)
          chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, ei - 10), to: Math.min(candleData.length - 1, ci + 10) })
        else chart.timeScale().fitContent()
      } catch { chart.timeScale().fitContent() }
    } else {
      chart.timeScale().fitContent()
    }

    posMarkersRef.current = allMarkers.sort((a, b) => a.time - b.time)
    mainSeries.setMarkers(posMarkersRef.current)

    // Resize observer
    const ro = new ResizeObserver(() => {
      if (chartContainerRef.current && chartRef.current) {
        const { width, height } = chartContainerRef.current.getBoundingClientRect()
        if (width > 0 && height > 0) chartRef.current.applyOptions({ width, height })
      }
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      positionLineSeriesRef.current = null
      if (positionLineSeriesRef._aux) positionLineSeriesRef._aux = []
      indicatorSeriesRef.current = { ema20: null, ema50: null, sma200: null, rsi: null, volume: null }
    }
  }, [candleData, selectedPosition, signals, bots, loading, selectedSymbol, selectedSymbolNorm, chartType, palette])

  // ─── EFFECT B: Indicator series ───────────────────────────────────────────
  useEffect(() => {
    const chart   = chartRef.current
    const cSeries = candleSeriesRef.current
    if (!chart || !cSeries || candleData.length === 0) return

    const calc = calculateIndicators(candleData)
    const panelCount = (showVolume ? 1 : 0) + (showRsi ? 1 : 0)
    const bottomMargin = panelCount === 0 ? 0.05 : panelCount === 1 ? 0.22 : 0.38
    cSeries.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: bottomMargin } })

    const iRef = indicatorSeriesRef.current
    const toggle = (key, shouldShow, createFn, getData) => {
      if (shouldShow && calc) {
        if (!iRef[key]) iRef[key] = createFn()
        iRef[key].setData(getData(calc).filter(p => p !== null))
      } else if (!shouldShow && iRef[key]) {
        chart.removeSeries(iRef[key]); iRef[key] = null
      }
    }

    toggle('ema20',  showEma20,  () => chart.addLineSeries({ color: '#f59e0b', lineWidth: 1, title: 'EMA 20', lastValueVisible: false, priceLineVisible: false }), c => c.ema20)
    toggle('ema50',  showEma50,  () => chart.addLineSeries({ color: '#3b82f6', lineWidth: 1, title: 'EMA 50', lastValueVisible: false, priceLineVisible: false }), c => c.ema50)
    toggle('sma200', showSma200, () => chart.addLineSeries({ color: '#ef4444', lineWidth: 1, title: 'SMA 200', lastValueVisible: false, priceLineVisible: false }), c => c.sma200)
    toggle('volume', showVolume, () => {
      const s = chart.addHistogramSeries({ color: '#64748b', priceFormat: { type: 'volume' }, priceScaleId: 'volume' })
      chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.80, bottom: 0 } })
      return s
    }, c => c.volume)
    toggle('rsi', showRsi, () => {
      const s = chart.addLineSeries({ color: '#a855f7', lineWidth: 1.5, title: 'RSI 14', priceScaleId: 'rsi', lastValueVisible: false, priceLineVisible: false })
      chart.priceScale('rsi').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 }, entireTextOnly: true })
      return s
    }, c => c.rsi14)
  }, [showEma20, showEma50, showSma200, showRsi, showVolume, candleData])

  // ─── EFFECT C: Indicators overlay ─────────────────────────────────────────
  useEffect(() => {
    const chart   = chartRef.current
    const cSeries = candleSeriesRef.current
    if (!chart || !cSeries || candleData.length === 0) return

    // Clean up previous overlays
    overlaySeriesRef.current.forEach(s => { try { chart.removeSeries(s) } catch {} })
    overlaySeriesRef.current = []
    overlayPriceLinesRef.current.forEach(l => { try { cSeries.removePriceLine(l) } catch {} })
    overlayPriceLinesRef.current = []
    overlayMarkersRef.current = []

    const anyActive = Object.values(activeIndicators).some(Boolean)
    if (!anyActive) { syncMarkers(); return }

    // API que recibe cada indicador para dibujar
    const api = {
      addMarker(m) { overlayMarkersRef.current.push(m) },
      addPriceLine(opts) {
        try {
          const pl = cSeries.createPriceLine(opts)
          overlayPriceLinesRef.current.push(pl)
        } catch {}
      },
      addSeries(createFn) {
        try {
          const s = createFn(chart)
          overlaySeriesRef.current.push(s)
          return s
        } catch { return null }
      },
    }

    // Ejecutar detect + render para cada indicador activo
    for (const ind of indicators) {
      if (!activeIndicators[ind.id]) continue
      const config = getConfig(ind.id)
      const result = ind.detect ? ind.detect(candleData, config) : null
      if (result && ind.render) {
        ind.render(chart, cSeries, result, config, api)
      }
    }

    syncMarkers()
  }, [activeIndicators, configs, candleData, syncMarkers])

  // ─── UI helpers ──────────────────────────────────────────────────────────────
  const filteredSymbols = useMemo(() => {
    if (!symbolSearch) return availableSymbols
    return availableSymbols.filter(s =>
      s.symbol?.toLowerCase().includes(symbolSearch.toLowerCase()) ||
      s.description?.toLowerCase().includes(symbolSearch.toLowerCase())
    )
  }, [availableSymbols, symbolSearch])

  const handleSelectSymbol = (symbol) => {
    setSelectedSymbol(symbol)
    setShowSymbolDropdown(false)
    setSymbolSearch('')
    tradingSignalsService.list({ symbol, days: 7, limit: 100 })
      .then(res => setSignals(res.data?.signals || []))
      .catch(() => setSignals([]))
  }

  const currentPrice = prices[selectedSymbol]
  const activeIndicatorCount = [showEma20, showEma50, showSma200, showRsi, showVolume, ...Object.values(activeIndicators)].filter(Boolean).length

  if (loading) return <div className="flex justify-center items-center h-64"><LoadingSpinner /></div>

  const openForSymbol   = positions.filter(p => p.status === 'open'   && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm)
  const closedForSymbol = positions.filter(p => p.status === 'closed' && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm)

  // Outer container: fixed viewport (or fullscreen modal)
  const outerClass = isFullscreen
    ? 'fixed inset-0 z-50 overflow-hidden flex flex-col bg-slate-100 dark:bg-gray-950'
    : 'fixed top-0 right-0 bottom-0 overflow-hidden flex flex-col bg-slate-100 dark:bg-gray-950 transition-all duration-200 pb-20 md:pb-0 z-10'
  const outerStyle = isFullscreen ? {} : { left: sidebarOpen ? '224px' : '64px' }

  return (
    <div className={outerClass} style={outerStyle}>
      <div className="flex flex-col h-full p-3 gap-2 overflow-hidden">

        {/* ── Toolbar ────────────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 flex-wrap shrink-0">

          {/* Title */}
          <div className="flex items-center gap-2 mr-1">
            <BarChart3 className="w-4 h-4 text-blue-500 flex-shrink-0" />
            <span className="text-sm font-bold text-slate-900 dark:text-white hidden sm:block">Chart</span>
          </div>

          {/* Symbol selector */}
          <div className="relative">
            <button
              onClick={() => setShowSymbolDropdown(!showSymbolDropdown)}
              className="flex items-center gap-2 px-3 py-1.5 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg hover:bg-slate-50 dark:hover:bg-gray-750 min-w-[140px] text-sm"
            >
              <span className="font-semibold text-slate-900 dark:text-white truncate">
                {selectedSymbol.replace('/USDT:USDT', '').replace('/USDC:USDC', '')}
              </span>
              {currentPrice && (
                <span className="text-slate-400 dark:text-gray-500 ml-1 hidden md:inline">${formatPrice(currentPrice)}</span>
              )}
              <ChevronDown size={13} className="ml-auto text-slate-400 flex-shrink-0" />
            </button>
            {showSymbolDropdown && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-xl shadow-xl z-50">
                <div className="p-2 border-b border-slate-100 dark:border-gray-700">
                  <input type="text" placeholder="Buscar par…" value={symbolSearch}
                    onChange={(e) => { setSymbolSearch(e.target.value); loadSymbols(e.target.value) }}
                    className="w-full px-3 py-2 text-sm bg-slate-100 dark:bg-gray-900 border-none rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                    autoFocus />
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {filteredSymbols.length === 0
                    ? <p className="p-3 text-sm text-slate-500">No se encontraron pares</p>
                    : filteredSymbols.slice(0, 20).map(s => (
                        <button key={s.symbol} onClick={() => handleSelectSymbol(s.symbol)}
                          className={`w-full px-4 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-gray-700 ${s.symbol === selectedSymbol ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600' : 'text-slate-700 dark:text-gray-300'}`}>
                          <div className="font-medium">{s.symbol}</div>
                          <div className="text-xs text-slate-400">{s.description}</div>
                        </button>
                      ))}
                </div>
              </div>
            )}
          </div>

          {/* Timeframe dropdown */}
          <div className="relative" ref={tfMenuRef}>
            <button
              onClick={() => setShowTfMenu(!showTfMenu)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg hover:bg-slate-50 dark:hover:bg-gray-750 text-sm font-semibold text-slate-700 dark:text-gray-200 min-w-[62px]"
            >
              {currentTf.label}
              <ChevronDown size={12} className={`transition-transform duration-150 ${showTfMenu ? 'rotate-180' : ''}`} />
            </button>
            {showTfMenu && (
              <div className="absolute top-full left-0 mt-1 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-xl shadow-xl z-50 p-2">
                <div className="grid grid-cols-4 gap-1 w-48">
                  {TIMEFRAMES.map(tf => (
                    <button key={tf.value}
                      onClick={() => { setTimeframe(tf.value); setShowTfMenu(false) }}
                      className={`px-2 py-1.5 text-xs font-semibold rounded-lg transition-colors text-center ${
                        tf.value === timeframe
                          ? 'bg-blue-600 text-white'
                          : 'text-slate-600 dark:text-gray-400 hover:bg-slate-100 dark:hover:bg-gray-700'
                      }`}>
                      {tf.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Chart type selector */}
          <div className="flex items-center gap-0.5 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg p-0.5">
            {[
              { type: 'candles', icon: <CandlestickChart size={13} />, title: 'Velas' },
              { type: 'line',    icon: <LineChart size={13} />,        title: 'Línea' },
              { type: 'area',    icon: <AreaChart size={13} />,        title: 'Área' },
            ].map(({ type, icon, title }) => (
              <button key={type} title={title} onClick={() => setChartType(type)}
                className={`p-1.5 rounded-md transition-colors ${
                  chartType === type ? 'bg-blue-600 text-white' : 'text-slate-500 dark:text-gray-400 hover:bg-slate-100 dark:hover:bg-gray-700'
                }`}>
                {icon}
              </button>
            ))}
          </div>

          {/* Palette selector */}
          <div className="relative" ref={paletteMenuRef}>
            <button
              onClick={() => setShowPaletteMenu(!showPaletteMenu)}
              title="Paleta de colores"
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg hover:bg-slate-50 dark:hover:bg-gray-750"
            >
              <div className="flex gap-0.5">
                <div className="w-2 h-3 rounded-sm" style={{ backgroundColor: pal.up }} />
                <div className="w-2 h-3 rounded-sm" style={{ backgroundColor: pal.down }} />
              </div>
              <ChevronDown size={11} className="text-slate-400" />
            </button>
            {showPaletteMenu && (
              <div className="absolute top-full left-0 mt-1 w-40 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-xl shadow-xl z-50 overflow-hidden">
                {Object.entries(PALETTES).map(([key, p]) => (
                  <button key={key} onClick={() => { setPalette(key); setShowPaletteMenu(false) }}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-slate-50 dark:hover:bg-gray-700 ${palette === key ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600' : 'text-slate-700 dark:text-gray-300'}`}>
                    <div className="flex gap-0.5">
                      <div className="w-3 h-4 rounded-sm" style={{ backgroundColor: p.up }} />
                      <div className="w-3 h-4 rounded-sm" style={{ backgroundColor: p.down }} />
                    </div>
                    <span className="text-xs">{p.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Indicators dropdown */}
          <div className="relative" ref={indicatorsMenuRef}>
            <button
              onClick={() => setShowIndicatorsMenu(!showIndicatorsMenu)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                showIndicatorsMenu || activeIndicatorCount > 0
                  ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-700 text-blue-600 dark:text-blue-400'
                  : 'bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:bg-slate-50 dark:hover:bg-gray-750'
              }`}
            >
              <LineChart size={13} />
              <span className="hidden sm:inline">Indicadores</span>
              {activeIndicatorCount > 0 && (
                <span className="w-4 h-4 rounded-full bg-blue-600 text-white text-[10px] font-bold flex items-center justify-center">{activeIndicatorCount}</span>
              )}
              <ChevronDown size={11} className={`transition-transform duration-150 ${showIndicatorsMenu ? 'rotate-180' : ''}`} />
            </button>

            {showIndicatorsMenu && (
              <div className="absolute top-full left-0 mt-1 w-52 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-xl shadow-xl z-50 overflow-hidden">
                <div className="px-3 pt-2.5 pb-1">
                  <span className="text-[10px] font-bold text-slate-400 dark:text-gray-500 uppercase tracking-widest">Overlays</span>
                </div>
                <IndicatorToggle active={showEma20}  onChange={setShowEma20}  color="#f59e0b" label="EMA 20" />
                <IndicatorToggle active={showEma50}  onChange={setShowEma50}  color="#3b82f6" label="EMA 50" />
                <IndicatorToggle active={showSma200} onChange={setShowSma200} color="#ef4444" label="SMA 200" />

                <div className="px-3 pt-2.5 pb-1 mt-1 border-t border-slate-100 dark:border-gray-700/60">
                  <span className="text-[10px] font-bold text-slate-400 dark:text-gray-500 uppercase tracking-widest">Paneles</span>
                </div>
                <IndicatorToggle active={showVolume} onChange={setShowVolume} color="#64748b" label="Volumen" />
                <IndicatorToggle active={showRsi}    onChange={setShowRsi}    color="#a855f7" label="RSI 14" />

                <div className="px-3 pt-2.5 pb-1 mt-1 border-t border-slate-100 dark:border-gray-700/60">
                  <span className="text-[10px] font-bold text-slate-400 dark:text-gray-500 uppercase tracking-widest">Indicadores</span>
                </div>
                {indicators.map(ind => (
                  <IndicatorToggle
                    key={ind.id}
                    active={!!activeIndicators[ind.id]}
                    onChange={(v) => {
                      setActiveIndicators(prev => ({ ...prev, [ind.id]: v }))
                      if (v) setOpenPanels(prev => ({ ...prev, [ind.id]: true }))
                    }}
                    color="#22c55e"
                    label={ind.name}
                  />
                ))}
                <div className="pb-1.5" />
              </div>
            )}
          </div>

          {/* Selected position badge */}
          {selectedPosition && (
            <div className="flex items-center gap-1.5">
              <span className={`text-xs font-bold px-2 py-1 rounded-full ${
                selectedPosition.side === 'long'
                  ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                  : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
              }`}>
                {selectedPosition.side.toUpperCase()} @ {formatPrice(selectedPosition.entry_price)}
              </span>
              <button onClick={() => setSelectedPosition(null)}
                className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-gray-300 rounded-md hover:bg-slate-100 dark:hover:bg-gray-700">
                <X size={13} />
              </button>
            </div>
          )}

          {/* Fullscreen toggle */}
          <button
            onClick={() => setIsFullscreen(!isFullscreen)}
            title={isFullscreen ? 'Salir de pantalla completa' : 'Pantalla completa'}
            className="ml-auto p-1.5 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg hover:bg-slate-50 dark:hover:bg-gray-750 text-slate-500 dark:text-gray-400"
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>

        {/* ── Main area ──────────────────────────────────────────────────────── */}
        <div className="flex-1 flex gap-2 min-h-0 overflow-hidden">

          {/* Chart */}
          <div className="flex-1 min-w-0 rounded-xl overflow-hidden relative border border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900">
            <div ref={chartContainerRef} className="w-full h-full" />

            {loadingCandles && (
              <div className="absolute top-2 right-2 flex items-center gap-2 bg-white/90 dark:bg-gray-900/90 backdrop-blur-sm px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-gray-700 shadow-sm">
                <div className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <span className="text-xs text-slate-500 dark:text-gray-400">Cargando…</span>
              </div>
            )}
            {chartError && !loadingCandles && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-50/90 dark:bg-gray-950/90">
                <div className="text-center p-6">
                  <AlertTriangle size={28} className="text-amber-500 mx-auto mb-2" />
                  <p className="text-slate-700 dark:text-gray-300 font-medium text-sm mb-1">No se pudieron cargar los datos</p>
                  <p className="text-slate-400 dark:text-gray-500 text-xs max-w-xs">{chartError}</p>
                </div>
              </div>
            )}

            {/* Indicator Badges + Settings Panels */}
            {indicators.map(ind => {
              if (!activeIndicators[ind.id]) return null
              const Badge = ind.BadgeComponent
              const Panel = ind.PanelComponent
              return (
                <div key={ind.id}>
                  {Badge && (
                    <Badge
                      onOpenSettings={() => setOpenPanels(prev => ({ ...prev, [ind.id]: true }))}
                      onClose={() => setActiveIndicators(prev => ({ ...prev, [ind.id]: false }))}
                    />
                  )}
                  {Panel && openPanels[ind.id] && (
                    <Panel
                      config={getConfig(ind.id)}
                      onChange={(next) => setConfig(ind.id, next)}
                      onClose={() => setOpenPanels(prev => ({ ...prev, [ind.id]: false }))}
                    />
                  )}
                </div>
              )
            })}
          </div>

          {/* ── Sidebar ──────────────────────────────────────────────────────── */}
          <div className="w-72 flex-shrink-0 flex flex-col gap-2 overflow-y-auto">

            {/* Open positions */}
            <div className="card py-3 px-3 space-y-2 flex-shrink-0">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold flex items-center gap-1.5 text-slate-700 dark:text-gray-300">
                  <Activity size={12} className="text-blue-500" />
                  Posiciones abiertas
                </h3>
                <span className="text-[10px] font-bold bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded-full">{openForSymbol.length}</span>
              </div>
              {openForSymbol.length === 0
                ? <p className="text-xs text-slate-400 dark:text-gray-600">Sin posiciones abiertas</p>
                : openForSymbol.map(pos => (
                    <div key={pos.id}
                      onClick={() => setSelectedPosition(selectedPosition?.id === pos.id ? null : pos)}
                      className={`p-2.5 rounded-lg text-xs cursor-pointer transition-all ${
                        selectedPosition?.id === pos.id
                          ? 'ring-2 ring-blue-500 bg-blue-50 dark:bg-blue-900/20'
                          : 'bg-slate-50 dark:bg-gray-800/60 hover:bg-slate-100 dark:hover:bg-gray-700'
                      }`}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className={`font-bold ${pos.side === 'long' ? 'text-green-500' : 'text-red-500'}`}>
                          {pos.side === 'long' ? 'LONG' : 'SHORT'}
                        </span>
                        <span className="font-mono text-slate-600 dark:text-gray-400">{formatPrice(pos.entry_price)}</span>
                      </div>
                      {(() => {
                        const roi = calculatePositionRoi(pos, prices[pos.symbol])
                        return (
                          <div className={`font-mono font-semibold mb-1.5 ${roi >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                            {roi >= 0 ? '+' : ''}{roi.toFixed(2)}% ROI (x{pos.leverage || 1})
                          </div>
                        )
                      })()}
                      <div className="space-y-0.5 text-[11px] text-slate-500 dark:text-gray-500">
                        <div className="flex justify-between"><span>Qty:</span><span className="font-mono">{parseFloat(pos.quantity).toFixed(4)}</span></div>
                        <div className="flex justify-between"><span>SL:</span><span className="font-mono text-red-400">{formatPrice(pos.current_sl_price) || '—'}</span></div>
                        {pos.current_tp_prices?.length > 0 && (
                          <div className="flex justify-between"><span>TP:</span><span className="font-mono text-green-400">{pos.current_tp_prices.map(tp => formatPrice(tp)).join(', ')}</span></div>
                        )}
                      </div>
                    </div>
                  ))
              }
            </div>

            {/* Closed positions */}
            <div className="card py-3 px-3 space-y-2 flex-shrink-0">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold flex items-center gap-1.5 text-slate-700 dark:text-gray-300">
                  <TrendingUp size={12} className="text-purple-500" />
                  Posiciones cerradas
                </h3>
                <span className="text-[10px] font-bold bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 px-1.5 py-0.5 rounded-full">{closedForSymbol.length}</span>
              </div>
              {closedForSymbol.length === 0
                ? <p className="text-xs text-slate-400 dark:text-gray-600">Sin posiciones cerradas</p>
                : (
                  <div className="space-y-1.5 max-h-52 overflow-y-auto pr-0.5">
                    {closedForSymbol.map(pos => {
                      const pnl = parseFloat(pos.realized_pnl || 0)
                      return (
                        <div key={pos.id}
                          onClick={() => setSelectedPosition(selectedPosition?.id === pos.id ? null : pos)}
                          className={`p-2.5 rounded-lg text-xs cursor-pointer transition-all ${
                            selectedPosition?.id === pos.id
                              ? 'ring-2 ring-blue-500 bg-blue-50 dark:bg-blue-900/20'
                              : 'bg-slate-50 dark:bg-gray-800/60 hover:bg-slate-100 dark:hover:bg-gray-700'
                          }`}>
                          <div className="flex items-center justify-between mb-1">
                            <span className={`font-bold ${pos.side === 'long' ? 'text-green-500' : 'text-red-500'}`}>
                              {pos.side === 'long' ? 'LONG' : 'SHORT'}
                            </span>
                            <span className={`font-mono font-bold ${pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                              {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} USDT
                            </span>
                          </div>
                          <div className="text-[11px] text-slate-400 dark:text-gray-600">
                            {formatTime(pos.opened_at)} → {formatTime(pos.closed_at)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              }
            </div>

            {/* Recent signals */}
            <div className="card py-3 px-3 space-y-2 flex-shrink-0">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold flex items-center gap-1.5 text-slate-700 dark:text-gray-300">
                  <Clock size={12} className="text-yellow-500" />
                  Señales recientes
                </h3>
                <span className="text-[10px] font-bold bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400 px-1.5 py-0.5 rounded-full">{signals.length}</span>
              </div>
              {signals.length === 0
                ? <p className="text-xs text-slate-400 dark:text-gray-600">Sin señales recientes</p>
                : (
                  <div className="space-y-1.5 max-h-52 overflow-y-auto pr-0.5">
                    {signals.slice(0, 10).map(sig => (
                      <div key={sig.id} className="p-2.5 bg-slate-50 dark:bg-gray-800/60 rounded-lg text-xs">
                        <div className="flex items-center justify-between mb-1">
                          <span className={`font-bold ${sig.action === 'long' ? 'text-green-500' : sig.action === 'short' ? 'text-red-500' : 'text-slate-500'}`}>
                            {sig.action?.toUpperCase()}
                          </span>
                          <span className="text-slate-400 dark:text-gray-600 text-[11px]">{formatTime(sig.received_at)}</span>
                        </div>
                        <div className="font-mono text-slate-600 dark:text-gray-400 mb-1">@ {formatPrice(sig.price)}</div>
                        {sig.indicator_values && Object.keys(sig.indicator_values).length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(sig.indicator_values).slice(0, 3).map(([k, v], i) => (
                              <IndicatorBadge key={k} name={k.toUpperCase()} value={v} color={i % 2 === 0 ? 'blue' : 'purple'} />
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )
              }
            </div>

            {/* Legend */}
            <div className="card py-3 px-3 flex-shrink-0">
              <h3 className="text-xs font-semibold text-slate-700 dark:text-gray-300 mb-2">Leyenda</h3>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px] text-slate-500 dark:text-gray-500">
                <div className="flex items-center gap-1.5"><TrendingUp  size={11} className="text-green-500 flex-shrink-0" /> Señal LONG</div>
                <div className="flex items-center gap-1.5"><TrendingDown size={11} className="text-red-500 flex-shrink-0" /> Señal SHORT</div>
                <div className="flex items-center gap-1.5"><div className="w-5 h-0.5 border-t-2 border-dotted border-green-500" /> Precio señal</div>
                <div className="flex items-center gap-1.5"><div className="w-5 h-0.5 bg-green-500" /> Entrada / TP</div>
                <div className="flex items-center gap-1.5"><div className="w-5 h-0.5 bg-red-500" /> Stop Loss</div>
                <div className="flex items-center gap-1.5"><div className="w-5 h-0.5 bg-amber-500" /> Break Even</div>
                <div className="flex items-center gap-1.5"><div className="w-5 h-0.5 bg-purple-500" /> Trailing Stop</div>
                <div className="flex items-center gap-1.5"><div className="w-5 h-1.5 bg-green-500/25 rounded" /> Duración LONG</div>
              </div>
            </div>

          </div>{/* /sidebar */}
        </div>{/* /main */}
      </div>{/* /inner */}
    </div>
  )
}
