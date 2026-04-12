import { useState, useEffect, useCallback } from 'react'
import { TrendingDown, TrendingUp, ArrowRight, BarChart3, Bot, FileText, User, Smartphone, X, ExternalLink, Clock, RefreshCw, ShieldCheck, ChevronDown, ChevronUp, Loader2, AlertCircle, Plus, Minus } from 'lucide-react'
import { useUnifiedPositions } from '@/hooks/useUnifiedPositions'
import usePositionStore from '@/store/positionStore'
import { positionsService } from '@/services/positions'
import { manualTradeService } from '@/services/manualTrade'
import PositionChartModal from '@/components/Positions/PositionChartModal'
import api from '@/services/api'

// Función para formatear precios con decimales dinámicos
function formatPrice(price, decimals = null) {
  if (price === null || price === undefined) return '—'
  const num = parseFloat(price)
  if (isNaN(num)) return '—'
  
  if (decimals === null) {
    if (num >= 1000) decimals = 2
    else if (num >= 1) decimals = 4
    else if (num >= 0.01) decimals = 6
    else if (num >= 0.0001) decimals = 8
    else decimals = 10
  }
  
  return num.toFixed(decimals)
}

function PnlCell({ value }) {
  const n = parseFloat(value || 0)
  return (
    <span className={`font-mono text-sm ${n >= 0 ? 'text-green-400' : 'text-red-400'}`}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}
    </span>
  )
}

