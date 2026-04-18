import { useEffect, useState } from 'react'
import { X, TrendingUp, TrendingDown, Calendar, DollarSign, Percent, Target, Shield, Activity, ArrowRight } from 'lucide-react'
import { analyticsService } from '@/services/analytics'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

const CLOSE_REASON_ICONS = {
  'SL': { icon: Shield, color: 'text-red-400', label: 'Stop Loss' },
  'TP1': { icon: Target, color: 'text-green-400', label: 'Take Profit 1' },
  'TP2': { icon: Target, color: 'text-green-400', label: 'Take Profit 2' },
  'TP3': { icon: Target, color: 'text-green-400', label: 'Take Profit 3' },
  'Trailing Stop': { icon: Activity, color: 'text-blue-400', label: 'Trailing Stop' },
  'Breakeven': { icon: DollarSign, color: 'text-yellow-400', label: 'Breakeven' },
  'Manual': { icon: Activity, color: 'text-slate-400', label: 'Manual' },
  'Unknown': { icon: Activity, color: 'text-gray-400', label: 'Unknown' },
}

function TradeRow({ trade, onShowChart }) {
  const isProfit = parseFloat(trade.realized_pnl || 0) >= 0
  const reasonConfig = CLOSE_REASON_ICONS[trade.close_reason] || CLOSE_REASON_ICONS['Unknown']
  const ReasonIcon = reasonConfig.icon
  
  const formatDate = (dateStr) => {
    if (!dateStr) return '—'
    const date = new Date(dateStr)
    return date.toLocaleDateString('es-ES', { 
      day: '2-digit', 
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    })
  }
  
  const formatNumber = (num, decimals = 2) => {
    if (num === null || num === undefined) return '—'
    return Number(num).toFixed(decimals)
  }

  return (
    <tr className="border-b border-slate-200 dark:border-gray-800 hover:bg-slate-50 dark:hover:bg-gray-800/50">
      <td className="py-3 px-2">
        <div className="flex items-center gap-2">
          {trade.side === 'long' ? (
            <TrendingUp size={14} className="text-green-400" />
          ) : (
            <TrendingDown size={14} className="text-red-400" />
          )}
          <span className="font-medium text-sm">{trade.symbol}</span>
        </div>
      </td>
      <td className="py-3 px-2 text-xs text-slate-500 dark:text-gray-400">
        {formatDate(trade.closed_at)}
      </td>
      <td className="py-3 px-2 text-right text-xs">
        {trade.position_value ? `$${formatNumber(trade.position_value)}` : '—'}
      </td>
      <td className="py-3 px-2 text-right">
        <span className={`font-mono font-medium ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
          {isProfit ? '+' : ''}{formatNumber(trade.realized_pnl)}
        </span>
      </td>
      <td className="py-3 px-2 text-right">
        <span className={`font-mono text-xs ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
          {trade.roi_percent ? `${isProfit ? '+' : ''}${formatNumber(trade.roi_percent)}%` : '—'}
        </span>
      </td>
      <td className="py-3 px-2">
        <div className="flex items-center gap-1.5">
          <ReasonIcon size={12} className={reasonConfig.color} />
          <span className={`text-xs ${reasonConfig.color}`}>
            {reasonConfig.label}
          </span>
        </div>
      </td>
      <td className="py-3 px-2 text-center">
        <button 
          className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          onClick={onShowChart}
          title="Ver detalle de entrada/salida"
        >
          Ver
        </button>
      </td>
    </tr>
  )
}

// Componente para mostrar el detalle visual de un trade
function TradeChartView({ trade, onClose }) {
  const entryPrice = parseFloat(trade.entry_price || 0)
  const exitPrice = parseFloat(trade.exit_price || 0)
  const pnl = parseFloat(trade.realized_pnl || 0)
  const isProfit = pnl >= 0
  
  // Calcular rangos para la visualización
  const minPrice = Math.min(entryPrice, exitPrice) * 0.995 || 1
  const maxPrice = Math.max(entryPrice, exitPrice) * 1.005 || 1
  const range = maxPrice - minPrice || 1
  
  // Posiciones en porcentaje para las líneas (con protección contra división por cero)
  const entryPos = entryPrice > 0 ? ((entryPrice - minPrice) / range) * 100 : 50
  const exitPos = exitPrice > 0 ? ((exitPrice - minPrice) / range) * 100 : 50
  
  const formatPrice = (price) => price ? price.toFixed(4) : '—'
  const formatDate = (dateStr) => {
    if (!dateStr) return '—'
    const date = new Date(dateStr)
    return date.toLocaleString('es-ES', { 
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' 
    })
  }
  
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/60">
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-xl w-full max-w-lg">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-gray-800">
          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
              {trade.symbol} · {trade.side.toUpperCase()}
            </h3>
            <p className="text-xs text-slate-500">
              {formatDate(trade.closed_at)}
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 dark:hover:bg-gray-800 rounded-lg">
            <X size={20} className="text-slate-500" />
          </button>
        </div>
        
        {/* Visualización del trade */}
        <div className="p-6 space-y-6">
          {/* Gráfico simple */}
          <div className="relative h-32 bg-slate-100 dark:bg-gray-800 rounded-lg overflow-hidden">
            {/* Línea de entrada */}
            <div 
              className="absolute w-full flex items-center"
              style={{ top: `${100 - entryPos}%` }}
            >
              <div className="absolute left-0 w-full h-px bg-blue-400/50"></div>
              <div className="absolute left-2 bg-blue-500 text-white text-xs px-2 py-0.5 rounded">
                Entrada: {formatPrice(entryPrice)}
              </div>
            </div>
            
            {/* Línea de salida */}
            <div 
              className="absolute w-full flex items-center"
              style={{ top: `${100 - exitPos}%` }}
            >
              <div className="absolute left-0 w-full h-px bg-purple-400/50"></div>
              <div className="absolute right-2 bg-purple-500 text-white text-xs px-2 py-0.5 rounded">
                Salida: {formatPrice(exitPrice)}
              </div>
            </div>
            
            {/* Flecha de dirección */}
            <div className="absolute inset-0 flex items-center justify-center">
              <ArrowRight 
                size={32} 
                className={`transform ${isProfit ? 'rotate-0 text-green-400' : 'rotate-180 text-red-400'}`}
              />
            </div>
          </div>
          
          {/* Métricas */}
          <div className="grid grid-cols-3 gap-4 text-center">
            <div className="bg-slate-50 dark:bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-slate-500 mb-1">PnL</p>
              <p className={`font-mono font-bold ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
                {isProfit ? '+' : ''}{pnl.toFixed(2)} USDT
              </p>
            </div>
            <div className="bg-slate-50 dark:bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-slate-500 mb-1">ROI</p>
              <p className={`font-mono font-bold ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
                {trade.roi_percent ? `${isProfit ? '+' : ''}${trade.roi_percent.toFixed(2)}%` : '—'}
              </p>
            </div>
            <div className="bg-slate-50 dark:bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-slate-500 mb-1">Cierre</p>
              <p className="font-medium text-sm">{trade.close_reason || 'Unknown'}</p>
            </div>
          </div>
          
          {/* Detalles adicionales */}
          <div className="text-sm text-slate-600 dark:text-gray-400 space-y-1">
            <div className="flex justify-between">
              <span>Cantidad:</span>
              <span className="font-mono">{parseFloat(trade.quantity || 0).toFixed(4)}</span>
            </div>
            <div className="flex justify-between">
              <span>Valor posición:</span>
              <span className="font-mono">${trade.position_value ? trade.position_value.toFixed(2) : '—'}</span>
            </div>
            {trade.bot_name && (
              <div className="flex justify-between">
                <span>Bot:</span>
                <span>{trade.bot_name}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function TradeDetailModal({ botId, botName, fromDate, toDate, source, onClose }) {
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedTrade, setSelectedTrade] = useState(null)

  useEffect(() => {
    const loadTrades = async () => {
      try {
        setLoading(true)
        const params = { limit: 100 }
        if (botId) params.bot_id = botId
        if (fromDate) params.from_date = fromDate
        if (toDate) params.to_date = toDate
        if (source) params.source = source
        
        const res = await analyticsService.tradesDetail(params)
        setTrades(res.data || [])
      } catch (err) {
        console.error('Error cargando trades:', err)
        setError('No se pudieron cargar los trades')
      } finally {
        setLoading(false)
      }
    }
    
    loadTrades()
  }, [botId, fromDate, toDate, source])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-xl w-full max-w-5xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-gray-800">
          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
              {botId ? `Trades - ${botName}` : 'Todos los trades'}
            </h3>
            <p className="text-xs text-slate-500 dark:text-gray-400">
              {trades.length} trades encontrados
            </p>
          </div>
          <button 
            onClick={onClose}
            className="p-2 hover:bg-slate-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X size={20} className="text-slate-500" />
          </button>
        </div>
        
        {/* Content */}
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner />
            </div>
          ) : error ? (
            <div className="text-center py-12 text-red-400">{error}</div>
          ) : trades.length === 0 ? (
            <div className="text-center py-12 text-slate-500">No hay trades en este período</div>
          ) : (
            <table className="w-full">
              <thead className="sticky top-0 bg-white dark:bg-gray-900">
                <tr className="border-b border-slate-200 dark:border-gray-800 text-xs text-slate-500 dark:text-gray-400">
                  <th className="py-2 px-2 text-left font-medium">Símbolo</th>
                  <th className="py-2 px-2 text-left font-medium">Fecha cierre</th>
                  <th className="py-2 px-2 text-right font-medium">Valor pos.</th>
                  <th className="py-2 px-2 text-right font-medium">PnL</th>
                  <th className="py-2 px-2 text-right font-medium">ROI</th>
                  <th className="py-2 px-2 text-left font-medium">Cierre</th>
                  <th className="py-2 px-2 text-center font-medium">Chart</th>
                </tr>
              </thead>
              <tbody>
                {trades.map(trade => (
                  <TradeRow 
                    key={trade.id} 
                    trade={trade} 
                    onShowChart={() => setSelectedTrade(trade)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
        
        {/* Footer con resumen */}
        {!loading && trades.length > 0 && (
          <div className="p-4 border-t border-slate-200 dark:border-gray-800 bg-slate-50 dark:bg-gray-800/50">
            <div className="flex gap-6 text-sm">
              <span className="text-slate-500">
                Total PnL: 
                <span className={`ml-1 font-mono font-medium ${
                  trades.reduce((s, t) => s + parseFloat(t.realized_pnl || 0), 0) >= 0 
                    ? 'text-green-400' 
                    : 'text-red-400'
                }`}>
                  {trades.reduce((s, t) => s + parseFloat(t.realized_pnl || 0), 0) >= 0 ? '+' : ''}
                  {trades.reduce((s, t) => s + parseFloat(t.realized_pnl || 0), 0).toFixed(2)} USDT
                </span>
              </span>
              <span className="text-slate-500">
                Win Rate: 
                <span className="ml-1 font-medium">
                  {Math.round(trades.filter(t => parseFloat(t.realized_pnl || 0) > 0).length / trades.length * 100)}%
                </span>
              </span>
            </div>
          </div>
        )}
      </div>
      
      {/* Vista de detalle del trade seleccionado */}
      {selectedTrade && (
        <TradeChartView 
          trade={selectedTrade} 
          onClose={() => setSelectedTrade(null)} 
        />
      )}
    </div>
  )
}
