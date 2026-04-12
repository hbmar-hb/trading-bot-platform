import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Edit, Plus, Trash2, TrendingUp, TrendingDown } from 'lucide-react'
import { useBots } from '@/hooks/useBotConfig'
import usePositionStore from '@/store/positionStore'
import BotStatusBadge from '@/components/Common/BotStatusBadge'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

// Componente para mostrar precio con cambio porcentual y colores
function PriceDisplay({ symbol, prices, priceChanges }) {
  const price = prices[symbol]
  const change = priceChanges[symbol] || 0
  const isPositive = change >= 0
  
  if (!price) {
    return (
      <div className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 dark:bg-gray-800/50 rounded-lg shrink-0">
        <span className="text-sm font-medium text-slate-400 dark:text-gray-500">—</span>
      </div>
    )
  }
  
  return (
    <div className="flex flex-col items-end px-3 py-1.5 bg-slate-100 dark:bg-gray-800/50 rounded-lg shrink-0 min-w-[120px]">
      <div className="flex items-center gap-1.5">
        {isPositive 
          ? <TrendingUp size={14} className="text-green-400" />
          : <TrendingDown size={14} className="text-red-400" />
        }
        <span className={`text-sm font-medium ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
          ${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
        </span>
      </div>
      <span className={`text-xs font-mono ${isPositive ? 'text-green-500' : 'text-red-500'}`}>
        {isPositive ? '+' : ''}{change.toFixed(2)}% (24h)
      </span>
    </div>
  )
}

export default function BotsListPage() {
  const { bots, loading, toggleStatus, deleteBot } = useBots()
  const { prices, priceChanges } = usePositionStore()
  const [deleting, setDeleting] = useState(null)
  const [toggling, setToggling] = useState(null)

  const handleToggle = async (bot) => {
    setToggling(bot.id)
    try { await toggleStatus(bot) }
    catch (e) { alert(e.response?.data?.detail || 'Error al cambiar estado') }
    finally { setToggling(null) }
  }

  const handleDelete = async (bot) => {
    if (!confirm(`¿Eliminar bot "${bot.bot_name}"?`)) return
    setDeleting(bot.id)
    try { await deleteBot(bot.id) }
    catch (e) { alert(e.response?.data?.detail || 'Error al eliminar') }
    finally { setDeleting(null) }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Bots</h1>
        <Link to="/bots/new" className="btn-primary flex items-center gap-2 text-sm">
          <Plus size={16} /> Nuevo bot
        </Link>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      ) : bots.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-slate-500 dark:text-gray-400 mb-4">No tienes bots configurados</p>
          <Link to="/bots/new" className="btn-primary text-sm">Crear primer bot</Link>
        </div>
      ) : (
        <div className="space-y-3">
          {bots.map(bot => (
            <div key={bot.id} className={`card flex items-center justify-between gap-4 ${bot.is_paper_trading ? 'border-l-4 border-l-purple-500' : ''}`}>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-slate-900 dark:text-gray-100">{bot.bot_name}</span>
                  <BotStatusBadge status={bot.status} />
                  {bot.is_paper_trading && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400 border border-purple-500/30">
                      📄 PAPER
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 dark:text-gray-400">
                  {bot.symbol} · x{bot.leverage} · SL {bot.initial_sl_percentage}% ·{' '}
                  {bot.position_sizing_type === 'percentage'
                    ? `${bot.position_value}% equity`
                    : `$${bot.position_value} fijo`}
                  {bot.account_display && (
                    <span className="ml-1">· {bot.account_display}</span>
                  )}
                </p>
              </div>

              {/* Precio en tiempo real con cambio % */}
              <PriceDisplay 
                symbol={bot.symbol} 
                prices={prices} 
                priceChanges={priceChanges} 
              />

              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => handleToggle(bot)}
                  disabled={toggling === bot.id || bot.status === 'disabled'}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-40 ${
                    bot.status === 'active'
                      ? 'border-yellow-500/40 text-yellow-500 dark:text-yellow-400 hover:bg-yellow-500/10'
                      : 'border-green-500/40 text-green-500 dark:text-green-400 hover:bg-green-500/10'
                  }`}
                >
                  {toggling === bot.id ? '...' : bot.status === 'active' ? 'Pausar' : 'Activar'}
                </button>

                <Link to={`/bots/${bot.id}/activity`} className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white rounded">
                  <Activity size={16} />
                </Link>
                <Link to={`/bots/${bot.id}/edit`} className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white rounded">
                  <Edit size={16} />
                </Link>
                <button
                  onClick={() => handleDelete(bot)}
                  disabled={deleting === bot.id || bot.status === 'active'}
                  className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-red-400 disabled:opacity-30 rounded"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
