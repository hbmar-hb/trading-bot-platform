import { useEffect, useRef, useState } from 'react'
import { createChart, CrosshairMode } from 'lightweight-charts'
import { X, TrendingUp, TrendingDown, Calculator, GripVertical, RefreshCw } from 'lucide-react'
import { positionsService } from '@/services/positions'
import PositionManager from './PositionManager'
import useUiStore from '@/store/uiStore'
import usePositionStore from '@/store/positionStore'

const TIMEFRAMES = [
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '30m', value: '30m' },
  { label: '1h', value: '1h' },
  { label: '4h', value: '4h' },
  { label: '1d', value: '1d' },
]

function formatPrice(price) {
  if (!price) return '—'
  const num = parseFloat(price)
  if (isNaN(num)) return '—'
  if (num >= 1000) return num.toFixed(2)
  if (num >= 1) return num.toFixed(4)
  if (num >= 0.01) return num.toFixed(6)
  return num.toFixed(8)
}

function RiskPanel({ position, livePnl = 0, livePnlPct = 0 }) {
  const entry = parseFloat(position?.entry_price || 0)
  const sl = parseFloat(position?.current_sl_price || 0)
  const qty = parseFloat(position?.quantity || 0)
  const tps = position?.current_tp_prices || []

  const risk = Math.abs(entry - sl) * qty

  const tpAnalysis = tps.map((tp, i) => {
    const tpPrice = parseFloat(tp.price || tp)
    const reward = Math.abs(tpPrice - entry) * qty
    const ratio = risk > 0 ? (reward / risk).toFixed(2) : '0'
    const pct = position?.side === 'long'
      ? ((tpPrice / entry - 1) * 100).toFixed(2)
      : ((entry / tpPrice - 1) * 100).toFixed(2)
    return { tpPrice, reward, ratio, pct, index: i + 1 }
  })

  const totalReward = tpAnalysis.reduce((sum, tp) => sum + tp.reward, 0)
  const avgRatio = risk > 0 ? (totalReward / risk).toFixed(2) : '0'

  const pnl = livePnl
  const pnlPercent = livePnlPct.toFixed(2)

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300 flex items-center gap-2">
        <Calculator size={14} />
        Análisis de Riesgo
      </h4>

      <div className={`p-2 rounded-lg ${pnl >= 0 ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
        <p className="text-xs text-slate-500 dark:text-gray-500">PnL Actual</p>
        <p className={`font-mono text-lg ${pnl >= 0 ? 'text-green-500 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
          {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} USDT
        </p>
        <p className={`text-xs ${pnl >= 0 ? 'text-green-500/70 dark:text-green-400/70' : 'text-red-500/70 dark:text-red-400/70'}`}>
          {pnlPercent}%
        </p>
      </div>

      <div className="bg-red-500/10 p-2 rounded-lg">
        <p className="text-xs text-slate-500 dark:text-gray-500">Riesgo Total</p>
        <p className="font-mono text-red-500 dark:text-red-400">${risk.toFixed(2)}</p>
        <p className="text-xs text-red-500/70 dark:text-red-400/70">SL a {((Math.abs(entry - sl) / entry) * 100).toFixed(2)}%</p>
      </div>

      {tpAnalysis.map((tp) => (
        <div key={tp.index} className="bg-green-500/10 p-2 rounded-lg">
          <div className="flex justify-between items-center">
            <span className="text-xs text-slate-500 dark:text-gray-500">TP{tp.index}</span>
            <span className="text-xs text-green-500 dark:text-green-400">+{tp.pct}%</span>
          </div>
          <p className="font-mono text-green-500 dark:text-green-400">${formatPrice(tp.tpPrice)}</p>
          <p className="text-xs text-slate-500 dark:text-gray-500">
            Reward: ${tp.reward.toFixed(2)} | 1:{tp.ratio}
          </p>
        </div>
      ))}

      <div className="border-t border-slate-200 dark:border-gray-700 pt-2">
        <div className="flex justify-between text-sm">
          <span className="text-slate-500 dark:text-gray-500">Ratio R/R Total:</span>
          <span className={`font-bold ${parseFloat(avgRatio) >= 2 ? 'text-green-500 dark:text-green-400' : parseFloat(avgRatio) >= 1 ? 'text-yellow-500 dark:text-yellow-400' : 'text-red-500 dark:text-red-400'}`}>
            1:{avgRatio}
          </span>
        </div>
      </div>
    </div>
  )
}

export default function PositionChartModal({ position, isOpen, onClose, onPositionUpdate }) {
  const chartContainerRef = useRef(null)
  const chartRef = useRef(null)
  const [timeframe, setTimeframe] = useState('15m')
  const [candles, setCandles] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [currentPosition, setCurrentPosition] = useState(position)
  const isDark = useUiStore(s => s.isDark)
  const prices = usePositionStore(s => s.prices)

  // PnL en tiempo real usando precio del WebSocket
  const livePrice = currentPosition ? prices[currentPosition.symbol] : null
  const entryPrice = parseFloat(currentPosition?.entry_price || 0)
  const quantity = parseFloat(currentPosition?.quantity || 0)
  const livePnl = livePrice
    ? (currentPosition?.side === 'long'
        ? (livePrice - entryPrice) * quantity
        : (entryPrice - livePrice) * quantity)
    : parseFloat(currentPosition?.unrealized_pnl || 0)
  const livePnlPct = entryPrice > 0
    ? (livePnl / (entryPrice * quantity) * 100)
    : 0

  // Sincronizar cuando cambia la posición seleccionada desde fuera
  useEffect(() => {
    setCurrentPosition(position)
  }, [position])

  const refreshPosition = async () => {
    try {
      const { data } = await positionsService.get(position.id)
      setCurrentPosition(data)
    } catch (_) {}
    onPositionUpdate?.()
  }
  
  const [syncing, setSyncing] = useState(false)
  const handleSync = async () => {
    if (!currentPosition?.id) return
    setSyncing(true)
    try {
      const { data } = await positionsService.syncStatus(currentPosition.id)
      if (data.status === 'closed') {
        alert('Posición sincronizada: marcada como cerrada (ya no existe en el exchange)')
        onPositionUpdate?.()
        onClose()
      } else if (data.status === 'open') {
        alert('La posición sigue abierta en el exchange')
      } else {
        alert(data.message)
      }
    } catch (e) {
      alert('Error sincronizando: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSyncing(false)
    }
  }

  useEffect(() => {
    if (!isOpen || !position) return

    const fetchCandles = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await positionsService.getCandles(position.id, timeframe, 150)
        if (response.data && Array.isArray(response.data) && response.data.length > 0) {
          setCandles(response.data)
        } else {
          setError('No hay datos disponibles')
          setCandles([])
        }
      } catch (e) {
        console.error('Error cargando velas:', e)
        setError('Error cargando datos')
        setCandles([])
      } finally {
        setLoading(false)
      }
    }

    fetchCandles()
  }, [isOpen, position, timeframe])

  useEffect(() => {
    if (!isOpen || !chartContainerRef.current || candles.length === 0) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const bgColor    = isDark ? '#0f172a' : '#ffffff'
    const textColor  = isDark ? '#94a3b8' : '#475569'
    const gridColor  = isDark ? '#1e293b' : '#e2e8f0'
    const borderColor = isDark ? '#334155' : '#cbd5e1'

    const container = chartContainerRef.current
    const chart = createChart(container, {
      layout: { background: { color: bgColor }, textColor },
      grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor },
      timeScale: { borderColor, timeVisible: true },
    })

    chartRef.current = chart

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    })
    candleSeries.setData(candles)

    if (currentPosition?.entry_price) {
      const entryLine = chart.addLineSeries({
        color: '#3b82f6', lineWidth: 2, lineStyle: 2,
        title: 'ENTRADA', priceLineVisible: false,
      })
      entryLine.setData(candles.map(c => ({ time: c.time, value: parseFloat(currentPosition.entry_price) })))
    }

    if (currentPosition?.current_sl_price) {
      const slLine = chart.addLineSeries({
        color: '#ef4444', lineWidth: 2,
        title: 'SL', priceLineVisible: false,
      })
      slLine.setData(candles.map(c => ({ time: c.time, value: parseFloat(currentPosition.current_sl_price) })))
    }

    currentPosition?.current_tp_prices?.forEach((tp, i) => {
      const tpLine = chart.addLineSeries({
        color: '#22c55e', lineWidth: i === 0 ? 2 : 1,
        title: `TP${i + 1}`, priceLineVisible: false,
      })
      tpLine.setData(candles.map(c => ({ time: c.time, value: parseFloat(tp.price || tp) })))
    })

    chart.timeScale().fitContent()

    return () => { chart.remove(); chartRef.current = null }
  }, [isOpen, candles, currentPosition, isDark])

  if (!isOpen || !currentPosition) return null

  return (
    <div className="fixed inset-0 z-50 flex bg-white dark:bg-gray-900">
      <div className="w-full h-full flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900 shrink-0">
          <div className="flex items-center gap-3">
            {currentPosition.side === 'long' ? (
              <TrendingUp size={18} className="text-green-500 dark:text-green-400" />
            ) : (
              <TrendingDown size={18} className="text-red-500 dark:text-red-400" />
            )}
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">{currentPosition.symbol}</h2>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              currentPosition.side === 'long'
                ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400'
                : 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400'
            }`}>
              {currentPosition.side.toUpperCase()}
            </span>
            <span className="text-xs text-slate-500 dark:text-gray-500 hidden md:inline">
              Bot: {currentPosition.bot_name || '—'}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-gray-800 text-slate-600 dark:text-gray-400"
          >
            <X size={20} />
          </button>
        </div>

        {/* Stats row */}
        <div className="flex flex-wrap items-center gap-4 md:gap-6 px-4 py-2 border-b border-slate-200 dark:border-gray-800 bg-slate-50 dark:bg-gray-900/50 text-sm shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-gray-500">Entrada:</span>
            <span className="font-mono text-blue-600 dark:text-blue-400">${formatPrice(currentPosition.entry_price)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-gray-500">Cantidad:</span>
            <span className="font-mono text-slate-800 dark:text-gray-200">{parseFloat(currentPosition.quantity).toFixed(4)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-gray-500">SL:</span>
            <span className="font-mono text-red-500 dark:text-red-400">${formatPrice(currentPosition.current_sl_price)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-gray-500">TPs:</span>
            <div className="flex gap-1 flex-wrap">
              {currentPosition.current_tp_prices?.map((tp, i) => (
                <span key={i} className="font-mono text-xs text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-500/10 px-1.5 py-0.5 rounded">
                  ${formatPrice(tp.price || tp)}
                </span>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-xs text-slate-500 dark:text-gray-500">PnL:</span>
            <span className={`font-mono font-bold ${livePnl >= 0 ? 'text-green-500 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
              {livePnl >= 0 ? '+' : ''}{livePnl.toFixed(2)} USDT
            </span>
            <span className={`text-xs ${livePnl >= 0 ? 'text-green-500 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
              ({livePnl >= 0 ? '+' : ''}{livePnlPct.toFixed(2)}%)
            </span>
          </div>
        </div>

        {/* Timeframes */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900 shrink-0 overflow-x-auto">
          <span className="text-xs text-slate-500 dark:text-gray-500 whitespace-nowrap">Timeframe:</span>
          {TIMEFRAMES.map(tf => (
            <button
              key={tf.value}
              onClick={() => setTimeframe(tf.value)}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                timeframe === tf.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 dark:bg-gray-800 text-slate-600 dark:text-gray-400 hover:bg-slate-200 dark:hover:bg-gray-700'
              }`}
            >
              {tf.label}
            </button>
          ))}
        </div>

        {/* Main content: 3 columns */}
        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* Left panel - Position Manager */}
          <div className="w-80 border-r border-slate-200 dark:border-gray-800 bg-slate-50 dark:bg-gray-900/30 overflow-y-auto shrink-0">
            <div className="p-3">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-slate-600 dark:text-gray-400">
                  <GripVertical size={16} />
                  <span className="text-sm font-medium">Gestión de Posición</span>
                </div>
                <button
                  onClick={handleSync}
                  disabled={syncing}
                  title="Sincronizar con exchange (si cerraste manualmente en BingX)"
                  className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-gray-700 text-slate-500 dark:text-gray-400 disabled:opacity-50"
                >
                  <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
                </button>
              </div>
              <PositionManager
                position={currentPosition}
                onPositionUpdate={refreshPosition}
              />
            </div>
          </div>

          {/* Center - Chart */}
          <div className="flex-1 relative min-w-0 bg-white dark:bg-[#0f172a]">
            {loading ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              </div>
            ) : error ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-400 dark:text-gray-500">
                <p>{error}</p>
              </div>
            ) : (
              <div ref={chartContainerRef} className="w-full h-full" />
            )}
          </div>

          {/* Right panel - Risk calculator */}
          <div className="w-72 border-l border-slate-200 dark:border-gray-800 bg-slate-50 dark:bg-gray-900/30 overflow-y-auto shrink-0">
            <div className="p-3">
              <RiskPanel position={currentPosition} livePnl={livePnl} livePnlPct={livePnlPct} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
