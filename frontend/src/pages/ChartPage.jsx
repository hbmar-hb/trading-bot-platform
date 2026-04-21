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
  const [showSignals, setShowSignals] = useState(true)
  const [showPositions, setShowPositions] = useState(true)
  const [showClosedPositions, setShowClosedPositions] = useState(true)
  const [candleData, setCandleData] = useState([])
  const [symbolSearch, setSymbolSearch] = useState('')
  const [showSymbolDropdown, setShowSymbolDropdown] = useState(false)
  const prices = usePositionStore(s => s.prices)
  const selectedSymbolNorm = useMemo(() => normalizeSymbol(selectedSymbol), [selectedSymbol])

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
    
    try {
      const to = Math.floor(Date.now() / 1000)
      // Ampliar histórico para poder ver posiciones antiguas (max ~1000 velas)
      const from = to - (
        timeframe === '1m' ? 43200 :      // 12h
        timeframe === '5m' ? 172800 :     // 2d
        timeframe === '15m' ? 432000 :    // 5d
        timeframe === '1h' ? 2592000 :    // 30d
        timeframe === '4h' ? 7776000 :    // 90d
        31536000                          // 1d -> 365d
      )
      
      const res = await chartingService.getHistory({
        symbol: selectedSymbol,
        resolution: timeframe,
        from_time: from,
        to_time: to,
      })
      
      if (res.data?.s === 'ok' && res.data.t) {
        const candles = res.data.t.map((time, i) => ({
          time,
          open: res.data.o[i],
          high: res.data.h[i],
          low: res.data.l[i],
          close: res.data.c[i],
        }))
        setCandleData(candles)
      } else {
        setCandleData(generateMockData(selectedSymbol, timeframe))
      }
    } catch (e) {
      console.error('Error loading candles:', e)
      setCandleData(generateMockData(selectedSymbol, timeframe))
    }
  }, [selectedSymbol, timeframe])

  // Cargar velas cuando cambia símbolo o timeframe
  useEffect(() => {
    loadCandleData()
  }, [loadCandleData])

  // Crear y actualizar gráfico
  useEffect(() => {
    if (!chartContainerRef.current || loading || candleData.length === 0) return

    const isDark = document.documentElement.classList.contains('dark')
    const bg = isDark ? '#0f172a' : '#ffffff'
    const text = isDark ? '#94a3b8' : '#64748b'
    const grid = isDark ? '#1e293b' : '#e2e8f0'

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
    
    // Preparar marcadores combinados (señales + posiciones cerradas)
    const allMarkers = []
    
    // Marcadores de señales
    if (showSignals && signals.length > 0) {
      const signalMarkers = signals
        .filter(s => normalizeSymbol(s.symbol) === selectedSymbolNorm)
        .map(s => {
          const signalTime = Math.floor(new Date(s.received_at).getTime() / 1000)
          const candle = candleData.find(c => c.time === signalTime)
          
          return {
            time: candle ? candle.time : signalTime,
            position: s.action === 'long' ? 'belowBar' : 'aboveBar',
            color: s.action === 'long' ? '#22c55e' : '#ef4444',
            shape: s.action === 'long' ? 'arrowUp' : 'arrowDown',
            text: s.action === 'long' ? 'BUY' : 'SELL',
            size: 2,
          }
        })
        .filter(m => m.time)
      
      allMarkers.push(...signalMarkers)
    }
    
    // Posiciones cerradas en el gráfico (líneas + marcadores)
    if (showClosedPositions) {
      const closedPositions = positions.filter(
        p => normalizeSymbol(p.symbol) === selectedSymbolNorm && p.status === 'closed' && p.closed_at
      )
      
      closedPositions.forEach(pos => {
        const entryTime = Math.floor(new Date(pos.opened_at).getTime() / 1000)
        const closeTime = Math.floor(new Date(pos.closed_at).getTime() / 1000)
        const entryPrice = parseFloat(pos.entry_price)
        
        // Usar precio de cierre de la vela en closed_at como exitPrice (más preciso visualmente)
        let exitPrice = entryPrice
        const closeCandle = candleData.find(c => c.time >= closeTime)
        if (closeCandle) {
          exitPrice = closeCandle.close
        } else {
          // Fallback: estimar desde realized_pnl
          const pnlVal = parseFloat(pos.realized_pnl || 0)
          const qty = parseFloat(pos.quantity || 0)
          if (qty > 0 && Math.abs(pnlVal) > 0.00000001) {
            exitPrice = pos.side === 'long'
              ? entryPrice + (pnlVal / qty)
              : entryPrice - (pnlVal / qty)
          }
        }
        
        const pnl = parseFloat(pos.realized_pnl || 0)
        const isWin = pnl >= 0
        const color = isWin ? '#22c55e' : '#ef4444'
        
        // Línea conectando entrada y salida (solo si hay diferencia de tiempo visible)
        if (Math.abs(exitPrice - entryPrice) > 0.00000001 || closeTime > entryTime) {
          const tradeLine = chart.addLineSeries({
            color,
            lineWidth: 2,
            lineStyle: 0,
            lastValueVisible: false,
          })
          tradeLine.setData([
            { time: entryTime, value: entryPrice },
            { time: closeTime, value: exitPrice },
          ])
        }
        
        // Marcadores de entrada y salida
        allMarkers.push({
          time: entryTime,
          position: pos.side === 'long' ? 'belowBar' : 'aboveBar',
          color,
          shape: pos.side === 'long' ? 'arrowUp' : 'arrowDown',
          text: `${pos.side === 'long' ? 'L' : 'S'}`,
          size: 1,
        })
        
        allMarkers.push({
          time: closeTime,
          position: pos.side === 'long' ? 'aboveBar' : 'belowBar',
          color,
          shape: 'circle',
          text: `${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}`,
          size: 1,
        })
      })
    }
    
    // Aplicar todos los marcadores
    if (allMarkers.length > 0) {
      candleSeries.setMarkers(allMarkers)
    }
    
    // Añadir líneas de precio para posiciones abiertas
    if (showPositions) {
      const relevantPositions = positions.filter(p => normalizeSymbol(p.symbol) === selectedSymbolNorm && p.status === 'open')
      const lastTime = candleData[candleData.length - 1]?.time || Math.floor(Date.now() / 1000)
      
      relevantPositions.forEach(pos => {
        const entryTime = Math.floor(new Date(pos.opened_at).getTime() / 1000)
        
        // Línea de entrada
        const entryLine = chart.addLineSeries({
          color: pos.side === 'long' ? '#22c55e' : '#ef4444',
          lineWidth: 2,
          lineStyle: 2,
          title: `Entry ${pos.side.toUpperCase()}`,
          lastValueVisible: false,
        })
        entryLine.setData([
          { time: entryTime, value: parseFloat(pos.entry_price) },
          { time: lastTime, value: parseFloat(pos.entry_price) },
        ])
        
        // SL
        if (pos.current_sl_price) {
          const slLine = chart.addLineSeries({
            color: '#ef4444',
            lineWidth: 1,
            lineStyle: 3,
            title: 'SL',
            lastValueVisible: false,
          })
          const slPrice = parseFloat(pos.current_sl_price)
          slLine.setData([
            { time: entryTime, value: slPrice },
            { time: lastTime, value: slPrice },
          ])
        }
        
        // TPs
        if (pos.current_tp_prices?.length > 0) {
          pos.current_tp_prices.forEach((tp, idx) => {
            const tpLine = chart.addLineSeries({
              color: '#22c55e',
              lineWidth: 1,
              lineStyle: 3,
              title: `TP${idx + 1}`,
              lastValueVisible: false,
            })
            const tpPrice = parseFloat(tp)
            tpLine.setData([
              { time: entryTime, value: tpPrice },
              { time: lastTime, value: tpPrice },
            ])
          })
        }
      })
    }
    
    chart.timeScale().fitContent()

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
  }, [selectedSymbol, timeframe, positions, signals, showSignals, showPositions, showClosedPositions, candleData, loading])

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
    <div className="h-[calc(100vh-4rem)] flex flex-col gap-4">
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
      <div className="flex items-center gap-6 shrink-0">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={showSignals}
            onChange={(e) => setShowSignals(e.target.checked)}
            className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="flex items-center gap-1.5 text-sm text-slate-700 dark:text-gray-300">
            <AlertTriangle size={14} className="text-yellow-500" />
            Mostrar señales
          </span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={showPositions}
            onChange={(e) => setShowPositions(e.target.checked)}
            className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="flex items-center gap-1.5 text-sm text-slate-700 dark:text-gray-300">
            <Target size={14} className="text-blue-500" />
            Mostrar posiciones abiertas
          </span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={showClosedPositions}
            onChange={(e) => setShowClosedPositions(e.target.checked)}
            className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="flex items-center gap-1.5 text-sm text-slate-700 dark:text-gray-300">
            <TrendingUp size={14} className="text-purple-500" />
            Mostrar posiciones cerradas
          </span>
        </label>
      </div>

      {/* Grid principal */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-4 gap-4 min-h-0">
        {/* Gráfico */}
        <div className="xl:col-span-3 card p-0 overflow-hidden flex flex-col">
          <div ref={chartContainerRef} className="flex-1 w-full min-h-[400px]" />
        </div>

        {/* Panel lateral */}
        <div className="space-y-4 overflow-y-auto xl:overflow-visible">
          {/* Posiciones abiertas */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-900 dark:text-white">
              <Activity size={14} className="text-blue-500" />
              Posiciones abiertas
              <span className="ml-auto text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 px-2 py-0.5 rounded-full">
                {positions.filter(p => p.status === 'open' && normalizeSymbol(p.symbol) === selectedSymbolNorm).length}
              </span>
            </h3>
            {positions.filter(p => p.status === 'open' && normalizeSymbol(p.symbol) === selectedSymbolNorm).length === 0 ? (
              <p className="text-sm text-slate-400">Sin posiciones abiertas</p>
            ) : (
              <div className="space-y-2">
                {positions
                  .filter(p => p.status === 'open' && normalizeSymbol(p.symbol) === selectedSymbolNorm)
                  .map(pos => (
                    <div key={pos.id} className="p-3 bg-slate-50 dark:bg-gray-800/50 rounded-lg text-sm">
                      <div className="flex items-center justify-between mb-2">
                        <span className={`font-semibold ${pos.side === 'long' ? 'text-green-500' : 'text-red-500'}`}>
                          {pos.side === 'long' ? 'LONG' : 'SHORT'}
                        </span>
                        <span className="text-slate-500 font-mono">{formatPrice(pos.entry_price)}</span>
                      </div>
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
                {positions.filter(p => p.status === 'closed' && normalizeSymbol(p.symbol) === selectedSymbolNorm).length}
              </span>
            </h3>
            {positions.filter(p => p.status === 'closed' && normalizeSymbol(p.symbol) === selectedSymbolNorm).length === 0 ? (
              <p className="text-sm text-slate-400">Sin posiciones cerradas</p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {positions
                  .filter(p => p.status === 'closed' && normalizeSymbol(p.symbol) === selectedSymbolNorm)
                  .map(pos => {
                    const pnl = parseFloat(pos.realized_pnl || 0)
                    const isWin = pnl >= 0
                    return (
                      <div key={pos.id} className="p-3 bg-slate-50 dark:bg-gray-800/50 rounded-lg text-sm">
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
                <span className="text-slate-600 dark:text-gray-400">Señal de compra (LONG)</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 flex items-center justify-center">
                  <TrendingDown size={16} className="text-red-500" />
                </div>
                <span className="text-slate-600 dark:text-gray-400">Señal de venta (SHORT)</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-green-500" />
                <span className="text-slate-600 dark:text-gray-400">Entrada / TP</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-red-500 border-dashed border-t border-red-500" />
                <span className="text-slate-600 dark:text-gray-400">Stop Loss</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-purple-500" />
                <span className="text-slate-600 dark:text-gray-400">Posición cerrada (ganancia)</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-8 h-0.5 bg-orange-500" />
                <span className="text-slate-600 dark:text-gray-400">Posición cerrada (pérdida)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
