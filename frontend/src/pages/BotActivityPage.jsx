import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { botsService } from '@/services/bots'
import api from '@/services/api'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import BotChart from '@/components/Common/BotChart'

const EVENT_COLORS = {
  order_opened:          'text-green-400',
  order_closed:          'text-blue-400',
  sl_moved:              'text-yellow-400',
  tp_hit:                'text-green-300',
  breakeven_activated:   'text-cyan-400',
  trailing_activated:    'text-cyan-400',
  conflict_rejected:     'text-orange-400',
  error:                 'text-red-400',
  signal_received:       'text-slate-400 dark:text-gray-400',
}

function LogRow({ log }) {
  const color = EVENT_COLORS[log.event_type] ?? 'text-slate-400 dark:text-gray-400'
  return (
    <tr className="border-b border-slate-200 dark:border-gray-800/50 hover:bg-slate-100 dark:hover:bg-gray-800/40">
      <td className="py-2 pr-4 text-xs text-slate-500 dark:text-gray-500 font-mono whitespace-nowrap">
        {new Date(log.created_at).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'medium' })}
      </td>
      <td className="py-2 pr-4">
        <span className={`text-xs font-medium ${color}`}>{log.event_type}</span>
      </td>
      <td className="py-2 text-sm text-slate-700 dark:text-gray-300">{log.message}</td>
    </tr>
  )
}

function SignalRow({ sig }) {
  const ok = sig.processed
  return (
    <tr className="border-b border-slate-200 dark:border-gray-800/50 hover:bg-slate-100 dark:hover:bg-gray-800/40">
      <td className="py-2 pr-4 text-xs text-slate-500 dark:text-gray-500 font-mono whitespace-nowrap">
        {new Date(sig.received_at).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'medium' })}
      </td>
      <td className="py-2 pr-4 text-xs font-mono text-blue-500 dark:text-blue-300">{sig.signal_action}</td>
      <td className="py-2 pr-4 text-xs font-mono text-slate-500 dark:text-gray-400">
        {sig.raw_payload?.price ? parseFloat(sig.raw_payload.price).toFixed(2) : '—'}
      </td>
      <td className="py-2 pr-4">
        <span className={`text-xs font-medium ${ok ? 'text-green-400' : sig.error_message ? 'text-red-400' : 'text-yellow-400'}`}>
          {ok ? 'procesada' : sig.error_message ? 'error' : 'pendiente'}
        </span>
      </td>
      <td className="py-2 text-xs text-slate-500 dark:text-gray-400 max-w-xs truncate">{sig.error_message || '—'}</td>
    </tr>
  )
}

