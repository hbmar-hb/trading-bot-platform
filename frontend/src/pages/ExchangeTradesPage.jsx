import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, RefreshCw, TrendingUp, TrendingDown, Bot, User, Filter, Upload } from 'lucide-react'
import { exchangeTradesService } from '@/services/exchangeTrades'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

const SOURCE_OPTIONS = [
  { value: '', label: 'Todos' },
  { value: 'bot', label: '🤖 Solo Bot', color: 'text-blue-400' },
  { value: 'manual', label: '👤 Solo Manuales', color: 'text-orange-400' },
]

function StatsCard({ title, stats, icon: Icon, color }) {
  if (!stats || typeof stats !== 'object') return null
  
  const total_pnl = stats.total_pnl ?? 0
  const count = stats.count ?? 0
  const win_rate = stats.win_rate ?? 0
  const winners = stats.winners ?? 0
  const losers = stats.losers ?? 0
  
  const isPositive = total_pnl >= 0
  
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 mb-3">
        <Icon size={18} className={color} />
        <h3 className="font-medium text-sm text-slate-700 dark:text-gray-300">{title}</h3>
      </div>
      
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-slate-500 dark:text-gray-400">Trades</p>
          <p className="text-xl font-bold text-slate-900 dark:text-white">{count}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500 dark:text-gray-400">PnL Total</p>
          <p className={`text-xl font-bold ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}{total_pnl.toFixed(2)} USDT
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500 dark:text-gray-400">Win Rate</p>
          <p className="text-lg font-semibold text-slate-900 dark:text-white">{win_rate}%</p>
        </div>
        <div>
          <p className="text-xs text-slate-500 dark:text-gray-400">Ganados/Perdidos</p>
          <p className="text-sm">
            <span className="text-green-400">{winners}</span>
            <span className="text-slate-500 dark:text-gray-500 mx-1">/</span>
            <span className="text-red-400">{losers}</span>
          </p>
        </div>
      </div>
    </div>
  )
}

function TradeRow({ trade }) {
  const isBot = trade.source === 'bot'
  const pnl = trade.realized_pnl !== null && trade.realized_pnl !== undefined 
    ? parseFloat(trade.realized_pnl) 
    : null
  const isPositive = pnl !== null ? pnl >= 0 : null
  
  // Calcular ROI basado en el margen (asumiendo apalancamiento)
  // ROI = PnL / (Cantidad * Precio / Leverage)
  // Si no tenemos leverage, asumimos 1x (margen = valor total)
  const quantity = parseFloat(trade.quantity || 0)
  const price = parseFloat(trade.exit_price || trade.entry_price || 0)
  const leverage = trade.leverage || 1  // Default 1x si no hay leverage
  const margin = (quantity * price) / leverage
  
  // Calcular ROI
  const roi = (pnl !== null && margin > 0) 
    ? ((pnl / margin) * 100).toFixed(2)
    : null
  
  // Calcular PnL total (realizado + fee)
  const fee = parseFloat(trade.fee || 0)
  const totalPnl = pnl !== null ? pnl - fee : null
  
  return (
    <tr className="border-b border-slate-200 dark:border-gray-800/50 hover:bg-slate-100 dark:hover:bg-gray-800/40">
      <td className="py-3 pr-4">
        <div className="flex items-center gap-2">
          {isBot ? (
            <Bot size={14} className="text-blue-400" title="Bot" />
          ) : (
            <User size={14} className="text-orange-400" title="Manual" />
          )}
          <span className="text-xs text-slate-500 dark:text-gray-500">
            {trade.closed_at ? new Date(trade.closed_at).toLocaleDateString('es-ES', { 
              month: 'short', 
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit'
            }) : '—'}
          </span>
        </div>
      </td>
      <td className="py-3 pr-4 font-mono text-sm text-slate-900 dark:text-gray-100">
        {trade.symbol}
      </td>
      <td className="py-3 pr-4">
        <span className={`text-xs font-medium ${trade.side === 'long' ? 'text-green-400' : 'text-red-400'}`}>
          {trade.side?.toUpperCase()}
        </span>
      </td>
      <td className="py-3 pr-4 text-sm text-slate-500 dark:text-gray-400">
        {quantity > 0 ? quantity.toFixed(4) : '—'}
      </td>
      <td className="py-3 pr-4 text-sm text-slate-500 dark:text-gray-400">
        {price > 0 ? price.toFixed(2) : '—'}
      </td>
      <td className="py-3">
        {totalPnl !== null ? (
          <div className="flex flex-col">
            <div className={`flex items-center gap-1 ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {totalPnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              <span className="font-medium">
                {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)} USDT
              </span>
            </div>
            {roi !== null && (
              <span className={`text-xs ${totalPnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {totalPnl >= 0 ? '+' : ''}{roi}% ROI
              </span>
            )}
            {fee > 0 && (
              <span className="text-xs text-slate-500 dark:text-gray-500">
                Fee: -{fee.toFixed(2)}
              </span>
            )}
          </div>
        ) : (
          <span className="text-xs text-slate-500 dark:text-gray-500">No disponible</span>
        )}
      </td>
    </tr>
  )
}

export default function ExchangeTradesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  
  const [accounts, setAccounts] = useState([])
  const [trades, setTrades] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [importing, setImporting] = useState(false)
  
  // Filtros
  const [selectedAccount, setSelectedAccount] = useState(searchParams.get('account') || '')
  const [selectedSource, setSelectedSource] = useState(searchParams.get('source') || '')
  const [days, setDays] = useState(parseInt(searchParams.get('days') || '30'))

  // Cargar cuentas y trades
  useEffect(() => {
    const loadData = async () => {
      try {
        const [accRes, statsRes] = await Promise.all([
          exchangeAccountsService.list(),
          exchangeTradesService.stats({ days }),
        ])
        // Validar que las respuestas sean arrays/objetos correctos
        setAccounts(Array.isArray(accRes.data) ? accRes.data : [])
        setStats(statsRes.data || null)
        
        await loadTrades()
      } catch (e) {
        console.error('Error cargando datos:', e)
        setAccounts([])
        setStats(null)
      } finally {
        setLoading(false)
      }
    }
    
    loadData()
  }, [])

  const loadTrades = async (overrides = {}) => {
    try {
      const params = {
        days:          overrides.days          ?? days,
        accountId:     overrides.accountId     ?? selectedAccount,
        source:        overrides.source        ?? selectedSource,
      }
      if (!params.accountId) delete params.accountId
      if (!params.source)    delete params.source

      const res = await exchangeTradesService.list(params)
      setTrades(Array.isArray(res.data) ? res.data : [])
    } catch (e) {
      console.error('Error cargando trades:', e)
      setTrades([])
    }
  }

  const loadStats = async (overrides = {}) => {
    try {
      const res = await exchangeTradesService.stats({
        accountId: (overrides.accountId ?? selectedAccount) || undefined,
        days:      overrides.days      ?? days,
      })
      setStats(res.data || null)
    } catch (e) {
      console.error('Error cargando stats:', e)
    }
  }

  const handleSync = async () => {
    if (!selectedAccount) {
      alert('Selecciona una cuenta para sincronizar')
      return
    }
    
    setSyncing(true)
    try {
      const res = await exchangeTradesService.sync(selectedAccount, days)
      const result = res.data
      
      let msg = `Sincronización completada:\n- Trades del exchange: ${result.total_synced}\n- Guardados en BD: ${result.new_trades}`
      if (result.updated_trades > 0) {
        msg += `\n- Reemplazados: ${result.updated_trades}`
      }
      if (result.errors && result.errors.length > 0) {
        msg += `\n- Errores: ${result.errors.length}`
        console.error('Errores de sincronización:', result.errors)
      }
      alert(msg)
      
      await loadTrades()
      
      // Recargar stats
      const statsRes = await exchangeTradesService.stats({ 
        accountId: selectedAccount || undefined, 
        days 
      })
      setStats(statsRes.data)
    } catch (e) {
      console.error('Error completo:', e)
      const errorDetail = e.response?.data?.detail 
        || e.response?.statusText 
        || e.message 
        || 'Error desconocido'
      alert(`Error sincronizando (${e.response?.status || '?'}): ${errorDetail}`)
    } finally {
      setSyncing(false)
    }
  }

  const handleImportCsv = async (event) => {
    const file = event.target.files[0]
    if (!file) return

    if (!selectedAccount) {
      alert('Selecciona una cuenta primero')
      event.target.value = ''
      return
    }

    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await exchangeTradesService.importCsv(selectedAccount, formData)
      const fmt = res.data.format === 'xlsx' ? 'Excel (XLSX)' : 'CSV'
      alert(`Importación completada (${fmt}):\n- Importados: ${res.data.imported}\n- Omitidos: ${res.data.skipped}`)
      await loadTrades()

      const statsRes = await exchangeTradesService.stats({
        accountId: selectedAccount || undefined,
        days,
      })
      setStats(statsRes.data)
    } catch (err) {
      console.error('Error importando:', err)
      let errorMsg = 'Error desconocido'
      if (err.response?.data?.detail) {
        errorMsg = err.response.data.detail
      } else if (err.response?.data) {
        errorMsg = typeof err.response.data === 'string'
          ? err.response.data
          : JSON.stringify(err.response.data, null, 2)
      } else if (err.message) {
        errorMsg = err.message
      }
      alert(`Error importando:\n${errorMsg}`)
    } finally {
      setImporting(false)
      event.target.value = ''
    }
  }

  const handleFilterChange = (key, value) => {
    const newParams = new URLSearchParams(searchParams)
    if (value) newParams.set(key, value)
    else newParams.delete(key)
    setSearchParams(newParams)

    // Calcular nuevos valores directamente para evitar closure stale
    const newAccount = key === 'account' ? value : selectedAccount
    const newSource  = key === 'source'  ? value : selectedSource
    const newDays    = key === 'days'    ? parseInt(value) : days

    if (key === 'account') setSelectedAccount(value)
    if (key === 'source')  setSelectedSource(value)
    if (key === 'days')    setDays(newDays)

    if (!loading) {
      loadTrades({ days: newDays, accountId: newAccount, source: newSource })
      loadStats({ days: newDays, accountId: newAccount })
    }
  }

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/bots" className="text-slate-500 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Historial de Trades</h1>
          <p className="text-xs text-slate-500 dark:text-gray-400">Importados desde el exchange - Bot vs Manual</p>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatsCard 
            title="🤖 Trades del Bot" 
            stats={stats.bot}
            icon={Bot}
            color="text-blue-400"
          />
          <StatsCard 
            title="👤 Trades Manuales" 
            stats={stats.manual}
            icon={User}
            color="text-orange-400"
          />
          <StatsCard 
            title="📊 Total" 
            stats={stats.total}
            icon={Filter}
            color="text-purple-400"
          />
        </div>
      )}

      {/* Filtros */}
      <div className="card p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          {/* Selector de cuenta */}
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-slate-500 dark:text-gray-400 mb-1">Cuenta de Exchange</label>
            <select
              value={selectedAccount}
              onChange={(e) => handleFilterChange('account', e.target.value)}
              className="input w-full"
            >
              <option value="">Todas las cuentas</option>
              {accounts.map(acc => (
                <option key={acc.id} value={acc.id}>
                  {acc.label} ({acc.exchange})
                </option>
              ))}
            </select>
          </div>

          {/* Selector de origen */}
          <div>
            <label className="block text-xs text-slate-500 dark:text-gray-400 mb-1">Origen</label>
            <select
              value={selectedSource}
              onChange={(e) => handleFilterChange('source', e.target.value)}
              className="input"
            >
              {SOURCE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Selector de días */}
          <div>
            <label className="block text-xs text-slate-500 dark:text-gray-400 mb-1">Período</label>
            <select
              value={days}
              onChange={(e) => handleFilterChange('days', e.target.value)}
              className="input"
            >
              <option value="7">7 días</option>
              <option value="30">30 días</option>
              <option value="90">90 días</option>
              <option value="365">1 año</option>
            </select>
          </div>

          {/* Botón sincronizar */}
          <div className="flex items-end">
            <button
              onClick={handleSync}
              disabled={syncing || !selectedAccount}
              className="btn-primary flex items-center gap-2"
            >
              <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
              {syncing ? 'Sincronizando...' : 'Sincronizar'}
            </button>
          </div>

          {/* Botón importar CSV */}
          <div className="flex items-end">
            <label className={`btn-secondary flex items-center gap-2 cursor-pointer ${importing || !selectedAccount ? 'opacity-50 pointer-events-none' : ''}`}>
              <Upload size={14} />
              {importing ? 'Importando...' : 'Importar CSV'}
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={handleImportCsv}
                disabled={importing || !selectedAccount}
                className="hidden"
              />
            </label>
          </div>
        </div>

        {!selectedAccount && (
          <p className="text-xs text-slate-500 dark:text-gray-400">
            💡 Selecciona una cuenta y presiona "Sincronizar" para importar trades desde el exchange
          </p>
        )}
      </div>

      {/* Tabla de trades */}
      <div className="card overflow-x-auto">
        {trades.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-slate-500 dark:text-gray-400 mb-2">No hay trades importados</p>
            <p className="text-sm text-slate-600 dark:text-gray-500">
              {selectedAccount 
                ? 'Presiona "Sincronizar" para importar trades desde el exchange'
                : 'Selecciona una cuenta para sincronizar trades'
              }
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 dark:text-gray-400 text-xs border-b border-slate-200 dark:border-gray-800">
                <th className="pb-3 pr-4">Fecha</th>
                <th className="pb-3 pr-4">Símbolo</th>
                <th className="pb-3 pr-4">Lado</th>
                <th className="pb-3 pr-4">Cantidad</th>
                <th className="pb-3 pr-4">Precio</th>
                <th className="pb-3">PnL</th>
              </tr>
            </thead>
            <tbody>
              {trades.map(trade => <TradeRow key={trade.id} trade={trade} />)}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
