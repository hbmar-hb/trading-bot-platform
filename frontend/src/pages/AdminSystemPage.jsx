import { useEffect, useState, useCallback } from 'react'
import { Activity, AlertTriangle, CheckCircle, ClipboardCopy, History, Loader2, RefreshCw, ShieldAlert } from 'lucide-react'
import { cn } from '@/utils/cn'
import { adminSystemService } from '@/services/adminSystem'
import useAuthStore from '@/store/authStore'
import { isDeveloper } from '@/constants/roles'
import EngineAIHelper from '@/components/IAEngine/EngineAIHelper'

const CHECK_ICONS = {
  infra: Activity,
  logs: ShieldAlert,
  database: Activity,
  ml_models: Activity,
  celery: Activity,
  exchange: Activity,
  full: RefreshCw,
}

const STATUS_COLORS = {
  healthy: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20',
  warning: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20',
  critical: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20',
}

const STATUS_LABELS = {
  healthy: 'Sano',
  warning: 'Advertencia',
  critical: 'Crítico',
}

export default function AdminSystemPage() {
  const user = useAuthStore(s => s.user)
  const [checks, setChecks] = useState([])
  const [loadingList, setLoadingList] = useState(true)
  const [running, setRunning] = useState(null)
  const [report, setReport] = useState(null)
  const [shareLog, setShareLog] = useState('')
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  const [debugInfo, setDebugInfo] = useState('')

  const [shadowHistory, setShadowHistory] = useState([])
  const [shadowLoading, setShadowLoading] = useState(false)
  const [shadowLog, setShadowLog] = useState('')

  const loadChecks = useCallback(async () => {
    setLoadingList(true)
    setError('')
    setDebugInfo('')
    try {
      const response = await adminSystemService.listChecks()
      const data = response?.data || {}
      setDebugInfo(`Status: ${response?.status}, Data: ${JSON.stringify(data).slice(0, 500)}`)
      const checksList = data.checks || []
      setChecks(checksList)
      if (checksList.length === 0) {
        setError('La API devolvió una lista de checks vacía.')
      }
    } catch (e) {
      const status = e.response?.status
      const detail = e.response?.data?.detail
      const fullData = JSON.stringify(e.response?.data || {}).slice(0, 500)
      let msg = detail || e.message || 'Error desconocido cargando checks'
      if (status === 401) msg = `No autenticado (401). Cerrá sesión y volvé a entrar.`
      if (status === 403) msg = `No tenés permisos de admin (403).`
      setError(`Error ${status || ''}: ${msg}`)
      setDebugInfo(`Error response data: ${fullData}`)
    } finally {
      setLoadingList(false)
    }
  }, [])

  const loadShadowHistory = useCallback(async () => {
    setShadowLoading(true)
    try {
      const { data } = await adminSystemService.getShadowHistory(20)
      setShadowHistory(data.history || [])
    } catch (e) {
      setError(e.response?.data?.detail || 'Error cargando historial de shadow mode')
    } finally {
      setShadowLoading(false)
    }
  }, [])

  const normalizeShadowReport = useCallback((data) => {
    const issues = data.healthy
      ? []
      : ['Shadow mode unhealthy — revisar signal_id=None o falta de actividad']
    return {
      timestamp: data.checked_at,
      status: data.healthy ? 'healthy' : 'critical',
      checks: {
        shadow_mode: {
          name: 'shadow_mode',
          healthy: data.healthy,
          info: {
            candidate_total: data.candidate?.total_in_window,
            candidate_resolved: data.candidate?.resolved,
            candidate_none_recent: data.candidate?.none_recent,
            candidate_recent: data.candidate?.recent_predictions,
            live_total: data.live?.total_in_window,
            live_none_recent: data.live?.none_recent,
            live_recent: data.live?.recent_predictions,
            candidate_eval: data.candidate_eval,
          },
          issues,
        },
      },
      summary: {
        total_issues: issues.length,
        criticals: issues.length,
        warnings: 0,
        issues_list: issues,
      },
    }
  }, [])

  const runShadowCheck = useCallback(async () => {
    setShadowLoading(true)
    setShadowLog('')
    try {
      const { data } = await adminSystemService.runShadowCheck()
      setReport(normalizeShadowReport(data))
      await loadShadowHistory()
    } catch (e) {
      setError(e.response?.data?.detail || 'Error ejecutando shadow monitor')
    } finally {
      setShadowLoading(false)
    }
  }, [loadShadowHistory, normalizeShadowReport])

  const generateShadowLog = useCallback(async (entry) => {
    setRunning('shadow-log')
    try {
      const reportForLog = {
        timestamp: entry.checked_at,
        status: entry.healthy ? 'healthy' : 'critical',
        checks: {
          shadow_mode: {
            name: 'shadow_mode',
            healthy: entry.healthy,
            info: {
              candidate_total: entry.candidate.total_in_window,
              candidate_resolved: entry.candidate.resolved,
              candidate_none_recent: entry.candidate.none_recent,
              live_total: entry.live.total_in_window,
              live_none_recent: entry.live.none_recent,
              candidate_eval: entry.candidate_eval,
            },
            issues: [],
          },
        },
        summary: {
          total_issues: entry.healthy ? 0 : 1,
          criticals: entry.healthy ? 0 : 1,
          warnings: 0,
          issues_list: entry.healthy
            ? []
            : ['Shadow mode unhealthy — revisar signal_id=None o falta de actividad'],
        },
      }
      const { data } = await adminSystemService.shareLog(reportForLog)
      setShadowLog(data.log)
    } catch (e) {
      setError(e.response?.data?.detail || 'Error generando log de shadow')
    } finally {
      setRunning(null)
    }
  }, [])

  const runCheck = useCallback(async (checkId) => {
    setRunning(checkId)
    setError('')
    setShareLog('')
    try {
      const { data } = await adminSystemService.runCheck(checkId)
      setReport(data)
    } catch (e) {
      setError(e.response?.data?.detail || `Error ejecutando ${checkId}`)
    } finally {
      setRunning(null)
    }
  }, [])

  const generateLog = useCallback(async () => {
    if (!report) return
    setRunning('share-log')
    try {
      const { data } = await adminSystemService.shareLog(report)
      setShareLog(data.log)
    } catch (e) {
      setError(e.response?.data?.detail || 'Error generando log')
    } finally {
      setRunning(null)
    }
  }, [report])

  useEffect(() => {
    loadChecks()
    loadShadowHistory()
  }, [loadChecks, loadShadowHistory])

  const copyToClipboard = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(shareLog)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback para HTTP (navigator.clipboard bloqueado sin HTTPS)
      try {
        const textarea = document.createElement('textarea')
        textarea.value = shareLog
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      } catch {
        setError('No se pudo copiar al portapapeles. Copiá manualmente desde el recuadro de abajo.')
      }
    }
  }, [shareLog])

  if (!user || !isDeveloper(user)) {
    return (
      <div className="p-8 text-center text-slate-500 dark:text-gray-400">
        <ShieldAlert size={48} className="mx-auto mb-4 opacity-50" />
        <p className="text-lg font-medium">Acceso restringido</p>
        <p className="text-sm">Solo el perfil desarrollador puede ver esta página.</p>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <Activity size={28} className="text-blue-600 dark:text-blue-400" />
            Admin de Sistema
          </h1>
          <p className="text-sm text-slate-500 dark:text-gray-400 mt-1">
            Monitoreo, diagnóstico y health checks de la plataforma.
          </p>
        </div>
        {report && (
          <div className={cn(
            'px-4 py-2 rounded-lg text-sm font-semibold',
            STATUS_COLORS[report.status] || STATUS_COLORS.warning
          )}>
            {STATUS_LABELS[report.status] || report.status}
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {debugInfo && (
        <div className="rounded-lg bg-slate-100 dark:bg-gray-800 border border-slate-200 dark:border-gray-700 px-4 py-3">
          <p className="text-xs font-semibold text-slate-600 dark:text-gray-400 mb-1">Debug:</p>
          <pre className="text-xs font-mono text-slate-700 dark:text-gray-300 whitespace-pre-wrap break-all">
            {debugInfo}
          </pre>
        </div>
      )}

      {/* Checks Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {loadingList ? (
          <div className="col-span-full flex items-center justify-center py-12 text-slate-400">
            <Loader2 size={24} className="animate-spin mr-2" /> Cargando checks...
          </div>
        ) : checks.length === 0 ? (
          <div className="col-span-full rounded-xl border border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 text-center">
            <p className="text-slate-600 dark:text-gray-300 mb-2">
              No se pudieron cargar los checks.
            </p>
            <p className="text-xs text-slate-500 dark:text-gray-400 mb-4">
              Revisá el mensaje de error de arriba o intentá de nuevo.
            </p>
            <button
              onClick={loadChecks}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white transition-colors"
            >
              <RefreshCw size={14} /> Reintentar
            </button>
          </div>
        ) : (
          checks.map((check) => {
            const Icon = CHECK_ICONS[check.id] || Activity
            const isRunning = running === check.id
            return (
              <button
                key={check.id}
                onClick={() => runCheck(check.id)}
                disabled={!!running}
                className={cn(
                  'group flex flex-col items-start p-4 rounded-xl border transition-all text-left',
                  'bg-white dark:bg-gray-900 border-slate-200 dark:border-gray-800',
                  'hover:border-blue-300 dark:hover:border-blue-700 hover:shadow-sm',
                  'disabled:opacity-60 disabled:cursor-not-allowed'
                )}
              >
                <div className="flex items-center justify-between w-full mb-2">
                  <Icon size={20} className="text-slate-500 dark:text-gray-400 group-hover:text-blue-500 transition-colors" />
                  {isRunning && <Loader2 size={16} className="animate-spin text-blue-500" />}
                </div>
                <span className="font-semibold text-slate-800 dark:text-gray-100 text-sm">
                  {check.label}
                </span>
                <span className="text-xs text-slate-500 dark:text-gray-400 mt-1">
                  {check.description}
                </span>
              </button>
            )
          })
        )}
      </div>

      {/* Report Results */}
      {report && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">
              Resultados del Check
            </h2>
            <div className="flex gap-2">
              <button
                onClick={generateLog}
                disabled={!!running}
                className={cn(
                  'inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  'bg-slate-100 dark:bg-gray-800 text-slate-700 dark:text-gray-200',
                  'hover:bg-slate-200 dark:hover:bg-gray-700',
                  'disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                {running === 'share-log' ? <Loader2 size={14} className="animate-spin" /> : <ClipboardCopy size={14} />}
                Generar log para compartir
              </button>
            </div>
          </div>

          {/* Summary */}
          <div className="rounded-xl border border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
            <div className="flex items-center gap-4 mb-3">
              {report.status === 'healthy' ? (
                <CheckCircle size={24} className="text-emerald-500" />
              ) : report.status === 'critical' ? (
                <ShieldAlert size={24} className="text-red-500" />
              ) : (
                <AlertTriangle size={24} className="text-amber-500" />
              )}
              <div>
                <p className="font-semibold text-slate-900 dark:text-white">
                  {report.summary?.criticals > 0
                    ? `${report.summary.criticals} problema(s) crítico(s)`
                    : report.summary?.warnings > 0
                    ? `${report.summary.warnings} advertencia(s)`
                    : 'Todos los checks pasaron'}
                </p>
                <p className="text-xs text-slate-500 dark:text-gray-400">
                  {report.timestamp ? new Date(report.timestamp).toLocaleString() : ''}
                </p>
              </div>
            </div>

            {report.summary?.issues_list?.length > 0 && (
              <ul className="space-y-1 mt-2">
                {report.summary.issues_list.map((issue, i) => (
                  <li
                    key={i}
                    className={cn(
                      'text-sm px-3 py-2 rounded-lg',
                      issue.startsWith('🔴')
                        ? 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300'
                        : 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300'
                    )}
                  >
                    {issue}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Individual checks detail */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {Object.entries(report.checks).map(([key, check]) => (
              <div
                key={key}
                className={cn(
                  'rounded-xl border p-4 transition-colors',
                  'bg-white dark:bg-gray-900',
                  check.healthy
                    ? 'border-slate-200 dark:border-gray-800'
                    : check.issues.some(i => i.startsWith('🔴'))
                    ? 'border-red-200 dark:border-red-800'
                    : 'border-amber-200 dark:border-amber-800'
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold text-sm text-slate800 dark:text-gray-200 capitalize">
                    {key.replace('_', ' ')}
                  </h3>
                  {check.healthy ? (
                    <CheckCircle size={16} className="text-emerald-500" />
                  ) : (
                    <AlertTriangle size={16} className="text-amber-500" />
                  )}
                </div>

                {Object.entries(check.info || {}).length > 0 && (
                  <div className="space-y-1 mb-2">
                    {Object.entries(check.info).map(([k, v]) => (
                      <div key={k} className="text-xs text-slate-600 dark:text-gray-400 flex justify-between">
                        <span className="capitalize">{k.replace(/_/g, ' ')}</span>
                        <span className="font-mono text-slate-800 dark:text-gray-200">
                          {typeof v === 'object' ? JSON.stringify(v).slice(0, 60) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {check.issues?.length > 0 && (
                  <ul className="space-y-1">
                    {check.issues.map((issue, i) => (
                      <li
                        key={i}
                        className={cn(
                          'text-xs px-2 py-1 rounded',
                          issue.startsWith('🔴')
                            ? 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                            : 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20'
                        )}
                      >
                        {issue}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Shareable Log */}
      {shareLog && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
              Log para compartir
            </h3>
            <button
              onClick={copyToClipboard}
              className={cn(
                'inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                copied
                  ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                  : 'bg-slate-100 dark:bg-gray-800 text-slate-700 dark:text-gray-200 hover:bg-slate-200 dark:hover:bg-gray-700'
              )}
            >
              <ClipboardCopy size={12} />
              {copied ? '¡Copiado!' : 'Copiar'}
            </button>
          </div>
          <pre className="rounded-xl border border-slate-200 dark:border-gray-800 bg-slate-50 dark:bg-gray-950 p-4 text-xs font-mono text-slate-700 dark:text-gray-300 overflow-auto max-h-96 whitespace-pre-wrap">
            {shareLog}
          </pre>
        </div>
      )}

      {/* Shadow Mode (Fase D) Monitor */}
      <div className="rounded-xl border border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History size={20} className="text-blue-600 dark:text-blue-400" />
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">
              Shadow Mode (Fase D)
            </h2>
          </div>
          <button
            onClick={runShadowCheck}
            disabled={shadowLoading}
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              'bg-blue-600 hover:bg-blue-700 text-white',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {shadowLoading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Ejecutar ahora
          </button>
        </div>

        <p className="text-sm text-slate-500 dark:text-gray-400">
          Monitor periódico de las predicciones shadow. Se ejecuta automáticamente cada 5 minutos.
          Últimas 20 ejecuciones:
        </p>

        {shadowHistory.length === 0 ? (
          <div className="text-sm text-slate-500 dark:text-gray-400">
            No hay historial aún. Ejecutá el check manualmente o esperá a la próxima pasada programada.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 dark:text-gray-400 border-b border-slate-200 dark:border-gray-800">
                  <th className="pb-2 font-medium">Hora</th>
                  <th className="pb-2 font-medium">Estado</th>
                  <th className="pb-2 font-medium">Candidato (total / resueltos / None)</th>
                  <th className="pb-2 font-medium">Live (total / None)</th>
                  <th className="pb-2 font-medium">Sharpe candidato / live</th>
                  <th className="pb-2 font-medium">Log</th>
                </tr>
              </thead>
              <tbody>
                {shadowHistory.map((entry, idx) => (
                  <tr
                    key={idx}
                    className="border-b border-slate-100 dark:border-gray-800/50 last:border-0"
                  >
                    <td className="py-3 text-slate-700 dark:text-gray-300">
                      {entry.checked_at ? new Date(entry.checked_at).toLocaleString() : '-'}
                    </td>
                    <td className="py-3">
                      {entry.healthy ? (
                        <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 text-xs font-medium">
                          <CheckCircle size={12} /> Sano
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400 text-xs font-medium">
                          <AlertTriangle size={12} /> Crítico
                        </span>
                      )}
                    </td>
                    <td className="py-3 text-slate-700 dark:text-gray-300">
                      {entry.candidate?.total_in_window ?? 0} / {entry.candidate?.resolved ?? 0} / {entry.candidate?.none_recent ?? 0}
                    </td>
                    <td className="py-3 text-slate-700 dark:text-gray-300">
                      {entry.live?.total_in_window ?? 0} / {entry.live?.none_recent ?? 0}
                    </td>
                    <td className="py-3 text-slate-700 dark:text-gray-300">
                      {entry.candidate_eval?.candidate_sharpe ?? '-'} / {entry.candidate_eval?.live_sharpe ?? '-'}
                    </td>
                    <td className="py-3">
                      <button
                        onClick={() => generateShadowLog(entry)}
                        disabled={running === 'shadow-log'}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-slate-100 dark:bg-gray-800 text-slate-700 dark:text-gray-200 hover:bg-slate-200 dark:hover:bg-gray-700 disabled:opacity-50"
                      >
                        {running === 'shadow-log' ? <Loader2 size={10} className="animate-spin" /> : <ClipboardCopy size={10} />}
                        Log
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {shadowLog && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                Log de Shadow Mode
              </h3>
              <button
                onClick={() => {
                  navigator.clipboard?.writeText(shadowLog).catch(() => {})
                }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-slate-100 dark:bg-gray-800 text-slate-700 dark:text-gray-200 hover:bg-slate-200 dark:hover:bg-gray-700"
              >
                <ClipboardCopy size={10} /> Copiar
              </button>
            </div>
            <pre className="rounded-xl border border-slate-200 dark:border-gray-800 bg-slate-50 dark:bg-gray-950 p-4 text-xs font-mono text-slate-700 dark:text-gray-300 overflow-auto max-h-96 whitespace-pre-wrap">
              {shadowLog}
            </pre>
          </div>
        )}
      </div>

      <EngineAIHelper page="admin-system" />
    </div>
  )
}
