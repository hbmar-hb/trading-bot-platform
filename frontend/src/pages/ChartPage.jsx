import { useEffect, useRef, useState, useCallback } from 'react'
import { createChart } from 'lightweight-charts'
import { positionsService } from '@/services/positions'
import { botsService } from '@/services/bots'
import { tradingSignalsService } from '@/services/tradingSignals'
import usePositionStore from '@/store/positionStore'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import { TrendingUp, TrendingDown, Target, AlertTriangle, Activity, Clock, BarChart3 } from 'lucide-react'

// Trading signals service importado desde services

function formatPrice(price) {
  if (price === null || price === undefined) return '—'
  return Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
}

function formatTime(dateString) {
  if (!dateString) return '—'
  const date = new Date(dateString)
  return date.toLocaleString('es-ES', { 
    month: 'short', 
    day: 'numeric', 
    hour: '2-digit', 
    minute: '2-digit' 
  })
}

export default function ChartPage() {
  const chartContainerRef = useRef(null)
  const chartRef = useRef(null)
  const [loading, setLoading] = useState(true)
  const [selectedSymbol, setSelectedSymbol] = useState('BTC/USDT:USDT')
  const [timeframe, setTimeframe] = useState('1h')
  const [positions, setPositions] = useState([])
  const [signals, setSignals] = useState([])
  const [bots, setBots] = useState([])
  const [showSignals, setShowSignals] = useState(true)
  const [showPositions, setShowPositions] = useState(true)
  const prices = usePositionStore(s => s.prices)

  // Cargar datos iniciales
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      try {
        const [posRes, botsRes] = await Promise.all([
          positionsService.getUnified({ include_manual: true }),
          botsService.list(),
        ])
        setPositions(positionsRes.data || [])
        setBots(botsRes.data || [])
        
        // Cargar señales de los últimos 7 días
        const signalsRes = await tradingSignalsService.list({ 
          symbol: selectedSymbol, 
          days: 7,
          limit: 100 
        })
        setSignals(signalsRes.signals || [])
      } catch (e) {
        console.error('Error loading chart data:', e)
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [selectedSymbol])

  // Crear y actualizar gráfico
  useEffect(() => {
    if (!chartContainerRef.current || loading) return

    const isDark = document.documentElement.classList.contains('dark')
    const bg = isDark ? '#030712' : '#ffffff'
    const text = isDark ? '#9ca3af' : '#64748b'
    const grid = isDark ? '#1f2937' : '#e2e8f0'

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: bg }, textColor: text },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: 1 },
      timeScale: { borderColor: grid, timeVisible: true },
      rightPriceScale: { borderColor: grid },
      height: 500,
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

    // Cargar datos históricos (simulados por ahora - luego vendrán del backend)
    const loadChartData = async () => {
      try {
        // Esto debería venir de tu endpoint /charting/history
        // Por ahora usamos datos de ejemplo
        const mockData = generateMockData(selectedSymbol, timeframe)
        candleSeries.setData(mockData)
        
        // Añadir marcadores de señales
        if (showSignals && signals.length > 0) {
          const signalMarkers = signals
            .filter(s => s.symbol === selectedSymbol)
            .map(s => ({
              time: Math.floor(new Date(s.received_at).getTime() / 1000),
              position: s.action === 'long' ? 'belowBar' : 'aboveBar',
              color: s.action === 'long' ? '#22c55e' : '#ef4444',
              shape: s.action === 'long' ? 'arrowUp' : 'arrowDown',
              text: `${s.action.toUpperCase()}`,
              size: 2,
            }))
          candleSeries.setMarkers(signalMarkers)
        }
        
        // Añadir líneas de precio para posiciones abiertas
        if (showPositions) {
          positions
            .filter(p => p.symbol === selectedSymbol && p.status === 'open')
            .forEach(pos => {
              // Línea de entrada
              const entryLine = chart.addLineSeries({
                color: pos.side === 'long' ? '#22c55e' : '#ef4444',
                lineWidth: 1,
                lineStyle: 2, // dashed
                title: `Entry ${pos.side.toUpperCase()}`,
              })
              const entryTime = Math.floor(new Date(pos.opened_at).getTime() / 1000)
              entryLine.setData([
                { time: entryTime, value: parseFloat(pos.entry_price) },
                { time: entryTime + 86400, value: parseFloat(pos.entry_price) },
              ])
              
              // SL si existe
              if (pos.current_sl_price) {
                const slLine = chart.addLineSeries({
                  color: '#ef4444',
                  lineWidth: 1,
                  lineStyle: 3, // dotted
                  title: 'SL',
                })
                const slPrice = parseFloat(pos.current_sl_price)
                slLine.setData([
                  { time: entryTime, value: slPrice },
                  { time: entryTime + 86400, value: slPrice },
                ])
              }
              
              // TPs si existen
              if (pos.current_tp_prices && pos.current_tp_prices.length > 0) {
                pos.current_tp_prices.forEach((tp, idx) => {
                  const tpLine = chart.addLineSeries({
                    color: '#22c55e',
                    lineWidth: 1,
                    lineStyle: 3,
                    title: `TP${idx + 1}`,
                  })
                  const tpPrice = parseFloat(tp)
                  tpLine.setData([
                    { time: entryTime, value: tpPrice },
                    { time: entryTime + 86400, value: tpPrice },
                  ])
                })
              }
            })
        }
        
        chart.timeScale().fitContent()
      } catch (e) {
        console.error('Error loading chart data:', e)
      }
    }
    
    loadChartData()

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [selectedSymbol, timeframe, positions, signals, showSignals, showPositions, loading])

  // Generar datos mock para demo
  const generateMockData = (symbol, tf) => {
    const data = []
    const now = new Date()
    let price = symbol.includes('BTC') ? 67500 : symbol.includes('ETH') ? 3450 : 150
    
    for (let i = 100; i >= 0; i--) {
      const time = new Date(now.getTime() - i * 3600000)
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

  // Símbolos únicos de bots y posiciones
  const availableSymbols = [...new Set([
    ...bots.map(b => b.symbol),
    ...positions.map(p => p.symbol),
    'BTC/USDT:USDT',
    'ETH/USDT:USDT',
  ])].filter(Boolean)

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <BarChart3 className="w-6 h-6 text-blue-500" />
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Chart</h1>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Selector de símbolo */}
          <select
            value={selectedSymbol}
            onChange={(e) => setSelectedSymbol(e.target.value)}
            className="px-3 py-1.5 text-sm bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg"
          >
            {availableSymbols.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          
          {/* Selector de timeframe */}
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="px-3 py-1.5 text-sm bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg"
          >
            {['1m', '5m', '15m', '1h', '4h', '1d'].map(tf => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Controles de visualización */}
      <div className="flex items-center gap-4 text-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={showSignals}
            onChange={(e) => setShowSignals(e.target.checked)}
            className="rounded"
          />
          <span className="flex items-center gap-1">
            <AlertTriangle size={14} className="text-yellow-500" />
            Mostrar señales
          </span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={showPositions}
            onChange={(e) => setShowPositions(e.target.checked)}
            className="rounded"
          />
          <span className="flex items-center gap-1">
            <Target size={14} className="text-blue-500" />
            Mostrar posiciones
          </span>
        </label>
      </div>

      {/* Grid principal */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Gráfico */}
        <div className="lg:col-span-3 card p-0 overflow-hidden">
          <div ref={chartContainerRef} className="w-full" />
        </div>

        {/* Panel lateral */}
        <div className="space-y-4">
          {/* Posiciones abiertas */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Activity size={14} className="text-blue-500" />
              Posiciones abiertas
            </h3>
            {positions.filter(p => p.status === 'open' && p.symbol === selectedSymbol).length === 0 ? (
              <p className="text-xs text-slate-400">Sin posiciones abiertas</p>
            ) : (
              <div className="space-y-2">
                {positions
                  .filter(p => p.status === 'open' && p.symbol === selectedSymbol)
                  .map(pos => (
                    <div key={pos.id} className="p-2 bg-slate-50 dark:bg-gray-800/50 rounded-lg text-xs">
                      <div className="flex items-center justify-between">
                        <span className={`font-semibold ${pos.side === 'long' ? 'text-green-500' : 'text-red-500'}`}>
                          {pos.side.toUpperCase()}
                        </span>
                        <span className="text-slate-400">{formatPrice(pos.entry_price)}</span>
                      </div>
                      <div className="text-slate-500 mt-1">
                        SL: {formatPrice(pos.current_sl_price) || '—'}
                      </div>
                      {pos.current_tp_prices?.length > 0 && (
                        <div className="text-slate-500">
                          TP: {pos.current_tp_prices.map(tp => formatPrice(tp)).join(', ')}
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>

          {/* Señales recientes */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Clock size={14} className="text-yellow-500" />
              Señales recientes
            </h3>
            {signals.length === 0 ? (
              <p className="text-xs text-slate-400">Sin señales recientes</p>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {signals.slice(0, 10).map(signal => (
                  <div key={signal.id} className="p-2 bg-slate-50 dark:bg-gray-800/50 rounded-lg text-xs">
                    <div className="flex items-center justify-between">
                      <span className={`font-semibold ${signal.action === 'long' ? 'text-green-500' : signal.action === 'short' ? 'text-red-500' : 'text-slate-500'}`}>
                        {signal.action.toUpperCase()}
                      </span>
                      <span className="text-slate-400">{formatTime(signal.received_at)}</span>
                    </div>
                    <div className="text-slate-500 mt-1">
                      @ {formatPrice(signal.price)}
                    </div>
                    {signal.indicator_values && Object.keys(signal.indicator_values).length > 0 && (
                      <div className="text-[10px] text-slate-400 mt-1">
                        {Object.entries(signal.indicator_values).slice(0, 2).map(([k, v]) => `${k}: ${v}`).join(', ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Leyenda */}
          <div className="card space-y-2">
            <h3 className="text-sm font-semibold">Leyenda</h3>
            <div className="space-y-1 text-xs">
              <div className="flex items-center gap-2">
                <TrendingUp size={12} className="text-green-500" />
                <span className="text-slate-500">Señal Long</span>
              </div>
              <div className="flex items-center gap-2">
                <TrendingDown size={12} className="text-red-500" />
                <span className="text-slate-500">Señal Short</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-green-500" />
                <span className="text-slate-500">Entrada / TP</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-red-500 border-dashed" />
                <span className="text-slate-500">Stop Loss</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
