import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, TrendingUp, TrendingDown, Activity, Bot, Filter, Search, ChevronRight, Sparkles, Zap } from 'lucide-react'
import { optimizerService } from '@/services/optimizer'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

// ─── KPI Card Component ─────────────────────────────────────

function KPICard({ title, value, subtitle, color = 'blue', icon: Icon }) {
  const colors = {
    blue: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 text-blue-700',
    green: 'bg-green-50 dark:bg-green-900/20 border-green-200 text-green-700',
    red: 'bg-red-50 dark:bg-red-900/20 border-red-200 text-red-700',
    yellow: 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 text-yellow-700',
  }
  
  return (
    <div className={`${colors[color]} rounded-xl p-4 border`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium opacity-70">{title}</span>
        {Icon && <Icon size={18} />}
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {subtitle && <div className="text-xs opacity-60 mt-1">{subtitle}</div>}
    </div>
  )
}

// ─── Health Badge Component ─────────────────────────────────

function HealthBadge({ score, level }) {
  if (!score && score !== 0) return <span className="text-xs text-slate-400">—</span>
  
  const configs = {
    excellent: { color: 'bg-green-500', text: 'Excelente' },
    good: { color: 'bg-green-400', text: 'Bueno' },
    fair: { color: 'bg-yellow-400', text: 'Regular' },
    critical: { color: 'bg-red-400', text: 'Crítico' },
  }
  
  const config = configs[level] || configs.fair
  
  return (
    <div className="flex items-center gap-2">
      <div className={`w-2 h-2 rounded-full ${config.color}`} />
      <span className="text-sm font-medium">{score}</span>
      <span className="text-xs text-slate-400">/100</span>
    </div>
  )
}

// ─── Bot Row Component ──────────────────────────────────────

function BotRow({ bot, isSelected, onClick }) {
  const getWinRateTrend = () => {
    if (!bot.win_rate) return null
    if (bot.win_rate >= 0.6) return <TrendingUp size={14} className="text-green-500" />
    if (bot.win_rate < 0.45) return <TrendingDown size={14} className="text-red-400" />
    return <Activity size={14} className="text-yellow-500" />
  }
  
  return (
    <tr 
      onClick={onClick}
      className={`border-b border-slate-100 dark:border-gray-700 hover:bg-slate-50 dark:hover:bg-gray-800/50 cursor-pointer transition-colors ${
        isSelected ? 'bg-blue-50 dark:bg-blue-900/20' : ''
      }`}
    >
      <td className="py-3 px-4">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${bot.auto_enabled ? 'bg-green-500' : 'bg-slate-300'}`} />
          <div>
            <p className="font-medium text-sm">{bot.name}</p>
            <p className="text-xs text-slate-500">{bot.symbol} · {bot.timeframe}</p>
          </div>
        </div>
      </td>
      <td className="py-3 px-4">
        <span className={`text-xs px-2 py-1 rounded-full ${
          bot.auto_enabled 
            ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' 
            : 'bg-slate-100 text-slate-600 dark:bg-gray-700 dark:text-gray-400'
        }`}>
          {bot.auto_enabled ? 'Auto ✅' : 'Manual'}
        </span>
      </td>
      <td className="py-3 px-4">
        <div className="flex items-center gap-2">
          {bot.win_rate ? (
            <>
              <span className="text-sm">{Math.round(bot.win_rate * 100)}%</span>
              {getWinRateTrend()}
            </>
          ) : (
            <span className="text-xs text-slate-400">—</span>
          )}
        </div>
      </td>
      <td className="py-3 px-4">
        {bot.profit_factor ? (
          <span className="text-sm">{bot.profit_factor.toFixed(1)}x</span>
        ) : (
          <span className="text-xs text-slate-400">—</span>
        )}
      </td>
      <td className="py-3 px-4">
        <HealthBadge score={bot.health_score} level={bot.health_level} />
      </td>
      <td className="py-3 px-4">
        {bot.total_changes > 0 ? (
          <div>
            <span className={`text-sm font-mono ${bot.effectiveness >= 0 ? 'text-green-500' : 'text-red-400'}`}>
              {bot.effectiveness >= 0 ? '+' : ''}{bot.effectiveness}
            </span>
            <span className="text-xs text-slate-400 ml-1">pts</span>
          </div>
        ) : (
          <span className="text-xs text-slate-400">Sin datos</span>
        )}
      </td>
      <td className="py-3 px-4">
        {bot.total_changes > 0 ? (
          <span className="text-sm">{bot.success_rate}%</span>
        ) : (
          <span className="text-xs text-slate-400">—</span>
        )}
      </td>
      <td className="py-3 px-4">
        {bot.last_change ? (
          <span className="text-xs text-slate-500">
            {new Date(bot.last_change).toLocaleDateString()}
          </span>
        ) : (
          <span className="text-xs text-slate-400">Nunca</span>
        )}
      </td>
      <td className="py-3 px-4">
        <ChevronRight size={16} className="text-slate-400" />
      </td>
    </tr>
  )
}

// ─── Componente Principal ───────────────────────────────────

export default function OptimizerDBPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedBot, setSelectedBot] = useState(null)
  const [filter, setFilter] = useState({
    autoOnly: false,
    healthLevel: 'all',
    search: '',
  })

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await optimizerService.getGlobalDB()
      setData(res.data)
      // Seleccionar primer bot crítico o el primero de la lista
      const critical = res.data.bots?.find(b => b.health_level === 'critical')
      setSelectedBot(critical || res.data.bots?.[0] || null)
    } catch (e) {
      console.error('Error cargando Optimizer DB:', e)
    } finally {
      setLoading(false)
    }
  }

  const filteredBots = data?.bots?.filter(bot => {
    if (filter.autoOnly && !bot.auto_enabled) return false
    if (filter.healthLevel !== 'all' && bot.health_level !== filter.healthLevel) return false
    if (filter.search && !bot.name.toLowerCase().includes(filter.search.toLowerCase()) && 
        !bot.symbol.toLowerCase().includes(filter.search.toLowerCase())) return false
    return true
  }) || []

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>
  
  if (!data) return (
    <div className="max-w-6xl mx-auto p-6">
      <p className="text-slate-500 text-center py-12">Error cargando datos</p>
    </div>
  )

  const { kpis, alerts } = data

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Zap className="text-blue-500" />
            Optimizer DB
          </h1>
          <p className="text-sm text-slate-500">Centro de control de auto-optimización</p>
        </div>
        
        {alerts.length > 0 && (
          <div className="flex items-center gap-2 px-3 py-2 bg-red-50 dark:bg-red-900/20 rounded-lg">
            <AlertTriangle size={16} className="text-red-500" />
            <span className="text-sm font-medium text-red-700 dark:text-red-400">
              {alerts.length} alerta{alerts.length > 1 ? 's' : ''}
            </span>
          </div>
        )}
      </div>

      {/* KPIs Globales */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KPICard 
          title="Bots Monitoreados" 
          value={kpis.total_bots} 
          subtitle={`${kpis.auto_enabled} con auto`}
          color="blue"
          icon={Bot}
        />
        <KPICard 
          title="Tasa Éxito Global" 
          value={`${kpis.global_success_rate}%`} 
          subtitle={`${kpis.total_changes} cambios`}
          color={kpis.global_success_rate >= 60 ? 'green' : kpis.global_success_rate >= 40 ? 'yellow' : 'red'}
          icon={TrendingUp}
        />
        <KPICard 
          title="Mejora Total" 
          value={`${kpis.total_improvement >= 0 ? '+' : ''}${kpis.total_improvement}`} 
          subtitle="puntos acumulados"
          color={kpis.total_improvement >= 0 ? 'green' : 'red'}
          icon={Activity}
        />
        <KPICard 
          title="Bots Críticos" 
          value={kpis.critical_bots} 
          subtitle="requieren atención"
          color={kpis.critical_bots > 0 ? 'red' : 'green'}
          icon={AlertTriangle}
        />
        <div className="bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl p-4 text-white">
          <div className="text-xs opacity-70 mb-1">Estado del Sistema</div>
          <div className="text-2xl font-bold">
            {kpis.critical_bots === 0 ? '✅ Saludable' : '⚠️ Revisar'}
          </div>
          <div className="text-xs opacity-60 mt-1">
            {kpis.critical_bots === 0 ? 'Todos los bots estables' : `${kpis.critical_bots} bots necesitan ajustes`}
          </div>
        </div>
      </div>

      {/* Alertas */}
      {alerts.length > 0 && (
        <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-red-800 dark:text-red-400 mb-2 flex items-center gap-2">
            <AlertTriangle size={16} /> Alertas Activas
          </h3>
          <div className="space-y-1">
            {alerts.map((alert, i) => (
              <div 
                key={i} 
                onClick={() => navigate(`/bots/${alert.bot_id}/optimizer`)}
                className="text-sm text-red-700 dark:text-red-300 p-2 bg-white dark:bg-gray-800 rounded cursor-pointer hover:bg-red-50 dark:hover:bg-red-900/20"
              >
                {alert.message}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filtros */}
      <div className="flex flex-wrap gap-3 bg-white dark:bg-gray-800 rounded-xl p-3 border border-slate-200">
        <div className="flex items-center gap-2">
          <Filter size={16} className="text-slate-400" />
          <span className="text-sm font-medium">Filtros:</span>
        </div>
        
        <label className="flex items-center gap-2 text-sm">
          <input 
            type="checkbox" 
            checked={filter.autoOnly}
            onChange={(e) => setFilter({...filter, autoOnly: e.target.checked})}
            className="rounded"
          />
          Solo auto-optimizador
        </label>
        
        <select 
          value={filter.healthLevel}
          onChange={(e) => setFilter({...filter, healthLevel: e.target.value})}
          className="text-sm px-2 py-1 rounded border border-slate-200"
        >
          <option value="all">Todos estados</option>
          <option value="critical">🔴 Crítico</option>
          <option value="fair">🟡 Regular</option>
          <option value="good">🟢 Bueno</option>
          <option value="excellent">⭐ Excelente</option>
        </select>
        
        <div className="flex-1 min-w-[200px]">
          <div className="relative">
            <Search size={16} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Buscar bot o símbolo..."
              value={filter.search}
              onChange={(e) => setFilter({...filter, search: e.target.value})}
              className="w-full text-sm pl-8 pr-3 py-1 rounded border border-slate-200"
            />
          </div>
        </div>
      </div>

      {/* Tabla de Bots */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50 dark:bg-gray-700/50">
              <tr className="text-left text-xs font-medium text-slate-500">
                <th className="py-2 px-4">Bot / Símbolo</th>
                <th className="py-2 px-4">Estado</th>
                <th className="py-2 px-4">Win Rate</th>
                <th className="py-2 px-4">PF</th>
                <th className="py-2 px-4">Salud</th>
                <th className="py-2 px-4">Efectividad</th>
                <th className="py-2 px-4">Tasa Éxito</th>
                <th className="py-2 px-4">Último</th>
                <th className="py-2 px-4"></th>
              </tr>
            </thead>
            <tbody>
              {filteredBots.map(bot => (
                <BotRow 
                  key={bot.id} 
                  bot={bot} 
                  isSelected={selectedBot?.id === bot.id}
                  onClick={() => setSelectedBot(bot)}
                />
              ))}
              {filteredBots.length === 0 && (
                <tr>
                  <td colSpan="9" className="py-8 text-center text-slate-400">
                    No hay bots que coincidan con los filtros
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Panel de Detalle */}
      {selectedBot && (
        <div className="bg-gradient-to-br from-slate-50 to-blue-50 dark:from-gray-800 dark:to-gray-700/50 rounded-xl p-6 border border-slate-200">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Sparkles className="text-blue-500" />
                Dashboard: {selectedBot.name}
              </h3>
              <p className="text-sm text-slate-500">{selectedBot.symbol} · {selectedBot.timeframe}</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => navigate(`/bots/${selectedBot.id}/optimizer`)}
                className="text-sm px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg"
              >
                Ver Optimizador
              </button>
              <button
                onClick={() => navigate(`/bots/${selectedBot.id}/effectiveness`)}
                className="text-sm px-4 py-2 bg-slate-200 hover:bg-slate-300 dark:bg-gray-700 dark:hover:bg-gray-600 rounded-lg"
              >
                Dashboard Completo
              </button>
            </div>
          </div>
          
          {/* Resumen rápido del bot seleccionado */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-slate-500">Trades</p>
              <p className="text-lg font-bold">{selectedBot.trade_count}</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-slate-500">Cambios Auto</p>
              <p className="text-lg font-bold">{selectedBot.total_changes}</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-slate-500">Win Rate</p>
              <p className="text-lg font-bold">
                {selectedBot.win_rate ? `${Math.round(selectedBot.win_rate * 100)}%` : '—'}
              </p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-slate-500">Profit Factor</p>
              <p className="text-lg font-bold">
                {selectedBot.profit_factor ? `${selectedBot.profit_factor.toFixed(1)}x` : '—'}
              </p>
            </div>
          </div>
          
          {/* Último cambio */}
          {selectedBot.last_change_summary && (
            <div className="mt-4 p-3 bg-white dark:bg-gray-800 rounded-lg">
              <p className="text-xs text-slate-500 mb-1">Último cambio aplicado:</p>
              <div className="font-mono text-sm">
                {Object.entries(selectedBot.last_change_summary).map(([k, v]) => (
                  <span key={k} className="mr-3">
                    {k.replace(/_/g, ' ')}: {typeof v === 'object' ? JSON.stringify(v) : v}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
