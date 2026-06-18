import { useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, BrainCircuit, CheckCircle2, Filter,
  Flame, Lightbulb, RefreshCw, ScanLine, ShieldX, XCircle, Zap,
} from 'lucide-react'
import { aiService } from '@/services/aiService'
import { useAiLiveStore } from '@/store/aiLiveStore'
import { cn } from '@/utils/cn'

const STATUS_FILTERS = [
  { id: 'ALL', label: 'Todos' },
  { id: 'SIGNAL', label: 'Señales' },
  { id: 'NO_SIGNAL', label: 'Rechazados' },
  { id: 'SCAN_START', label: 'Inicios' },
  { id: 'SCAN_END', label: 'Finales' },
  { id: 'ERROR', label: 'Errores' },
]

function StatusBadge({ status }) {
  const styles = {
    SIGNAL:     'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400',
    NO_SIGNAL:  'bg-slate-100 text-slate-700 dark:bg-slate-700/40 dark:text-slate-400',
    SCAN_START: 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400',
    SCAN_END:   'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-400',
    ERROR:      'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
    REJECTED:   'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400',
  }
  const labels = {
    SIGNAL: 'SEÑAL',
    NO_SIGNAL: 'NO SIGNAL',
    SCAN_START: 'START',
    SCAN_END: 'END',
    ERROR: 'ERROR',
    REJECTED: 'RECHAZADO',
  }
  return (
    <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider', styles[status] || styles.NO_SIGNAL)}>
      {labels[status] || status}
    </span>
  )
}

function TierBadge({ tier }) {
  if (!tier) return null
  const color = {
    STRONG: 'text-emerald-600 dark:text-emerald-400',
    MODERATE: 'text-blue-600 dark:text-blue-400',
    WEAK: 'text-amber-600 dark:text-amber-400',
  }[tier] || 'text-slate-500'
  return <span className={cn('text-[10px] font-semibold uppercase', color)}>{tier}</span>
}

function KpiCard({ label, value, icon: Icon, color }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3 flex items-center gap-3">
      <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', color)}>
        <Icon size={18} />
      </div>
      <div>
        <p className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wide">{label}</p>
        <p className="text-lg font-bold text-slate-800 dark:text-slate-200">{value}</p>
      </div>
    </div>
  )
}

