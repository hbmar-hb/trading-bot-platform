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
  Maximize2, Minimize2, CandlestickChart, AreaChart, Layers,
  Crosshair, Loader2, Star, Plus, Minus, Settings2,
} from 'lucide-react'
import { manualTradeService } from '@/services/manualTrade'
import DrawingTools from '@/components/Chart/DrawingTools'
import ICTCanvas from '@/components/Chart/ICTCanvas'
import ICTConfigPanel, { DEFAULT_ICT_CONFIG } from '@/components/Chart/ICTConfigPanel'
import SBTCanvas from '@/components/Chart/SBTCanvas'

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

// ─── Fondos de gráfico ────────────────────────────────────────────────────────
const BACKGROUNDS = {
  default:    { label: 'Auto',      bg: null,      text: null,      grid: null,      isDark: null  },
  // Oscuros neutros
  dark:       { label: 'Slate',     bg: '#111827', text: '#94a3b8', grid: '#1f2937', isDark: true  },
  charcoal:   { label: 'Carbón',    bg: '#1c1c2e', text: '#8b8baf', grid: '#252542', isDark: true  },
  obsidian:   { label: 'Obsidiana', bg: '#0a0a0a', text: '#6b7280', grid: '#1a1a1a', isDark: true  },
  // Oscuros azulados
  navy:       { label: 'Navy',      bg: '#0a1628', text: '#7ec8e3', grid: '#0f2035', isDark: true  },
  midnight:   { label: 'Midnight',  bg: '#020817', text: '#475569', grid: '#0f172a', isDark: true  },
  deepBlue:   { label: 'Índigo',    bg: '#0c0f2e', text: '#818cf8', grid: '#14183d', isDark: true  },
  // Oscuros con color
  forest:     { label: 'Bosque',    bg: '#0d1f12', text: '#6ee7b7', grid: '#132018', isDark: true  },
  teal:       { label: 'Teal',      bg: '#051c1c', text: '#5eead4', grid: '#0a2828', isDark: true  },
  deepPurple: { label: 'Violeta',   bg: '#0f0a1e', text: '#a78bfa', grid: '#1a1030', isDark: true  },
  deepRed:    { label: 'Burdeos',   bg: '#1a0808', text: '#fca5a5', grid: '#2a1010', isDark: true  },
  copper:     { label: 'Cobre',     bg: '#1a1005', text: '#d97706', grid: '#241808', isDark: true  },
  terminal:   { label: 'Terminal',  bg: '#0d1117', text: '#3fb950', grid: '#161b22', isDark: true  },
  // Claros
  light:      { label: 'Blanco',    bg: '#ffffff', text: '#64748b', grid: '#f1f5f9', isDark: false },
  cream:      { label: 'Crema',     bg: '#fffbf0', text: '#78716c', grid: '#fef3dc', isDark: false },
  sky:        { label: 'Cielo',     bg: '#f0f7ff', text: '#475569', grid: '#dbeafe', isDark: false },
  sepia:      { label: 'Sepia',     bg: '#f4efe6', text: '#6b5a3e', grid: '#e8dcc8', isDark: false },
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
function IndicatorToggle({ active, onChange, color, label, onSettings }) {
  return (
    <div className="flex items-center">
      <button
        onClick={() => onChange(!active)}
        className="flex-1 flex items-center gap-2.5 px-3 py-2 hover:bg-slate-50 dark:hover:bg-gray-700/60 transition-colors text-left"
      >
        <div className="w-4 h-1 rounded-full flex-shrink-0" style={{ backgroundColor: active ? color : '#64748b' }} />
        <span className={`text-sm flex-1 ${active ? 'text-slate-800 dark:text-gray-100' : 'text-slate-400 dark:text-gray-500'}`}>
          {label}
        </span>
        {active
          ? <Eye size={12} className="text-slate-400 dark:text-gray-500 flex-shrink-0" />
          : <EyeOff size={12} className="text-slate-300 dark:text-gray-700 flex-shrink-0" />}
      </button>
      {onSettings && active && (
        <button
          onClick={onSettings}
          className="px-2 py-2 text-slate-400 dark:text-gray-500 hover:text-slate-700 dark:hover:text-gray-200 hover:bg-slate-100 dark:hover:bg-gray-700 transition-colors"
          title="Configurar"
        >
          <Settings2 size={11} />
        </button>
      )}
    </div>
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
  const slPriceLineRef        = useRef(null)
  const tpPriceLinesRef       = useRef([])
  const draggingLineRef       = useRef(null)   // 'sl' | 'tp_0' | 'tp_1' | null
  const dragNewPriceRef       = useRef(null)
  const savedRangeRef         = useRef(null)   // { range, data } – restored on chart recreation
  const indicatorsMenuRef  = useRef(null)
  const tfMenuRef          = useRef(null)
  const paletteMenuRef     = useRef(null)
  const bgMenuRef          = useRef(null)
  const appearanceKeyRef   = useRef('')
  const candleDataRef      = useRef([])
  const overlayLabelsRawRef = useRef([])
  const tradingModeRef     = useRef(false)
  const tradeEntryPriceRef = useRef(null)
  const tradeEntryLineRef  = useRef(null)

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
  const [showEma20, setShowEma20]   = useState(false)
  const [showEma50, setShowEma50]   = useState(false)
  const [showSma200, setShowSma200] = useState(false)
  const [showRsi, setShowRsi]       = useState(false)
  const [showVolume, setShowVolume] = useState(false)
  const [showICT, setShowICT]               = useState(false)
  const [ictData, setIctData]               = useState(null)
  const [ictSignal, setIctSignal]           = useState(null)
  const [ictHistoryData, setIctHistoryData] = useState(null)
  const [ictConfig, setIctConfig]           = useState(DEFAULT_ICT_CONFIG)
  const [showICTConfig, setShowICTConfig]   = useState(false)

  // Indicators system
  const { configs, getConfig, setConfig } = useIndicatorConfig()
  const [activeIndicators, setActiveIndicators] = useState({})
  const [openPanels, setOpenPanels] = useState({})

  // Chart appearance
  const [chartType, setChartType] = useState('candles')  // 'candles' | 'line' | 'area'
  const [palette, setPalette]     = useState('classic')
  const [chartBg, setChartBg]     = useState('default')
  const [showBgMenu, setShowBgMenu] = useState(false)
  const [overlayLabels, setOverlayLabels] = useState([])
  const [indResults, setIndResults] = useState({})   // resultados detect() para los badges

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

  // Trade panel
  const [showTradePanel, setShowTradePanel]     = useState(false)
  const [tradingMode, setTradingMode]           = useState(false)
  const [tradeEntryPrice, setTradeEntryPrice]   = useState(null)
  const [tradeAccounts, setTradeAccounts]       = useState([])
  const [tradeAccountId, setTradeAccountId]     = useState('')
  const [tradeAccountType, setTradeAccountType] = useState('real')
  const [tradeLeverage, setTradeLeverage]       = useState(10)
  const [tradeSizingType, setTradeSizingType]   = useState('percentage')
  const [tradeSizingValue, setTradeSizingValue] = useState(5)
  const [tradeSlPct, setTradeSlPct]             = useState(2)
  const [tradeLoading, setTradeLoading]         = useState(false)
  const [tradeFeedback, setTradeFeedback]       = useState(null)
  const [tradeAdvOpen, setTradeAdvOpen]         = useState(false)
  const [tradeTPs, setTradeTPs]                 = useState([])
  const [tradeTrailing, setTradeTrailing]       = useState({ enabled: false, activation_profit: 1, callback_rate: 0.5 })
  const [tradeBreakeven, setTradeBreakeven]     = useState({ enabled: false, activation_profit: 1, lock_profit: 0.2 })
  const [tradeDynamicSL, setTradeDynamicSL]     = useState({ enabled: false, step_percent: 1, max_steps: 3 })
  const [favorites, setFavorites]               = useState(() => { try { return JSON.parse(localStorage.getItem('chart_favorites') || '[]') } catch { return [] } })
  const [showFavMenu, setShowFavMenu]           = useState(false)
  const favMenuRef                              = useRef(null)
  const [sidebarVisible, setSidebarVisible]     = useState({ openPos: false, closedPos: false, signals: false, legend: false })
  const [closedLoaded, setClosedLoaded]         = useState(false)
  const [strategyEdit, setStrategyEdit]         = useState({ tps: [], trailing: { enabled: false, activation_profit: 1, callback_rate: 0.5 } })
  const [strategyLoading, setStrategyLoading]   = useState(false)
  const [showStrategyPanel, setShowStrategyPanel] = useState(false)
  const [chartVersion, setChartVersion]           = useState(0)

  const prices      = usePositionStore(s => s.prices)
  const sidebarOpen = useUiStore(s => s.sidebarOpen)
  const isDark      = useUiStore(s => s.isDark)

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
      if (bgMenuRef.current && !bgMenuRef.current.contains(e.target))
        setShowBgMenu(false)
      if (favMenuRef.current && !favMenuRef.current.contains(e.target))
        setShowFavMenu(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Init strategy edit panel from selected position
  useEffect(() => {
    if (!selectedPosition) { setShowStrategyPanel(false); return }
    const bot = bots.find(b => b.id === selectedPosition.bot_id)
    const tps = (selectedPosition.current_tp_prices || []).map(tp => {
      const price = parseFloat(tp?.price ?? tp)
      const entry = parseFloat(selectedPosition.entry_price)
      const profitPct = selectedPosition.side === 'long'
        ? ((price - entry) / entry * 100)
        : ((entry - price) / entry * 100)
      return { profit_percent: parseFloat(profitPct.toFixed(2)), close_percent: tp?.close_percent ?? 50 }
    })
    const trailing = bot?.trailing_config || { enabled: false, activation_profit: 1, callback_rate: 0.5 }
    setStrategyEdit({ tps, trailing: { enabled: !!trailing.enabled, activation_profit: trailing.activation_profit ?? 1, callback_rate: trailing.callback_rate ?? 0.5 } })
  }, [selectedPosition?.id])

  const toggleFavorite = (symbol) => {
    setFavorites(prev => {
      const next = prev.includes(symbol) ? prev.filter(s => s !== symbol) : [...prev, symbol]
      localStorage.setItem('chart_favorites', JSON.stringify(next))
      return next
    })
  }

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
        // Carga en paralelo: posiciones abiertas, bots, símbolos y señales al mismo tiempo
        // Las cerradas se cargan en lazy cuando el usuario abre ese panel
        const [posRes, botsRes, , sigRes] = await Promise.all([
          positionsService.unified(true),
          botsService.list(),
          loadSymbols(''),
          tradingSignalsService.list({ symbol: selectedSymbol, days: 7, limit: 100 }).catch(() => null),
        ])
        const open     = Array.isArray(posRes?.data)  ? posRes.data  : Array.isArray(posRes)  ? posRes  : []
        const botsData = Array.isArray(botsRes?.data) ? botsRes.data : Array.isArray(botsRes) ? botsRes : []
        setPositions(open)
        setBots(botsData)
        setSignals(sigRes?.data?.signals || [])
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

  useEffect(() => { candleDataRef.current = candleData }, [candleData])

  // ─── Reposition HTML signal labels on scroll / zoom ──────────────────────────
  const updateLabelPositions = useCallback(() => {
    if (!chartRef.current || !candleSeriesRef.current || overlayLabelsRawRef.current.length === 0) {
      setOverlayLabels([])
      return
    }
    const positioned = overlayLabelsRawRef.current.map(l => {
      const candle = candleDataRef.current.find(c => c.time === l.time)
      const price  = l.isBull ? (candle?.low ?? l.fallbackPrice) : (candle?.high ?? l.fallbackPrice)
      const x = chartRef.current.timeScale().timeToCoordinate(l.time)
      const y = candleSeriesRef.current.priceToCoordinate(price)
      if (x === null || y === null) return null
      return { ...l, x, y }
    }).filter(Boolean)
    setOverlayLabels(positioned)
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

    // ── Fast path: appearance unchanged → just swap candle data ──────────────
    const appearanceKey = `${chartType}|${palette}|${chartBg}|${isDark}`
    if (
      chartRef.current &&
      candleSeriesRef.current &&
      !selectedPosition &&
      appearanceKeyRef.current === appearanceKey
    ) {
      if (chartType === 'line' || chartType === 'area') {
        candleSeriesRef.current.setData(candleData.map(c => ({ time: c.time, value: c.close })))
      } else {
        candleSeriesRef.current.setData(candleData)
      }
      chartRef.current.timeScale().fitContent()
      return
    }
    appearanceKeyRef.current = appearanceKey

    if (chartRef.current) {
      try { savedRangeRef.current = { range: chartRef.current.timeScale().getVisibleLogicalRange(), data: candleData } } catch {}
      chartRef.current.remove(); chartRef.current = null
    }
    candleSeriesRef.current = null
    indicatorSeriesRef.current = { ema20: null, ema50: null, sma200: null, rsi: null, volume: null }
    overlayPriceLinesRef.current = []
    overlaySeriesRef.current = []
    posMarkersRef.current = []
    overlayMarkersRef.current = []

    // ── Background preset ─────────────────────────────────────────────────────
    const bgPreset = BACKGROUNDS[chartBg]
    const bg       = bgPreset?.bg   ?? (isDark ? '#111827' : '#ffffff')
    const text     = bgPreset?.text ?? (isDark ? '#94a3b8' : '#64748b')
    const grid     = bgPreset?.grid ?? (isDark ? '#1f2937' : '#f1f5f9')
    const bgDark   = bgPreset ? bgPreset.isDark !== false : isDark

    const container = chartContainerRef.current
    const chart = createChart(container, {
      layout:  { background: { color: bg }, textColor: text, fontSize: 11 },
      grid:    { vertLines: { color: grid, style: 2 }, horzLines: { color: grid, style: 2 } },
      crosshair: {
        mode: 1,
        vertLine: { color: bgDark ? '#475569' : '#94a3b8', labelBackgroundColor: bgDark ? '#374151' : '#94a3b8' },
        horzLine: { color: bgDark ? '#475569' : '#94a3b8', labelBackgroundColor: bgDark ? '#374151' : '#94a3b8' },
      },
      timeScale: { borderColor: grid, timeVisible: true, secondsVisible: false, barSpacing: 8, minBarSpacing: 3 },
      rightPriceScale: { borderColor: grid },
      handleScroll: { vertTouchDrag: false },
      width:  container.offsetWidth  || 800,
      height: container.offsetHeight || 500,
    })
    chartRef.current = chart
    setChartVersion(v => v + 1)

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
      slPriceLineRef.current = null
      tpPriceLinesRef.current = []
      if (pos.current_sl_price) {
        const slLine = mainSeries.createPriceLine({ price: parseFloat(pos.current_sl_price), color: '#ef4444', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: '⬡ SL' })
        positionPriceLinesRef.current.push(slLine)
        slPriceLineRef.current = slLine
      }
      if (pos.current_tp_prices?.length > 0) pos.current_tp_prices.forEach((tp, idx) => {
        const tpLine = mainSeries.createPriceLine({ price: parseFloat(tp?.price ?? tp), color: '#22c55e', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: `⬡ TP${idx + 1}` })
        positionPriceLinesRef.current.push(tpLine)
        tpPriceLinesRef.current.push(tpLine)
      })

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

      const canRestore = savedRangeRef.current?.range && savedRangeRef.current.data === candleData
      if (canRestore) {
        try { chart.timeScale().setVisibleLogicalRange(savedRangeRef.current.range) } catch { chart.timeScale().fitContent() }
      } else {
        chart.timeScale().fitContent()
      }
    } else {
      const canRestore = savedRangeRef.current?.range && savedRangeRef.current.data === candleData
      if (canRestore) {
        try { chart.timeScale().setVisibleLogicalRange(savedRangeRef.current.range) } catch { chart.timeScale().fitContent() }
      } else {
        chart.timeScale().fitContent()
      }
    }

    posMarkersRef.current = allMarkers.sort((a, b) => a.time - b.time)
    mainSeries.setMarkers(posMarkersRef.current)

    // Trade entry price line (restored on chart recreation)
    tradeEntryLineRef.current = null
    if (tradeEntryPriceRef.current) {
      try {
        tradeEntryLineRef.current = mainSeries.createPriceLine({
          price: tradeEntryPriceRef.current,
          color: '#f59e0b',
          lineWidth: 2,
          lineStyle: 1,
          axisLabelVisible: true,
          title: 'Entry',
        })
      } catch {}
    }

    // Crosshair: change cursor when near SL/TP lines (for drag affordance)
    const DRAG_PX = 12
    const handleCrosshairMove = (param) => {
      if (!param.point || !chartContainerRef.current) return
      const y = param.point.y
      let nearLine = false
      const checkPrice = (price) => {
        if (!price) return
        const lineY = mainSeries.priceToCoordinate(parseFloat(price))
        if (lineY !== null && Math.abs(y - lineY) < DRAG_PX) nearLine = true
      }
      if (selectedPosition) {
        checkPrice(selectedPosition.current_sl_price)
        ;(selectedPosition.current_tp_prices || []).forEach(tp => checkPrice(tp?.price ?? tp))
      }
      chartContainerRef.current.style.cursor = nearLine ? 'ns-resize' : (tradingModeRef.current ? 'crosshair' : '')
    }
    chart.subscribeCrosshairMove(handleCrosshairMove)

    // Chart click handler for drawing mode
    const handleChartClick = (params) => {
      if (!tradingModeRef.current || !params.point) return
      const price = mainSeries.coordinateToPrice(params.point.y)
      if (price && price > 0) {
        setTradeEntryPrice(price)
        setTradingMode(false)
      }
    }
    chart.subscribeClick(handleChartClick)

    // Resize observer
    const ro = new ResizeObserver(() => {
      if (chartContainerRef.current && chartRef.current) {
        const { width, height } = chartContainerRef.current.getBoundingClientRect()
        if (width > 0 && height > 0) chartRef.current.applyOptions({ width, height })
      }
    })
    ro.observe(container)

    const onViewChange = () => updateLabelPositions()
    chart.timeScale().subscribeVisibleLogicalRangeChange(onViewChange)

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onViewChange)
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
      chart.unsubscribeClick(handleChartClick)
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      tradeEntryLineRef.current = null
      positionLineSeriesRef.current = null
      slPriceLineRef.current = null
      tpPriceLinesRef.current = []
      if (positionLineSeriesRef._aux) positionLineSeriesRef._aux = []
      indicatorSeriesRef.current = { ema20: null, ema50: null, sma200: null, rsi: null, volume: null }
      overlayLabelsRawRef.current = []
      setOverlayLabels([])
    }
  }, [candleData, selectedPosition, signals, bots, loading, selectedSymbol, selectedSymbolNorm, chartType, palette, chartBg, isDark, updateLabelPositions])

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
  }, [showEma20, showEma50, showSma200, showRsi, showVolume, candleData, palette, chartType, chartBg, isDark, chartVersion]) // eslint-disable-line react-hooks/exhaustive-deps

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
    overlayLabelsRawRef.current = []

    const anyActive = Object.values(activeIndicators).some(Boolean)
    if (!anyActive) { syncMarkers(); updateLabelPositions(); return }

    // API que recibe cada indicador para dibujar
    const api = {
      addMarker(m) { overlayMarkersRef.current.push(m) },
      addLabel(l)  { overlayLabelsRawRef.current.push(l) },
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
    const newResults = {}
    for (const ind of indicators) {
      if (!activeIndicators[ind.id]) continue
      const config = getConfig(ind.id)
      const result = ind.detect ? ind.detect(candleData, config) : null
      newResults[ind.id] = result
      if (result && ind.render) {
        ind.render(chart, cSeries, result, config, api)
      }
    }
    setIndResults(newResults)

    syncMarkers()
    updateLabelPositions()
  }, [activeIndicators, configs, candleData, syncMarkers, updateLabelPositions, palette, chartType, chartBg, isDark])

  // ─── ICT/SMC indicators ───────────────────────────────────────────────────────
  // Use first-candle timestamp as dep: changes when timeframe or symbol loads new candles,
  // but NOT on every tick (to avoid refetching on each new close).
  const ictFrom = candleData[0]?.time ?? 0

  const ictSignalParams = useMemo(() => {
    const sig = ictConfig.signal ?? {}
    const mtf = ictConfig.multiTimeframe ?? {}
    return {
      min_score:                 sig.minScore ?? 4,
      require_sweep:             sig.requireSweep ?? false,
      reject_asia:               sig.rejectAsia ?? false,
      reject_equilibrium:        sig.rejectEquilibrium ?? false,
      require_premium_discount:  sig.requirePremiumDiscount ?? false,
      min_rr:                    sig.minRR ?? 1.2,
      use_structural_sl_tp:      sig.useStructuralSLTP ?? true,
      require_htf_alignment:     mtf.requireHTFAlignment ?? false,
      poi_proximity_pct:         sig.poiProximityPct ?? 0.5,
      recent_structure_bars:     sig.recentStructureBars ?? 15,
      sl_tp_recency_bars:        sig.slTpRecencyBars ?? 20,
      use_volume:                sig.useVolume ?? true,
      vol_spike_threshold:       sig.volSpikeThreshold ?? 1.5,
    }
  }, [ictConfig.signal, ictConfig.multiTimeframe])

  const ictFvgParams = useMemo(() => ({
    fvg_max_per_tf:        ictConfig.fvg?.maxFVG ?? 10,
    fvg_max_ifvg_per_tf:   ictConfig.fvg?.maxIFVG ?? 5,
    fvg_min_size_atr_mult: ictConfig.fvg?.minSizeATRMult ?? 0.5,
    fvg_extension_bars:    ictConfig.fvg?.extensionBars ?? 5,
  }), [ictConfig.fvg])

  const ictObParams = useMemo(() => ({
    ob_max_per_tf:        ictConfig.ob?.maxPerTf ?? 10,
    ob_lookback:          ictConfig.ob?.lookback ?? 30,
    ob_extension_bars:    ictConfig.ob?.extensionBars ?? 10,
    ob_mitigation:        ictConfig.ob?.mitigation ?? 'wick',
    ob_min_volume_grade:  ictConfig.ob?.minVolumeGrade ?? 1.2,
  }), [ictConfig.ob])

  const ictStructureParams = useMemo(() => ({
    structure_swing_len:      ictConfig.structure?.swingLen ?? 10,
    structure_internal_len:   ictConfig.structure?.internalLen ?? 5,
    structure_min_atr_mult:   ictConfig.structure?.minMoveATRMult ?? 0.5,
    show_strong_weak:         ictConfig.structure?.showStrongWeak ?? true,
  }), [ictConfig.structure])

  const ictFibParams = useMemo(() => ({
    fib_enabled:    ictConfig.fib?.showFib ?? true,
    fib_show_ote:   ictConfig.fib?.showOTE ?? true,
  }), [ictConfig.fib])

  const ictHtfParams = useMemo(() => {
    const mtf = ictConfig.multiTimeframe ?? {}
    return {
      enable_htf:      mtf.enableHTF ?? true,
      htf_resolution:  mtf.htfResolution || undefined,
      htf_ema_len:     mtf.htfEMALen ?? 50,
    }
  }, [ictConfig.multiTimeframe])

  useEffect(() => {
    if (!showICT || candleData.length === 0 || ictFrom === 0) {
      setIctData(null)
      setIctSignal(null)
      return
    }
    const params = {
      symbol:     selectedSymbol,
      resolution: timeframe,
      from_time:  candleData[0].time,
      to_time:    candleData[candleData.length - 1].time,
      ...ictSignalParams,
      ...ictFvgParams,
      ...ictObParams,
      ...ictStructureParams,
      ...ictFibParams,
      ...ictHtfParams,
    }
    Promise.all([
      chartingService.getICT(params),
      chartingService.getICTSignal(params),
    ]).then(([ictRes, sigRes]) => {
      setIctData(ictRes.data ?? ictRes)
      const sig = sigRes.data ?? sigRes
      setIctSignal(sig?.direction && sig.direction !== 'none' ? sig : null)
    }).catch(() => {})
  }, [showICT, selectedSymbol, timeframe, ictFrom, ictSignalParams, ictFvgParams, ictObParams, ictStructureParams, ictFibParams, ictHtfParams]) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── ICT historical signal scan ──────────────────────────────────────────────
  const showHistory = ictConfig.signal?.showHistory ?? true
  useEffect(() => {
    if (!showICT || !showHistory || candleData.length === 0 || ictFrom === 0) {
      setIctHistoryData(null)
      return
    }
    const params = {
      symbol:     selectedSymbol,
      resolution: timeframe,
      from_time:  candleData[0].time,
      to_time:    candleData[candleData.length - 1].time,
      ...ictSignalParams,
      ...ictFvgParams,
      ...ictObParams,
      ...ictStructureParams,
      ...ictFibParams,
      ...ictHtfParams,
    }
    chartingService.getICTSignalsHistory(params)
      .then(res => { setIctHistoryData(res.data ?? res) })
      .catch(() => {})
  }, [showICT, showHistory, selectedSymbol, timeframe, ictFrom, ictSignalParams, ictFvgParams, ictObParams, ictStructureParams, ictFibParams, ictHtfParams]) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Keep trading refs in sync ────────────────────────────────────────────────
  useEffect(() => { tradingModeRef.current = tradingMode }, [tradingMode])
  useEffect(() => { tradeEntryPriceRef.current = tradeEntryPrice }, [tradeEntryPrice])

  // ─── Update trade entry line when price changes (without chart recreation) ────
  useEffect(() => {
    const series = candleSeriesRef.current
    if (!series) return
    if (tradeEntryLineRef.current) {
      try { series.removePriceLine(tradeEntryLineRef.current) } catch {}
      tradeEntryLineRef.current = null
    }
    if (tradeEntryPrice) {
      try {
        tradeEntryLineRef.current = series.createPriceLine({
          price: tradeEntryPrice,
          color: '#f59e0b',
          lineWidth: 2,
          lineStyle: 1,
          axisLabelVisible: true,
          title: 'Entry',
        })
      } catch {}
    }
  }, [tradeEntryPrice])

  // ─── Load trade accounts when panel opens ─────────────────────────────────────
  useEffect(() => {
    if (!showTradePanel || tradeAccounts.length > 0) return
    manualTradeService.getAccounts()
      .then(res => {
        const accs = res.data?.accounts || []
        setTradeAccounts(accs)
        if (accs.length > 0) {
          setTradeAccountId(accs[0].id)
          setTradeAccountType(accs[0].type || 'real')
        }
      })
      .catch(() => {})
  }, [showTradePanel])

  // ─── Execute trade from chart ──────────────────────────────────────────────────
  const executeTrade = async (action) => {
    if (!tradeAccountId) return
    setTradeLoading(true)
    setTradeFeedback(null)
    const payload = {
      symbol: toCcxtSymbol(selectedSymbol),
      action,
      leverage: tradeLeverage,
      position_sizing_type: tradeSizingType,
      position_value: tradeSizingValue,
      initial_sl_percentage: tradeSlPct,
      take_profits: tradeTPs.filter(tp => tp.profit_percent && tp.close_percent),
      trailing_config: tradeTrailing.enabled ? { enabled: true, activation_profit: tradeTrailing.activation_profit, callback_rate: tradeTrailing.callback_rate } : null,
      breakeven_config: tradeBreakeven.enabled ? { enabled: true, activation_profit: tradeBreakeven.activation_profit, lock_profit: tradeBreakeven.lock_profit } : null,
      dynamic_sl_config: tradeDynamicSL.enabled ? { enabled: true, step_percent: tradeDynamicSL.step_percent, max_steps: tradeDynamicSL.max_steps } : null,
      order_type: tradeEntryPrice ? 'limit' : 'market',
    }
    if (tradeEntryPrice) payload.limit_price = tradeEntryPrice
    if (tradeAccountType === 'paper') payload.paper_balance_id = tradeAccountId
    else payload.exchange_account_id = tradeAccountId

    try {
      await manualTradeService.execute(payload)
      const isLimit = !!tradeEntryPrice
      setTradeFeedback({ type: 'ok', msg: `${action.toUpperCase()} enviado — procesando…` })
      setTradeEntryPrice(null)
      setTradingMode(false)

      // Celery processes the trade async — short wait then poll
      await new Promise(r => setTimeout(r, 800))

      const posRes = await positionsService.unified(true)
      const open   = Array.isArray(posRes?.data) ? posRes.data : Array.isArray(posRes) ? posRes : []
      setPositions(prev => [...open, ...prev.filter(p => p.status === 'closed')])

      // Auto-select the new position and show it on chart
      const newPos = open.find(p =>
        normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm &&
        p.status === 'open' && p.side === action
      )
      if (newPos) {
        setSelectedPosition(newPos)
        setSidebarVisible(v => ({ ...v, openPos: true }))
        setTradeFeedback({ type: 'ok', msg: `${action.toUpperCase()} abierto @ ${formatPrice(newPos.entry_price)}` })
      } else if (isLimit) {
        setTradeFeedback({ type: 'ok', msg: `Limit ${action.toUpperCase()} pendiente de ejecución` })
      } else {
        setTradeFeedback({ type: 'ok', msg: `${action.toUpperCase()} enviado — revisa posiciones` })
      }
    } catch (err) {
      setTradeFeedback({ type: 'error', msg: err.response?.data?.detail || 'Error al ejecutar' })
    } finally {
      setTradeLoading(false)
    }
  }

  // ─── Drag price lines ────────────────────────────────────────────────────────
  const refreshSelectedPosition = async (posId) => {
    const posRes = await positionsService.unified(true)
    const open = Array.isArray(posRes?.data) ? posRes.data : Array.isArray(posRes) ? posRes : []
    const updated = open.find(p => p.id === posId)
    if (updated) {
      setSelectedPosition(updated)
      setPositions(prev => prev.map(p => p.id === posId ? updated : p))
    }
  }

  const handleChartMouseDown = useCallback((e) => {
    if (!selectedPosition || !candleSeriesRef.current) return
    const y = e.nativeEvent.offsetY
    const THRESHOLD = 14
    const tryLine = (price, lineId) => {
      if (!price) return false
      const lineY = candleSeriesRef.current.priceToCoordinate(parseFloat(price))
      if (lineY !== null && Math.abs(y - lineY) < THRESHOLD) {
        draggingLineRef.current = lineId
        dragNewPriceRef.current = parseFloat(price)
        e.preventDefault()
        // Freeze chart pan/zoom so the drag only moves the price line
        if (chartRef.current) chartRef.current.applyOptions({ handleScroll: false, handleScale: false })
        return true
      }
      return false
    }
    if (tryLine(selectedPosition.current_sl_price, 'sl')) return
    ;(selectedPosition.current_tp_prices || []).forEach((tp, i) => {
      tryLine(tp?.price ?? tp, `tp_${i}`)
    })
  }, [selectedPosition])

  const handleChartMouseMove = useCallback((e) => {
    if (!draggingLineRef.current || !candleSeriesRef.current) return
    const price = candleSeriesRef.current.coordinateToPrice(e.nativeEvent.offsetY)
    if (!price || price <= 0) return
    dragNewPriceRef.current = price
    if (draggingLineRef.current === 'sl' && slPriceLineRef.current) {
      slPriceLineRef.current.applyOptions({ price })
    } else if (draggingLineRef.current?.startsWith('tp_')) {
      const idx = parseInt(draggingLineRef.current.split('_')[1])
      if (tpPriceLinesRef.current[idx]) tpPriceLinesRef.current[idx].applyOptions({ price })
    }
  }, [])

  const handleChartMouseUp = useCallback(async () => {
    const lineId = draggingLineRef.current
    const newPrice = dragNewPriceRef.current
    draggingLineRef.current = null
    // Restore chart interaction after drag
    if (chartRef.current) chartRef.current.applyOptions({ handleScroll: { vertTouchDrag: false }, handleScale: true })
    if (!lineId || !newPrice || !selectedPosition) return
    try {
      if (lineId === 'sl') {
        await positionsService.updateSL(selectedPosition.id, { sl_price: newPrice })
      } else if (lineId.startsWith('tp_')) {
        const idx = parseInt(lineId.split('_')[1])
        const newTPs = (selectedPosition.current_tp_prices || []).map((tp, i) =>
          i === idx ? { ...(typeof tp === 'object' ? tp : { price: tp }), price: newPrice } : tp
        )
        await positionsService.updateTP(selectedPosition.id, { tp_levels: newTPs })
      }
      await refreshSelectedPosition(selectedPosition.id)
    } catch (err) {
      console.error('Error updating price line:', err)
    }
  }, [selectedPosition])

  // ─── Strategy edit panel ─────────────────────────────────────────────────────
  const applyStrategyChanges = async (pos) => {
    setStrategyLoading(true)
    try {
      const bot = bots.find(b => b.id === pos.bot_id)
      const trailing = strategyEdit.trailing
      await positionsService.updateStrategy(pos.id, {
        take_profits: strategyEdit.tps.filter(t => t.profit_percent > 0 && t.close_percent > 0),
        trailing_config: { enabled: trailing.enabled, activation_profit: Number(trailing.activation_profit), callback_rate: Number(trailing.callback_rate) },
        breakeven_config: bot?.breakeven_config || undefined,
        dynamic_sl_config: bot?.dynamic_sl_config || undefined,
      })
      await refreshSelectedPosition(pos.id)
      setShowStrategyPanel(false)
    } catch (err) {
      console.error('Error applying strategy:', err)
    } finally {
      setStrategyLoading(false)
    }
  }

  const closePosition = async (pos) => {
    try {
      await positionsService.close(pos.id)
      const posRes = await positionsService.unified(true)
      const open = Array.isArray(posRes?.data) ? posRes.data : Array.isArray(posRes) ? posRes : []
      setPositions(prev => [...open, ...prev.filter(p => p.status === 'closed')])
      if (selectedPosition?.id === pos.id) setSelectedPosition(null)
    } catch (err) {
      console.error('Error cerrando posición:', err)
    }
  }

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
  const activeIndicatorCount = [showEma20, showEma50, showSma200, showRsi, showVolume, showICT, ...Object.values(activeIndicators)].filter(Boolean).length

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
                        <div key={s.symbol} className={`flex items-center hover:bg-slate-50 dark:hover:bg-gray-700 ${s.symbol === selectedSymbol ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}>
                          <button onClick={() => handleSelectSymbol(s.symbol)}
                            className={`flex-1 px-4 py-2 text-left text-sm ${s.symbol === selectedSymbol ? 'text-blue-600' : 'text-slate-700 dark:text-gray-300'}`}>
                            <div className="font-medium">{s.symbol}</div>
                            <div className="text-xs text-slate-400">{s.description}</div>
                          </button>
                          <button onClick={e => { e.stopPropagation(); toggleFavorite(s.symbol) }}
                            title={favorites.includes(s.symbol) ? 'Quitar de favoritos' : 'Añadir a favoritos'}
                            className="px-2 py-2 text-slate-300 dark:text-gray-600 hover:text-amber-400 dark:hover:text-amber-400 flex-shrink-0">
                            <Star size={12} className={favorites.includes(s.symbol) ? 'fill-amber-400 text-amber-400' : ''} />
                          </button>
                        </div>
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

          {/* Background selector */}
          <div className="relative" ref={bgMenuRef}>
            {(() => {
              const bgPreset = BACKGROUNDS[chartBg]
              const previewBg = bgPreset?.bg ?? (isDark ? '#111827' : '#ffffff')
              return (
                <button
                  onClick={() => setShowBgMenu(!showBgMenu)}
                  title="Fondo del gráfico"
                  className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg hover:bg-slate-50 dark:hover:bg-gray-750"
                >
                  <div className="w-4 h-3 rounded-sm border border-slate-200 dark:border-gray-600" style={{ backgroundColor: previewBg }} />
                  <Layers size={11} className="text-slate-400" />
                  <ChevronDown size={11} className="text-slate-400" />
                </button>
              )
            })()}
            {showBgMenu && (
              <div className="absolute top-full left-0 mt-1 w-52 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-xl shadow-xl z-50 p-3">
                <p className="text-[10px] font-semibold text-slate-400 dark:text-gray-500 mb-2 uppercase tracking-wide">Fondo del gráfico</p>
                <div className="grid grid-cols-4 gap-1.5">
                  {Object.entries(BACKGROUNDS).map(([key, b]) => {
                    const previewBg = b.bg ?? (isDark ? '#111827' : '#ffffff')
                    const isSelected = chartBg === key
                    return (
                      <button
                        key={key}
                        onClick={() => { setChartBg(key); setShowBgMenu(false) }}
                        title={b.label}
                        className={`group relative flex flex-col items-center gap-1 p-1 rounded-lg transition-colors ${isSelected ? 'bg-blue-50 dark:bg-blue-900/30' : 'hover:bg-slate-50 dark:hover:bg-gray-700'}`}
                      >
                        <div
                          className={`w-8 h-6 rounded border-2 transition-all ${isSelected ? 'border-blue-500 shadow-sm shadow-blue-500/40' : 'border-slate-200 dark:border-gray-600'}`}
                          style={key === 'default'
                            ? { background: 'linear-gradient(135deg, #111827 50%, #ffffff 50%)' }
                            : { backgroundColor: previewBg }
                          }
                        />
                        <span className={`text-[8px] leading-tight text-center truncate w-full ${isSelected ? 'text-blue-600 dark:text-blue-400 font-semibold' : 'text-slate-500 dark:text-gray-400'}`}>
                          {b.label}
                        </span>
                      </button>
                    )
                  })}
                </div>
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
                <IndicatorToggle active={showICT}    onChange={setShowICT}    color="#22d3ee" label="ICT / SMC" onSettings={() => setShowICTConfig(v => !v)} />

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
                    }}
                    onSettings={ind.PanelComponent ? () => {
                      setOpenPanels(prev => ({ ...prev, [ind.id]: true }))
                      setShowIndicatorsMenu(false)
                    } : undefined}
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

          {/* Right-side actions */}
          <div className="ml-auto flex items-center gap-1.5">

            {/* Favorites dropdown */}
            <div className="relative" ref={favMenuRef}>
              <button onClick={() => setShowFavMenu(v => !v)} title="Pares favoritos"
                className={`flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                  showFavMenu || favorites.length > 0
                    ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-700 text-amber-600 dark:text-amber-400'
                    : 'bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:bg-slate-50 dark:hover:bg-gray-750'
                }`}>
                <Star size={13} className={favorites.length > 0 ? 'fill-amber-400 text-amber-400' : ''} />
                {favorites.length > 0 && <span>{favorites.length}</span>}
              </button>
              {showFavMenu && (
                <div className="absolute top-full right-0 mt-1 w-52 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-xl shadow-xl z-50 overflow-hidden">
                  {favorites.length === 0
                    ? <p className="px-4 py-3 text-xs text-slate-400 dark:text-gray-600">Sin favoritos. Usa la ★ en el buscador.</p>
                    : favorites.map(sym => (
                      <button key={sym} onClick={() => { handleSelectSymbol(sym); setShowFavMenu(false) }}
                        className={`w-full flex items-center justify-between px-4 py-2 text-sm hover:bg-slate-50 dark:hover:bg-gray-700 ${sym === selectedSymbol ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600' : 'text-slate-700 dark:text-gray-300'}`}>
                        <span className="font-medium">{sym.replace('/USDT:USDT', '').replace('/USDC:USDC', '')}</span>
                        <button onClick={e => { e.stopPropagation(); toggleFavorite(sym) }}
                          className="p-0.5 text-amber-400 hover:text-slate-400 rounded">
                          <Star size={11} className="fill-amber-400" />
                        </button>
                      </button>
                    ))
                  }
                </div>
              )}
            </div>

            {/* Panel toggle buttons */}
            {[
              { key: 'openPos',   label: 'Pos. abiertas',  badge: openForSymbol.length },
              { key: 'closedPos', label: 'Pos. cerradas',  badge: null },
              { key: 'signals',   label: 'Señales',        badge: null },
              { key: 'legend',    label: 'Leyenda',        badge: null },
            ].map(({ key, label, badge }) => (
              <div key={key} className="relative hidden md:block">
                <button
                  onClick={() => {
                    setSidebarVisible(v => ({ ...v, [key]: !v[key] }))
                    if (key === 'closedPos' && !closedLoaded) {
                      setClosedLoaded(true)
                      positionsService.list({ status: 'closed', limit: 500 })
                        .then(res => {
                          const closed = Array.isArray(res?.data) ? res.data : Array.isArray(res) ? res : []
                          setPositions(prev => [...prev.filter(p => p.status === 'open'), ...closed])
                        })
                        .catch(() => {})
                    }
                  }}
                  title={label}
                  className={`px-2.5 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                    sidebarVisible[key]
                      ? 'bg-slate-700 dark:bg-slate-200 border-slate-700 dark:border-slate-200 text-white dark:text-slate-800'
                      : 'bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:bg-slate-50 dark:hover:bg-gray-750'
                  }`}>
                  {label}
                </button>
                {badge > 0 && !sidebarVisible[key] && (
                  <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 flex items-center justify-center text-[9px] font-bold bg-blue-500 text-white rounded-full pointer-events-none">
                    {badge}
                  </span>
                )}
              </div>
            ))}

            <button
              onClick={() => setShowTradePanel(v => !v)}
              title="Abrir panel de trading"
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                showTradePanel
                  ? 'bg-blue-600 border-blue-600 text-white'
                  : 'bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:bg-slate-50 dark:hover:bg-gray-750'
              }`}
            >
              <Crosshair size={13} />
              <span className="hidden sm:inline">Trade</span>
            </button>
            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              title={isFullscreen ? 'Salir de pantalla completa' : 'Pantalla completa'}
              className="p-1.5 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg hover:bg-slate-50 dark:hover:bg-gray-750 text-slate-500 dark:text-gray-400"
            >
              {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
          </div>
        </div>

        {/* ── Main area ──────────────────────────────────────────────────────── */}
        <div className="flex-1 flex gap-2 min-h-0 overflow-hidden">

          {/* Chart */}
          <div className="flex-1 min-w-0 rounded-xl overflow-hidden relative border border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900">
            <div ref={chartContainerRef} className="w-full h-full" style={tradingMode ? { cursor: 'crosshair' } : {}}
              onMouseDown={handleChartMouseDown}
              onMouseMove={handleChartMouseMove}
              onMouseUp={handleChartMouseUp}
              onMouseLeave={handleChartMouseUp}
            />

            {/* ── Drawing tools overlay ─────────────────────────────────────── */}
            {!loading && candleData.length > 0 && (
              <DrawingTools
                chartRef={chartRef}
                candleSeriesRef={candleSeriesRef}
                isDark={isDark}
                symbol={selectedSymbol}
                chartVersion={chartVersion}
              />
            )}

            {/* ── ICT/SMC canvas overlay ────────────────────────────────────── */}
            {showICT && ictData && (
              <ICTCanvas
                chartRef={chartRef}
                seriesRef={candleSeriesRef}
                data={ictData}
                config={ictConfig}
                signal={ictSignal}
                historySignals={ictHistoryData}
                chartVersion={chartVersion}
              />
            )}
            {showICT && showICTConfig && (
              <ICTConfigPanel
                config={ictConfig}
                onChange={setIctConfig}
                onClose={() => setShowICTConfig(false)}
              />
            )}

            {/* ── Squeeze Breakout canvas overlay ──────────────────────────── */}
            {activeIndicators['squeeze_breakout'] && indResults['squeeze_breakout'] && (
              <SBTCanvas
                chartRef={chartRef}
                seriesRef={candleSeriesRef}
                result={indResults['squeeze_breakout']}
                config={getConfig('squeeze_breakout')}
                chartVersion={chartVersion}
              />
            )}

            {loadingCandles && (
              <div className="absolute top-2 right-2 flex items-center gap-2 bg-white/90 dark:bg-gray-900/90 backdrop-blur-sm px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-gray-700 shadow-sm">
                <div className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <span className="text-xs text-slate-500 dark:text-gray-400">Cargando…</span>
              </div>
            )}
            {tradingMode && (
              <div className="absolute top-2 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-amber-50/95 dark:bg-amber-900/80 backdrop-blur-sm px-3 py-1.5 rounded-full border border-amber-300 dark:border-amber-600 shadow-sm pointer-events-none">
                <Crosshair size={12} className="text-amber-600 dark:text-amber-400" />
                <span className="text-xs font-medium text-amber-700 dark:text-amber-300">Haz clic en el precio de entrada</span>
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

            {/* ── HTML signal labels (A+/A/A-) ──────────────────────────────── */}
            {overlayLabels.map((label, i) => (
              <div
                key={i}
                className="absolute pointer-events-none select-none z-10"
                style={{
                  left: label.x,
                  top:  label.isBull ? label.y + 6 : label.y - 6,
                  transform: label.isBull ? 'translateX(-50%)' : 'translate(-50%, -100%)',
                }}
              >
                {label.isBull ? (
                  <div className="flex flex-col items-center" style={{ gap: 0 }}>
                    <div style={{ width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderBottom: `5px solid ${label.color}` }} />
                    <div style={{ backgroundColor: label.color }} className="text-white text-[9px] font-bold px-[5px] py-px rounded-[2px] leading-[14px] tracking-wide whitespace-nowrap shadow-sm">
                      {label.text}
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center" style={{ gap: 0 }}>
                    <div style={{ backgroundColor: label.color }} className="text-white text-[9px] font-bold px-[5px] py-px rounded-[2px] leading-[14px] tracking-wide whitespace-nowrap shadow-sm">
                      {label.text}
                    </div>
                    <div style={{ width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: `5px solid ${label.color}` }} />
                  </div>
                )}
              </div>
            ))}

            {/* Indicator Badges + Settings Panels */}
            {(() => {
              const active = indicators.filter(ind => activeIndicators[ind.id])
              return active.map((ind, idx) => {
                const Badge = ind.BadgeComponent
                const Panel = ind.PanelComponent
                return (
                  <div
                    key={ind.id}
                    className="absolute top-0 left-0 z-10"
                    style={{ transform: `translateY(${8 + idx * 44}px)` }}
                  >
                    {Badge && (
                      <Badge
                        result={indResults[ind.id]}
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
              })
            })()}
          </div>

          {/* ── Sidebar ──────────────────────────────────────────────────────── */}
          {(showTradePanel || Object.values(sidebarVisible).some(Boolean)) && (
          <div className="w-72 flex-shrink-0 flex flex-col gap-2 overflow-y-auto">

            {/* Trade panel */}
            {showTradePanel && (
              <div className="card py-3 px-3 space-y-2.5 flex-shrink-0 border-blue-200 dark:border-blue-800/50">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold flex items-center gap-1.5 text-slate-700 dark:text-gray-300">
                    <Crosshair size={12} className="text-blue-500" />
                    Orden rápida · {selectedSymbol.replace('/USDT:USDT', '').replace('/USDC:USDC', '')}
                  </h3>
                  <button onClick={() => { setShowTradePanel(false); setTradingMode(false); setTradeEntryPrice(null); setTradeFeedback(null) }}
                    className="p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-gray-300">
                    <X size={12} />
                  </button>
                </div>

                {/* Account */}
                {tradeAccounts.length > 0 ? (
                  <select
                    value={tradeAccountId}
                    onChange={e => {
                      const acc = tradeAccounts.find(a => a.id === e.target.value)
                      setTradeAccountId(e.target.value)
                      setTradeAccountType(acc?.type || 'real')
                    }}
                    className="w-full text-xs bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded-lg px-2 py-1.5 text-slate-700 dark:text-gray-300"
                  >
                    {tradeAccounts.map(a => (
                      <option key={a.id} value={a.id}>{a.label} ({a.exchange})</option>
                    ))}
                  </select>
                ) : (
                  <p className="text-[11px] text-slate-400 dark:text-gray-600">Cargando cuentas…</p>
                )}

                {/* Order type: Market / Limit */}
                <div className="space-y-1.5">
                  <span className="text-[10px] font-medium text-slate-400 dark:text-gray-500 uppercase tracking-wide">Tipo de orden</span>
                  <div className="grid grid-cols-2 gap-1">
                    <button
                      onClick={() => { setTradeEntryPrice(null); setTradingMode(false) }}
                      className={`text-[11px] font-semibold py-1.5 rounded-lg border transition-colors ${
                        !tradeEntryPrice && !tradingMode
                          ? 'bg-blue-500 border-blue-500 text-white'
                          : 'bg-slate-50 dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-500 dark:text-gray-400 hover:border-blue-300 dark:hover:border-blue-600'
                      }`}
                    >
                      Market
                    </button>
                    <button
                      onClick={() => { setTradingMode(true); setTradeEntryPrice(null) }}
                      className={`text-[11px] font-semibold py-1.5 rounded-lg border transition-colors flex items-center justify-center gap-1 ${
                        tradingMode
                          ? 'bg-amber-100 dark:bg-amber-900/30 border-amber-400 dark:border-amber-600 text-amber-700 dark:text-amber-400'
                          : tradeEntryPrice
                            ? 'bg-amber-500 border-amber-500 text-white'
                            : 'bg-slate-50 dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-500 dark:text-gray-400 hover:border-amber-300 dark:hover:border-amber-600'
                      }`}
                    >
                      <Crosshair size={10} />
                      Limit
                    </button>
                  </div>
                  {tradingMode && (
                    <p className="text-[10px] text-center text-amber-600 dark:text-amber-400">Haz clic en el gráfico para fijar precio</p>
                  )}
                  {tradeEntryPrice && (
                    <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
                      <Crosshair size={10} className="text-amber-500 flex-shrink-0" />
                      <span className="text-[11px] font-mono text-amber-700 dark:text-amber-400 flex-1 font-semibold">${formatPrice(tradeEntryPrice)}</span>
                      <button onClick={() => { setTradeEntryPrice(null); setTradingMode(true) }} title="Cambiar precio"
                        className="p-0.5 text-amber-400 hover:text-amber-600 dark:hover:text-amber-300 rounded">
                        <Crosshair size={9} />
                      </button>
                      <button onClick={() => { setTradeEntryPrice(null); setTradingMode(false) }} title="Volver a market"
                        className="p-0.5 text-slate-400 hover:text-red-500 dark:hover:text-red-400 rounded">
                        <X size={9} />
                      </button>
                    </div>
                  )}
                </div>

                {/* Leverage + Size */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <span className="text-[10px] font-medium text-slate-400 dark:text-gray-500 uppercase tracking-wide">Leverage</span>
                    <div className="flex items-center gap-1">
                      <input type="number" value={tradeLeverage} onChange={e => setTradeLeverage(Math.max(1, Math.min(125, Number(e.target.value))))}
                        min={1} max={125}
                        className="flex-1 text-xs text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded-lg px-1.5 py-1.5 text-slate-700 dark:text-gray-300 w-0" />
                      <span className="text-[11px] text-slate-400">x</span>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <span className="text-[10px] font-medium text-slate-400 dark:text-gray-500 uppercase tracking-wide">Tamaño</span>
                    <div className="flex items-center gap-1">
                      <input type="number" value={tradeSizingValue} onChange={e => setTradeSizingValue(Number(e.target.value))}
                        min={0.1} step={tradeSizingType === 'percentage' ? 1 : 10}
                        className="flex-1 text-xs text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded-lg px-1.5 py-1.5 text-slate-700 dark:text-gray-300 w-0" />
                      <button onClick={() => setTradeSizingType(t => t === 'percentage' ? 'fixed' : 'percentage')}
                        className="text-[11px] px-1.5 py-1 bg-slate-100 dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-md text-slate-600 dark:text-gray-400 hover:bg-slate-200 dark:hover:bg-gray-700">
                        {tradeSizingType === 'percentage' ? '%' : 'U'}
                      </button>
                    </div>
                  </div>
                </div>

                {/* SL */}
                <div className="space-y-1">
                  <span className="text-[10px] font-medium text-slate-400 dark:text-gray-500 uppercase tracking-wide">Stop Loss</span>
                  <div className="flex items-center gap-1.5">
                    <input type="number" value={tradeSlPct} onChange={e => setTradeSlPct(Number(e.target.value))}
                      min={0.1} step={0.1}
                      className="flex-1 text-xs text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded-lg px-2 py-1.5 text-slate-700 dark:text-gray-300" />
                    <span className="text-[11px] text-slate-400 dark:text-gray-500">% desde entrada</span>
                  </div>
                </div>

                {/* Estrategia (collapsible) */}
                <div className="border border-slate-200 dark:border-gray-700 rounded-lg overflow-hidden">
                  <button onClick={() => setTradeAdvOpen(v => !v)}
                    className="w-full flex items-center justify-between px-2.5 py-1.5 bg-slate-50 dark:bg-gray-800/60 hover:bg-slate-100 dark:hover:bg-gray-700/60">
                    <span className="text-[10px] font-semibold text-slate-500 dark:text-gray-400 uppercase tracking-wide flex items-center gap-1">
                      {tradeAdvOpen ? <Minus size={10} /> : <Plus size={10} />}
                      Estrategia
                    </span>
                    {(tradeTPs.length > 0 || tradeTrailing.enabled || tradeBreakeven.enabled || tradeDynamicSL.enabled) && (
                      <span className="text-[9px] font-bold bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 px-1.5 py-0.5 rounded-full">
                        {[tradeTPs.length > 0 && `${tradeTPs.length}TP`, tradeTrailing.enabled && 'Trail', tradeBreakeven.enabled && 'BE', tradeDynamicSL.enabled && 'DSL'].filter(Boolean).join(' · ')}
                      </span>
                    )}
                  </button>

                  {tradeAdvOpen && (
                    <div className="px-2.5 py-2 space-y-3">
                      {/* Take Profits */}
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-semibold text-slate-500 dark:text-gray-400 uppercase tracking-wide">Take Profits</span>
                          <button onClick={() => setTradeTPs(tps => [...tps, { profit_percent: 2, close_percent: 50 }])}
                            className="text-[10px] text-indigo-500 hover:text-indigo-400 font-semibold">+ Añadir</button>
                        </div>
                        {tradeTPs.length === 0
                          ? <p className="text-[10px] text-slate-400 dark:text-gray-600 italic">Sin TPs</p>
                          : tradeTPs.map((tp, i) => (
                            <div key={i} className="flex items-center gap-1">
                              <div className="flex-1 flex items-center gap-1">
                                <input type="number" value={tp.profit_percent} min={0.1} step={0.1}
                                  onChange={e => setTradeTPs(tps => tps.map((t, j) => j === i ? { ...t, profit_percent: Number(e.target.value) } : t))}
                                  className="w-0 flex-1 text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                                <span className="text-[10px] text-slate-400 flex-shrink-0">%</span>
                              </div>
                              <div className="flex-1 flex items-center gap-1">
                                <input type="number" value={tp.close_percent} min={1} max={100} step={5}
                                  onChange={e => setTradeTPs(tps => tps.map((t, j) => j === i ? { ...t, close_percent: Number(e.target.value) } : t))}
                                  className="w-0 flex-1 text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                                <span className="text-[10px] text-slate-400 flex-shrink-0">cierre</span>
                              </div>
                              <button onClick={() => setTradeTPs(tps => tps.filter((_, j) => j !== i))}
                                className="p-0.5 text-slate-400 hover:text-red-500 flex-shrink-0"><X size={10} /></button>
                            </div>
                          ))
                        }
                        {tradeTPs.length > 0 && <p className="text-[9px] text-slate-400 dark:text-gray-600">Ganancia % · % posición a cerrar</p>}
                      </div>
                      {/* Trailing Stop */}
                      <div className="space-y-1.5">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" checked={tradeTrailing.enabled} onChange={e => setTradeTrailing(t => ({ ...t, enabled: e.target.checked }))} className="accent-indigo-500" />
                          <span className="text-[10px] font-semibold text-slate-600 dark:text-gray-300 uppercase tracking-wide">Trailing Stop</span>
                        </label>
                        {tradeTrailing.enabled && (
                          <div className="grid grid-cols-2 gap-1.5 pl-4">
                            <div className="space-y-0.5">
                              <span className="text-[9px] text-slate-400">Activación %</span>
                              <input type="number" value={tradeTrailing.activation_profit} min={0.1} step={0.1}
                                onChange={e => setTradeTrailing(t => ({ ...t, activation_profit: Number(e.target.value) }))}
                                className="w-full text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                            </div>
                            <div className="space-y-0.5">
                              <span className="text-[9px] text-slate-400">Callback %</span>
                              <input type="number" value={tradeTrailing.callback_rate} min={0.1} step={0.1}
                                onChange={e => setTradeTrailing(t => ({ ...t, callback_rate: Number(e.target.value) }))}
                                className="w-full text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                            </div>
                          </div>
                        )}
                      </div>
                      {/* Breakeven */}
                      <div className="space-y-1.5">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" checked={tradeBreakeven.enabled} onChange={e => setTradeBreakeven(t => ({ ...t, enabled: e.target.checked }))} className="accent-indigo-500" />
                          <span className="text-[10px] font-semibold text-slate-600 dark:text-gray-300 uppercase tracking-wide">Breakeven</span>
                        </label>
                        {tradeBreakeven.enabled && (
                          <div className="grid grid-cols-2 gap-1.5 pl-4">
                            <div className="space-y-0.5">
                              <span className="text-[9px] text-slate-400">Activación %</span>
                              <input type="number" value={tradeBreakeven.activation_profit} min={0.1} step={0.1}
                                onChange={e => setTradeBreakeven(t => ({ ...t, activation_profit: Number(e.target.value) }))}
                                className="w-full text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                            </div>
                            <div className="space-y-0.5">
                              <span className="text-[9px] text-slate-400">Lock %</span>
                              <input type="number" value={tradeBreakeven.lock_profit} min={0} step={0.1}
                                onChange={e => setTradeBreakeven(t => ({ ...t, lock_profit: Number(e.target.value) }))}
                                className="w-full text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                            </div>
                          </div>
                        )}
                      </div>
                      {/* Dynamic SL */}
                      <div className="space-y-1.5">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" checked={tradeDynamicSL.enabled} onChange={e => setTradeDynamicSL(t => ({ ...t, enabled: e.target.checked }))} className="accent-indigo-500" />
                          <span className="text-[10px] font-semibold text-slate-600 dark:text-gray-300 uppercase tracking-wide">SL Dinámico</span>
                        </label>
                        {tradeDynamicSL.enabled && (
                          <div className="grid grid-cols-2 gap-1.5 pl-4">
                            <div className="space-y-0.5">
                              <span className="text-[9px] text-slate-400">Paso %</span>
                              <input type="number" value={tradeDynamicSL.step_percent} min={0.1} step={0.1}
                                onChange={e => setTradeDynamicSL(t => ({ ...t, step_percent: Number(e.target.value) }))}
                                className="w-full text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                            </div>
                            <div className="space-y-0.5">
                              <span className="text-[9px] text-slate-400">Máx pasos</span>
                              <input type="number" value={tradeDynamicSL.max_steps} min={1} step={1}
                                onChange={e => setTradeDynamicSL(t => ({ ...t, max_steps: Number(e.target.value) }))}
                                className="w-full text-[11px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-1 text-slate-700 dark:text-gray-300" />
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Feedback */}
                {tradeFeedback && (
                  <div className={`text-[11px] px-2.5 py-1.5 rounded-lg flex items-center gap-1.5 ${
                    tradeFeedback.type === 'ok'
                      ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'
                      : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
                  }`}>
                    {tradeFeedback.msg}
                  </div>
                )}

                {/* LONG / SHORT */}
                <div className="grid grid-cols-2 gap-1.5">
                  <button onClick={() => executeTrade('long')}
                    disabled={!tradeAccountId || tradeLoading}
                    className="py-2 px-3 text-xs font-bold bg-green-500 hover:bg-green-600 disabled:opacity-50 text-white rounded-lg flex items-center justify-center gap-1.5 transition-colors">
                    {tradeLoading ? <Loader2 size={11} className="animate-spin" /> : <TrendingUp size={11} />}
                    LONG
                  </button>
                  <button onClick={() => executeTrade('short')}
                    disabled={!tradeAccountId || tradeLoading}
                    className="py-2 px-3 text-xs font-bold bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white rounded-lg flex items-center justify-center gap-1.5 transition-colors">
                    {tradeLoading ? <Loader2 size={11} className="animate-spin" /> : <TrendingDown size={11} />}
                    SHORT
                  </button>
                </div>
              </div>
            )}

            {/* Strategy config — duplicate removed, now lives inside trade panel */}
            {/* Open positions */}
            {sidebarVisible.openPos && (
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
                          <div className="flex justify-between"><span>TP:</span><span className="font-mono text-green-400">{pos.current_tp_prices.map(tp => formatPrice(tp?.price ?? tp)).join(', ')}</span></div>
                        )}
                      </div>
                      {/* Strategy edit panel — only when position is selected */}
                      {selectedPosition?.id === pos.id && (
                        <div className="mt-2 border-t border-slate-200 dark:border-gray-700 pt-2" onClick={e => e.stopPropagation()}>
                          <button onClick={() => setShowStrategyPanel(v => !v)}
                            className="flex items-center justify-between w-full text-[10px] font-semibold text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-200">
                            <span>Modificar estrategia</span>
                            <span>{showStrategyPanel ? '▲' : '▼'}</span>
                          </button>
                          {showStrategyPanel && (
                            <div className="mt-2 space-y-2">
                              {/* TPs */}
                              <div className="space-y-1">
                                <div className="flex items-center justify-between">
                                  <span className="text-[9px] font-bold uppercase tracking-wide text-slate-400 dark:text-gray-500">Take Profits</span>
                                  <button onClick={() => setStrategyEdit(s => ({ ...s, tps: [...s.tps, { profit_percent: 2, close_percent: 50 }] }))}
                                    className="text-[9px] text-blue-500 hover:text-blue-700 font-semibold">+ TP</button>
                                </div>
                                {strategyEdit.tps.length === 0
                                  ? <p className="text-[9px] text-slate-400 italic">Sin TPs</p>
                                  : strategyEdit.tps.map((tp, i) => (
                                    <div key={i} className="flex items-center gap-1">
                                      <input type="number" value={tp.profit_percent} min={0.1} step={0.1}
                                        onChange={e => setStrategyEdit(s => ({ ...s, tps: s.tps.map((t, j) => j === i ? { ...t, profit_percent: Number(e.target.value) } : t) }))}
                                        className="w-14 text-[10px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-0.5 text-slate-700 dark:text-gray-300" />
                                      <span className="text-[9px] text-slate-400">%</span>
                                      <input type="number" value={tp.close_percent} min={1} max={100} step={5}
                                        onChange={e => setStrategyEdit(s => ({ ...s, tps: s.tps.map((t, j) => j === i ? { ...t, close_percent: Number(e.target.value) } : t) }))}
                                        className="w-14 text-[10px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-0.5 text-slate-700 dark:text-gray-300" />
                                      <span className="text-[9px] text-slate-400">cierre%</span>
                                      <button onClick={() => setStrategyEdit(s => ({ ...s, tps: s.tps.filter((_, j) => j !== i) }))}
                                        className="text-red-400 hover:text-red-600 text-[10px] ml-auto">×</button>
                                    </div>
                                  ))
                                }
                              </div>
                              {/* Trailing */}
                              <div className="space-y-1">
                                <label className="flex items-center gap-1.5 cursor-pointer">
                                  <input type="checkbox" checked={strategyEdit.trailing.enabled}
                                    onChange={e => setStrategyEdit(s => ({ ...s, trailing: { ...s.trailing, enabled: e.target.checked } }))}
                                    className="accent-blue-500 w-3 h-3" />
                                  <span className="text-[9px] font-bold uppercase tracking-wide text-slate-400 dark:text-gray-500">Trailing Stop</span>
                                </label>
                                {strategyEdit.trailing.enabled && (
                                  <div className="flex gap-1 pl-4">
                                    <div className="flex-1 space-y-0.5">
                                      <span className="text-[8px] text-slate-400">Activar en %</span>
                                      <input type="number" value={strategyEdit.trailing.activation_profit} min={0.1} step={0.1}
                                        onChange={e => setStrategyEdit(s => ({ ...s, trailing: { ...s.trailing, activation_profit: Number(e.target.value) } }))}
                                        className="w-full text-[10px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-0.5 text-slate-700 dark:text-gray-300" />
                                    </div>
                                    <div className="flex-1 space-y-0.5">
                                      <span className="text-[8px] text-slate-400">Retroceso %</span>
                                      <input type="number" value={strategyEdit.trailing.callback_rate} min={0.1} step={0.1}
                                        onChange={e => setStrategyEdit(s => ({ ...s, trailing: { ...s.trailing, callback_rate: Number(e.target.value) } }))}
                                        className="w-full text-[10px] text-center bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700 rounded px-1 py-0.5 text-slate-700 dark:text-gray-300" />
                                    </div>
                                  </div>
                                )}
                              </div>
                              <button onClick={() => applyStrategyChanges(pos)} disabled={strategyLoading}
                                className="w-full py-1 text-[10px] font-semibold rounded-md bg-blue-500 hover:bg-blue-600 disabled:opacity-50 text-white transition-colors">
                                {strategyLoading ? 'Aplicando…' : 'Aplicar cambios'}
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                      <button
                        onClick={e => { e.stopPropagation(); closePosition(pos) }}
                        className="mt-2 w-full py-1 text-[11px] font-semibold rounded-md bg-slate-200 dark:bg-gray-700 hover:bg-red-100 dark:hover:bg-red-900/30 hover:text-red-600 dark:hover:text-red-400 text-slate-600 dark:text-gray-400 transition-colors">
                        Cerrar posición
                      </button>
                    </div>
                  ))
              }
            </div>
            )}

            {/* Closed positions */}
            {sidebarVisible.closedPos && (
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
            )}

            {/* Recent signals */}
            {sidebarVisible.signals && (
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
            )}

            {/* Legend */}
            {sidebarVisible.legend && (
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
            )}

          </div>)}{/* /sidebar */}
        </div>{/* /main */}
      </div>{/* /inner */}
    </div>
  )
}
