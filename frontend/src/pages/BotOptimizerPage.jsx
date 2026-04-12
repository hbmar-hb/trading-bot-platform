import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, ChevronDown, ChevronUp,
  Info, Loader2, Sparkles, TrendingDown, TrendingUp,
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

// ─── Subcomponentes ────────────────────────────────────────────

function StatCard({ label, value, sub, color = 'default' }) {
  const colors = {
    default: 'text-slate-900 dark:text-gray-100',
    green:   'text-green-500',
    red:     'text-red-400',
    yellow:  'text-yellow-400',
    blue:    'text-blue-400',
  }
  return (
    <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl p-4 space-y-1">
      <p className="text-xs text-slate-500 dark:text-gray-400">{label}</p>
      <p className={`text-xl font-bold ${colors[color]}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 dark:text-gray-500">{sub}</p>}
    </div>
  )
}

function DeltaBadge({ current, suggested }) {
  if (current === suggested) return (
    <span className="text-xs text-slate-400 dark:text-gray-500">Sin cambios</span>
  )
  const up = suggested > current
  return (
    <span className={`flex items-center gap-1 text-xs font-medium ${up ? 'text-green-400' : 'text-yellow-400'}`}>
      {up ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      {up ? '+' : ''}{(Number(suggested) - Number(current)).toFixed(2)}
    </span>
  )
}

function SuggestionRow({ icon, label, current, suggested, unit = '', reason, onApply, applying }) {
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
            {/* Actual */}
            <div className="text-center">
              <p className="text-xs text-slate-400 dark:text-gray-500 mb-0.5">Actual</p>
              <p className="text-base font-mono font-semibold text-slate-600 dark:text-gray-300">
                {current}{unit}
              </p>
            </div>

            <ArrowRight size={14} className="text-slate-400 dark:text-gray-500 mt-3 shrink-0" />

            {/* Sugerido */}
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
          <button
            onClick={() => setShowReason(s => !s)}
            className="p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-gray-200 rounded transition-colors"
            title="Ver razonamiento"
          >
            <Info size={14} />
          </button>
          {changed && (
            <button
              onClick={onApply}
              disabled={applying}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 transition-colors"
            >
              {applying ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Aplicar
            </button>
          )}
        </div>
      </div>

      {showReason && reason && (
        <p className="text-xs text-slate-500 dark:text-gray-400 border-t border-slate-200 dark:border-gray-700 pt-2">
          {reason}
        </p>
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
      hasChange
        ? 'border-blue-500/30 bg-blue-500/5'
        : 'border-slate-200 dark:border-gray-700 bg-slate-50 dark:bg-gray-800/40'
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2">
          <p className="text-sm font-medium text-slate-700 dark:text-gray-200">Take Profits</p>
          <div className="flex gap-6 flex-wrap">
            <div>
              <p className="text-xs text-slate-400 dark:text-gray-500 mb-0.5">Actual</p>
              {renderTps(current)}
            </div>
            <ArrowRight size={14} className="text-slate-400 dark:text-gray-500 mt-4 shrink-0" />
            <div>
              <p className="text-xs text-slate-400 dark:text-gray-500 mb-0.5">Sugerido</p>
              {renderTps(suggested)}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 mt-1">
          <button
            onClick={() => setShowReason(s => !s)}
            className="p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-gray-200 rounded transition-colors"
          >
            <Info size={14} />
          </button>
          {hasChange && (
            <button
              onClick={onApply}
              disabled={applying}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 transition-colors"
            >
              {applying ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Aplicar
            </button>
          )}
        </div>
      </div>
      {showReason && reason && (
        <p className="text-xs text-slate-500 dark:text-gray-400 border-t border-slate-200 dark:border-gray-700 pt-2">
          {reason}
        </p>
      )}
    </div>
  )
}

// ─── Página principal ──────────────────────────────────────────

export default function BotOptimizerPage() {
  const { botId } = useParams()
  const navigate = useNavigate()

  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [applying, setApplying] = useState(null)   // key del parámetro aplicándose
  const [applied, setApplied]   = useState({})      // {key: true}
  const [applyAllLoading, setApplyAllLoading] = useState(false)

  useEffect(() => {
    optimizerService.get(botId)
      .then(r => setData(r.data))
      .catch(() => setError('No se pudo cargar el análisis'))
      .finally(() => setLoading(false))
  }, [botId])

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>
  if (error)   return <p className="text-red-400">{error}</p>
  if (!data)   return null

  const { analysis: a, current: c, suggestions: s } = data

  // Aplica un único parámetro al bot (fetch config actual → patch)
  const applyParam = async (key, value) => {
    setApplying(key)
    try {
      const { data: bot } = await botsService.get(botId)
      const payload = _buildPayload(bot, { [key]: value })
      await botsService.update(botId, payload)
      setApplied(prev => ({ ...prev, [key]: true }))
      // Refrescar data
      const { data: fresh } = await optimizerService.get(botId)
      setData(fresh)
    } catch (e) {
      alert(e.response?.data?.detail || 'Error al aplicar')
    } finally {
      setApplying(null)
    }
  }

  // Aplica todas las sugerencias a la vez
  const applyAll = async () => {
    if (!window.confirm('¿Aplicar todas las sugerencias al bot?')) return
    setApplyAllLoading(true)
    try {
      const { data: bot } = await botsService.get(botId)
      const overrides = {}
      if (s.initial_sl_percentage) overrides.initial_sl_percentage = s.initial_sl_percentage.value
      if (s.take_profits)          overrides.take_profits          = s.take_profits.value
      if (s.leverage)              overrides.leverage              = s.leverage.value
      if (s.signal_confirmation_minutes) overrides.signal_confirmation_minutes = s.signal_confirmation_minutes.value
      const payload = _buildPayload(bot, overrides)
      await botsService.update(botId, payload)
      const { data: fresh } = await optimizerService.get(botId)
      setData(fresh)
      setApplied({ initial_sl_percentage: true, take_profits: true, leverage: true, signal_confirmation_minutes: true })
    } catch (e) {
      alert(e.response?.data?.detail || 'Error al aplicar')
    } finally {
      setApplyAllLoading(false)
    }
  }

  const hasAnySuggestion = Object.keys(s).length > 0
  const hasPendingChanges = s.initial_sl_percentage || s.take_profits || s.leverage || s.signal_confirmation_minutes

  return (
    <div className="max-w-2xl space-y-6">

      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/bots')} className="btn-ghost p-2">
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

      {/* Warning datos insuficientes */}
      {data.insufficient_data && (
        <div className="flex items-start gap-3 bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3">
          <AlertTriangle size={16} className="text-yellow-400 mt-0.5 shrink-0" />
          <p className="text-sm text-yellow-300">
            Solo {a.total_closed} trade{a.total_closed !== 1 ? 's' : ''} cerrado{a.total_closed !== 1 ? 's' : ''}.
            Las sugerencias son orientativas — se necesitan al menos 5 trades para fiabilidad estadística.
          </p>
        </div>
      )}

      {/* Sin trades */}
      {a.total_closed === 0 && (
        <div className="card text-center py-10 space-y-2">
          <p className="text-slate-500 dark:text-gray-400 text-sm">Sin trades cerrados aún.</p>
          <p className="text-slate-400 dark:text-gray-500 text-xs">El optimizador necesita historial de posiciones para generar sugerencias.</p>
        </div>
      )}

      {/* Métricas */}
      {a.total_closed > 0 && (
        <>
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-300 uppercase tracking-wide">
              Análisis histórico — {a.total_closed} trades
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard
                label="Win rate"
                value={pct(a.win_rate)}
                sub={`${a.winning}W / ${a.losing}L`}
                color={a.win_rate >= 0.55 ? 'green' : a.win_rate >= 0.45 ? 'yellow' : 'red'}
              />
              <StatCard
                label="Profit factor"
                value={a.profit_factor != null ? fmt(a.profit_factor) : '—'}
                sub="ganancia / pérdida"
                color={a.profit_factor >= 1.5 ? 'green' : a.profit_factor >= 1 ? 'yellow' : 'red'}
              />
              <StatCard
                label="Media ganador"
                value={signed(a.avg_win_pnl)}
                sub={`${fmt(a.avg_win_pct)}% nominal`}
                color="green"
              />
              <StatCard
                label="Media perdedor"
                value={signed(a.avg_loss_pnl)}
                sub={`${fmt(a.avg_loss_pct)}% nominal`}
                color="red"
              />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard
                label="Duración media"
                value={`${fmt(a.avg_duration_hours, 1)}h`}
                sub="todas las ops."
              />
              <StatCard
                label="Dur. ganadores"
                value={`${fmt(a.avg_winner_hours, 1)}h`}
                color="green"
              />
              <StatCard
                label="Dur. perdedores"
                value={`${fmt(a.avg_loser_hours, 1)}h`}
                color="red"
              />
              <StatCard
                label="Golpes SL"
                value={`${a.sl_hit_count} (${pct(a.sl_hit_rate, 0)})`}
                sub={`SL medio ${fmt(a.avg_sl_pct)}%`}
                color={a.sl_hit_rate > 0.5 ? 'red' : 'default'}
              />
            </div>

            {a.signals_total > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <StatCard
                  label="Señales recibidas"
                  value={a.signals_total}
                  sub="long + short"
                />
                <StatCard
                  label="Filtradas (anti-falso)"
                  value={a.signals_cancelled}
                  sub={pct(a.signals_cancel_rate)}
                  color={a.signals_cancel_rate > 0.2 ? 'yellow' : 'default'}
                />
                <StatCard
                  label="Ejecutadas"
                  value={a.signals_total - a.signals_cancelled}
                  sub="llegaron al exchange"
                  color="blue"
                />
              </div>
            )}
          </div>

          {/* Sugerencias */}
          {hasAnySuggestion && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-300 uppercase tracking-wide">
                  Sugerencias de parámetros
                </h2>
                {hasPendingChanges && (
                  <button
                    onClick={applyAll}
                    disabled={applyAllLoading}
                    className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 transition-colors"
                  >
                    {applyAllLoading
                      ? <Loader2 size={12} className="animate-spin" />
                      : <Sparkles size={12} />
                    }
                    Aplicar todo
                  </button>
                )}
              </div>

              <div className="space-y-3">
                {s.initial_sl_percentage && (
                  <SuggestionRow
                    label="Stop Loss inicial"
                    current={fmt(c.initial_sl_percentage)}
                    suggested={fmt(s.initial_sl_percentage.value)}
                    unit="%"
                    reason={s.initial_sl_percentage.reason}
                    onApply={() => applyParam('initial_sl_percentage', s.initial_sl_percentage.value)}
                    applying={applying === 'initial_sl_percentage'}
                  />
                )}

                {s.take_profits && (
                  <TpSuggestionRow
                    current={c.take_profits}
                    suggested={s.take_profits.value}
                    reason={s.take_profits.reason}
                    onApply={() => applyParam('take_profits', s.take_profits.value)}
                    applying={applying === 'take_profits'}
                  />
                )}

                {s.leverage && (
                  <SuggestionRow
                    label="Apalancamiento"
                    current={c.leverage}
                    suggested={s.leverage.value}
                    unit="x"
                    reason={s.leverage.reason}
                    onApply={() => applyParam('leverage', s.leverage.value)}
                    applying={applying === 'leverage'}
                  />
                )}

                {s.signal_confirmation_minutes && (
                  <SuggestionRow
                    label="Confirmación de señal"
                    current={c.signal_confirmation_minutes}
                    suggested={s.signal_confirmation_minutes.value}
                    unit=" min"
                    reason={s.signal_confirmation_minutes.reason}
                    onApply={() => applyParam('signal_confirmation_minutes', s.signal_confirmation_minutes.value)}
                    applying={applying === 'signal_confirmation_minutes'}
                  />
                )}
              </div>

              <p className="text-xs text-slate-400 dark:text-gray-500">
                Pulsa el icono <Info size={11} className="inline" /> en cada fila para ver el razonamiento.
                Los cambios aplican al bot pero no lo activan.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─── Helper: construir payload PUT /bots/{id} ──────────────────

function _buildPayload(bot, overrides = {}) {
  const tr = bot.trailing_config  ?? {}
  const be = bot.breakeven_config ?? {}
  const dy = bot.dynamic_sl_config ?? {}

  const tpSource = overrides.take_profits !== undefined
    ? overrides.take_profits
    : (bot.take_profits ?? [])

  const payload = {
    bot_name:              bot.bot_name,
    symbol:                bot.symbol,
    timeframe:             bot.timeframe,
    leverage:              overrides.leverage !== undefined ? Number(overrides.leverage) : bot.leverage,
    position_sizing_type:  bot.position_sizing_type,
    position_value:        parseFloat(bot.position_value),
    initial_sl_percentage: overrides.initial_sl_percentage !== undefined
      ? Number(overrides.initial_sl_percentage)
      : parseFloat(bot.initial_sl_percentage),
    signal_confirmation_minutes: overrides.signal_confirmation_minutes !== undefined
      ? Number(overrides.signal_confirmation_minutes)
      : (bot.signal_confirmation_minutes ?? 0),
    take_profits: tpSource.map(tp => ({
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
