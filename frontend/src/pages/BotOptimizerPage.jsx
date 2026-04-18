import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, ChevronDown, ChevronUp,
  Info, Loader2, Sparkles,
} from 'lucide-react'
import { optimizerService } from '@/services/optimizer'
import { botsService } from '@/services/bots'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

// ─── Helpers ──────────────────────────────────────────────────

function pct(v, decimals = 1) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(decimals)}%`
}

function fmt(v, decimals = 2) {
  if (v == null) return '—'
  return Number(v).toFixed(decimals)
}

function signed(v, decimals = 2, suffix = ' USDT') {
  if (v == null) return '—'
  const n = Number(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}${suffix}`
}

function volatilityLabel(pctMove) {
  if (pctMove > 5)   return { label: 'Muy alta', color: 'text-red-400' }
  if (pctMove > 3)   return { label: 'Alta',     color: 'text-orange-400' }
  if (pctMove > 1.5) return { label: 'Media',    color: 'text-yellow-400' }
  return               { label: 'Baja',           color: 'text-green-400' }
}

// ─── Subcomponentes ────────────────────────────────────────────

function StatCard({ label, value, sub, color = 'default', tooltip = null }) {
  const colors = {
    default: 'text-slate-900 dark:text-gray-100',
    green:   'text-green-500',
    red:     'text-red-400',
    yellow:  'text-yellow-400',
    blue:    'text-blue-400',
    orange:  'text-orange-400',
  }
  return (
    <div className="group relative bg-slate-50 dark:bg-gray-800/60 rounded-xl p-4 space-y-1 cursor-help">
      <div className="flex items-center gap-1">
        <p className="text-xs text-slate-500 dark:text-gray-400">{label}</p>
        {tooltip && (
          <Info size={12} className="text-slate-400 dark:text-gray-500 opacity-50 group-hover:opacity-100 transition-opacity" />
        )}
      </div>
      <p className={`text-xl font-bold ${colors[color]}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 dark:text-gray-500">{sub}</p>}
      {tooltip && (
        <div className="absolute z-10 invisible group-hover:visible bg-slate-800 dark:bg-gray-900 text-white text-xs p-2 rounded shadow-lg max-w-[200px] -top-2 left-1/2 -translate-x-1/2 -translate-y-full">
          {tooltip}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-800 dark:border-t-gray-900"></div>
        </div>
      )}
    </div>
  )
}

function DeltaBadge({ current, suggested }) {
  if (String(current) === String(suggested)) return (
    <span className="text-xs text-slate-400 dark:text-gray-500">Sin cambios</span>
  )
  const up = Number(suggested) > Number(current)
  return (
    <span className={`flex items-center gap-1 text-xs font-medium ${up ? 'text-green-400' : 'text-yellow-400'}`}>
      {up ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      {up ? '+' : ''}{(Number(suggested) - Number(current)).toFixed(2)}
    </span>
  )
}

function SuggestionRow({ label, current, suggested, unit = '', reason, onApply, applying }) {
  const [showReason, setShowReason] = useState(false)
  const changed = String(current) !== String(suggested)

  return (
    <div className={`border rounded-xl p-4 space-y-3 transition-colors ${
      changed
        ? 'border-blue-500/30 bg-blue-500/5'
        : 'border-slate-200 dark:border-gray-700 bg-slate-50 dark:bg-gray-800/40'
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2">
          <p className="text-sm font-medium text-slate-700 dark:text-gray-200">{label}</p>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="text-center">
              <p className="text-xs text-slate-400 dark:text-gray-500 mb-0.5">Actual</p>
              <p className="text-base font-mono font-semibold text-slate-600 dark:text-gray-300">
                {current}{unit}
              </p>
            </div>
            <ArrowRight size={14} className="text-slate-400 dark:text-gray-500 mt-3 shrink-0" />
            <div className="text-center">
              <p className="text-xs text-slate-400 dark:text-gray-500 mb-0.5">Sugerido</p>
              <p className={`text-base font-mono font-bold ${changed ? 'text-blue-400' : 'text-slate-600 dark:text-gray-300'}`}>
                {suggested}{unit}
              </p>
            </div>
            <DeltaBadge current={current} suggested={suggested} />
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 mt-1">
          <button onClick={() => setShowReason(s => !s)} className="p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-gray-200 rounded">
            <Info size={14} />
          </button>
          {changed && (
            <button onClick={onApply} disabled={applying}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">
              {applying ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Aplicar
            </button>
          )}
        </div>
      </div>
      {showReason && reason && (
        <p className="text-xs text-slate-500 dark:text-gray-400 border-t border-slate-200 dark:border-gray-700 pt-2">{reason}</p>
      )}
    </div>
  )
}

function TpSuggestionRow({ current, suggested, reason, onApply, applying }) {
  const [showReason, setShowReason] = useState(false)
  const hasChange = JSON.stringify(current) !== JSON.stringify(suggested)

  const renderTps = (tps) => {
    if (!tps || tps.length === 0) return <span className="text-slate-400 dark:text-gray-500 text-xs">Sin TPs</span>
    return (
      <div className="space-y-1 mt-1">
        {tps.map((tp, i) => (
          <div key={i} className="flex gap-2 text-xs font-mono">
            <span className="text-blue-400 w-16">TP{i + 1} {Number(tp.profit_percent).toFixed(1)}%</span>
            <span className="text-slate-400 dark:text-gray-500">→ cierra {Number(tp.close_percent).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className={`border rounded-xl p-4 space-y-3 transition-colors ${
      hasChange ? 'border-blue-500/30 bg-blue-500/5' : 'border-slate-200 dark:border-gray-700 bg-slate-50 dark:bg-gray-800/40'
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2">
          <p className="text-sm font-medium text-slate-700 dark:text-gray-200">Take Profits</p>
          <div className="flex gap-6 flex-wrap">
            <div><p className="text-xs text-slate-400 dark:text-gray-500 mb-0.5">Actual</p>{renderTps(current)}</div>
            <ArrowRight size={14} className="text-slate-400 dark:text-gray-500 mt-4 shrink-0" />
            <div><p className="text-xs text-slate-400 dark:text-gray-500 mb-0.5">Sugerido</p>{renderTps(suggested)}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 mt-1">
          <button onClick={() => setShowReason(s => !s)} className="p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-gray-200 rounded">
            <Info size={14} />
          </button>
          {hasChange && (
            <button onClick={onApply} disabled={applying}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">
              {applying ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Aplicar
            </button>
          )}
        </div>
      </div>
      {showReason && reason && (
        <p className="text-xs text-slate-500 dark:text-gray-400 border-t border-slate-200 dark:border-gray-700 pt-2">{reason}</p>
      )}
    </div>
  )
}

function ConfigSuggestionRow({ label, current, suggested, reason, onApply, applying, renderConfig }) {
  const [showReason, setShowReason] = useState(false)
  const hasChange = JSON.stringify(current) !== JSON.stringify(suggested)

  return (
    <div className={`border rounded-xl p-4 space-y-3 transition-colors ${
      hasChange ? 'border-blue-500/30 bg-blue-500/5' : 'border-slate-200 dark:border-gray-700 bg-slate-50 dark:bg-gray-800/40'
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2">
          <p className="text-sm font-medium text-slate-700 dark:text-gray-200">{label}</p>
          <div className="flex gap-6 flex-wrap">
            <div>
              <p className="text-xs text-slate-400 dark:text-gray-500 mb-1">Actual</p>
              {renderConfig(current)}
            </div>
            <ArrowRight size={14} className="text-slate-400 dark:text-gray-500 mt-4 shrink-0" />
            <div>
              <p className="text-xs text-slate-400 dark:text-gray-500 mb-1">Sugerido</p>
              {renderConfig(suggested)}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 mt-1">
          <button onClick={() => setShowReason(s => !s)} className="p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-gray-200 rounded">
            <Info size={14} />
          </button>
          {hasChange && (
            <button onClick={onApply} disabled={applying}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">
              {applying ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Aplicar
            </button>
          )}
        </div>
      </div>
      {showReason && reason && (
        <p className="text-xs text-slate-500 dark:text-gray-400 border-t border-slate-200 dark:border-gray-700 pt-2">{reason}</p>
      )}
    </div>
  )
}

function renderTrailing(cfg) {
  if (!cfg) return <span className="text-xs text-slate-400">—</span>
  return (
    <div className="space-y-0.5 text-xs font-mono">
      <div className={cfg.enabled ? 'text-green-400' : 'text-slate-400'}>{cfg.enabled ? 'Activado' : 'Desactivado'}</div>
      {cfg.enabled && <>
        <div className="text-slate-500 dark:text-gray-400">Activa en: {fmt(cfg.activation_profit)}%</div>
        <div className="text-slate-500 dark:text-gray-400">Callback: {fmt(cfg.callback_rate)}%</div>
      </>}
    </div>
  )
}

function renderBreakeven(cfg) {
  if (!cfg) return <span className="text-xs text-slate-400">—</span>
  return (
    <div className="space-y-0.5 text-xs font-mono">
      <div className={cfg.enabled ? 'text-green-400' : 'text-slate-400'}>{cfg.enabled ? 'Activado' : 'Desactivado'}</div>
      {cfg.enabled && <>
        <div className="text-slate-500 dark:text-gray-400">Activa en: {fmt(cfg.activation_profit)}%</div>
        <div className="text-slate-500 dark:text-gray-400">Lock: +{fmt(cfg.lock_profit)}%</div>
      </>}
    </div>
  )
}

function renderDynamic(cfg) {
  if (!cfg) return <span className="text-xs text-slate-400">—</span>
  return (
    <div className="space-y-0.5 text-xs font-mono">
      <div className={cfg.enabled ? 'text-green-400' : 'text-slate-400'}>{cfg.enabled ? 'Activado' : 'Desactivado'}</div>
      {cfg.enabled && <>
        <div className="text-slate-500 dark:text-gray-400">Paso: {fmt(cfg.step_percent)}%</div>
        <div className="text-slate-500 dark:text-gray-400">Máx pasos: {cfg.max_steps || '∞'}</div>
      </>}
    </div>
  )
}

// ─── Página principal ──────────────────────────────────────────

export default function BotOptimizerPage() {
  const { botId } = useParams()
  const navigate = useNavigate()

  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [applying, setApplying] = useState(null)
  const [applyAllLoading, setApplyAllLoading] = useState(false)

  const load = () => {
    setLoading(true)
    optimizerService.get(botId)
      .then(r => {
        console.log('Optimizer response:', r.data)
        setData(r.data)
      })
      .catch(() => setError('No se pudo cargar el análisis'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [botId])

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>
  if (error)   return <p className="text-red-400">{error}</p>
  if (!data)   return null

  const { analysis: a = {}, current: c = {}, suggestions: s = {}, cooldown = {} } = data

  const applyParam = async (key, value) => {
    setApplying(key)
    try {
      await optimizerService.apply(botId, { [key]: value })
      load()
    } catch (e) {
      alert(e.response?.data?.detail || 'Error al aplicar')
    } finally {
      setApplying(null)
    }
  }

  const applyAll = async () => {
    if (!window.confirm('¿Aplicar todas las sugerencias al bot?')) return
    setApplyAllLoading(true)
    try {
      const overrides = {}
      if (s.initial_sl_percentage)       overrides.initial_sl_percentage       = s.initial_sl_percentage.value
      if (s.take_profits)                overrides.take_profits                = s.take_profits.value
      if (s.leverage)                    overrides.leverage                    = s.leverage.value
      if (s.signal_confirmation_minutes) overrides.signal_confirmation_minutes = s.signal_confirmation_minutes.value
      if (s.trailing_config)             overrides.trailing_config             = s.trailing_config.value
      if (s.breakeven_config)            overrides.breakeven_config            = s.breakeven_config.value
      if (s.dynamic_sl_config)           overrides.dynamic_sl_config           = s.dynamic_sl_config.value
      await optimizerService.apply(botId, overrides)
      load()
    } catch (e) {
      alert(e.response?.data?.detail || 'Error al aplicar')
    } finally {
      setApplyAllLoading(false)
    }
  }

  const vol = a.avg_price_move_pct != null ? volatilityLabel(a.avg_price_move_pct) : null
  const hasSuggestions = Object.keys(s).length > 0

  return (
    <div className="max-w-2xl space-y-6">

      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => window.history.back()} className="btn-ghost p-2" title="Volver">
          <ArrowLeft size={16} />
        </button>
        <div>
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-blue-400" />
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">Optimizador</h1>
          </div>
          <p className="text-sm text-slate-500 dark:text-gray-400">{data.bot_name} · {data.symbol} · {data.timeframe}</p>
        </div>
      </div>

      {/* Aviso datos insuficientes */}
      {data.insufficient_data && (
        <div className="flex items-start gap-3 bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3">
          <AlertTriangle size={16} className="text-yellow-400 mt-0.5 shrink-0" />
          <p className="text-sm text-yellow-300">
            Solo {a.total_closed} trade{a.total_closed !== 1 ? 's' : ''} cerrado{a.total_closed !== 1 ? 's' : ''}.
            Las sugerencias son orientativas — se necesitan al menos 3 trades para mayor fiabilidad.
          </p>
        </div>
      )}

      {/* Debug - muestra raw data para troubleshooting */}
      {data && (
        <div className="text-xs font-mono text-slate-600 dark:text-slate-400 p-3 bg-slate-100 dark:bg-gray-800/80 rounded border border-slate-200 dark:border-gray-700">
          <div className="font-semibold mb-1">Debug Data:</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <div>Posiciones: <span className="font-bold">{data.debug?.positions_count ?? 'N/A'}</span></div>
            <div>Trades (exchange): <span className="font-bold">{data.debug?.trades_count ?? 'N/A'}</span></div>
            <div>Trade views: <span className="font-bold">{data.debug?.trade_views_count ?? 'N/A'}</span></div>
            <div>Mínimo requerido: <span className="font-bold">{data.debug?.min_required ?? 'N/A'}</span></div>
            <div>Símbolo bot: <span className="font-bold">{data.symbol || 'N/A'}</span></div>
            <div>Símbolo buscado: <span className="font-bold">{data.debug?.symbol_searched || 'N/A'}</span></div>
            <div>Data source: <span className="font-bold">{data.debug?.data_source || 'N/A'}</span></div>
          </div>
        </div>
      )}

      {a.total_closed === 0 ? (
        <div className="card text-center py-10 space-y-2">
          <p className="text-slate-500 dark:text-gray-400 text-sm">Sin trades cerrados aún.</p>
          <p className="text-slate-400 dark:text-gray-500 text-xs">El optimizador necesita historial de posiciones para generar sugerencias.</p>
        </div>
      ) : (
        <>
          {/* ── Métricas ── */}
          <div className="space-y-3">
            <h2 className="text-xs font-semibold text-slate-500 dark:text-gray-400 uppercase tracking-wide">
              Análisis · {a.total_closed} trades cerrados
            </h2>

            {/* Fila 1: resultados */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label="Win rate" value={pct(a.win_rate)}
                sub={`${a.winning}W / ${a.losing}L`}
                color={a.win_rate >= 0.55 ? 'green' : a.win_rate >= 0.45 ? 'yellow' : 'red'}
                tooltip="Porcentaje de trades ganadores. >55% es bueno, <45% necesita ajustes." />
              <StatCard label="Profit factor" value={a.profit_factor != null ? fmt(a.profit_factor) : '—'}
                sub="ganancia / pérdida"
                color={a.profit_factor >= 1.5 ? 'green' : a.profit_factor >= 1 ? 'yellow' : 'red'}
                tooltip="Ganancia total dividida entre pérdida total. >1.5 es rentable, >2 es muy bueno, >3 es excelente." />
              <StatCard label="Ratio R:R real" value={a.real_rr != null ? `${fmt(a.real_rr)}x` : '—'}
                sub="ganancia% / pérdida%"
                color={a.real_rr >= 1.5 ? 'green' : a.real_rr >= 1 ? 'yellow' : 'red'}
                tooltip="Ratio riesgo:beneficio real basado en movimientos de precio. >1.5 significa ganar 1.5 veces lo que arriesgas." />
              <StatCard label="Volatilidad activo"
                value={vol ? vol.label : '—'}
                sub={`${fmt(a.avg_price_move_pct)}% movimiento medio`}
                color={vol ? (vol.color.includes('red') ? 'red' : vol.color.includes('orange') ? 'orange' : vol.color.includes('yellow') ? 'yellow' : 'green') : 'default'}
                tooltip="Movimiento medio del precio entre entrada y salida. Indica qué tan volátil es el par." />
            </div>

            {/* Fila 2: P&L */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label="Media ganador" value={signed(a.avg_win_pnl)}
                sub={`${fmt(a.avg_win_pct)}% movimiento`} color="green"
                tooltip="Ganancia promedio en cada trade ganador." />
              <StatCard label="Media perdedor" value={signed(a.avg_loss_pnl)}
                sub={`${fmt(a.avg_loss_pct)}% movimiento`} color="red"
                tooltip="Pérdida promedio en cada trade perdedor." />
              <StatCard label="Dur. ganadores" value={`${fmt(a.avg_winner_hours, 1)}h`}
                sub="tiempo medio en win" color="green"
                tooltip="Tiempo promedio que dura un trade ganador antes de cerrarse." />
              <StatCard label="Dur. perdedores" value={`${fmt(a.avg_loser_hours, 1)}h`}
                sub="tiempo medio en loss" color="red"
                tooltip="Tiempo promedio que dura un trade perdedor antes de cerrarse." />
            </div>

            {/* Fila 3: SL + TP + señales */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label="SL hit rate" value={`${pct(a.sl_hit_rate, 0)}`}
                sub={`${a.sl_hit_count} de ${a.losing} pérdidas`}
                color={a.sl_hit_rate > 0.5 ? 'red' : a.sl_hit_rate > 0.3 ? 'yellow' : 'default'}
                tooltip="Porcentaje de pérdidas que fueron por Stop Loss. >50% indica SL muy ajustado." />
              <StatCard label="SL medio config." value={`${fmt(a.avg_sl_pct)}%`}
                sub="dist. entrada→SL"
                tooltip="Distancia media entre el precio de entrada y el Stop Loss configurado." />
              <StatCard label="TP1 alcanzado" value={a.tp1_reach_rate != null ? pct(a.tp1_reach_rate) : '—'}
                sub={a.avg_tp1_target != null ? `TP1 objetivo: ${fmt(a.avg_tp1_target)}%` : 'sin TPs configurados'}
                color={a.tp1_reach_rate >= 0.6 ? 'green' : a.tp1_reach_rate >= 0.35 ? 'yellow' : 'red'}
                tooltip="Porcentaje de ganadores que alcanzaron el primer Take Profit. >60% es excelente." />
              {a.signals_total > 0 && (
                <StatCard label="Señales filtradas" value={`${a.signals_cancelled}/${a.signals_total}`}
                  sub={pct(a.signals_cancel_rate)}
                  color={a.signals_cancel_rate > 0.2 ? 'yellow' : 'default'}
                  tooltip="Señales que fueron ignoradas por filtros anti-falsos (confirmación de tendencia)." />
              )}
            </div>
          </div>

          {/* ── Cooldown Banner ── */}
          {cooldown.active && (
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle size={18} className="text-amber-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-amber-800 dark:text-amber-400">
                    Optimización en espera
                  </p>
                  <p className="text-xs text-amber-700 dark:text-amber-500 mt-1">
                    Se aplicaron cambios recientemente. Espera {cooldown.trades_needed - cooldown.trades_since_apply} trades más 
                    para ver nuevas sugerencias (actual: {cooldown.trades_since_apply}/{cooldown.trades_needed}).
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* ── Sugerencias Aplicadas (en gris) ── */}
          {cooldown.applied_params && Object.keys(cooldown.applied_params).length > 0 && (
            <div className="space-y-3 opacity-60">
              <h2 className="text-xs font-semibold text-slate-400 dark:text-gray-500 uppercase tracking-wide">
                Parámetros aplicados
              </h2>
              <div className="bg-slate-100 dark:bg-gray-800/50 border border-slate-200 dark:border-gray-700 rounded-xl p-3">
                <div className="text-xs text-slate-500 dark:text-gray-400">
                  {Object.entries(cooldown.applied_params).map(([key, value]) => (
                    <div key={key} className="flex justify-between py-1">
                      <span>{key.replace(/_/g, ' ')}:</span>
                      <span className="font-mono">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-slate-400 dark:text-gray-500 mt-2 pt-2 border-t border-slate-200 dark:border-gray-700">
                  Aplicado el {cooldown.last_applied_at ? new Date(cooldown.last_applied_at).toLocaleDateString() : '—'}
                </p>
              </div>
            </div>
          )}

          {/* ── Sugerencias ── */}
          {hasSuggestions && !cooldown.active && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold text-slate-500 dark:text-gray-400 uppercase tracking-wide">
                  Sugerencias de parámetros
                </h2>
                <button onClick={applyAll} disabled={applyAllLoading}
                  className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">
                  {applyAllLoading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                  Aplicar todo
                </button>
              </div>

              <div className="space-y-3">
                {s.leverage && (
                  <SuggestionRow label="Apalancamiento"
                    current={c.leverage} suggested={s.leverage.value} unit="x"
                    reason={s.leverage.reason}
                    onApply={() => applyParam('leverage', s.leverage.value)}
                    applying={applying === 'leverage'} />
                )}

                {s.initial_sl_percentage && (
                  <SuggestionRow label="Stop Loss inicial"
                    current={fmt(c.initial_sl_percentage)} suggested={fmt(s.initial_sl_percentage.value)} unit="%"
                    reason={s.initial_sl_percentage.reason}
                    onApply={() => applyParam('initial_sl_percentage', s.initial_sl_percentage.value)}
                    applying={applying === 'initial_sl_percentage'} />
                )}

                {s.take_profits && (
                  <TpSuggestionRow
                    current={c.take_profits} suggested={s.take_profits.value}
                    reason={s.take_profits.reason}
                    onApply={() => applyParam('take_profits', s.take_profits.value)}
                    applying={applying === 'take_profits'} />
                )}

                {s.trailing_config && (
                  <ConfigSuggestionRow label="Trailing Stop"
                    current={c.trailing_config} suggested={s.trailing_config.value}
                    reason={s.trailing_config.reason}
                    onApply={() => applyParam('trailing_config', s.trailing_config.value)}
                    applying={applying === 'trailing_config'}
                    renderConfig={renderTrailing} />
                )}

                {s.breakeven_config && (
                  <ConfigSuggestionRow label="Breakeven"
                    current={c.breakeven_config} suggested={s.breakeven_config.value}
                    reason={s.breakeven_config.reason}
                    onApply={() => applyParam('breakeven_config', s.breakeven_config.value)}
                    applying={applying === 'breakeven_config'}
                    renderConfig={renderBreakeven} />
                )}

                {s.dynamic_sl_config && (
                  <ConfigSuggestionRow label="Stop Dinámico"
                    current={c.dynamic_sl_config} suggested={s.dynamic_sl_config.value}
                    reason={s.dynamic_sl_config.reason}
                    onApply={() => applyParam('dynamic_sl_config', s.dynamic_sl_config.value)}
                    applying={applying === 'dynamic_sl_config'}
                    renderConfig={renderDynamic} />
                )}

                {s.signal_confirmation_minutes && (
                  <SuggestionRow label="Confirmación de señal"
                    current={c.signal_confirmation_minutes} suggested={s.signal_confirmation_minutes.value} unit=" min"
                    reason={s.signal_confirmation_minutes.reason}
                    onApply={() => applyParam('signal_confirmation_minutes', s.signal_confirmation_minutes.value)}
                    applying={applying === 'signal_confirmation_minutes'} />
                )}
              </div>

              <p className="text-xs text-slate-400 dark:text-gray-500">
                Pulsa <Info size={11} className="inline" /> para ver el razonamiento.
                Los cambios se guardan en el bot pero no lo activan.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─── Helper: construir payload completo para PUT /bots/{id} ───

function _buildPayload(bot, overrides = {}) {
  const tr = overrides.trailing_config   ?? bot.trailing_config   ?? {}
  const be = overrides.breakeven_config  ?? bot.breakeven_config  ?? {}
  const dy = overrides.dynamic_sl_config ?? bot.dynamic_sl_config ?? {}
  const tps = overrides.take_profits     ?? bot.take_profits      ?? []

  const payload = {
    bot_name:             bot.bot_name,
    symbol:               bot.symbol,
    timeframe:            bot.timeframe,
    leverage:             overrides.leverage !== undefined ? Number(overrides.leverage) : bot.leverage,
    position_sizing_type: bot.position_sizing_type,
    position_value:       parseFloat(bot.position_value),
    initial_sl_percentage: overrides.initial_sl_percentage !== undefined
      ? Number(overrides.initial_sl_percentage)
      : parseFloat(bot.initial_sl_percentage),
    signal_confirmation_minutes: overrides.signal_confirmation_minutes !== undefined
      ? Number(overrides.signal_confirmation_minutes)
      : (bot.signal_confirmation_minutes ?? 0),
    take_profits: tps.map(tp => ({
      profit_percent: parseFloat(tp.profit_percent),
      close_percent:  parseFloat(tp.close_percent),
    })),
    trailing_config: {
      enabled:           tr.enabled ?? false,
      activation_profit: parseFloat(tr.activation_profit) || 0,
      callback_rate:     parseFloat(tr.callback_rate) || 0,
    },
    breakeven_config: {
      enabled:           be.enabled ?? false,
      activation_profit: parseFloat(be.activation_profit) || 0,
      lock_profit:       parseFloat(be.lock_profit) || 0,
    },
    dynamic_sl_config: {
      enabled:      dy.enabled ?? false,
      step_percent: parseFloat(dy.step_percent) || 0,
      max_steps:    parseInt(dy.max_steps) || 0,
    },
  }

  if (bot.paper_balance_id) {
    payload.paper_balance_id = bot.paper_balance_id
  } else {
    payload.exchange_account_id = bot.exchange_account_id
  }

  return payload
}
