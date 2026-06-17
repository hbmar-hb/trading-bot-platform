import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Brain, Edit, Plus, Sparkles, Trash2, TrendingUp, TrendingDown } from 'lucide-react'
import { useBots } from '@/hooks/useBotConfig'
import usePositionStore from '@/store/positionStore'
import BotStatusBadge from '@/components/Common/BotStatusBadge'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

const AI_WL_KEY = 'ai_watchlist_v2'

function loadAiWatchlistSymbols() {
  try {
    const raw = localStorage.getItem(AI_WL_KEY)
    if (!raw) return new Set()
    return new Set(JSON.parse(raw).map(e => e.symbol))
  } catch {
    return new Set()
  }
}

// "XRP/USDT:USDT" → "XRPUSDT"
function normalizeSymbol(sym) {
  return sym
    .replace(/\/([^:]+):[^:]+$/, '$1')
    .replace('/', '')
}

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

  const aiWatchlistSymbols = useMemo(() => loadAiWatchlistSymbols(), [])

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
          {bots.map(bot => {
            const normalizedBotSym = normalizeSymbol(bot.symbol)
            const inAiWatchlist    = aiWatchlistSymbols.has(normalizedBotSym)
            const isAiMode         = bot.ai_signal_mode

            return (
              <div key={bot.id} className={`card flex items-center justify-between gap-4 ${bot.is_paper_trading ? 'border-l-4 border-l-purple-500' : ''}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="font-medium text-slate-900 dark:text-gray-100">{bot.bot_name}</span>
                    <BotStatusBadge status={bot.status} />
                    <button
                      onClick={() => { navigator.clipboard.writeText(bot.id); alert('UUID copiado: ' + bot.id) }}
                      title={`UUID: ${bot.id} (click para copiar)`}
                      className="text-[9px] font-mono text-slate-400 dark:text-gray-500 bg-slate-100 dark:bg-gray-800 px-1.5 py-0.5 rounded hover:text-slate-600 dark:hover:text-gray-300 cursor-pointer"
                    >
                      {bot.id.slice(0, 8)}...
                    </button>
                    {bot.is_paper_trading && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400 border border-purple-500/30">
                        📄 PAPER
                      </span>
                    )}
                    {bot.alerts_only && (
                      <span
                        title="Bot solo alertas — no ejecuta trades"
                        className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400"
                      >
                        📣 ALERT
                      </span>
                    )}
                    {isAiMode && (
                      <span
                        title="Modo señal IA activo — el bot opera cuando el scanner detecta una señal"
                        className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400"
                      >
                        <Brain size={10} />IA
                      </span>
                    )}
                    {bot.ai_optimal_config_enabled && (
                      <span
                        title="Configuración óptima automática activa — el bot se auto-ajusta según estadísticas históricas"
                        className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400"
                      >
                        <Sparkles size={10} />AUTO
                      </span>
                    )}
                    {bot.montecarlo_config?.strategy_id && (
                      <span
                        title={
                          bot.montecarlo_config?.enabled && bot.montecarlo_config?.mode === 'setup_base'
                            ? `🤖 Setup Base MC+IA activo — Joint Score: ${bot.montecarlo_config?.setup_cache?.context?.mc_validation?.score || 'N/A'} | Bias: ${bot.montecarlo_config?.setup_cache?.context?.direction_bias || 'N/A'} | Confianza: ${bot.montecarlo_config?.setup_cache?.context?.confidence_tier || 'N/A'}`
                            : `Estrategia MC: ${bot.montecarlo_config.strategy_id}`
                        }
                        className={`flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          bot.montecarlo_config?.enabled && bot.montecarlo_config?.mode === 'setup_base'
                            ? 'bg-gradient-to-r from-amber-100 to-purple-100 text-purple-700 dark:from-amber-500/20 dark:to-purple-500/20 dark:text-purple-300'
                            : 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400'
                        }`}
                      >
                        {bot.montecarlo_config?.enabled && bot.montecarlo_config?.mode === 'setup_base' ? '📊🤖 MC+IA' : '📊 MC'}
                      </span>
                    )}
                    {inAiWatchlist && !isAiMode && !bot.alerts_only && (
                      <span
                        title="Este símbolo está en el scanner IA"
                        className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-400"
                      >
                        <Brain size={10} />Scanner
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
                  {bot.montecarlo_config?.strategy_id && (
                    <p className="text-[10px] text-amber-600 dark:text-amber-400 mt-0.5">
                      📊 MC: {bot.montecarlo_config.strategy_symbol || bot.symbol} · {bot.montecarlo_config.strategy_timeframe || bot.timeframe}
                      {bot.montecarlo_config?.setup_cache?.context?.direction_bias && (
                        <span className="ml-1">
                          · Bias {bot.montecarlo_config.setup_cache.context.direction_bias}
                          · {bot.montecarlo_config.setup_cache.context.confidence_tier} conf
                        </span>
                      )}
                    </p>
                  )}
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
                    disabled={toggling === bot.id || bot.status === 'disabled' || (isAiMode && !inAiWatchlist && bot.status !== 'active')}
                    title={isAiMode && !inAiWatchlist && bot.status !== 'active' ? `${bot.symbol} no está en el scanner IA` : undefined}
                    className={`text-xs px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-40 ${
                      bot.status === 'active'
                        ? 'border-yellow-500/40 text-yellow-500 dark:text-yellow-400 hover:bg-yellow-500/10'
                        : 'border-green-500/40 text-green-500 dark:text-green-400 hover:bg-green-500/10'
                    }`}
                  >
                    {toggling === bot.id ? '...' : bot.status === 'active' ? 'Pausar' : 'Activar'}
                  </button>

                  <Link to={`/bots/${bot.id}/activity`} className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white rounded" title="Actividad">
                    <Activity size={16} />
                  </Link>
                  <Link to={`/bots/${bot.id}/optimizer`} className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-blue-400 rounded" title="Optimizador">
                    <Sparkles size={16} />
                  </Link>
                  <Link to={`/bots/${bot.id}/edit`} className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white rounded" title="Editar">
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
            )
          })}
        </div>
      )}
    </div>
  )
}