// Badge para mostrar el tipo de posición
function SourceBadge({ source }) {
  const configs = {
    bot: { 
      icon: Bot, 
      label: 'Bot', 
      className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800' 
    },
    app_manual: { 
      icon: Smartphone, 
      label: 'App Manual', 
      className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 border-purple-200 dark:border-purple-800' 
    },
    paper: { 
      icon: FileText, 
      label: 'Paper', 
      className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-green-200 dark:border-green-800' 
    },
    manual: {
      icon: User,
      label: 'BingX Manual',
      className: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 border-orange-200 dark:border-orange-800'
    },
    pending_limit: {
      icon: Clock,
      label: 'Limit',
      className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 border-yellow-200 dark:border-yellow-800'
    },
  }
  
  const config = configs[source] || configs.manual
  const Icon = config.icon
  
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${config.className}`}>
      <Icon size={12} />
      {config.label}
    </span>
  )
}

// Celda que muestra precio de entrada vs actual con diferencia %
function PriceComparisonCell({ entryPrice, currentPrice, side }) {
  if (!currentPrice) {
    return <span className="font-mono text-slate-500 dark:text-gray-500">—</span>
  }
  
  const entry = parseFloat(entryPrice)
  const current = parseFloat(currentPrice)
  const diffPercent = ((current - entry) / entry) * 100
  const isProfitable = side === 'long' ? diffPercent >= 0 : diffPercent <= 0
  const colorClass = isProfitable ? 'text-green-400' : 'text-red-400'
  
  return (
    <div className="flex flex-col">
      <span className="font-mono text-slate-900 dark:text-white">{formatPrice(current)}</span>
      <div className="flex items-center gap-1 text-xs">
        <span className="text-slate-500 dark:text-gray-500">{formatPrice(entry)}</span>
        <ArrowRight size={10} className="text-slate-400 dark:text-gray-600" />
        <span className={`font-mono ${colorClass}`}>
          {isProfitable ? '+' : ''}{diffPercent.toFixed(2)}%
        </span>
      </div>
    </div>
  )
}

// ── Adopt Modal ──────────────────────────────────────────────

function AdoptModal({ position, onClose, onAdopted }) {
  const [slPct, setSlPct] = useState(2)
  const [takeProfits, setTakeProfits] = useState([{ profit_percent: 2, close_percent: 50 }])
  const [trailingEnabled, setTrailingEnabled] = useState(false)
  const [trailingActivation, setTrailingActivation] = useState(1)
  const [trailingCallback, setTrailingCallback] = useState(0.5)
  const [breakevenEnabled, setBreakevenEnabled] = useState(false)
  const [breakevenActivation, setBreakevenActivation] = useState(1)
  const [breakevenLock, setBreakevenLock] = useState(0.2)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const slPrice = position.side === 'long'
    ? position.entry_price * (1 - slPct / 100)
    : position.entry_price * (1 + slPct / 100)

  const handleAdopt = async () => {
    setLoading(true)
    setError(null)
    try {
      await manualTradeService.adoptPosition({
        exchange_account_id: position.exchange_account_id,
        symbol: position.symbol,
        side: position.side,
        sl_percentage: slPct,
        take_profits: takeProfits.filter(tp => tp.profit_percent && tp.close_percent),
        trailing_config: trailingEnabled
          ? { enabled: true, activation_profit: trailingActivation, callback_rate: trailingCallback }
          : null,
        breakeven_config: breakevenEnabled
          ? { enabled: true, activation_profit: breakevenActivation, lock_profit: breakevenLock }
          : null,
      })
      onAdopted()
    } catch (e) {
      setError(e?.response?.data?.detail || 'Error al adoptar la posición')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-md overflow-y-auto max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b border-slate-200 dark:border-gray-700">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <ShieldCheck size={20} className="text-blue-500" />
              Adoptar posición
            </h2>
            <p className="text-sm text-slate-500 dark:text-gray-400">
              {position.side === 'long' ? '🟢 LONG' : '🔴 SHORT'} {position.symbol}
              {' · '}Entrada: ${position.entry_price.toFixed(4)}
              {position.account_label && <span className="ml-2 text-xs">({position.account_label})</span>}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 dark:hover:text-gray-300">
            <X size={20} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Stop Loss */}
          <div>
            <label className="block text-xs text-slate-500 dark:text-gray-400 mb-1">Stop Loss %</label>
            <input
              type="number" min="0.1" step="0.1"
              className="w-full rounded-lg border border-slate-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-slate-900 dark:text-white"
              value={slPct}
              onChange={e => setSlPct(Number(e.target.value))}
            />
            <p className="text-xs text-red-500 mt-1">SL se colocará a ${slPrice.toFixed(4)}</p>
          </div>

          {/* Take Profits */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs text-slate-500 dark:text-gray-400">Take Profits</label>
              <button
                type="button"
                onClick={() => setTakeProfits(tp => [...tp, { profit_percent: 3, close_percent: 25 }])}
                className="text-xs text-blue-500 hover:underline flex items-center gap-1"
              >
                <Plus size={12} /> Añadir TP
              </button>
            </div>
            {takeProfits.map((tp, i) => (
              <div key={i} className="flex gap-2 items-center mb-2">
                <input
                  type="number" min="0.1" step="0.1" placeholder="Profit %"
                  className="flex-1 rounded-lg border border-slate-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-slate-900 dark:text-white"
                  value={tp.profit_percent}
                  onChange={e => setTakeProfits(tps => tps.map((t, j) => j === i ? { ...t, profit_percent: Number(e.target.value) } : t))}
                />
                <input
                  type="number" min="1" max="100" step="1" placeholder="Cierre %"
                  className="flex-1 rounded-lg border border-slate-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-slate-900 dark:text-white"
                  value={tp.close_percent}
                  onChange={e => setTakeProfits(tps => tps.map((t, j) => j === i ? { ...t, close_percent: Number(e.target.value) } : t))}
                />
                {takeProfits.length > 1 && (
                  <button onClick={() => setTakeProfits(tps => tps.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-500">
                    <Minus size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Trailing Stop */}
          <div className="border border-slate-200 dark:border-gray-700 rounded-lg p-3">
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-gray-300 cursor-pointer">
              <input type="checkbox" checked={trailingEnabled} onChange={e => setTrailingEnabled(e.target.checked)} />
              Trailing Stop
            </label>
            {trailingEnabled && (
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Activación %</label>
                  <input type="number" min="0.1" step="0.1"
                    className="w-full mt-1 rounded-lg border border-slate-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-slate-900 dark:text-white"
                    value={trailingActivation} onChange={e => setTrailingActivation(Number(e.target.value))} />
                </div>
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Callback %</label>
                  <input type="number" min="0.1" step="0.1"
                    className="w-full mt-1 rounded-lg border border-slate-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-slate-900 dark:text-white"
                    value={trailingCallback} onChange={e => setTrailingCallback(Number(e.target.value))} />
                </div>
              </div>
            )}
          </div>

          {/* Breakeven */}
          <div className="border border-slate-200 dark:border-gray-700 rounded-lg p-3">
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-gray-300 cursor-pointer">
              <input type="checkbox" checked={breakevenEnabled} onChange={e => setBreakevenEnabled(e.target.checked)} />
              Breakeven
            </label>
            {breakevenEnabled && (
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Activación %</label>
                  <input type="number" min="0.1" step="0.1"
                    className="w-full mt-1 rounded-lg border border-slate-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-slate-900 dark:text-white"
                    value={breakevenActivation} onChange={e => setBreakevenActivation(Number(e.target.value))} />
                </div>
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Lock profit %</label>
                  <input type="number" min="0" step="0.1"
                    className="w-full mt-1 rounded-lg border border-slate-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-slate-900 dark:text-white"
                    value={breakevenLock} onChange={e => setBreakevenLock(Number(e.target.value))} />
                </div>
              </div>
            )}
          </div>

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg p-3">
              <AlertCircle size={16} /> {error}
            </div>
          )}

          <button
            onClick={handleAdopt}
            disabled={loading}
            className="w-full py-3 rounded-xl font-semibold text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : <ShieldCheck size={18} />}
            Adoptar y activar gestión
          </button>
        </div>
      </div>
    </div>
  )
}

// ── External Positions Section ────────────────────────────────

function ExternalPositionsSection({ onAdopted }) {
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(false)
  const [adoptTarget, setAdoptTarget] = useState(null)
  const [expanded, setExpanded] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await manualTradeService.getExternalPositions()
      const list = res.data?.external_positions || []
      setPositions(list)
      if (list.length > 0) setExpanded(true)
    } catch {
      setPositions([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (!loading && positions.length === 0) return null

  return (
    <>
      {adoptTarget && (
        <AdoptModal
          position={adoptTarget}
          onClose={() => setAdoptTarget(null)}
          onAdopted={() => {
            setAdoptTarget(null)
            load()
            onAdopted?.()
          }}
        />
      )}

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-orange-200 dark:border-orange-800 shadow-sm">
        <button
          type="button"
          onClick={() => setExpanded(e => !e)}
          className="w-full flex items-center justify-between px-5 py-4"
        >
          <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-300 flex items-center gap-2">
            <ExternalLink size={16} className="text-orange-500" />
            Posiciones externas sin gestión
            <span className="bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 text-xs px-2 py-0.5 rounded-full">
              {loading ? '…' : positions.length}
            </span>
          </h3>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={e => { e.stopPropagation(); load() }}
              className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-gray-300 flex items-center gap-1"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Actualizar
            </button>
            {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
          </div>
        </button>

        {expanded && (
          <div className="px-5 pb-5 space-y-3">
            <p className="text-xs text-slate-500 dark:text-gray-400">
              Abiertas directamente en BingX. Adoptarlas activa SL automático, TPs parciales, trailing y breakeven.
            </p>

            {positions.map((p, i) => (
              <div
                key={i}
                className="flex items-center justify-between bg-slate-50 dark:bg-gray-800 rounded-lg p-3"
              >
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                    p.side === 'long'
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                      : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                  }`}>
                    {p.side.toUpperCase()}
                  </span>
                  <div>
                    <p className="text-sm font-mono font-semibold text-slate-900 dark:text-white">{p.symbol}</p>
                    <p className="text-xs text-slate-500 dark:text-gray-400">
                      ${p.entry_price.toFixed(4)} · {p.quantity} · {p.account_label}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-sm font-mono font-semibold ${
                    p.unrealized_pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl.toFixed(2)}
                  </span>
                  <button
                    onClick={() => setAdoptTarget(p)}
                    className="flex items-center gap-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors"
                  >
                    <ShieldCheck size={13} /> Adoptar
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