export default function IALiveScannerTab() {
  const { events, latestBySymbol, stats, isLive, setLive, setHistory, reset } = useAiLiveStore()
  const [filter, setFilter] = useState('ALL')
  const [selected, setSelected] = useState(null)
  const [tip, setTip] = useState(null)
  const [loadingTip, setLoadingTip] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)

  const loadHistory = async () => {
    setLoadingHistory(true)
    try {
      const { data } = await aiService.liveScanEvents(500)
      setHistory(data?.events || [])
    } catch {
      // ignore
    } finally {
      setLoadingHistory(false)
    }
  }

  useEffect(() => {
    loadHistory()
    setLive(true)
    return () => setLive(false)
  }, [setLive])

  const filteredEvents = useMemo(() => {
    if (filter === 'ALL') return events
    return events.filter((e) => e.status === filter)
  }, [events, filter])

  const latestList = useMemo(() => {
    return Object.values(latestBySymbol)
      .filter((ev) => ev.symbol && !ev.symbol.startsWith('_'))
      .sort((a, b) => new Date(b.scanned_at) - new Date(a.scanned_at))
  }, [latestBySymbol])

  const rejectionBreakdown = useMemo(() => {
    const map = {}
    events.forEach((e) => {
      if (e.status !== 'NO_SIGNAL') return
      const reason = e.rejection_reason || 'unknown'
      map[reason] = (map[reason] || 0) + 1
    })
    return Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
  }, [events])

  const askTip = async (event) => {
    setSelected(event)
    setLoadingTip(true)
    setTip(null)
    try {
      const { data } = await aiService.liveTip(event)
      setTip(data)
    } catch (exc) {
      setTip({ tip: 'No se pudo obtener el tip ahora mismo.', rationale: String(exc), confidence: 'low' })
    } finally {
      setLoadingTip(false)
    }
  }

  return (
    <div className="space-y-4 animate-in fade-in duration-300">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-gradient-to-r from-slate-900 to-slate-800 text-white rounded-xl p-4 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="relative">
            <ScanLine size={24} className="text-cyan-400" />
            {isLive && (
              <span className="absolute -top-0.5 -right-0.5 flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500" />
              </span>
            )}
          </div>
          <div>
            <h2 className="text-base font-bold flex items-center gap-2">
              Scanner Live
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                BETA
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              {isLive ? 'Escuchando eventos en tiempo real vía WebSocket' : 'Reconectando...'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadHistory}
            disabled={loadingHistory}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-700 hover:bg-slate-600 disabled:opacity-50 transition"
          >
            <RefreshCw size={13} className={cn(loadingHistory && 'animate-spin')} />
            Recargar histórico
          </button>
          <button
            onClick={reset}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-300 hover:bg-red-500/30 transition"
          >
            Limpiar
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Escaneados" value={stats.scanned} icon={ScanLine} color="bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400" />
        <KpiCard label="Señales" value={stats.signals} icon={Zap} color="bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400" />
        <KpiCard label="No Signal" value={stats.noSignals} icon={ShieldX} color="bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-400" />
        <KpiCard label="Errores" value={stats.errors} icon={AlertTriangle} color="bg-red-100 text-red-600 dark:bg-red-500/20 dark:text-red-400" />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Filter size={14} className="text-slate-400" />
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={cn(
              'px-2.5 py-1 rounded-full text-[11px] font-medium border transition',
              filter === f.id
                ? 'bg-slate-800 text-white border-slate-800 dark:bg-cyan-500/20 dark:text-cyan-300 dark:border-cyan-500/40'
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700 hover:border-slate-400'
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Latest by symbol */}
        <div className="xl:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
              <Activity size={14} /> Último estado por par
            </h3>
            <span className="text-[10px] text-slate-400">{latestList.length} pares</span>
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            {latestList.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-400">
                Aún no hay eventos. Lanza un scan manual o espera al próximo scan automático.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3">
                {latestList.map((ev) => (
                  <div
                    key={`${ev.symbol}:${ev.timeframe}`}
                    className="group relative p-3 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 hover:border-cyan-300 dark:hover:border-cyan-500/40 transition"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-slate-800 dark:text-slate-200">{ev.symbol}</span>
                        <span className="text-[10px] text-slate-500">{ev.timeframe}</span>
                      </div>
                      <StatusBadge status={ev.status} />
                    </div>
                    <div className="grid grid-cols-2 gap-y-1 text-[11px]">
                      {ev.score != null && (
                        <div><span className="text-slate-400">Score:</span> <span className="font-semibold">{ev.score}</span></div>
                      )}
                      {ev.success_probability != null && (
                        <div><span className="text-slate-400">Prob:</span> <span className="font-semibold">{(ev.success_probability * 100).toFixed(1)}%</span></div>
                      )}
                      {ev.quality_tier && (
                        <div><span className="text-slate-400">Tier:</span> <TierBadge tier={ev.quality_tier} /></div>
                      )}
                      {ev.regime && (
                        <div><span className="text-slate-400">Régimen:</span> <span className="font-medium">{ev.regime}</span></div>
                      )}
                    </div>
                    {ev.rejection_reason && (
                      <div className="mt-2 text-[10px] text-amber-600 dark:text-amber-400 truncate">
                        {ev.rejection_reason}
                      </div>
                    )}
                    <button
                      onClick={() => askTip(ev)}
                      className="mt-2 opacity-0 group-hover:opacity-100 transition flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 hover:bg-cyan-500/20"
                    >
                      <Lightbulb size={11} /> Tip de IA
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Sidebar: event log + breakdown */}
        <div className="space-y-4">
          {/* Rejection breakdown */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3 flex items-center gap-2">
              <Flame size={14} /> Top rechazos
            </h3>
            {rejectionBreakdown.length === 0 ? (
              <p className="text-xs text-slate-400">Sin datos de rechazo todavía.</p>
            ) : (
              <div className="space-y-2">
                {rejectionBreakdown.map(([reason, count]) => (
                  <div key={reason} className="flex items-center justify-between text-xs">
                    <span className="text-slate-600 dark:text-slate-400 truncate max-w-[70%]">{reason}</span>
                    <span className="font-bold text-slate-800 dark:text-slate-200">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Live event log */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
                <BrainCircuit size={14} /> Eventos en vivo
              </h3>
              <span className="text-[10px] text-slate-400">{filteredEvents.length}</span>
            </div>
            <div className="max-h-[400px] overflow-y-auto">
              {filteredEvents.length === 0 ? (
                <div className="p-6 text-center text-xs text-slate-400">No hay eventos con este filtro.</div>
              ) : (
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {filteredEvents.slice(0, 100).map((ev, idx) => (
                    <li
                      key={`${ev.scan_id}-${ev.symbol}-${idx}`}
                      className="px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition cursor-pointer"
                      onClick={() => setSelected(ev)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <StatusBadge status={ev.status} />
                          <span className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">
                            {ev.symbol !== '_ALL_' ? `${ev.symbol} ${ev.timeframe}` : ev.message || 'Scan global'}
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-400 shrink-0">
                          {new Date(ev.scanned_at).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </span>
                      </div>
                      {ev.rejection_reason && (
                        <div className="mt-1 text-[10px] text-amber-600 dark:text-amber-400 truncate">{ev.rejection_reason}</div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Detail modal */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl">
            <div className="flex items-center justify-between p-4 border-b border-slate-100 dark:border-slate-800">
              <h3 className="text-sm font-bold flex items-center gap-2">
                <ScanLine size={16} className="text-cyan-500" />
                {selected.symbol !== '_ALL_' ? `${selected.symbol} ${selected.timeframe}` : 'Evento global'}
              </h3>
              <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-slate-600">
                <XCircle size={18} />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div className="flex items-center gap-2">
                <StatusBadge status={selected.status} />
                <span className="text-xs text-slate-500">{new Date(selected.scanned_at).toLocaleString('es-ES')}</span>
              </div>
              {selected.score != null && (
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="p-2 rounded bg-slate-50 dark:bg-slate-800"><span className="text-slate-400">Score</span><div className="font-semibold">{selected.score}</div></div>
                  <div className="p-2 rounded bg-slate-50 dark:bg-slate-800"><span className="text-slate-400">Probabilidad</span><div className="font-semibold">{selected.success_probability != null ? `${(selected.success_probability * 100).toFixed(1)}%` : '—'}</div></div>
                  <div className="p-2 rounded bg-slate-50 dark:bg-slate-800"><span className="text-slate-400">Tier</span><div className="font-semibold">{selected.quality_tier || '—'}</div></div>
                  <div className="p-2 rounded bg-slate-50 dark:bg-slate-800"><span className="text-slate-400">Régimen</span><div className="font-semibold">{selected.regime || '—'}</div></div>
                </div>
              )}
              {selected.rejection_reason && (
                <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-800 text-xs">
                  <div className="font-semibold text-amber-700 dark:text-amber-400 mb-1">Motivo de rechazo</div>
                  <div className="text-amber-600 dark:text-amber-300">{selected.rejection_reason}</div>
                </div>
              )}
              {Object.keys(selected.features_preview || {}).length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5">Features</div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {Object.entries(selected.features_preview).map(([k, v]) => (
                      <div key={k} className="p-2 rounded bg-slate-50 dark:bg-slate-800 flex justify-between">
                        <span className="text-slate-400">{k}</span>
                        <span className="font-medium truncate max-w-[60%]">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <button
                onClick={() => askTip(selected)}
                disabled={loadingTip}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-500 text-white text-sm font-semibold hover:from-cyan-400 hover:to-blue-400 disabled:opacity-50 transition"
              >
                <Lightbulb size={16} />
                {loadingTip ? 'Pensando...' : 'Pedir tip de IA local'}
              </button>
              {tip && (
                <div className="p-3 rounded-lg bg-violet-50 dark:bg-violet-900/20 border border-violet-100 dark:border-violet-800 text-xs">
                  <div className="font-semibold text-violet-700 dark:text-violet-300 mb-1 flex items-center gap-1">
                    <CheckCircle2 size={12} /> Tip ({tip.confidence} confianza)
                  </div>
                  <p className="text-violet-800 dark:text-violet-200 mb-2">{tip.tip}</p>
                  <p className="text-[10px] text-violet-500 dark:text-violet-400">{tip.rationale}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
