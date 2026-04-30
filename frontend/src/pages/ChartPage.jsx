import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { createChart } from 'lightweight-charts'
import { positionsService } from '@/services/positions'
import { botsService } from '@/services/bots'
import { tradingSignalsService } from '@/services/tradingSignals'
import { chartingService } from '@/services/charting'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import usePositionStore from '@/store/positionStore'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import { TrendingUp, TrendingDown, Target, AlertTriangle, Activity, Clock, BarChart3, ChevronDown } from 'lucide-react'

function formatPrice(price) {
  if (price === null || price === undefined) return '—'
  const num = Number(price)
  if (num >= 1000) {
    return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  return num.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 })
}

function formatTime(dateString) {
  if (!dateString) return '—'
  const date = new Date(dateString)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleString('es-ES', { 
    month: 'short', 
    day: 'numeric', 
    hour: '2-digit', 
    minute: '2-digit' 
  })
}

function calculatePositionRoi(pos, currentPrice) {
  const entry = parseFloat(pos.entry_price)
  const qty = parseFloat(pos.quantity)
  const lev = parseFloat(pos.leverage || 1)
  let unrealizedPnl = parseFloat(pos.unrealized_pnl || 0)
  if (currentPrice && entry > 0 && qty > 0) {
    unrealizedPnl = pos.side === 'long'
      ? (currentPrice - entry) * qty
      : (entry - currentPrice) * qty
  }
  const margin = entry > 0 && qty > 0 ? (entry * qty) / lev : 0
  return margin > 0 ? (unrealizedPnl / margin) * 100 : 0
}

// ─── Indicadores técnicos ─────────────────────────────────────

function sma(data, period) {
  const result = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue }
    const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b.close, 0)
    result.push({ time: data[i].time, value: sum / period })
  }
  return result
}

function ema(data, period) {
  const k = 2 / (period + 1)
  const result = []
  let prevEma = null
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue }
    if (i === period - 1) {
      const sum = data.slice(0, period).reduce((a, b) => a + b.close, 0)
      prevEma = sum / period
    } else {
      prevEma = data[i].close * k + prevEma * (1 - k)
    }
    result.push({ time: data[i].time, value: prevEma })
  }
  return result
}

function rsi(data, period = 14) {
  const result = []
  let avgGain = 0, avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const change = data[i].close - data[i - 1].close
    if (change > 0) avgGain += change
    else avgLoss -= change
  }
  avgGain /= period
  avgLoss /= period
  for (let i = 0; i < data.length; i++) {
    if (i < period) { result.push(null); continue }
    const change = data[i].close - data[i - 1].close
    const gain = change > 0 ? change : 0
    const loss = change < 0 ? -change : 0
    avgGain = (avgGain * (period - 1) + gain) / period
    avgLoss = (avgLoss * (period - 1) + loss) / period
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
    result.push({ time: data[i].time, value: 100 - (100 / (1 + rs)) })
  }
  return result
}

function calculateIndicators(candles) {
  if (!candles || candles.length < 200) return null
  return {
    ema20: ema(candles, 20),
    ema50: ema(candles, 50),
    sma200: sma(candles, 200),
    rsi14: rsi(candles, 14),
    volume: candles.map(c => ({ time: c.time, value: c.volume || 0 })),
  }
}