// ─────────────────────────────────────────────────────────────

export default function PositionsPage() {
  const { positions, loading, refresh, counts } = useUnifiedPositions()
  const prices = usePositionStore(s => s.prices)
  const priceChanges = usePositionStore(s => s.priceChanges)
  const [selectedPosition, setSelectedPosition] = useState(null)
  const [isChartOpen, setIsChartOpen] = useState(false)
  const [isManualModalOpen, setIsManualModalOpen] = useState(false)
  const [isLimitModalOpen, setIsLimitModalOpen] = useState(false)
  const [closingPosition, setClosingPosition] = useState(false)
  const [closePercentage, setClosePercentage] = useState(100)
  const [filter, setFilter] = useState('all')
  const [syncingId, setSyncingId] = useState(null)
  const [syncingAll, setSyncingAll] = useState(false)
  
  // Sincronizar TODAS las posiciones
  const handleSyncAll = async () => {
    const positionsToSync = positions.filter(p => p.id && p.status !== 'pending_limit')
    if (positionsToSync.length === 0) {
      alert('No hay posiciones para sincronizar')
      return
    }
    
    setSyncingAll(true)
    let closed = 0
    let open = 0
    let errors = 0
    
    for (const pos of positionsToSync) {
      try {
        const { data } = await positionsService.syncStatus(pos.id)
        if (data.status === 'closed') closed++
        else if (data.status === 'open') open++
      } catch (e) {
        errors++
      }
    }
    
    setSyncingAll(false)
    refresh()
    
    let msg = `Sincronización completada:`
    if (closed > 0) msg += `\n✓ ${closed} posiciones cerradas`
    if (open > 0) msg += `\n• ${open} posiciones siguen abiertas`
    if (errors > 0) msg += `\n✗ ${errors} errores`
    alert(msg)
  }
  
  // Usar account_id de la posición seleccionada (viene del backend en unified positions)
  const selectedAccountId = selectedPosition?.account_id

  // Filtrar posiciones según el filtro seleccionado
  const filteredPositions = filter === 'all'
    ? positions
    : filter === 'pending_limit'
      ? positions.filter(p => p.status === 'pending_limit')
      : positions.filter(p => p.source === filter && p.status !== 'pending_limit')
  
  // Abrir posición (gráfico o modal según tipo)
  const handleOpenPosition = (pos) => {
    setSelectedPosition(pos)
    
    if (pos.status === 'pending_limit') {
      // Orden limit pendiente - modal para cancelar
      setIsLimitModalOpen(true)
    } else if (pos.source === 'manual') {
      // BingX manual externo
      setIsManualModalOpen(true)
    } else if (pos.id) {
      // Bot, App Manual, Paper - gráfico
      setIsChartOpen(true)
    }
  }
  
  // Cancelar orden limit pendiente
  const handleCancelLimit = async (pos) => {
    if (!window.confirm(`¿Cancelar orden limit ${pos.side.toUpperCase()} ${pos.symbol}?`)) return
    try {
      if (pos.id) {
        // Orden registrada en DB
        await api.delete(`/positions/${pos.id}/cancel-limit`)
      } else {
        // Orden externa (directamente en el exchange, sin registro en DB)
        await api.delete('/positions/external/cancel-limit', {
          params: {
            order_id: pos.exchange_position_id,
            symbol: pos.symbol,
            account_id: pos.account_id,
          }
        })
      }
      refresh()
    } catch (e) {
      alert('Error cancelando: ' + (e.response?.data?.detail || e.message))
    }
  }

  // Sincronizar posición con el exchange (cuando se cierra manualmente en BingX)
  const handleSyncPosition = async (pos) => {
    if (!pos.id) return
    setSyncingId(pos.id)
    try {
      const { data } = await positionsService.syncStatus(pos.id)
      if (data.status === 'closed') {
        alert(`✓ ${pos.symbol}: Posición sincronizada - marcada como cerrada`)
        refresh()
      } else if (data.status === 'open') {
        alert(`${pos.symbol}: La posición sigue abierta en el exchange`)
      } else {
        alert(data.message)
      }
    } catch (e) {
      alert('Error sincronizando: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSyncingId(null)
    }
  }

  // Cerrar posición manual de BingX
  const handleCloseManual = async () => {
    if (!selectedPosition || !selectedAccountId) return
    
    setClosingPosition(true)
    try {
      const qty = closePercentage === 100 
        ? selectedPosition.quantity 
        : (selectedPosition.quantity * closePercentage / 100)
      
      await positionsService.closeExternal({
        symbol: selectedPosition.symbol,
        side: selectedPosition.side,
        quantity: qty,
        exchange_position_id: selectedPosition.exchange_position_id,
        account_id: selectedAccountId,
      })
      
      setIsManualModalOpen(false)
      refresh()
    } catch (e) {
      alert('Error cerrando posición: ' + (e.response?.data?.detail || e.message))
    } finally {
      setClosingPosition(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Posiciones</h1>
          <button
            onClick={handleSyncAll}
            disabled={syncingAll || loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-slate-400 text-white rounded-lg transition-colors"
            title="Sincronizar todas las posiciones con el exchange"
          >
            <RefreshCw size={14} className={syncingAll ? 'animate-spin' : ''} />
            {syncingAll ? 'Sincronizando...' : 'Sincronizar Todo'}
          </button>
        </div>
        
        {/* Contadores */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button 
            onClick={() => setFilter('all')}
            className={`px-3 py-1.5 rounded-lg border transition-colors ${
              filter === 'all' 
                ? 'bg-slate-800 text-white border-slate-800 dark:bg-white dark:text-slate-900 dark:border-white' 
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700 dark:hover:bg-gray-800'
            }`}
          >
            Todas ({counts.total})
          </button>
          <button 
            onClick={() => setFilter('bot')}
            className={`px-3 py-1.5 rounded-lg border transition-colors ${
              filter === 'bot' 
                ? 'bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/50 dark:text-blue-300 dark:border-blue-700' 
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700 dark:hover:bg-gray-800'
            }`}
          >
            <span className="flex items-center gap-1">
              <Bot size={12} /> Bots ({counts.bot})
            </span>
          </button>
          <button 
            onClick={() => setFilter('app_manual')}
            className={`px-3 py-1.5 rounded-lg border transition-colors ${
              filter === 'app_manual' 
                ? 'bg-purple-100 text-purple-700 border-purple-300 dark:bg-purple-900/50 dark:text-purple-300 dark:border-purple-700' 
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700 dark:hover:bg-gray-800'
            }`}
          >
            <span className="flex items-center gap-1">
              <Smartphone size={12} /> App ({counts.app_manual || 0})
            </span>
          </button>
          <button 
            onClick={() => setFilter('paper')}
            className={`px-3 py-1.5 rounded-lg border transition-colors ${
              filter === 'paper' 
                ? 'bg-green-100 text-green-700 border-green-300 dark:bg-green-900/50 dark:text-green-300 dark:border-green-700' 
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700 dark:hover:bg-gray-800'
            }`}
          >
            <span className="flex items-center gap-1">
              <FileText size={12} /> Paper ({counts.paper})
            </span>
          </button>
          <button
            onClick={() => setFilter('manual')}
            className={`px-3 py-1.5 rounded-lg border transition-colors ${
              filter === 'manual'
                ? 'bg-orange-100 text-orange-700 border-orange-300 dark:bg-orange-900/50 dark:text-orange-300 dark:border-orange-700'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700 dark:hover:bg-gray-800'
            }`}
          >
            <span className="flex items-center gap-1">
              <User size={12} /> Manual ({counts.manual})
            </span>
          </button>
          {counts.pending_limit > 0 && (
            <button
              onClick={() => setFilter('pending_limit')}
              className={`px-3 py-1.5 rounded-lg border transition-colors ${
                filter === 'pending_limit'
                  ? 'bg-yellow-100 text-yellow-700 border-yellow-300 dark:bg-yellow-900/50 dark:text-yellow-300 dark:border-yellow-700'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700 dark:hover:bg-gray-800'
              }`}
            >
              <span className="flex items-center gap-1">
                <Clock size={12} /> Limit ({counts.pending_limit})
              </span>
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <p className="text-slate-500 dark:text-gray-400 text-sm">Cargando...</p>
      ) : filteredPositions.length === 0 ? (
        <div className="card text-center py-10">
          <p className="text-slate-500 dark:text-gray-400">
            {filter === 'all' 
              ? 'No hay posiciones abiertas' 
              : `No hay posiciones ${filter === 'bot' ? 'de bots' : filter === 'paper' ? 'de paper trading' : 'manuales'}`
            }
          </p>
          {filter !== 'all' && (
            <button 
              onClick={() => setFilter('all')}
              className="mt-2 text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            >
              Ver todas las posiciones
            </button>
          )}
        </div>
      ) : (
        <>
          {/* Vista móvil: tarjetas */}
          <div className="md:hidden space-y-3">
            {filteredPositions.map((pos, idx) => {
              const price = pos.current_price || prices[pos.symbol]
              const change24h = pos.change_24h || priceChanges[pos.symbol] || 0
              const pnlVal = parseFloat(pos.unrealized_pnl || 0)
              const entry = parseFloat(pos.entry_price)
              const priceDiffPercent = price ? ((price - entry) / entry) * 100 : 0
              const isPriceProfitable = pos.side === 'long' ? priceDiffPercent >= 0 : priceDiffPercent <= 0
              
              // Key única (las posiciones manuales no tienen id)
              const key = pos.id || `${pos.symbol}-${pos.source}-${idx}`

              return (
                <div key={key} className="card space-y-2 cursor-pointer hover:bg-slate-100 dark:hover:bg-gray-800/50 transition-colors" onClick={() => handleOpenPosition(pos)}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 flex-wrap">
                      {pos.side === 'long'
                        ? <TrendingUp size={14} className="text-green-400" />
                        : <TrendingDown size={14} className="text-red-400" />}
                      <span className="font-semibold text-slate-900 dark:text-gray-100">{pos.symbol}</span>
                      <span className={`text-xs font-medium ${pos.side === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                        {pos.side.toUpperCase()}
                      </span>
                      <SourceBadge source={pos.source} />
                    </div>
                    <div className="flex items-center gap-2">
                      {pos.id && (
                        <button className="p-1.5 bg-blue-500/20 text-blue-400 rounded-lg hover:bg-blue-500/30 transition-colors">
                          <BarChart3 size={14} />
                        </button>
                      )}
                      <PnlCell value={pnlVal} />
                    </div>
                  </div>
                  
                  {/* Orden limit pendiente */}
                  {pos.status === 'pending_limit' && (
                    <div className="flex items-center justify-between bg-yellow-50 dark:bg-yellow-900/20 px-2 py-1.5 rounded">
                      <span className="text-xs text-yellow-700 dark:text-yellow-400 flex items-center gap-1">
                        <Clock size={10} /> Limit pendiente @ ${parseFloat(pos.entry_price).toFixed(4)}
                      </span>
                      <button
                        onClick={e => { e.stopPropagation(); handleCancelLimit(pos) }}
                        className="text-xs px-2 py-0.5 rounded bg-yellow-600 hover:bg-yellow-700 text-white"
                      >
                        Cancelar
                      </button>
                    </div>
                  )}

                  {/* Info adicional para posiciones manuales */}
                  {pos.source === 'manual' && pos.status !== 'pending_limit' && (
                    <div className="flex items-center justify-between">
                      <div className="text-xs text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 px-2 py-1 rounded flex items-center gap-1">
                        <ExternalLink size={10} /> Abierta en {pos.exchange} - Click para gestionar
                      </div>
                      <button
                        onClick={e => { e.stopPropagation(); handleSyncPosition(pos) }}
                        disabled={syncingId === pos.id}
                        className="p-1.5 bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400 rounded hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
                        title="Sincronizar con exchange"
                      >
                        <RefreshCw size={12} className={syncingId === pos.id ? 'animate-spin' : ''} />
                      </button>
                    </div>
                  )}
                  
                  {/* Info del bot para posiciones de bot */}
                  {pos.source === 'bot' && pos.bot_name && (
                    <div className="text-xs text-blue-600 dark:text-blue-400">
                      Bot: {pos.bot_name}
                    </div>
                  )}
                  
                  {/* Precio actual con cambio 24h */}
                  {price && (
                    <div className="flex items-center gap-2 text-sm">
                      <span className={`font-mono font-medium ${change24h >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${price.toFixed(2)}
                      </span>
                      <span className={`text-xs ${change24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                        ({change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}% 24h)
                      </span>
                    </div>
                  )}
                  
                  {/* Entrada vs Actual */}
                  {price && (
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-slate-500 dark:text-gray-500">Entrada: {formatPrice(entry)}</span>
                      <ArrowRight size={10} className="text-slate-400 dark:text-gray-600" />
                      <span className={`font-mono ${isPriceProfitable ? 'text-green-400' : 'text-red-400'}`}>
                        {isPriceProfitable ? '+' : ''}{priceDiffPercent.toFixed(2)}%
                      </span>
                    </div>
                  )}
                  
                  <div className="grid grid-cols-2 gap-2 text-xs text-slate-500 dark:text-gray-400">
                    <div>
                      <p className="text-slate-600 dark:text-gray-600">SL</p>
                      <p className="font-mono text-red-400">{pos.current_sl_price ? formatPrice(pos.current_sl_price) : '—'}</p>
                    </div>
                    <div>
                      <p className="text-slate-600 dark:text-gray-600">Qty</p>
                      <p className="font-mono text-slate-900 dark:text-white">{parseFloat(pos.quantity).toFixed(4)}</p>
                    </div>
                  </div>
                  
                  {pos.opened_at && (
                    <p className="text-xs text-slate-500 dark:text-gray-500">
                      {new Date(pos.opened_at).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' })}
                    </p>
                  )}
                </div>
              )
            })}
          </div>

          {/* Vista desktop: tabla */}
          <div className="hidden md:block card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 dark:text-gray-400 border-b border-slate-200 dark:border-gray-800">
                  <th className="pb-3 pr-4">Tipo / Par</th>
                  <th className="pb-3 pr-4">Entrada → Actual</th>
                  <th className="pb-3 pr-4">Cambio 24h</th>
                  <th className="pb-3 pr-4">SL</th>
                  <th className="pb-3 pr-4">Qty</th>
                  <th className="pb-3 pr-4">PnL</th>
                  <th className="pb-3">Info</th>
                </tr>
              </thead>
              <tbody>
                {filteredPositions.map((pos, idx) => {
                  const price = pos.current_price || prices[pos.symbol]
                  const change24h = pos.change_24h || priceChanges[pos.symbol] || 0
                  const pnlVal = parseFloat(pos.unrealized_pnl || 0)
                  const key = pos.id || `${pos.symbol}-${pos.source}-${idx}`
                  
                  const isPendingLimit = pos.status === 'pending_limit'
                  return (
                    <tr key={key} className={`border-b border-slate-200 dark:border-gray-800/50 hover:bg-slate-100 dark:hover:bg-gray-800/30 cursor-pointer ${isPendingLimit ? 'opacity-80' : ''}`} onClick={() => handleOpenPosition(pos)}>
                      <td className="py-3 pr-4">
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center gap-2">
                            {pos.side === 'long'
                              ? <TrendingUp size={14} className={isPendingLimit ? 'text-yellow-400' : 'text-green-400'} />
                              : <TrendingDown size={14} className={isPendingLimit ? 'text-yellow-400' : 'text-red-400'} />}
                            <span className="font-medium text-slate-900 dark:text-gray-100">{pos.symbol}</span>
                            <span className={`text-xs ${pos.side === 'long' ? 'text-green-500' : 'text-red-500'}`}>
                              {pos.side.toUpperCase()}
                            </span>
                          </div>
                          <SourceBadge source={isPendingLimit ? 'pending_limit' : pos.source} />
                        </div>
                      </td>
                      <td className="py-3 pr-4">
                        <PriceComparisonCell 
                          entryPrice={pos.entry_price} 
                          currentPrice={price} 
                          side={pos.side}
                        />
                      </td>
                      <td className="py-3 pr-4">
                        {price ? (
                          <span className={`font-mono text-xs ${change24h >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}%
                          </span>
                        ) : (
                          <span className="text-slate-500 dark:text-gray-500">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 font-mono text-red-400">
                        {pos.current_sl_price ? formatPrice(pos.current_sl_price) : '—'}
                      </td>
                      <td className="py-3 pr-4 font-mono text-slate-900 dark:text-gray-100">
                        {parseFloat(pos.quantity).toFixed(4)}
                      </td>
                      <td className="py-3 pr-4">
                        <PnlCell value={pnlVal} />
                      </td>
                      <td className="py-3">
                        <div className="flex items-center gap-2">
                          {isPendingLimit ? (
                            <span className="text-xs text-yellow-600 dark:text-yellow-400">Esperando...</span>
                          ) : pos.source === 'bot' && pos.bot_name ? (
                            <span className="text-xs text-blue-600 dark:text-blue-400">{pos.bot_name}</span>
                          ) : pos.source === 'manual' ? (
                            <span className="text-xs text-orange-600 dark:text-orange-400">Manual ({pos.exchange})</span>
                          ) : pos.source === 'paper' ? (
                            <span className="text-xs text-green-600 dark:text-green-400">{pos.bot_name || 'Paper'}</span>
                          ) : null}
                          
                          {/* Botón de sincronización para posiciones con ID */}
                          {pos.id && !isPendingLimit && (
                            <button
                              onClick={e => { e.stopPropagation(); handleSyncPosition(pos) }}
                              disabled={syncingId === pos.id}
                              title="Sincronizar con exchange"
                              className="p-1 rounded hover:bg-slate-200 dark:hover:bg-gray-700 text-slate-400 hover:text-slate-600 dark:text-gray-500 dark:hover:text-gray-300 disabled:opacity-50"
                            >
                              <RefreshCw size={12} className={syncingId === pos.id ? 'animate-spin' : ''} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      
      {/* Modal del Gráfico - solo para posiciones con ID (no manuales externas) */}
      {isChartOpen && selectedPosition?.id && (
        <PositionChartModal
          position={selectedPosition}
          isOpen={isChartOpen}
          onClose={() => setIsChartOpen(false)}
          onPositionUpdate={refresh}
        />
      )}
      
      {/* Modal para posiciones manuales de BingX */}
      {isManualModalOpen && selectedPosition && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                {selectedPosition.side === 'long' ? (
                  <TrendingUp size={20} className="text-green-500" />
                ) : (
                  <TrendingDown size={20} className="text-red-500" />
                )}
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                  {selectedPosition.symbol}
                </h3>
                <span className={`text-xs px-2 py-0.5 rounded ${selectedPosition.side === 'long' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                  {selectedPosition.side.toUpperCase()}
                </span>
              </div>
              <button 
                onClick={() => setIsManualModalOpen(false)}
                className="p-1 hover:bg-slate-100 dark:hover:bg-gray-800 rounded"
              >
                <X size={20} />
              </button>
            </div>
            
            <div className="space-y-4">
              <div className="bg-orange-50 dark:bg-orange-900/20 p-3 rounded-lg">
                <p className="text-sm text-orange-700 dark:text-orange-400">
                  <ExternalLink size={14} className="inline mr-1" />
                  Posición abierta en <strong>BingX</strong>
                </p>
                <p className="text-xs text-orange-600/70 dark:text-orange-400/70 mt-1">
                  Puedes cerrarla desde aquí, pero el SL/TP debe gestionarse en BingX
                </p>
              </div>
              
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-slate-500 dark:text-gray-500">Precio Entrada</p>
                  <p className="font-mono text-slate-900 dark:text-white">${parseFloat(selectedPosition.entry_price).toFixed(2)}</p>
                </div>
                <div>
                  <p className="text-slate-500 dark:text-gray-500">Cantidad</p>
                  <p className="font-mono text-slate-900 dark:text-white">{parseFloat(selectedPosition.quantity).toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-slate-500 dark:text-gray-500">PnL</p>
                  <p className={`font-mono ${selectedPosition.unrealized_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    {selectedPosition.unrealized_pnl >= 0 ? '+' : ''}{parseFloat(selectedPosition.unrealized_pnl).toFixed(2)} USDT
                  </p>
                </div>
                <div>
                  <p className="text-slate-500 dark:text-gray-500">Precio Actual</p>
                  <p className="font-mono text-slate-900 dark:text-white">
                    ${prices[selectedPosition.symbol] ? prices[selectedPosition.symbol].toFixed(2) : '—'}
                  </p>
                </div>
              </div>
              
              <div className="border-t border-slate-200 dark:border-gray-700 pt-4">
                <p className="text-sm font-medium text-slate-700 dark:text-gray-300 mb-2">Cerrar posición</p>
                
                <div className="flex items-center gap-2 mb-3">
                  <input
                    type="range"
                    min="10"
                    max="100"
                    step="10"
                    value={closePercentage}
                    onChange={(e) => setClosePercentage(Number(e.target.value))}
                    className="flex-1"
                  />
                  <span className="text-sm font-mono w-12 text-right">{closePercentage}%</span>
                </div>
                
                <div className="flex gap-2">
                  <button
                    onClick={handleCloseManual}
                    disabled={closingPosition || !selectedAccountId}
                    className="flex-1 bg-red-500 hover:bg-red-600 text-white py-2 rounded-lg text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {closingPosition 
                      ? 'Cerrando...' 
                      : `Cerrar ${closePercentage === 100 ? 'Todo' : closePercentage + '%'}`
                    }
                  </button>
                  <button
                    onClick={() => setIsManualModalOpen(false)}
                    className="px-4 py-2 border border-slate-300 dark:border-gray-600 text-slate-700 dark:text-gray-300 rounded-lg text-sm"
                  >
                    Cancelar
                  </button>
                </div>
                
                {!selectedAccountId && (
                  <p className="text-xs text-red-500 mt-2">
                    Error: No se encontró account_id en la posición
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
      
      {/* Modal para órdenes limit pendientes */}
      {isLimitModalOpen && selectedPosition && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Clock size={20} className="text-yellow-500" />
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                  Orden Limit Pendiente
                </h3>
              </div>
              <button 
                onClick={() => setIsLimitModalOpen(false)}
                className="p-1 hover:bg-slate-100 dark:hover:bg-gray-800 rounded"
              >
                <X size={20} />
              </button>
            </div>
            
            <div className="space-y-4">
              <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded-lg">
                <p className="text-sm text-yellow-700 dark:text-yellow-400">
                  <strong>{selectedPosition.symbol}</strong> - {selectedPosition.side.toUpperCase()}
                </p>
                <p className="text-xs text-yellow-600/70 dark:text-yellow-400/70 mt-1">
                  Precio limit: ${parseFloat(selectedPosition.entry_price).toFixed(2)}
                </p>
              </div>
              
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-slate-500 dark:text-gray-500">Cantidad</p>
                  <p className="font-mono text-slate-900 dark:text-white">{parseFloat(selectedPosition.quantity).toFixed(4)}</p>
                </div>
                <div>
                  <p className="text-slate-500 dark:text-gray-500">Precio Mercado</p>
                  <p className="font-mono text-slate-900 dark:text-white">
                    ${prices[selectedPosition.symbol] ? prices[selectedPosition.symbol].toFixed(2) : '—'}
                  </p>
                </div>
              </div>
              
              <div className="border-t border-slate-200 dark:border-gray-700 pt-4">
                <p className="text-sm text-slate-600 dark:text-gray-400 mb-3">
                  La orden se ejecutará automáticamente cuando el precio alcance el nivel establecido.
                </p>
                
                <button
                  onClick={() => handleCancelLimit(selectedPosition)}
                  className="w-full bg-red-500 hover:bg-red-600 text-white py-2 rounded-lg text-sm font-medium"
                >
                  Cancelar Orden
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Posiciones externas de BingX sin gestión */}
      <ExternalPositionsSection onAdopted={refresh} />
    </div>
  )
}