export default function BotActivityPage() {
  const { botId } = useParams()
  const [bot, setBot]           = useState(null)
  const [logs, setLogs]         = useState([])
  const [signals, setSignals]   = useState([])
  const [candles, setCandles]           = useState([])
  const [candlesError, setCandlesError] = useState(null)
  const [timeframe, setTimeframe]       = useState('1h')
  const [position, setPosition]         = useState(null)
  const [activeTab, setTab]             = useState('chart')
  const [loading, setLoading]           = useState(true)
  const [refreshing, setRefreshing]     = useState(false)

  const fetchData = async () => {
    const [botRes, logsRes, sigRes, posRes] = await Promise.all([
      botsService.get(botId),
      api.get(`/bots/${botId}/logs?limit=100`),
      api.get(`/bots/${botId}/signals?limit=100`),
      api.get(`/positions?status=open&bot_id=${botId}`),
    ])
    setBot(botRes.data)
    setLogs(logsRes.data)
    setSignals(sigRes.data)
    setPosition(posRes.data?.[0] ?? null)
  }

  const fetchCandles = async (tf = timeframe) => {
    setCandlesError(null)
    try {
      const res = await api.get(`/bots/${botId}/candles?limit=200&timeframe=${tf}`)
      setCandles(res.data)
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Error desconocido'
      setCandlesError(msg)
    }
  }

  useEffect(() => {
    fetchData().catch(() => {}).finally(() => setLoading(false))
    fetchCandles()
  }, [botId])

  useEffect(() => {
    if (activeTab === 'chart') fetchCandles()
  }, [activeTab])

  // Reload candles when timeframe changes
  useEffect(() => {
    if (activeTab === 'chart') fetchCandles(timeframe)
  }, [timeframe])

  const refresh = () => {
    setRefreshing(true)
    Promise.all([fetchData(), fetchCandles()]).catch(() => {}).finally(() => setRefreshing(false))
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
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">{bot?.bot_name ?? 'Bot'}</h1>
          <p className="text-xs text-slate-500 dark:text-gray-400">{bot?.symbol} · Actividad</p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="btn-ghost ml-auto p-2"
          title="Actualizar"
        >
          <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-0 border-b border-slate-200 dark:border-gray-800">
        {[
          ['chart',   'Gráfico'],
          ['logs',    `Logs (${logs.length})`],
          ['signals', `Señales (${signals.length})`],
        ].map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              activeTab === key
                ? 'border-blue-500 text-slate-900 dark:text-white'
                : 'border-transparent text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-300'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Chart */}
      {activeTab === 'chart' && (
        <div className="card p-0 overflow-hidden">
          {/* Timeframe selector */}
          <div className="flex items-center gap-1 px-3 py-2 border-b border-slate-200 dark:border-gray-800">
            {[['15m','15m'],['1h','1h'],['4h','4h'],['1d','1D'],['1w','1S']].map(([tf, label]) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 text-xs rounded transition-colors ${
                  timeframe === tf
                    ? 'bg-blue-600 text-white'
                    : 'text-slate-500 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-gray-800'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Position summary bar */}
          {position && (
            <div className="flex flex-wrap gap-4 px-4 py-3 border-b border-slate-200 dark:border-gray-800 text-xs">
              <span className={`font-semibold ${position.side === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                {position.side.toUpperCase()}
              </span>
              <span className="text-slate-500 dark:text-gray-400">Entrada <span className="text-slate-900 dark:text-white font-mono">{parseFloat(position.entry_price).toFixed(4)}</span></span>
              <span className="text-slate-500 dark:text-gray-400">SL <span className="text-red-400 font-mono">{parseFloat(position.current_sl_price).toFixed(4)}</span></span>
              {(position.current_tp_prices ?? []).filter(t => !t.hit).map(t => (
                <span key={t.level} className="text-slate-500 dark:text-gray-400">
                  TP{t.level} <span className="text-green-400 font-mono">{parseFloat(t.price).toFixed(4)}</span>
                  <span className="text-slate-400 dark:text-gray-600 ml-1">({t.close_percent}%)</span>
                </span>
              ))}
              <span className="text-slate-500 dark:text-gray-400">Qty <span className="text-slate-900 dark:text-white font-mono">{position.quantity}</span></span>
              <span className="text-slate-500 dark:text-gray-400">x<span className="text-slate-900 dark:text-white font-mono">{position.leverage}</span></span>
            </div>
          )}
          {candlesError ? (
            <div className="flex flex-col items-center justify-center py-16 gap-2 text-center px-6">
              <p className="text-sm text-red-400 font-medium">No se pudieron cargar las velas</p>
              <p className="text-xs text-slate-500 dark:text-gray-400 font-mono break-all">{candlesError}</p>
              <button onClick={fetchCandles} className="btn-ghost text-xs mt-2 px-3 py-1 border border-slate-200 dark:border-gray-700 rounded">
                Reintentar
              </button>
            </div>
          ) : candles.length === 0 ? (
            <div className="flex items-center justify-center py-20 text-slate-500 dark:text-gray-400 text-sm">
              Cargando velas…
            </div>
          ) : (
            <BotChart candles={candles} position={position} height={420} />
          )}
        </div>
      )}

      {/* Logs */}
      {activeTab === 'logs' && (
        <div className="card overflow-x-auto">
          {logs.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-gray-400 text-center py-8">Sin registros</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 dark:text-gray-400 text-xs border-b border-slate-200 dark:border-gray-800">
                  <th className="pb-2 pr-4">Fecha</th>
                  <th className="pb-2 pr-4">Evento</th>
                  <th className="pb-2">Mensaje</th>
                </tr>
              </thead>
              <tbody>
                {logs.map(log => <LogRow key={log.id} log={log} />)}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Signals */}
      {activeTab === 'signals' && (
        <div className="card overflow-x-auto">
          {signals.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-gray-400 text-center py-8">Sin señales recibidas</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 dark:text-gray-400 text-xs border-b border-slate-200 dark:border-gray-800">
                  <th className="pb-2 pr-4">Fecha</th>
                  <th className="pb-2 pr-4">Acción</th>
                  <th className="pb-2 pr-4">Precio</th>
                  <th className="pb-2 pr-4">Estado</th>
                  <th className="pb-2">Error</th>
                </tr>
              </thead>
              <tbody>
                {signals.map(sig => <SignalRow key={sig.id} sig={sig} />)}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
