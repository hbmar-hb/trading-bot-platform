import { useEffect, useState } from 'react'
import {
  X, Brain, BarChart3, TrendingUp, TrendingDown, ShieldAlert, AlertTriangle,
  ShieldCheck, Clock, Activity, AlertOctagon, Info, ChevronRight, Sparkles,
  Globe, Zap
} from 'lucide-react'
import { aiService } from '@/services/aiService'
import useAuthStore from '@/store/authStore'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import { cn } from '@/utils/cn'

const VERDICT_CONFIG = {
  BLOCK: {
    label: 'BLOQUEAR',
    color: 'text-red-600 dark:text-red-400',
    bg: 'bg-red-100 dark:bg-red-500/10',
    border: 'border-red-200 dark:border-red-500/20',
    icon: ShieldAlert,
  },
  CAUTION: {
    label: 'PRECAUCIÓN',
    color: 'text-yellow-600 dark:text-yellow-400',
    bg: 'bg-yellow-100 dark:bg-yellow-500/10',
    border: 'border-yellow-200 dark:border-yellow-500/20',
    icon: AlertTriangle,
  },
  CLEAR: {
    label: 'LIMPIO',
    color: 'text-emerald-600 dark:text-emerald-400',
    bg: 'bg-emerald-100 dark:bg-emerald-500/10',
    border: 'border-emerald-200 dark:border-emerald-500/20',
    icon: ShieldCheck,
  },
}

const SEVERITY_CONFIG = {
  critical: { color: 'text-red-500', bg: 'bg-red-50 dark:bg-red-500/5', border: 'border-red-100 dark:border-red-500/10', label: 'Crítico' },
  warning:  { color: 'text-yellow-500', bg: 'bg-yellow-50 dark:bg-yellow-500/5', border: 'border-yellow-100 dark:border-yellow-500/10', label: 'Advertencia' },
  info:     { color: 'text-blue-500', bg: 'bg-blue-50 dark:bg-blue-500/5', border: 'border-blue-100 dark:border-blue-500/10', label: 'Info' },
}