// Componente para mostrar valores de indicadores
function IndicatorBadge({ name, value, color = 'blue' }) {
  const colors = {
    blue: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    green: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    red: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    purple: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
    orange: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  }
  
  if (value === null || value === undefined) return null
  
  return (
    <div className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium ${colors[color]}`}>
      <span className="opacity-70">{name}:</span>
      <span>{typeof value === 'number' ? value.toFixed(2) : value}</span>
    </div>
  )
}

// Helper to normalize symbol for comparison
const normalizeSymbol = (s) => s?.replace(':USDT', '').replace(':USDC', '').replace('/USDT', '').replace('/USDC', '').toUpperCase()

// Convert various exchange symbol formats to CCXT format (e.g. DOGEUSDT.P → DOGE/USDT:USDT)
function toCcxtSymbol(raw) {
  if (!raw) return raw
  // Already CCXT format
  if (raw.includes('/')) return raw
  // Remove .P perpetual suffix
  let s = raw.replace(/\.P$/i, '')
  // Handle common patterns: BTCUSDT, BTC-USDT, BTC_USDT
  s = s.replace(/_/g, '-')
  if (s.includes('-')) {
    const [base, quote] = s.split('-')
    return `${base}/${quote}:${quote}`
  }
  // Try to split at USDT, USDC, BTC, ETH endings
  const quoteMatch = s.match(/^(.*?)(USDT|USDC|BTC|ETH|USD)$/i)
  if (quoteMatch) {
    const [, base, quote] = quoteMatch
    return `${base}/${quote}:${quote}`
  }
  return raw
}

export default function ChartPage() {
  const chartContainerRef = useRef(null)
  const chartRef = useRef(null)
  const [loading, setLoading] = useState(true)
  const [availableSymbols, setAvailableSymbols] = useState([])
  const [selectedSymbol, setSelectedSymbol] = useState('BTC/USDT:USDT')
  const [timeframe, setTimeframe] = useState('1h')
  const [positions, setPositions] = useState([])
  const [signals, setSignals] = useState([])
  const [bots, setBots] = useState([])
  // showPositionsOverlay eliminado — ahora solo se muestra al seleccionar una posición
  const [showEma20, setShowEma20] = useState(true)
  const [showEma50, setShowEma50] = useState(true)
  const [showSma200, setShowSma200] = useState(true)
  const [showRsi, setShowRsi] = useState(false)
  const [showVolume, setShowVolume] = useState(true)
  const [candleData, setCandleData] = useState([])
  const [symbolSearch, setSymbolSearch] = useState('')
  const [showSymbolDropdown, setShowSymbolDropdown] = useState(false)
  const [selectedPosition, setSelectedPosition] = useState(null)
  const [chartError, setChartError] = useState(null)
  const prices = usePositionStore(s => s.prices)
  const selectedSymbolNorm = useMemo(() => normalizeSymbol(selectedSymbol), [selectedSymbol])
  const positionPriceLinesRef = useRef([])
  const positionLineSeriesRef = useRef(null)

  // Cargar símbolos disponibles - Same as BotEditPage
  const loadSymbols = useCallback(async (search = '') => {
    try {
      // Use same endpoint as BotEditPage (marketsByExchange)
      const res = await exchangeAccountsService.marketsByExchange('bingx')
      // Response is list of strings: ["BTC/USDT:USDT", "ETH/USDT:USDT", ...]
      const symbols = Array.isArray(res.data) ? res.data : []
      // Format for dropdown
      let formatted = symbols.map(s => ({
        symbol: s,
        description: s.replace('/USDT:USDT', '').replace('/USDC:USDC', '')
      }))
      // Filter by search if provided
      if (search) {
        const q = search.toUpperCase()
        formatted = formatted.filter(s => s.symbol.toUpperCase().includes(q))
      }
      setAvailableSymbols(formatted)
    } catch (e) {
      console.error('Error loading symbols:', e)
      setAvailableSymbols([
        { symbol: 'BTC/USDT:USDT', description: 'BTC' },
        { symbol: 'ETH/USDT:USDT', description: 'ETH' },
      ])
    }
  }, [])

  // Cargar datos iniciales
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      try {
        const [posRes, botsRes, closedPosRes] = await Promise.all([
          positionsService.unified(true),
          botsService.list(),
          positionsService.list({ status: 'closed', limit: 500 }),
        ])
        // Asegurar que los datos son arrays
        const openPositions = Array.isArray(posRes?.data) ? posRes.data : 
                             Array.isArray(posRes) ? posRes : []
        const closedPositions = Array.isArray(closedPosRes?.data) ? closedPosRes.data : 
                               Array.isArray(closedPosRes) ? closedPosRes : []
        const botsData = Array.isArray(botsRes?.data) ? botsRes.data : 
                        Array.isArray(botsRes) ? botsRes : []
        // Combinar abiertas (unified) y cerradas (list)
        setPositions([...openPositions, ...closedPositions])
        setBots(botsData)
        // Load symbols using the same method as dropdown
        await loadSymbols('')
        
        // Cargar señales de los últimos 7 días
        if (selectedSymbol) {
          try {
            const signalsRes = await tradingSignalsService.list({ 
              symbol: selectedSymbol, 
              days: 7,
              limit: 100 
            })
            setSignals(signalsRes.data?.signals || [])
          } catch (e) {
            console.log('Trading signals not available')
            setSignals([])
          }
        }
      } catch (e) {
        console.error('Error loading chart data:', e)
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [])

  // Cargar datos de velas
  const loadCandleData = useCallback(async () => {
    if (!selectedSymbol) return
    setChartError(null)
    
    try {
      const to = Math.floor(Date.now() / 1000)
      // 1 año completo de histórico (365 días) para cualquier temporalidad
      const from = to - 31536000
      
      const ccxtSymbol = toCcxtSymbol(selectedSymbol)
      
      const res = await chartingService.getHistory({
        symbol: ccxtSymbol,
        resolution: timeframe,
        from_time: from,
        to_time: to,
      })
      
      if (res.data?.s === 'ok' && res.data.t && res.data.t.length > 0) {
        const candles = res.data.t.map((time, i) => ({
          time,
          open: res.data.o[i],
          high: res.data.h[i],
          low: res.data.l[i],
          close: res.data.c[i],
        }))
        setCandleData(candles)
      } else {
        const errmsg = res.data?.errmsg || 'No data returned from exchange'
        setChartError(errmsg)
        setCandleData([])
      }
    } catch (e) {
      console.error('Error loading candles:', e)
      setChartError(e.response?.data?.detail || e.message || 'Failed to load chart data')
      setCandleData([])
    }
  }, [selectedSymbol, timeframe])

  // Cargar velas cuando cambia símbolo o timeframe
  useEffect(() => {
    loadCandleData()
  }, [loadCandleData])

  // Crear y actualizar gráfico
  useEffect(() => {
    if (!chartContainerRef.current || loading || candleData.length === 0) {
      // Limpiar chart previo si existe y no hay datos
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
      return
    }

    const isDark = document.documentElement.classList.contains('dark')
    const bg = isDark ? '#111827' : '#ffffff'
    const text = isDark ? '#94a3b8' : '#64748b'
    const grid = isDark ? '#1f2937' : '#e2e8f0'

    const chart = createChart(chartContainerRef.current, {
      layout: { 
        background: { color: bg }, 
        textColor: text,
        fontSize: 12,
      },
      grid: { 
        vertLines: { color: grid, style: 2 }, 
        horzLines: { color: grid, style: 2 } 
      },
      crosshair: { 
        mode: 1,
        vertLine: {
          color: isDark ? '#475569' : '#94a3b8',
          labelBackgroundColor: isDark ? '#475569' : '#94a3b8',
        },
        horzLine: {
          color: isDark ? '#475569' : '#94a3b8',
          labelBackgroundColor: isDark ? '#475569' : '#94a3b8',
        },
      },
      timeScale: { 
        borderColor: grid, 
        timeVisible: true,
        secondsVisible: false,
        barSpacing: 8,
        minBarSpacing: 4,
      },
      rightPriceScale: { 
        borderColor: grid,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      handleScroll: { vertTouchDrag: false },
    })
    
    chartRef.current = chart

    // ── Limpiar overlays de posición seleccionada previa ──
    positionPriceLinesRef.current.forEach(pl => {
      try { candleSeries.removePriceLine(pl) } catch (e) {}
    })
    positionPriceLinesRef.current = []
    if (positionLineSeriesRef.current) {
      try { chart.removeSeries(positionLineSeriesRef.current) } catch (e) {}
      positionLineSeriesRef.current = null
    }
    if (positionLineSeriesRef._aux) {
      positionLineSeriesRef._aux.forEach(s => {
        try { chart.removeSeries(s) } catch (e) {}
      })
      positionLineSeriesRef._aux = []
    }

    // Serie de velas
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    candleSeries.setData(candleData)
    
    // ─── Indicadores técnicos ───────────────────────────────────
    const indicators = calculateIndicators(candleData)
    
    if (indicators) {
      // Ajustar márgenes del panel principal para paneles inferiores
      const bottomMargin = (showVolume ? 0.2 : 0) + (showRsi ? 0.15 : 0)
      candleSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.05, bottom: bottomMargin > 0 ? bottomMargin : 0.05 },
      })
      
      // EMA 20
      if (showEma20) {
        const ema20Series = chart.addLineSeries({ color: '#f59e0b', lineWidth: 1, title: 'EMA 20', lastValueVisible: false })
        ema20Series.setData(indicators.ema20.filter(p => p))
      }
      // EMA 50
      if (showEma50) {
        const ema50Series = chart.addLineSeries({ color: '#3b82f6', lineWidth: 1, title: 'EMA 50', lastValueVisible: false })
        ema50Series.setData(indicators.ema50.filter(p => p))
      }
      // SMA 200
      if (showSma200) {
        const sma200Series = chart.addLineSeries({ color: '#ef4444', lineWidth: 1, title: 'SMA 200', lastValueVisible: false })
        sma200Series.setData(indicators.sma200.filter(p => p))
      }
      // Volumen (panel inferior)
      if (showVolume) {
        const volSeries = chart.addHistogramSeries({
          color: '#64748b',
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume',
        })
        volSeries.setData(indicators.volume)
        chart.priceScale('volume').applyOptions({
          scaleMargins: { top: 0.9, bottom: 0 },
        })
      }
      // RSI 14 (panel inferior)
      if (showRsi) {
        const rsiSeries = chart.addLineSeries({
          color: '#a855f7',
          lineWidth: 1.5,
          title: 'RSI 14',
          priceScaleId: 'rsi',
          lastValueVisible: false,
        })
        rsiSeries.setData(indicators.rsi14.filter(p => p))
        chart.priceScale('rsi').applyOptions({
          scaleMargins: { top: 0.9, bottom: 0 },
          entireTextOnly: true,
        })
      }
    }
    
    // Marcadores: solo posición seleccionada (nada global)
    const allMarkers = []

    // ═══════════════════════════════════════════════════════════
    // POSICIÓN SELECCIONADA — Overlay estilo TradingView
    // ═══════════════════════════════════════════════════════════
    if (selectedPosition && normalizeSymbol(toCcxtSymbol(selectedPosition.symbol)) === selectedSymbolNorm) {
      const pos = selectedPosition
      const entryTime = Math.floor(new Date(pos.opened_at).getTime() / 1000)
      const closeTime = pos.closed_at ? Math.floor(new Date(pos.closed_at).getTime() / 1000) : null
      const entryPrice = parseFloat(pos.entry_price)
      const side = pos.side
      const isLong = side === 'long'
      const posColor = isLong ? '#22c55e' : '#ef4444'

      // ── 1. Buscar la señal más cercana a esta posición ──
      const posOpenedMs = new Date(pos.opened_at).getTime()
      let relatedSignal = null

      // Prioridad 1: match directo por position_id
      relatedSignal = signals.find(s => s.position_id === pos.id)

      // Prioridad 2: la señal más cercana en tiempo (±2 min) mismo símbolo + lado
      if (!relatedSignal) {
        const candidates = signals
          .filter(s => normalizeSymbol(toCcxtSymbol(s.symbol)) === selectedSymbolNorm && s.action === side)
          .map(s => ({
            ...s,
            _delta: Math.abs(new Date(s.received_at).getTime() - posOpenedMs),
          }))
          .filter(s => s._delta < 2 * 60 * 1000)
          .sort((a, b) => a._delta - b._delta)
        if (candidates.length > 0) {
          relatedSignal = candidates[0]
        }
      }

      // ── 2. Marker de señal (la que disparó la posición) ──
      if (relatedSignal) {
        const s = relatedSignal
        const signalTime = Math.floor(new Date(s.received_at).getTime() / 1000)
        const signalPrice = s.price ? parseFloat(s.price) : null
        const candle = candleData.find(c => c.time === signalTime)
        const snapTime = candle ? candle.time : signalTime

        // Marker de la señal en la vela correspondiente
        allMarkers.push({
          time: snapTime,
          position: s.action === 'long' ? 'belowBar' : 'aboveBar',
          color: s.action === 'long' ? '#22c55e' : '#ef4444',
          shape: s.action === 'long' ? 'arrowUp' : 'arrowDown',
          text: s.action === 'long' ? 'LONG' : 'SHORT',
          size: 2,
        })

        // Si tenemos precio exacto de la señal, mostrarlo como priceLine punteada
        if (signalPrice) {
          const plSignal = candleSeries.createPriceLine({
            price: signalPrice,
            color: s.action === 'long' ? '#16a34a' : '#dc2626',
            lineWidth: 1,
            lineStyle: 3, // dotted
            axisLabelVisible: true,
            title: `Señal ${s.action.toUpperCase()}`,
          })
          positionPriceLinesRef.current.push(plSignal)
        }
      }

      // ── 3. Marker de entrada de la posición (precio exacto) ──
      allMarkers.push({
        time: entryTime,
        position: isLong ? 'belowBar' : 'aboveBar',
        color: posColor,
        shape: isLong ? 'arrowUp' : 'arrowDown',
        text: 'Entry',
        size: 2,
      })

      // PriceLine del precio de entrada exacto
      const plEntryExact = candleSeries.createPriceLine({
        price: entryPrice,
        color: posColor,
        lineWidth: 2,
        lineStyle: 0,
        axisLabelVisible: true,
        title: `Entry ${side.toUpperCase()}`,
      })
      positionPriceLinesRef.current.push(plEntryExact)

      if (closeTime) {
        const pnl = parseFloat(pos.realized_pnl || 0)
        allMarkers.push({
          time: closeTime,
          position: isLong ? 'aboveBar' : 'belowBar',
          color: pnl >= 0 ? '#22c55e' : '#ef4444',
          shape: 'circle',
          text: `${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}`,
          size: 2,
        })
      }

      // ── 2. Price lines: SL, TP(s) ──
      if (pos.current_sl_price) {
        const plSl = candleSeries.createPriceLine({
          price: parseFloat(pos.current_sl_price),
          color: '#ef4444',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'SL',
        })
        positionPriceLinesRef.current.push(plSl)
      }

      if (pos.current_tp_prices?.length > 0) {
        pos.current_tp_prices.forEach((tp, idx) => {
          const plTp = candleSeries.createPriceLine({
            price: parseFloat(tp),
            color: '#22c55e',
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: `TP${idx + 1}`,
          })
          positionPriceLinesRef.current.push(plTp)
        })
      }

      // ── 3. BE / TS detection ──
      // Si el SL se movió a favor del trade vs el SL inicial del bot, mostrar BE/TS
      const bot = bots.find(b => b.id === pos.bot_id)
      let bePrice = null
      let tsPrice = null
      if (bot?.initial_sl_percentage && pos.entry_price) {
        const initialSlPct = parseFloat(bot.initial_sl_percentage)
        const initialSl = isLong
          ? entryPrice * (1 - initialSlPct / 100)
          : entryPrice * (1 + initialSlPct / 100)
        const currentSl = parseFloat(pos.current_sl_price || 0)
        if (currentSl > 0) {
          // Si el SL actual está mejor que el inicial → BE o TS aplicado
          const improved = isLong ? currentSl > initialSl : currentSl < initialSl
          if (improved) {
            // Determinar si es BE (cerca del entry) o TS (por encima/delante)
            const nearEntry = Math.abs(currentSl - entryPrice) / entryPrice < 0.005
            if (nearEntry) {
              bePrice = currentSl
            } else {
              tsPrice = currentSl
            }
          }
        }
      }
      // También revisar extra_config por flags explícitos
      const extra = pos.extra_config || {}
      if (extra.breakeven_applied) bePrice = parseFloat(pos.current_sl_price) || bePrice
      if (extra.trailing_sl_activated) tsPrice = parseFloat(pos.current_sl_price) || tsPrice

      if (bePrice) {
        const plBe = candleSeries.createPriceLine({
          price: bePrice,
          color: '#f59e0b',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'BE',
        })
        positionPriceLinesRef.current.push(plBe)
      }
      if (tsPrice) {
        const plTs = candleSeries.createPriceLine({
          price: tsPrice,
          color: '#a855f7',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'TS',
        })
        positionPriceLinesRef.current.push(plTs)
      }

      // ── 4. LineSeries de duración (banda gruesa simulando rectángulo) ──
      const lastCandle = candleData[candleData.length - 1]
      const endTime = closeTime || (lastCandle ? lastCandle.time : entryTime)
      if (endTime > entryTime) {
        // Línea gruesa en el precio de entrada (base de la posición)
        const durSeries = chart.addLineSeries({
          color: posColor,
          lineWidth: 3,
          lineStyle: 0,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        })
        durSeries.setData([
          { time: entryTime, value: entryPrice },
          { time: endTime, value: entryPrice },
        ])
        positionLineSeriesRef.current = durSeries

        // Banda semitransparente de fondo (área bajo la línea de entrada)
        const bandSeries = chart.addAreaSeries({
          topColor: isLong ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
          bottomColor: 'rgba(0,0,0,0)',
          lineColor: 'rgba(0,0,0,0)',
          lineWidth: 0,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        })
        // Para area series necesitamos un valor base (0 o un precio lejano)
        // Usamos el low de las velas como base para que el área se vea desde entry hacia abajo
        const chartLow = Math.min(...candleData.map(c => c.low)) * 0.95
        bandSeries.setData([
          { time: entryTime, value: entryPrice },
          { time: endTime, value: entryPrice },
        ])
        // Guardar referencia para cleanup (usamos un array auxiliar)
        if (!positionLineSeriesRef._aux) positionLineSeriesRef._aux = []
        positionLineSeriesRef._aux.push(bandSeries)
      }

      // ── 5. Zoom automático a la posición ──
      try {
        const entryIndex = candleData.findIndex(c => c.time >= entryTime)
        const closeIndex = closeTime
          ? candleData.findIndex(c => c.time >= closeTime)
          : candleData.length - 1
        if (entryIndex >= 0 && closeIndex >= 0) {
          chart.timeScale().setVisibleLogicalRange({
            from: Math.max(0, entryIndex - 10),
            to: Math.min(candleData.length - 1, closeIndex + 10),
          })
        }
      } catch (e) {
        // fallback: fitContent
        chart.timeScale().fitContent()
      }
    } else {
      chart.timeScale().fitContent()
    }

    // Aplicar markers (vacío por defecto, solo se llena al seleccionar posición)
    candleSeries.setMarkers(allMarkers)

    const handleResize = () => {
      if (chartContainerRef.current) {
        const { width, height } = chartContainerRef.current.getBoundingClientRect()
        chart.applyOptions({ width, height })
      }
    }
    
    handleResize()
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [selectedSymbol, timeframe, positions, signals, candleData, loading, showEma20, showEma50, showSma200, showRsi, showVolume, selectedPosition, bots])

  // Generar datos mock para demo
  const generateMockData = (symbol, tf) => {
    const data = []
    const now = new Date()
    const multiplier = tf === '1m' ? 60000 : tf === '5m' ? 300000 : tf === '15m' ? 900000 : tf === '1h' ? 3600000 : tf === '4h' ? 14400000 : 86400000
    let price = symbol?.includes('BTC') ? 67500 : symbol?.includes('ETH') ? 3450 : 150
    
    for (let i = 200; i >= 0; i--) {
      const time = new Date(now.getTime() - i * multiplier)
      const volatility = price * 0.002
      const open = price
      const close = price + (Math.random() - 0.5) * volatility * 2
      const high = Math.max(open, close) + Math.random() * volatility
      const low = Math.min(open, close) - Math.random() * volatility
      
      data.push({
        time: Math.floor(time.getTime() / 1000),
        open,
        high,
        low,
        close,
      })
      price = close
    }
    return data
  }

  // Filtrar símbolos por búsqueda
  const filteredSymbols = useMemo(() => {
    if (!symbolSearch) return availableSymbols
    return availableSymbols.filter(s => 
      s.symbol?.toLowerCase().includes(symbolSearch.toLowerCase()) ||
      s.description?.toLowerCase().includes(symbolSearch.toLowerCase())
    )
  }, [availableSymbols, symbolSearch])

  // Seleccionar símbolo
  const handleSelectSymbol = (symbol) => {
    setSelectedSymbol(symbol)
    setShowSymbolDropdown(false)
    setSymbolSearch('')
    // Recargar señales para el nuevo símbolo
    tradingSignalsService.list({ symbol, days: 7, limit: 100 })
      .then(res => setSignals(res.data?.signals || []))
      .catch(() => setSignals([]))
  }

  // Current price
  const currentPrice = prices[selectedSymbol]

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] flex flex-col gap-4 bg-slate-100 dark:bg-gray-950">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3">
          <BarChart3 className="w-6 h-6 text-blue-500" />
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Chart</h1>
        </div>
        
        <div className="flex flex-wrap items-center gap-3">
          {/* Selector de símbolo con búsqueda */}
          <div className="relative">
            <button
              onClick={() => setShowSymbolDropdown(!showSymbolDropdown)}
              className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg hover:bg-slate-50 dark:hover:bg-gray-700 min-w-[200px]"
            >
              <span className="font-medium text-slate-900 dark:text-white">{selectedSymbol}</span>
              {currentPrice && (
                <span className="text-sm text-slate-500 dark:text-gray-400">
                  ${formatPrice(currentPrice)}
                </span>
              )}
              <ChevronDown size={16} className="ml-auto text-slate-400" />
            </button>
            
            {showSymbolDropdown && (
              <div className="absolute top-full left-0 mt-2 w-72 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg shadow-xl z-50">
                <div className="p-2 border-b border-slate-200 dark:border-gray-700">
                  <input
                    type="text"
                    placeholder="Buscar par..."
                    value={symbolSearch}
                    onChange={(e) => {
                      setSymbolSearch(e.target.value)
                      loadSymbols(e.target.value)
                    }}
                    className="w-full px-3 py-2 text-sm bg-slate-100 dark:bg-gray-900 border-none rounded-lg focus:ring-2 focus:ring-blue-500"
                    autoFocus
                  />
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {filteredSymbols.length === 0 ? (
                    <p className="p-3 text-sm text-slate-500">No se encontraron pares</p>
                  ) : (
                    filteredSymbols.slice(0, 20).map(s => (
                      <button
                        key={s.symbol}
                        onClick={() => handleSelectSymbol(s.symbol)}
                        className={`w-full px-4 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-gray-700 ${
                          s.symbol === selectedSymbol ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600' : 'text-slate-700 dark:text-gray-300'
                        }`}
                      >
                        <div className="font-medium">{s.symbol}</div>
                        <div className="text-xs text-slate-500">{s.description}</div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
          
          {/* Selector de timeframe */}
          <div className="flex items-center gap-1 bg-slate-100 dark:bg-gray-800 rounded-lg p-1">
            {['1m', '5m', '15m', '1h', '4h', '1d'].map(tf => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  timeframe === tf
                    ? 'bg-white dark:bg-gray-700 text-slate-900 dark:text-white shadow-sm'
                    : 'text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-200'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Controles de visualización */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 shrink-0">
        <span className="text-xs font-semibold text-slate-500 dark:text-gray-400 uppercase">Overlay</span>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showEma20} onChange={(e) => setShowEma20(e.target.checked)} className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
          <span className="text-sm text-slate-700 dark:text-gray-300"><span className="inline-block w-3 h-0.5 bg-amber-500 mr-1" />EMA 20</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showEma50} onChange={(e) => setShowEma50(e.target.checked)} className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
          <span className="text-sm text-slate-700 dark:text-gray-300"><span className="inline-block w-3 h-0.5 bg-blue-500 mr-1" />EMA 50</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showSma200} onChange={(e) => setShowSma200(e.target.checked)} className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
          <span className="text-sm text-slate-700 dark:text-gray-300"><span className="inline-block w-3 h-0.5 bg-red-500 mr-1" />SMA 200</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
          <span className="text-sm text-slate-700 dark:text-gray-300">Volumen</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showRsi} onChange={(e) => setShowRsi(e.target.checked)} className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
          <span className="text-sm text-slate-700 dark:text-gray-300">RSI 14</span>
        </label>
        {selectedPosition && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-xs font-semibold text-slate-500 dark:text-gray-400 uppercase">Posición seleccionada</span>
            <span className={`text-xs font-bold px-2 py-1 rounded-full ${selectedPosition.side === 'long' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'}`}>
              {selectedPosition.side.toUpperCase()} @ {formatPrice(selectedPosition.entry_price)}
            </span>
            <button
              onClick={() => setSelectedPosition(null)}
              className="text-xs text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-200 underline"
            >
              Limpiar
            </button>
          </div>
        )}
      </div>

      {/* Grid principal */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-4 gap-4 min-h-0">
        {/* Gráfico */}
        <div className="xl:col-span-3 card p-0 overflow-hidden flex flex-col">
          <div ref={chartContainerRef} className="flex-1 w-full min-h-[400px] relative">
            {chartError && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-100/80 dark:bg-gray-950/80 z-10">
                <div className="text-center p-6">
                  <AlertTriangle size={32} className="text-amber-500 mx-auto mb-3" />
                  <p className="text-slate-700 dark:text-gray-300 font-medium mb-1">No se pudieron cargar los datos del gráfico</p>
                  <p className="text-slate-500 dark:text-gray-400 text-sm">{chartError}</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Panel lateral */}
        <div className="space-y-4 overflow-y-auto xl:overflow-visible">
          {/* Posiciones abiertas */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-900 dark:text-white">
              <Activity size={14} className="text-blue-500" />
              Posiciones abiertas
              <span className="ml-auto text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 px-2 py-0.5 rounded-full">
                {positions.filter(p => p.status === 'open' && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm).length}
              </span>
            </h3>
            {positions.filter(p => p.status === 'open' && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm).length === 0 ? (
              <p className="text-sm text-slate-400">Sin posiciones abiertas</p>
            ) : (
              <div className="space-y-2">
                {positions
                  .filter(p => p.status === 'open' && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm)
                  .map(pos => (
                    <div
                      key={pos.id}
                      onClick={() => setSelectedPosition(selectedPosition?.id === pos.id ? null : pos)}
                      className={`p-3 bg-slate-50 dark:bg-gray-800/50 rounded-lg text-sm cursor-pointer transition-all hover:bg-slate-100 dark:hover:bg-gray-700 ${
                        selectedPosition?.id === pos.id ? 'ring-2 ring-blue-500 bg-blue-50 dark:bg-blue-900/20' : ''
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className={`font-semibold ${pos.side === 'long' ? 'text-green-500' : 'text-red-500'}`}>
                          {pos.side === 'long' ? 'LONG' : 'SHORT'}
                        </span>
                        <span className="text-slate-500 font-mono">{formatPrice(pos.entry_price)}</span>
                      </div>
                      {(() => {
                        const roi = calculatePositionRoi(pos, prices[pos.symbol])
                        const isPos = roi >= 0
                        return (
                          <div className={`text-xs font-mono font-semibold mb-2 ${isPos ? 'text-green-500' : 'text-red-500'}`}>
                            {isPos ? '+' : ''}{roi.toFixed(2)}% ROI (x{pos.leverage || 1})
                          </div>
                        )
                      })()}
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Cantidad:</span>
                          <span className="font-mono">{parseFloat(pos.quantity).toFixed(4)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">SL:</span>
                          <span className="font-mono text-red-500">{formatPrice(pos.current_sl_price) || '—'}</span>
                        </div>
                        {pos.current_tp_prices?.length > 0 && (
                          <div className="flex justify-between">
                            <span className="text-slate-400">TP:</span>
                            <span className="font-mono text-green-500">
                              {pos.current_tp_prices.map(tp => formatPrice(tp)).join(', ')}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>

          {/* Posiciones cerradas */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-900 dark:text-white">
              <TrendingUp size={14} className="text-purple-500" />
              Posiciones cerradas
              <span className="ml-auto text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 px-2 py-0.5 rounded-full">
                {positions.filter(p => p.status === 'closed' && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm).length}
              </span>
            </h3>
            {positions.filter(p => p.status === 'closed' && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm).length === 0 ? (
              <p className="text-sm text-slate-400">Sin posiciones cerradas</p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {positions
                  .filter(p => p.status === 'closed' && normalizeSymbol(toCcxtSymbol(p.symbol)) === selectedSymbolNorm)
                  .map(pos => {
                    const pnl = parseFloat(pos.realized_pnl || 0)
                    const isWin = pnl >= 0
                    return (
                      <div
                        key={pos.id}
                        onClick={() => setSelectedPosition(selectedPosition?.id === pos.id ? null : pos)}
                        className={`p-3 bg-slate-50 dark:bg-gray-800/50 rounded-lg text-sm cursor-pointer transition-all hover:bg-slate-100 dark:hover:bg-gray-700 ${
                          selectedPosition?.id === pos.id ? 'ring-2 ring-blue-500 bg-blue-50 dark:bg-blue-900/20' : ''
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className={`font-semibold ${pos.side === 'long' ? 'text-green-500' : 'text-red-500'}`}>
                            {pos.side === 'long' ? 'LONG' : 'SHORT'}
                          </span>
                          <span className={`font-mono font-bold ${isWin ? 'text-green-500' : 'text-red-500'}`}>
                            {isWin ? '+' : ''}{pnl.toFixed(2)} USDT
                          </span>
                        </div>
                        <div className="space-y-1 text-xs">
                          <div className="flex justify-between">
                            <span className="text-slate-400">Entrada:</span>
                            <span className="font-mono">{formatPrice(pos.entry_price)}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-400">Cantidad:</span>
                            <span className="font-mono">{parseFloat(pos.quantity).toFixed(4)}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-400">Abierta:</span>
                            <span className="text-slate-500">{formatTime(pos.opened_at)}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-400">Cerrada:</span>
                            <span className="text-slate-500">{formatTime(pos.closed_at)}</span>
                          </div>
                        </div>
                      </div>
                    )
                  })}
              </div>
            )}
          </div>

          {/* Señales recientes */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-900 dark:text-white">
              <Clock size={14} className="text-yellow-500" />
              Señales recientes
              <span className="ml-auto text-xs bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 px-2 py-0.5 rounded-full">
                {signals.length}
              </span>
            </h3>
            {signals.length === 0 ? (
              <p className="text-sm text-slate-400">Sin señales recientes</p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {signals.slice(0, 10).map(signal => (
                  <div key={signal.id} className="p-3 bg-slate-50 dark:bg-gray-800/50 rounded-lg text-sm">
                    <div className="flex items-center justify-between mb-2">
                      <span className={`font-semibold ${
                        signal.action === 'long' ? 'text-green-500' : 
                        signal.action === 'short' ? 'text-red-500' : 
                        'text-slate-500'
                      }`}>
                        {signal.action?.toUpperCase()}
                      </span>
                      <span className="text-xs text-slate-400">{formatTime(signal.received_at)}</span>
                    </div>
                    
                    <div className="text-slate-700 dark:text-gray-300 font-mono mb-2">
                      @ {formatPrice(signal.price)}
                    </div>
                    
                    {/* Indicadores */}
                    {signal.indicator_values && Object.keys(signal.indicator_values).length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(signal.indicator_values).slice(0, 4).map(([key, value], idx) => (
                          <IndicatorBadge 
                            key={key} 
                            name={key.toUpperCase()} 
                            value={value}
                            color={idx % 2 === 0 ? 'blue' : 'purple'}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Leyenda */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Leyenda</h3>
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 flex items-center justify-center">
                  <TrendingUp size={16} className="text-green-500" />
                </div>
                <span className="text-slate-600 dark:text-gray-400">Señal LONG</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 flex items-center justify-center">
                  <TrendingDown size={16} className="text-red-500" />
                </div>
                <span className="text-slate-600 dark:text-gray-400">Señal SHORT</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 border-t-2 border-dotted border-green-600" />
                <span className="text-slate-600 dark:text-gray-400">Precio señal</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-green-500" />
                <span className="text-slate-600 dark:text-gray-400">Entrada / TP</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-red-500" />
                <span className="text-slate-600 dark:text-gray-400">Stop Loss</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-amber-500" />
                <span className="text-slate-600 dark:text-gray-400">Break Even (BE)</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-purple-500" />
                <span className="text-slate-600 dark:text-gray-400">Trailing Stop (TS)</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-1.5 bg-green-500/30 rounded" />
                <span className="text-slate-600 dark:text-gray-400">Duración LONG</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-1.5 bg-red-500/30 rounded" />
                <span className="text-slate-600 dark:text-gray-400">Duración SHORT</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
