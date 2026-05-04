import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertCircle, ArrowRight, Shield, ShieldAlert, ShieldCheck, Smartphone, TrendingDown, TrendingUp, User } from 'lucide-react'
import { useUnifiedPositions } from '@/hooks/useUnifiedPositions'
import usePositionStore from '@/store/positionStore'
import useBalanceStore  from '@/store/balanceStore'
import useBotStore      from '@/store/botStore'
import { botsService }  from '@/services/bots'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import BotStatusBadge   from '@/components/Common/BotStatusBadge'
import LoadingSpinner   from '@/components/Common/LoadingSpinner'
import PnlChart         from '@/components/Common/PnlChart'

function StatCard({ label, value, sub, color = 'text-slate-900 dark:text-white', children }) {
  return (
    <div className="card">
      <p className="text-xs text-slate-500 dark:text-gray-400 mb-1">{label}</p>
      <p className={`text-2xl font-bold font-mono ${color}`}>{value}</p>
      {sub && <p className="text-xs text-slate-600 dark:text-gray-500 mt-0.5">{sub}</p>}
      {children}
    </div>
  )
}

// Widget para mostrar estado de cuentas de exchange
function ExchangeAccountsWidget() {
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadAccounts()
  }, [])

  const loadAccounts = async () => {
    try {
      const { data } = await exchangeAccountsService.list()
      setAccounts(data)
    } catch (e) {
      console.error('Error cargando cuentas:', e)
    } finally {
      setLoading(false)
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'healthy':
        return <ShieldCheck size={16} className="text-green-400" />
      case 'error_credentials':
      case 'error_network':
      case 'error_unknown':
        return <ShieldAlert size={16} className="text-red-400" />
      default:
        return <Shield size={16} className="text-slate-400 dark:text-gray-500" />
    }
  }

  const getStatusText = (status) => {
    switch (status) {
      case 'healthy':         return 'OK'
      case 'error_credentials': return 'Credenciales inválidas'
      case 'error_network':   return 'Error de red'
      case 'error_unknown':   return 'Error'
      default:                return 'Sin verificar'
    }
  }

  const healthyCount   = accounts.filter(a => a.last_health_status === 'healthy').length
  const errorCount     = accounts.filter(a => a.last_health_status && a.last_health_status !== 'healthy').length
  const unverifiedCount= accounts.filter(a => !a.last_health_status).length

  if (loading) {
    return (
      <div className="card">
        <h2 className="font-semibold mb-4">Cuentas de Exchange</h2>
        <LoadingSpinner className="mx-auto" />
      </div>
    )
  }

  if (accounts.length === 0) {
    return (
      <div className="card">
        <h2 className="font-semibold mb-4">Cuentas de Exchange</h2>
        <p className="text-sm text-slate-500 dark:text-gray-400">No hay cuentas configuradas</p>
        <Link to="/exchange-accounts" className="text-xs text-blue-500 dark:text-blue-400 hover:underline mt-2 inline-block">
          Configurar cuenta →
        </Link>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold">Cuentas de Exchange</h2>
        <Link to="/exchange-accounts" className="text-xs text-blue-500 dark:text-blue-400 hover:underline">
          Gestionar
        </Link>
      </div>

      {/* Resumen */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        <div className="bg-green-500/10 rounded-lg p-2 text-center">
          <p className="text-lg font-bold text-green-400">{healthyCount}</p>
          <p className="text-xs text-slate-500 dark:text-gray-400">OK</p>
        </div>
        {errorCount > 0 && (
          <div className="bg-red-500/10 rounded-lg p-2 text-center">
            <p className="text-lg font-bold text-red-400">{errorCount}</p>
            <p className="text-xs text-slate-500 dark:text-gray-400">Error</p>
          </div>
        )}
        {unverifiedCount > 0 && (
          <div className="bg-slate-500/10 dark:bg-gray-500/10 rounded-lg p-2 text-center">
            <p className="text-lg font-bold text-slate-400 dark:text-gray-400">{unverifiedCount}</p>
            <p className="text-xs text-slate-500 dark:text-gray-400">Sin verificar</p>
          </div>
        )}
      </div>

      {/* Lista de cuentas */}
      <div className="space-y-2">
        {accounts.map(account => (
          <div
            key={account.id}
            className={`flex items-center justify-between py-2 px-3 rounded-lg ${
              account.last_health_status && account.last_health_status !== 'healthy'
                ? 'bg-red-500/5 border border-red-500/20'
                : 'bg-slate-100/50 dark:bg-gray-800/50'
            }`}
          >
            <div className="flex items-center gap-2">
              {getStatusIcon(account.last_health_status)}
              <div>
                <p className="text-sm font-medium text-slate-900 dark:text-gray-100">{account.label}</p>
                <p className="text-xs text-slate-500 dark:text-gray-500 uppercase">{account.exchange}</p>
              </div>
            </div>
            <div className="text-right">
              <p className={`text-xs ${
                account.last_health_status === 'healthy' ? 'text-green-400' :
                account.last_health_status ? 'text-red-400' : 'text-slate-400 dark:text-gray-500'
              }`}>
                {getStatusText(account.last_health_status)}
              </p>
              {account.last_health_check_at && (
                <p className="text-[10px] text-slate-400 dark:text-gray-600">
                  {new Date(account.last_health_check_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>

      {errorCount > 0 && (
        <div className="mt-4 p-3 bg-red-500/10 rounded-lg">
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle size={16} />
            <span>{errorCount} cuenta(s) con problemas</span>
          </div>
          <p className="text-xs text-slate-500 dark:text-gray-400 mt-1">
            Revisa las credenciales en Configuración → Cuentas de Exchange
          </p>
        </div>
      )}
    </div>
  )
}

// Badge para tipo de posición
function SourceBadge({ source }) {
  const configs = {
    bot:        { icon: Activity,  label: 'Bot',   className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
    app_manual: { icon: Smartphone,label: 'App',   className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
    paper:      { icon: Activity,  label: 'Paper', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
    manual:     { icon: User,      label: 'BingX', className: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400' },
  }
  const config = configs[source] || configs.manual
  const Icon = config.icon
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${config.className}`}>
      <Icon size={10} />
      {config.label}
    </span>
  )
}

function PositionRow({ position }) {
  const prices      = usePositionStore(s => s.prices)
  const priceChanges= usePositionStore(s => s.priceChanges)
  const price       = prices[position.symbol]
  const change24h   = priceChanges[position.symbol] || 0
  const entry       = parseFloat(position.entry_price)
  const pnl         = price
    ? (position.side === 'long' ? (price - entry) : (entry - price)) * parseFloat(position.quantity)
    : parseFloat(position.unrealized_pnl || 0)
  const isPos       = pnl >= 0
  const priceDiffPct= price ? ((price - entry) / entry) * 100 : 0
  const isPriceProfit = position.side === 'long' ? priceDiffPct >= 0 : priceDiffPct <= 0

  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-200 dark:border-gray-800 last:border-0">
      <div className="flex items-center gap-3">
        {position.side === 'long'
          ? <TrendingUp  size={16} className="text-green-400" />
          : <TrendingDown size={16} className="text-red-400" />
        }
        <div>
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-slate-900 dark:text-gray-100">{position.symbol}</p>
            <SourceBadge source={position.source} />
          </div>
          <p className="text-xs text-slate-500 dark:text-gray-400">
            Entrada: <span className="font-mono">{entry.toFixed(2)}</span>
            {position.current_sl_price && (
              <>{' · '}SL: <span className="font-mono text-red-400">{parseFloat(position.current_sl_price).toFixed(2)}</span></>
            )}
          </p>
          {price && (
            <p className="text-xs mt-0.5">
              <span className="text-slate-500 dark:text-gray-500">Actual: </span>
              <span className={`font-mono ${isPriceProfit ? 'text-green-400' : 'text-red-400'}`}>
                {price.toFixed(2)}
              </span>
              <span className="text-slate-400 dark:text-gray-600 mx-1">|</span>
              <span className={`font-mono ${isPriceProfit ? 'text-green-500' : 'text-red-500'}`}>
                {isPriceProfit ? '+' : ''}{priceDiffPct.toFixed(2)}%
              </span>
            </p>
          )}
        </div>
      </div>
      <div className="text-right">
        <p className={`text-sm font-mono font-semibold ${isPos ? 'text-green-400' : 'text-red-400'}`}>
          {isPos ? '+' : ''}{pnl.toFixed(2)} USDT
        </p>
        {price && (
          <p className={`text-xs font-mono ${change24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            {change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}% (24h)
          </p>
        )}
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const { positions, loading, counts } = useUnifiedPositions()
  const totalEquity  = useBalanceStore(s => s.getTotalEquity())
  const [bots, setBots]       = useState([])
  const [accountMap, setAccountMap] = useState({}) // id → label

  const updateBalance = useBalanceStore(s => s.updateBalance)

  useEffect(() => {
    const loadBalances = () => {
      exchangeAccountsService.allBalances().then(r => {
        r.data.accounts.forEach(acc => {
          if (!acc.error) {
            updateBalance(acc.account_id, {
              total_equity:      acc.total_equity,
              available_balance: acc.available_balance,
            })
          }
        })
      }).catch(() => {})
    }

    const loadAccounts = () => {
      exchangeAccountsService.list().then(r => {
        const map = {}
        r.data.forEach(a => { map[a.id] = a.label })
        setAccountMap(map)
      }).catch(() => {})
    }

    botsService.list().then(r => setBots(r.data)).catch(() => {})
    loadAccounts()
    loadBalances()

    // Polling fallback cada 30s (balances) y 60s (accounts health)
    const balanceInterval = setInterval(loadBalances, 30000)
    const accountInterval = setInterval(loadAccounts, 60000)
    return () => {
      clearInterval(balanceInterval)
      clearInterval(accountInterval)
    }
  }, [updateBalance])

  const prices     = usePositionStore(s => s.prices)
  const activeBots = bots.filter(b => b.status === 'active').length
  const pausedBots = bots.filter(b => b.status === 'paused').length

  // PnL no realizado de todas las posiciones abiertas
  const totalPnl = positions.reduce((s, p) => {
    const price = prices[p.symbol]
    const entry = parseFloat(p.entry_price)
    const qty   = parseFloat(p.quantity)
    const pnl   = price
      ? (p.side === 'long' ? (price - entry) : (entry - price)) * qty
      : parseFloat(p.unrealized_pnl || 0)
    return s + pnl
  }, 0)

  // Margen total y %PNL (ROI global)
  const totalMargin = positions.reduce((s, p) => {
    const entry = parseFloat(p.entry_price)
    const qty   = parseFloat(p.quantity)
    const lev   = parseFloat(p.leverage || 1)
    return s + (entry > 0 && qty > 0 ? (entry * qty) / lev : 0)
  }, 0)
  const totalPnlPercent = totalMargin > 0 ? (totalPnl / totalMargin) * 100 : 0

  // Subtext de posiciones
  const posSubParts = []
  if (counts.bot)         posSubParts.push(`${counts.bot} bots`)
  if (counts.app_manual)  posSubParts.push(`${counts.app_manual} app`)
  if (counts.manual)      posSubParts.push(`${counts.manual} BingX`)
  if (counts.pending_limit) posSubParts.push(`${counts.pending_limit} límite`)

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-slate-900 dark:text-white">Dashboard</h1>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Equity — viene directamente del balance de BingX (incluye todo) */}
        <StatCard
          label="Equity total"
          value={`$${totalEquity.toFixed(2)}`}
          sub="USDT · balance BingX"
        />
        <StatCard
          label="PnL no realizado"
          value={`${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}`}
          sub={`USDT · ${totalPnlPercent >= 0 ? '+' : ''}${totalPnlPercent.toFixed(2)}% ROI`}
          color={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <StatCard
          label="Posiciones abiertas"
          value={counts.total}
          sub={posSubParts.join(' · ') || 'ninguna'}
        />
        <StatCard
          label="Bots activos"
          value={activeBots}
          sub={`${pausedBots} pausados · ${bots.length} total`}
        />
      </div>

      {/* Gráfico PnL */}
      <PnlChart />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Posiciones */}
        <div className="lg:col-span-2 card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-slate-900 dark:text-white">Posiciones abiertas</h2>
            <Link to="/positions" className="text-xs text-blue-500 dark:text-blue-400 hover:underline">Ver todas</Link>
          </div>
          {loading ? (
            <LoadingSpinner className="mx-auto" />
          ) : positions.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-gray-400 text-center py-6">No hay posiciones abiertas</p>
          ) : (
            positions.slice(0, 10).map(p => <PositionRow key={p.id || `${p.symbol}-${p.source}`} position={p} />)
          )}
          {positions.length > 10 && (
            <p className="text-center text-xs text-slate-500 dark:text-gray-400 mt-4">
              +{positions.length - 10} más…{' '}
              <Link to="/positions" className="text-blue-500 dark:text-blue-400 hover:underline">Ver todas</Link>
            </p>
          )}
        </div>

        {/* Columna derecha: Cuentas + Bots */}
        <div className="space-y-6">
          <ExchangeAccountsWidget />

          {/* Bots */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-slate-900 dark:text-white">Bots</h2>
              <Link to="/bots" className="text-xs text-blue-500 dark:text-blue-400 hover:underline">Gestionar</Link>
            </div>
            {bots.length === 0 ? (
              <div className="text-center py-6">
                <p className="text-sm text-slate-500 dark:text-gray-400 mb-3">No tienes bots configurados</p>
                <Link to="/bots/new" className="btn-primary text-sm">Crear bot</Link>
              </div>
            ) : (
              bots.slice(0, 6).map(bot => (
                <div key={bot.id} className="flex items-center justify-between py-2.5 border-b border-slate-200 dark:border-gray-800 last:border-0">
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-gray-100">{bot.bot_name}</p>
                    <p className="text-xs text-slate-500 dark:text-gray-400">
                      {bot.symbol}
                      {bot.is_paper_trading
                        ? ' · Paper'
                        : accountMap[bot.exchange_account_id]
                          ? ` · ${accountMap[bot.exchange_account_id]}`
                          : ''}
                    </p>
                  </div>
                  <BotStatusBadge status={bot.status} />
                </div>
              ))
            )}
            {bots.length > 6 && (
              <p className="text-center text-xs text-slate-500 dark:text-gray-400 mt-3">
                +{bots.length - 6} más…{' '}
                <Link to="/bots" className="text-blue-500 dark:text-blue-400 hover:underline">Ver todos</Link>
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