function AdminDiagnosisView({ data }) {
  const verdict = data?.diagnosis?.verdict || data?.verdict
  const verdictCfg = VERDICT_CONFIG[verdict] || VERDICT_CONFIG.CLEAR
  const VerdictIcon = verdictCfg.icon
  const confidence = data?.diagnosis?.confidence ?? data?.confidence ?? 0

  return (
    <>
      <div className="flex items-center gap-4">
        <div className={cn('flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-bold', verdictCfg.bg, verdictCfg.color, verdictCfg.border)}>
          <VerdictIcon size={14} />
          {verdictCfg.label}
        </div>
        <div className="flex-1">
          <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
            <span>Confianza del modelo</span>
            <span className="font-bold">{confidence}%</span>
          </div>
          <div className="w-full h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div className={cn('h-full rounded-full transition-all', confidence >= 80 ? 'bg-red-500' : confidence >= 50 ? 'bg-yellow-500' : 'bg-emerald-500')} style={{ width: `${confidence}%` }} />
          </div>
        </div>
      </div>

      <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-100 dark:border-slate-700">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles size={14} className="text-blue-500" />
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Resumen</span>
        </div>
        <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
          {data.diagnosis?.summary || data.summary || 'Sin resumen disponible.'}
        </p>
      </div>

      {(data.diagnosis?.factors || data.factors)?.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Activity size={14} className="text-slate-400" />
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Factores analizados</span>
          </div>
          <div className="space-y-2">
            {(data.diagnosis?.factors || data.factors).map((f, i) => {
              const sev = SEVERITY_CONFIG[f.severity] || SEVERITY_CONFIG.info
              return (
                <div key={i} className={cn('flex items-start gap-3 rounded-lg border p-3 text-sm', sev.bg, sev.border)}>
                  <div className="mt-0.5"><AlertOctagon size={14} className={sev.color} /></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={cn('text-[10px] font-bold uppercase tracking-wider', sev.color)}>{sev.label}</span>
                      <span className="text-[10px] text-slate-400">·</span>
                      <span className="text-[10px] text-slate-500 capitalize">{f.category}</span>
                      {f.metric && <><span className="text-[10px] text-slate-400">·</span><span className="text-[10px] font-mono text-slate-500">{f.metric}</span></>}
                    </div>
                    <p className="mt-1 text-slate-700 dark:text-slate-300 text-sm leading-relaxed">{f.description}</p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="bg-blue-50 dark:bg-blue-500/5 rounded-lg p-4 border border-blue-100 dark:border-blue-500/10">
        <div className="flex items-center gap-2 mb-2">
          <ChevronRight size={14} className="text-blue-500" />
          <span className="text-xs font-semibold text-blue-700 dark:text-blue-400 uppercase tracking-wide">Recomendación</span>
        </div>
        <p className="text-sm text-blue-800 dark:text-blue-300 leading-relaxed">
          {data.diagnosis?.recommendation || data.recommendation || 'Sin recomendación disponible.'}
        </p>
      </div>

      <div className="p-3 border-t border-slate-200 dark:border-gray-800 bg-slate-50 dark:bg-gray-800/50 flex items-center justify-between text-[11px] text-slate-400">
        <div className="flex items-center gap-3">
          <span>Modelo: <span className="text-slate-600 dark:text-slate-300 font-medium">{data.model_used || 'internal'}</span></span>
          {data.latency_ms != null && <span className="flex items-center gap-1"><Clock size={11} />{data.latency_ms}ms</span>}
        </div>
        <span>{data.created_at ? new Date(data.created_at).toLocaleString('es-ES') : ''}</span>
      </div>
    </>
  )
}

function UserContextView({ data }) {
  const stats = data.symbol_stats || {}
  const regime = data.market_regime || {}
  const macro = data.macro_context || {}

  return (
    <>
      {/* Symbol Stats */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-100 dark:border-slate-700 text-center">
          <div className="text-xs text-slate-500 mb-1">Win Rate (30d)</div>
          <div className="text-lg font-bold text-slate-900 dark:text-slate-100">{stats.win_rate != null ? `${stats.win_rate}%` : '—'}</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-100 dark:border-slate-700 text-center">
          <div className="text-xs text-slate-500 mb-1">Trades</div>
          <div className="text-lg font-bold text-slate-900 dark:text-slate-100">{stats.total_trades ?? '—'}</div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-100 dark:border-slate-700 text-center">
          <div className="text-xs text-slate-500 mb-1">P&L Total</div>
          <div className={cn('text-lg font-bold', (stats.total_pnl || 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
            {stats.total_pnl != null ? `${stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl}` : '—'}
          </div>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-100 dark:border-slate-700 text-center">
          <div className="text-xs text-slate-500 mb-1">P&L Promedio</div>
          <div className={cn('text-lg font-bold', (stats.avg_pnl || 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
            {stats.avg_pnl != null ? `${stats.avg_pnl >= 0 ? '+' : ''}${stats.avg_pnl}` : '—'}
          </div>
        </div>
      </div>

      {/* Market Regime */}
      <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-100 dark:border-slate-700">
        <div className="flex items-center gap-2 mb-2">
          <Zap size={14} className="text-amber-500" />
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Régimen de mercado</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn('text-sm font-bold capitalize', regime.regime === 'bull' ? 'text-green-500' : regime.regime === 'bear' ? 'text-red-500' : 'text-slate-500')}>
            {regime.regime || 'Desconocido'}
          </span>
          {regime.confidence != null && <span className="text-xs text-slate-400">({Math.round(regime.confidence * 100)}% confianza)</span>}
        </div>
      </div>

      {/* Macro Context */}
      <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-100 dark:border-slate-700">
        <div className="flex items-center gap-2 mb-2">
          <Globe size={14} className="text-blue-500" />
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Contexto macro</span>
        </div>
        <p className="text-sm text-slate-700 dark:text-slate-300">
          {macro.context || macro.trend || 'Datos macro no disponibles.'}
        </p>
      </div>

      {/* Recent Rejections */}
      {data.recent_rejections?.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <ShieldAlert size={14} className="text-red-400" />
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Rechazos recientes (72h)</span>
          </div>
          <div className="space-y-1.5">
            {data.recent_rejections.map((r, i) => (
              <div key={i} className="flex items-center justify-between text-sm bg-red-50 dark:bg-red-500/5 rounded-lg px-3 py-2 border border-red-100 dark:border-red-500/10">
                <span className="text-slate-700 dark:text-slate-300 capitalize">{r.reason}</span>
                <span className="text-xs font-bold text-red-500">{r.count}×</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Signals */}
      {data.recent_signals?.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <BarChart3 size={14} className="text-slate-400" />
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wide">Señales recientes</span>
          </div>
          <div className="space-y-1.5">
            {data.recent_signals.map((s, i) => (
              <div key={i} className="flex items-center justify-between text-sm bg-slate-50 dark:bg-slate-800/30 rounded-lg px-3 py-2 border border-slate-100 dark:border-slate-700">
                <div className="flex items-center gap-2">
                  {s.direction === 'long' ? <TrendingUp size={12} className="text-green-500" /> : <TrendingDown size={12} className="text-red-500" />}
                  <span className="text-slate-700 dark:text-slate-300">Score {s.score}</span>
                </div>
                <span className={cn('text-xs font-bold', s.outcome === 'SUCCESS' ? 'text-green-500' : s.outcome?.startsWith('FAILURE') ? 'text-red-500' : 'text-slate-400')}>
                  {s.outcome || 'PENDING'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

export default function SignalDiagnosisModal({ signal, onClose }) {
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        if (isAdmin) {
          const res = await aiService.signalDiagnosis(signal.id)
          setData(res.data)
        } else {
          const res = await aiService.signalContext(signal.id)
          setData(res.data)
        }
      } catch (err) {
        console.error('Error cargando datos:', err)
        setError(isAdmin ? 'No se pudo cargar el diagnóstico' : 'No se pudo cargar el contexto')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [signal.id, isAdmin])

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-gray-800">
          <div className="flex items-center gap-3">
            <div className={cn('p-2 rounded-lg', isAdmin ? 'bg-blue-100 dark:bg-blue-500/10' : 'bg-slate-100 dark:bg-slate-800')}>
              {isAdmin ? (
                <Brain size={20} className="text-blue-600 dark:text-blue-400" />
              ) : (
                <BarChart3 size={20} className="text-slate-600 dark:text-slate-400" />
              )}
            </div>
            <div>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                {signal.ticker} · {signal.direction?.toUpperCase()}
              </h3>
              <p className="text-xs text-slate-500 dark:text-gray-400">
                {isAdmin ? 'Diagnóstico IA · ' + signal.timeframe : 'Contexto del par · ' + signal.timeframe}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X size={20} className="text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-5 space-y-5">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner />
              <span className="ml-3 text-sm text-slate-500">
                {isAdmin ? 'Analizando con Kimi…' : 'Cargando contexto…'}
              </span>
            </div>
          ) : error ? (
            <div className="text-center py-12 text-red-400">{error}</div>
          ) : !data ? (
            <div className="text-center py-12 text-slate-500">
              <Info size={32} className="mx-auto mb-3 text-slate-300 dark:text-slate-600" />
              <p>{isAdmin ? 'Aún no hay diagnóstico para esta señal.' : 'Contexto no disponible.'}</p>
            </div>
          ) : (
            isAdmin ? <AdminDiagnosisView data={data} /> : <UserContextView data={data} />
          )}
        </div>
      </div>
    </div>
  )
}
