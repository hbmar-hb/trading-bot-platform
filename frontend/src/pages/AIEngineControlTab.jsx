/**
 * AIEngineControlTab — Diagnóstico real del Motor IA
 * Muestra: salud del sistema, rechazos, señales evaluadas, y estado de filtros.
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import {
  Activity, AlertTriangle, ArrowUpDown, BrainCircuit, CheckCircle2, ChevronLeft, ChevronRight,
  Filter, Gauge, Lock, ShieldCheck, ShieldX, SlidersHorizontal, TrendingUp, XCircle, Zap,
} from 'lucide-react'
import { aiService } from '@/services/aiService'
import { cn } from '@/utils/cn'

const fmt1 = (n) => n == null ? '—' : Number(n).toFixed(1)
const fmt2 = (n) => n == null ? '—' : Number(n).toFixed(2)

function Section({ title, subtitle, children, icon: Icon, action }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-start gap-2">
          {Icon && <Icon size={16} className="text-slate-400 mt-0.5" />}
          <div>
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">{title}</h3>
            {subtitle && <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

function KPICard({ label, value, sub, icon: Icon, color }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3 flex items-center gap-3">
      <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', color)}>
        <Icon size={18} />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] text-slate-500 dark:text-slate-400">{label}</p>
        <p className="text-lg font-bold text-slate-800 dark:text-slate-200 truncate">{value}</p>
        {sub && <p className="text-[10px] text-slate-400 dark:text-slate-500">{sub}</p>}
      </div>
    </div>
  )
}

export default function AIEngineControlTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Table filters
  const [filterTicker, setFilterTicker] = useState('')
  const [filterDirection, setFilterDirection] = useState('all')
  const [filterDecision, setFilterDecision] = useState('all')
  const [filterMode, setFilterMode] = useState('all')
  const [sortKey, setSortKey] = useState('evaluated_at')
  const [sortDir, setSortDir] = useState('desc')
  const [page, setPage] = useState(1)
  const perPage = 25

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data: d } = await aiService.engineControl(7)
      setData(d)
    } catch (e) {
      setError(e?.message || 'Error al cargar control del motor')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const health = data?.system_health || {}
  const rejDiag = data?.rejection_diagnosis || {}
  const signals = data?.evaluated_signals || []
  const gates = data?.gate_status || {}
  const meta = data?.meta || {}

  const tickers = useMemo(() => {
    const set = new Set(signals.map(s => s.ticker))
    return Array.from(set).sort()
  }, [signals])

  const filtered = useMemo(() => {
    let rows = [...signals]
    if (filterTicker) rows = rows.filter(s => s.ticker === filterTicker)
    if (filterDirection !== 'all') rows = rows.filter(s => s.direction === filterDirection)
    if (filterDecision !== 'all') rows = rows.filter(s => s.decision === filterDecision)
    if (filterMode !== 'all') rows = rows.filter(s => s.mode === filterMode)
    rows.sort((a, b) => {
      let va = a[sortKey], vb = b[sortKey]
      if (va == null) va = ''
      if (vb == null) vb = ''
      if (typeof va === 'number' && typeof vb === 'number') {
        return sortDir === 'asc' ? va - vb : vb - va
      }
      return sortDir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
    })
    return rows
  }, [signals, filterTicker, filterDirection, filterDecision, filterMode, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage))
  const paged = filtered.slice((page - 1) * perPage, page * perPage)

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
    setPage(1)
  }

  if (loading) {
    return (
      <div className="py-20 text-center text-sm text-slate-400 dark:text-slate-500">
        <Activity className="inline-block animate-spin mb-2" size={20} />
        <p>Cargando diagnóstico del motor IA...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="py-20 text-center text-sm text-red-500">
        <AlertTriangle className="inline-block mb-2" size={20} />
        <p>{error}</p>
        <button onClick={load} className="mt-3 text-xs bg-slate-100 dark:bg-slate-800 px-3 py-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">
          Reintentar
        </button>
      </div>
    )
  }

  // Format dates nicely
  const fmtRel = (iso) => {
    if (!iso) return '—'
    const d = new Date(iso)
    const now = new Date()
    const diffMin = Math.floor((now - d) / 60000)
    if (diffMin < 1) return 'ahora'
    if (diffMin < 60) return `hace ${diffMin}min`
    const diffH = Math.floor(diffMin / 60)
    if (diffH < 24) return `hace ${diffH}h`
    const diffD = Math.floor(diffH / 24)
    return `hace ${diffD}d`
  }

  return (
    <div className="space-y-5">
      {/* ── System Health Banner ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPICard
          label="Bots IA activos"
          value={health.active_ai_bots ?? 0}
          sub={`${health.real_bots ?? 0} real · ${health.paper_bots ?? 0} paper`}
          icon={BrainCircuit}
          color="bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400"
        />
        <KPICard
          label="Posiciones abiertas"
          value={(health.open_real_count ?? 0) + (health.open_paper_count ?? 0)}
          sub={`${health.open_real_count ?? 0} real · ${health.open_paper_count ?? 0} paper`}
          icon={TrendingUp}
          color="bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400"
        />
        <KPICard
          label="Última señal"
          value={fmtRel(health.last_signal_at)}
          sub={health.last_signal_at ? new Date(health.last_signal_at).toLocaleTimeString() : '—'}
          icon={Zap}
          color={health.last_signal_at && (new Date() - new Date(health.last_signal_at)) < 3600000
            ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400'
            : 'bg-amber-100 text-amber-600 dark:bg-amber-500/20 dark:text-amber-400'}
        />
        <KPICard
          label="Último scan"
          value={fmtRel(health.last_scan_at)}
          sub={health.last_scan_at ? new Date(health.last_scan_at).toLocaleTimeString() : '—'}
          icon={Gauge}
          color={health.last_scan_at && (new Date() - new Date(health.last_scan_at)) < 900000
            ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400'
            : 'bg-red-100 text-red-600 dark:bg-red-500/20 dark:text-red-400'}
        />
      </div>

      {/* ── Alert if no recent signals ── */}
      {(!health.last_signal_at || (new Date() - new Date(health.last_signal_at)) > 3600000) && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-3 flex items-start gap-3">
          <AlertTriangle size={18} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-700 dark:text-amber-400">
              No hay señales recientes
            </p>
            <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-0.5">
              {(() => {
                const now = new Date()
                const lastScan = health.last_scan_at ? new Date(health.last_scan_at) : null
                const scanAgeMin = lastScan ? (now - lastScan) / 60000 : null
                if (scanAgeMin == null || scanAgeMin > 30) {
                  return 'No se han registrado scans automáticos recientes. Verifica que Celery beat y Celery worker estén activos.'
                }
                return 'El scanner ha analizado pares recientemente, pero ninguno ha superado los filtros de confluencia, tier y scoring. Revisa el diagnóstico de rechazos para ver por qué se descartan.'
              })()}
            </p>
          </div>
        </div>
      )}

      {/* ── Rejection Diagnosis ── */}
      <Section title="Diagnóstico de Rechazos" subtitle="Por qué se bloquean las señales" icon={ShieldX}>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {Object.entries(rejDiag).map(([window, rows]) => (
            <div key={window}>
              <h4 className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2 uppercase tracking-wide">
                Últimas {window}
              </h4>
              <div className="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-lg">
                <table className="w-full text-[11px]">
                  <thead className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium">Razón</th>
                      <th className="px-2 py-1.5 text-right font-medium">Total</th>
                      <th className="px-2 py-1.5 text-right font-medium">Would Win</th>
                      <th className="px-2 py-1.5 text-right font-medium">% Win</th>
                      <th className="px-2 py-1.5 text-right font-medium">Score ↓</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {rows.sort((a, b) => b.total - a.total).map((row, i) => (
                      <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                        <td className="px-2 py-1.5 font-medium text-slate-700 dark:text-slate-300">{row.reason}</td>
                        <td className="px-2 py-1.5 text-right font-mono">{row.total}</td>
                        <td className="px-2 py-1.5 text-right">
                          <span className={cn(
                            'font-mono font-medium',
                            row.would_win_pct > 60 ? 'text-red-600 dark:text-red-400' :
                            row.would_win_pct > 40 ? 'text-amber-600 dark:text-amber-400' :
                            'text-slate-500 dark:text-slate-400'
                          )}>
                            {row.would_win}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <span className={cn(
                            'font-mono font-bold',
                            row.would_win_pct > 60 ? 'text-red-600 dark:text-red-400' :
                            row.would_win_pct > 40 ? 'text-amber-600 dark:text-amber-400' :
                            'text-emerald-600 dark:text-emerald-400'
                          )}>
                            {row.would_win_pct}%
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-slate-500">{row.avg_score}</td>
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr><td colSpan={5} className="px-2 py-3 text-center text-slate-400">Sin rechazos</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* ── Gate Status ── */}
      <Section title="Estado de Filtros (Umbrales Actuales)" subtitle="Valores relajados el 2026-05-24" icon={Lock}>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px]">
          {[
            { k: 'drift', label: 'Drift (PSI)', val: `Healthy ≤${gates.drift?.healthy}, Degraded ≤${gates.drift?.degraded}, Paused ≤${gates.drift?.paused}` },
            { k: 'kelly', label: 'Kelly Edge', val: `Min ${gates.kelly?.min_edge * 100}%. ${gates.kelly?.behavior}` },
            { k: 'rolling_beta', label: 'Rolling Beta', val: `High ≤${gates.rolling_beta?.high}, Extreme ≤${gates.rolling_beta?.extreme}. ${gates.rolling_beta?.behavior}` },
            { k: 'concurrent', label: 'Concurrent', val: gates.concurrent },
            { k: 'tier', label: 'Tier Inclusion', val: gates.tier },
            { k: 'portfolio', label: 'Portfolio', val: gates.portfolio },
            { k: 'slippage', label: 'Slippage', val: gates.slippage },
            { k: 'pattern_wr', label: 'Pattern WR', val: gates.pattern_wr },
          ].map(g => (
            <div key={g.k} className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-2.5 border border-slate-100 dark:border-slate-800">
              <p className="font-semibold text-slate-600 dark:text-slate-300 mb-0.5">{g.label}</p>
              <p className="text-slate-500 dark:text-slate-400 leading-snug">{g.val}</p>
            </div>
          ))}
        </div>
        {gates.notes && (
          <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-2">{gates.notes}</p>
        )}
      </Section>

      {/* ── Open Positions ── */}
      {health.open_positions?.length > 0 && (
        <Section title="Posiciones Abiertas" subtitle="Activas ahora mismo" icon={TrendingUp}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {health.open_positions.map((p, i) => (
              <div key={i} className="flex items-center justify-between bg-slate-50 dark:bg-slate-800/50 rounded-lg p-2.5 border border-slate-100 dark:border-slate-800">
                <div>
                  <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">{p.symbol}</p>
                  <p className="text-[10px] text-slate-500">{p.bot_name} · {p.side.toUpperCase()}</p>
                </div>
                <div className="text-right">
                  <span className={cn(
                    'text-[10px] font-bold px-1.5 py-0.5 rounded uppercase',
                    p.mode === 'paper' ? 'bg-blue-100 text-blue-600 dark:bg-blue-500/20' : 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20'
                  )}>
                    {p.mode}
                  </span>
                  <p className={cn('text-xs font-mono font-medium mt-0.5', p.unrealized_pnl >= 0 ? 'text-emerald-600' : 'text-red-600')}>
                    {p.unrealized_pnl >= 0 ? '+' : ''}{fmt2(p.unrealized_pnl)} USDT
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Data Control Table ── */}
      <Section title="Señales Evaluadas" subtitle={`${meta.total_evaluated ?? 0} total · ${meta.accepted_count ?? 0} aceptadas · ${meta.rejected_count ?? 0} rechazadas`} icon={ShieldCheck}
        action={
          <div className="flex items-center gap-2 flex-wrap">
            <select value={filterTicker} onChange={e => { setFilterTicker(e.target.value); setPage(1) }} className="text-[11px] bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-2 py-1 text-slate-600 dark:text-slate-300">
              <option value="">Todos los tickers</option>
              {tickers.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={filterDirection} onChange={e => { setFilterDirection(e.target.value); setPage(1) }} className="text-[11px] bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-2 py-1 text-slate-600 dark:text-slate-300">
              <option value="all">Dir: Todas</option>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
            <select value={filterDecision} onChange={e => { setFilterDecision(e.target.value); setPage(1) }} className="text-[11px] bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-2 py-1 text-slate-600 dark:text-slate-300">
              <option value="all">Dec: Todas</option>
              <option value="ACCEPTED">Aceptadas</option>
              <option value="REJECTED">Rechazadas</option>
            </select>
            <select value={filterMode} onChange={e => { setFilterMode(e.target.value); setPage(1) }} className="text-[11px] bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-2 py-1 text-slate-600 dark:text-slate-300">
              <option value="all">Modo: Todos</option>
              <option value="real">Real</option>
              <option value="paper">Paper</option>
            </select>
          </div>
        }
      >
        <div className="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-lg">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
              <tr>
                {[
                  { key: 'ticker', label: 'Ticker' },
                  { key: 'timeframe', label: 'TF' },
                  { key: 'direction', label: 'Dir' },
                  { key: 'score', label: 'Score' },
                  { key: 'quality_tier', label: 'Tier' },
                  { key: 'anti_fake_status', label: 'Status' },
                  { key: 'mode', label: 'Modo' },
                  { key: 'decision', label: 'Decisión' },
                  { key: 'outcome', label: 'Outcome' },
                  { key: 'pnl_pct', label: 'PnL %' },
                  { key: 'rejection_reason', label: 'Razón' },
                ].map(col => (
                  <th key={col.key} className="px-2 py-2 text-left font-medium whitespace-nowrap cursor-pointer hover:text-slate-700 dark:hover:text-slate-200 select-none" onClick={() => handleSort(col.key)}>
                    <span className="flex items-center gap-1">
                      {col.label}
                      {sortKey === col.key && <ArrowUpDown size={10} className={sortDir === 'asc' ? 'rotate-180' : ''} />}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {paged.map((row, idx) => {
                const isAccepted = row.decision === 'ACCEPTED'
                const isWinner = row.outcome === 'SUCCESS'
                const isRejectedWinner = !isAccepted && row.would_have_been_winner === true
                const rowClass = cn(
                  'hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors',
                  isAccepted && isWinner && 'bg-emerald-50/40 dark:bg-emerald-900/10',
                  isAccepted && !isWinner && row.outcome !== 'PENDING' && 'bg-red-50/40 dark:bg-red-900/10',
                  isRejectedWinner && 'bg-amber-50/40 dark:bg-amber-900/10',
                )
                return (
                  <tr key={`${row.id}-${idx}`} className={rowClass}>
                    <td className="px-2 py-1.5 font-mono font-semibold text-slate-700 dark:text-slate-300">{row.ticker}</td>
                    <td className="px-2 py-1.5 text-slate-500 dark:text-slate-400">{row.timeframe}</td>
                    <td className={cn('px-2 py-1.5 font-medium', row.direction === 'long' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
                      {row.direction?.toUpperCase()}
                    </td>
                    <td className="px-2 py-1.5 font-mono">{fmt1(row.score)}</td>
                    <td className="px-2 py-1.5">
                      <span className={cn(
                        'inline-block text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide',
                        row.quality_tier === 'STRONG' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400' :
                        row.quality_tier === 'MODERATE' ? 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400' :
                        'bg-slate-100 text-slate-600 dark:bg-slate-500/20 dark:text-slate-400'
                      )}>
                        {row.quality_tier}
                      </span>
                    </td>
                    <td className={cn('px-2 py-1.5',
                      row.anti_fake_status === 'CLEAR' ? 'text-emerald-600 dark:text-emerald-400' :
                      row.anti_fake_status === 'CAUTION' ? 'text-amber-600 dark:text-amber-400' :
                      'text-red-600 dark:text-red-400'
                    )}>
                      {row.anti_fake_status}
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={cn('inline-block text-[9px] font-bold px-1.5 py-0.5 rounded uppercase',
                        row.mode === 'paper' ? 'bg-blue-100 text-blue-600 dark:bg-blue-500/20' :
                        row.mode === 'real' ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20' :
                        'bg-slate-100 text-slate-500 dark:bg-slate-800'
                      )}>
                        {row.mode === 'paper' ? '📄 Paper' : row.mode === 'real' ? '🏦 Real' : '❓'}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={cn('inline-flex items-center gap-1 text-[10px] font-bold',
                        isAccepted ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'
                      )}>
                        {isAccepted ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                        {row.decision}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={cn(
                        row.outcome === 'SUCCESS' && 'text-emerald-600 dark:text-emerald-400',
                        row.outcome === 'FAILURE' && 'text-red-600 dark:text-red-400',
                        row.outcome === 'PENDING' && 'text-slate-400',
                        row.outcome === 'REJECTED' && 'text-amber-600 dark:text-amber-400',
                      )}>
                        {row.outcome}
                      </span>
                    </td>
                    <td className={cn('px-2 py-1.5 font-mono font-medium',
                      row.pnl_pct != null && row.pnl_pct >= 0 ? 'text-emerald-600 dark:text-emerald-400' :
                      row.pnl_pct != null ? 'text-red-600 dark:text-red-400' : 'text-slate-400'
                    )}>
                      {row.pnl_pct != null ? `${row.pnl_pct >= 0 ? '+' : ''}${fmt2(row.pnl_pct)}%` : '—'}
                    </td>
                    <td className="px-2 py-1.5 text-slate-500 dark:text-slate-400 max-w-[120px] truncate" title={row.rejection_reason || ''}>
                      {row.rejection_reason || '—'}
                    </td>
                  </tr>
                )
              })}
              {paged.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-2 py-8 text-center text-slate-400 dark:text-slate-500">
                    Sin señales que coincidan con los filtros
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between mt-3">
          <p className="text-[11px] text-slate-400 dark:text-slate-500">
            Mostrando {filtered.length > 0 ? (page - 1) * perPage + 1 : 0}–{Math.min(page * perPage, filtered.length)} de {filtered.length}
          </p>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30 text-slate-500 dark:text-slate-400">
              <ChevronLeft size={16} />
            </button>
            <span className="text-[11px] text-slate-500 dark:text-slate-400 px-2">{page} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30 text-slate-500 dark:text-slate-400">
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </Section>
    </div>
  )
}
