/**
 * AIDashboardTab — Panel visual del motor IA
 * Muestra salud del modelo, equity curve, funnel de señales,
 * matriz tier×status y feature importance.
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, Legend,
} from 'recharts'
import {
  Activity, Award, Brain, ChevronUp, ChevronDown, Minus,
  RefreshCw, ShieldCheck, Target, TrendingUp, TrendingDown, Zap,
  HelpCircle, ShieldAlert, Layers,
} from 'lucide-react'
import { aiService } from '@/services/aiService'
import { cn } from '@/utils/cn'

// ─── helpers ─────────────────────────────────────────────────────────────────

const fmt2   = (n) => n == null ? '—' : Number(n).toFixed(2)
const fmt1   = (n) => n == null ? '—' : Number(n).toFixed(1)
const fmtPct = (n) => n == null ? '—' : `${Number(n).toFixed(1)}%`
const fmtPnl = (n) => {
  if (n == null) return '—'
  const v = Number(n)
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)} USDT`
}

const TIER_ORDER   = ['STRONG', 'MODERATE', 'WEAK']
const STATUS_ORDER = ['CLEAR', 'CAUTION', 'BLOCK']

const TIER_COLOR = {
  STRONG:   { bg: 'bg-emerald-500/15 dark:bg-emerald-500/20', text: 'text-emerald-600 dark:text-emerald-400' },
  MODERATE: { bg: 'bg-blue-500/15 dark:bg-blue-500/20',       text: 'text-blue-600 dark:text-blue-400' },
  WEAK:     { bg: 'bg-slate-400/15 dark:bg-slate-500/20',     text: 'text-slate-500 dark:text-slate-400' },
}

const STATUS_COLOR = {
  CLEAR:   'text-emerald-600 dark:text-emerald-400',
  CAUTION: 'text-amber-600 dark:text-amber-400',
  BLOCK:   'text-red-600 dark:text-red-400',
}

const wrColor = (wr) => {
  if (wr == null) return 'bg-slate-100 dark:bg-slate-800 text-slate-400'
  if (wr >= 60)   return 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400'
  if (wr >= 45)   return 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400'
  return 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400'
}

// ─── Info Tooltip ─────────────────────────────────────────────────────────────

function InfoTooltip({ text }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  return (
    <span className="relative inline-block" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 focus:outline-none"
        title="Más información"
      >
        <HelpCircle size={14} />
      </button>
      {open && (
        <div className="absolute z-50 left-0 top-5 w-64 p-2.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
          {text}
        </div>
      )}
    </span>
  )
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({ icon: Icon, label, value, sub, trend, color = 'blue', info }) {
  const colors = {
    blue:    'bg-blue-500/10 text-blue-600 dark:text-blue-400',
    emerald: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    violet:  'bg-violet-500/10 text-violet-600 dark:text-violet-400',
    amber:   'bg-amber-500/10 text-amber-600 dark:text-amber-400',
    rose:    'bg-rose-500/10 text-rose-600 dark:text-rose-400',
    slate:   'bg-slate-500/10 text-slate-600 dark:text-slate-400',
  }
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className={cn('p-2 rounded-lg', colors[color]?.split(' ')[0])}>
            <Icon size={15} className={colors[color]?.split(' ').slice(1).join(' ')} />
          </span>
          {info && <InfoTooltip text={info} />}
        </div>
        {trend != null && (
          <span className={cn('text-xs font-semibold flex items-center gap-0.5',
            trend > 0 ? 'text-emerald-500' : trend < 0 ? 'text-red-500' : 'text-slate-400'
          )}>
            {trend > 0 ? <ChevronUp size={12} /> : trend < 0 ? <ChevronDown size={12} /> : <Minus size={12} />}
            {Math.abs(trend).toFixed(1)}%
          </span>
        )}
      </div>
      <div>
        <p className="text-2xl font-bold text-slate-900 dark:text-white tabular-nums">{value}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{label}</p>
        {sub && <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

// ─── Model Health Card ────────────────────────────────────────────────────────

function ModelHealthCard({ health, info }) {
  if (!health) return null
  // AUC is 0-1 score, never percentage. Accuracy shown as %.
  const aucRaw = health.ensemble_auc ?? health.oof_auc ?? health.auc
  const auc = aucRaw != null ? aucRaw.toFixed(4) : null
  const accRaw = health.ensemble_accuracy ?? health.oof_accuracy ?? health.accuracy
  const acc = accRaw != null ? (accRaw * 100).toFixed(1) : null

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Brain size={15} className="text-violet-500" />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">XGBoost Anti-Fake</span>
        {info && <InfoTooltip text={info} />}
        {health.model_ready
          ? <span className="ml-auto text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400">ACTIVO</span>
          : <span className="ml-auto text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500">ENTRENANDO</span>
        }
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3">
        {[
          { label: 'AUC-ROC', value: auc ?? '—', good: (aucRaw ?? 0) >= 0.70 },
          { label: 'Accuracy', value: acc != null ? `${acc}%` : '—', good: (accRaw ?? 0) >= 0.80 },
          { label: 'Muestras', value: health.samples?.toLocaleString() ?? '—', good: health.samples >= 500 },
        ].map(m => (
          <div key={m.label} className="text-center p-2 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
            <p className={cn('text-lg font-bold tabular-nums', m.good ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-700 dark:text-slate-300')}>{m.value}</p>
            <p className="text-[10px] text-slate-400">{m.label}</p>
          </div>
        ))}
      </div>

      {health.last_trained_at && (
        <p className="text-[11px] text-slate-400 dark:text-slate-500">
          Último entreno: {new Date(health.last_trained_at).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' })}
          {' · '}{health.reason === 'first_training' ? 'Entrenamiento inicial' : health.reason}
        </p>
      )}
    </div>
  )
}

// ─── Equity Curve Chart ───────────────────────────────────────────────────────

function EquityCurveChart({ data }) {
  if (!data?.length) return <EmptyState label="Sin trades registrados aún" />

  const hasData = data.some(d => d.daily_pnl !== 0)
  if (!hasData) return <EmptyState label="Sin trades cerrados en los últimos 60 días" />

  const finalPnl   = data[data.length - 1]?.cumulative_pnl ?? 0
  const isPositive = finalPnl >= 0

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-2 text-xs shadow-lg">
        <p className="font-semibold text-slate-600 dark:text-slate-300 mb-1">{label}</p>
        <p className="text-slate-500">Diario: <span className={payload[0]?.value >= 0 ? 'text-emerald-500' : 'text-red-500'}>{fmtPnl(payload[0]?.value)}</span></p>
        <p className="text-slate-500">Acumulado: <span className={payload[1]?.value >= 0 ? 'text-emerald-500' : 'text-red-500'}>{fmtPnl(payload[1]?.value)}</span></p>
      </div>
    )
  }

  // Reducir densidad de puntos en eje X
  const tickData = data.filter((_, i) => i % 7 === 0 || i === data.length - 1)
  const ticks    = tickData.map(d => d.date)

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
        <defs>
          <linearGradient id="gradCumPnl" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={isPositive ? '#10b981' : '#ef4444'} stopOpacity={0.25} />
            <stop offset="95%" stopColor={isPositive ? '#10b981' : '#ef4444'} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
        <XAxis dataKey="date" ticks={ticks} tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={v => `${v.toFixed(0)}`} width={48} />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="daily_pnl" fill="rgba(99,102,241,0.4)" radius={[2, 2, 0, 0]} maxBarSize={8} />
        <Area
          type="monotone" dataKey="cumulative_pnl"
          stroke={isPositive ? '#10b981' : '#ef4444'}
          strokeWidth={2}
          fill="url(#gradCumPnl)"
          dot={false}
          activeDot={{ r: 3 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ─── Signal Funnel ────────────────────────────────────────────────────────────

function SignalFunnel({ data }) {
  if (!data?.length) return <EmptyState label="Sin señales en los últimos 30 días" />
  const max = data[0]?.value || 1

  return (
    <div className="space-y-2">
      {data.map((d, i) => {
        const pct = Math.round(d.value / max * 100)
        const rate = i > 0 && data[i - 1]?.value
          ? Math.round(d.value / data[i - 1].value * 100)
          : null
        return (
          <div key={d.stage}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">{d.stage}</span>
              <div className="flex items-center gap-2">
                {rate != null && (
                  <span className="text-[10px] text-slate-400">→ {rate}%</span>
                )}
                <span className="text-sm font-bold text-slate-800 dark:text-slate-200 tabular-nums">{d.value.toLocaleString()}</span>
              </div>
            </div>
            <div className="h-6 bg-slate-100 dark:bg-slate-800 rounded-md overflow-hidden">
              <div
                className="h-full rounded-md flex items-center pl-2 transition-all duration-700"
                style={{ width: `${Math.max(pct, 4)}%`, backgroundColor: d.color }}
              >
                {pct > 15 && <span className="text-[10px] text-white font-semibold">{pct}%</span>}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Tier × Status Matrix ─────────────────────────────────────────────────────

function TierMatrix({ data }) {
  if (!data?.length) return <EmptyState label="Sin datos suficientes (mín. 1 señal resuelta)" />

  // Construir mapa lookup
  const map = {}
  data.forEach(cell => {
    map[`${cell.tier}|${cell.status}`] = cell
  })

  const tiers   = TIER_ORDER.filter(t => data.some(d => d.tier === t))
  const statuses = STATUS_ORDER.filter(s => data.some(d => d.status === s))

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-center text-xs">
        <thead>
          <tr>
            <th className="pb-2 text-left text-slate-400 font-normal pr-2">Tier \ Status</th>
            {statuses.map(s => (
              <th key={s} className={cn('pb-2 font-semibold', STATUS_COLOR[s])}>{s}</th>
            ))}
          </tr>
        </thead>
        <tbody className="space-y-1">
          {tiers.map(tier => (
            <tr key={tier}>
              <td className={cn('pr-3 py-1 text-left font-semibold', TIER_COLOR[tier]?.text)}>{tier}</td>
              {statuses.map(status => {
                const cell = map[`${tier}|${status}`]
                if (!cell) return <td key={status} className="py-1"><span className="text-slate-300 dark:text-slate-600">—</span></td>
                return (
                  <td key={status} className="py-1">
                    <div className={cn('inline-flex flex-col items-center px-3 py-1.5 rounded-lg', wrColor(cell.win_rate))}>
                      <span className="text-sm font-bold">{fmtPct(cell.win_rate)}</span>
                      <span className="text-[9px] opacity-70">{cell.total} señales</span>
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-2">
        Verde ≥60% · Ámbar 45–60% · Rojo &lt;45% · Últimos 30 días
      </p>
      <p className="text-[9px] text-slate-400 dark:text-slate-500 mt-1 italic">
        ℹ️ Estas son señales teóricas (backtest TP1 vs SL en OHLCV). No incluyen slippage, fees ni ejecución real.
      </p>
    </div>
  )
}

// ─── Feature Importance Chart ─────────────────────────────────────────────────

const FEATURE_LABELS = {
  ob_distance_atr:  'OB Distance (ATR)',
  trigger_fvg:      'Trigger: FVG',
  trigger_ob:       'Trigger: OB',
  bias_bull:        'Sesgo Alcista',
  hour_utc:         'Hora UTC',
  fvg_aligned_count:'FVGs Alineados',
  sweep_detected:   'Liquidity Sweep',
  pd_position:      'Premium/Discount',
  volume_ratio:     'Vol. Ratio',
  spread_atr:       'Spread/ATR',
  score:            'Puntuación',
  day_of_week:      'Día Semana',
  eq_highs_count:   'EQ Highs',
  eq_lows_count:    'EQ Lows',
  sweep_bool:       'Sweep (bool)',
  break_choch:      'Break: CHoCH',
}

function FeatureImportanceChart({ data }) {
  if (!data?.length) return <EmptyState label="Modelo no entrenado aún" />

  const labeled = data.map(d => ({ ...d, label: FEATURE_LABELS[d.feature] || d.feature }))

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 text-xs shadow-lg">
        <p className="font-semibold text-slate-700 dark:text-slate-300">{payload[0]?.payload?.label}</p>
        <p className="text-violet-600 dark:text-violet-400">Importancia: {fmt1(payload[0]?.value)}%</p>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={labeled} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="rgba(148,163,184,0.15)" />
        <XAxis type="number" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}%`} />
        <YAxis type="category" dataKey="label" width={110} tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="importance" radius={[0, 4, 4, 0]} maxBarSize={14}>
          {labeled.map((_, i) => (
            <Cell key={i} fill={`hsl(${260 - i * 18}, 70%, ${55 + i * 3}%)`} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// ─── Rolling Win Rate ─────────────────────────────────────────────────────────

function RollingWinRateChart({ data }) {
  if (!data?.length) return <EmptyState label="Sin datos suficientes" />

  const hasData = data.some(d => d.win_rate != null)
  if (!hasData) return <EmptyState label="Sin señales resueltas en los últimos 30 días" />

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 text-xs shadow-lg">
        <p className="font-semibold text-slate-600 dark:text-slate-300 mb-1">{label} (ventana 7d)</p>
        <p className="text-blue-600 dark:text-blue-400">Win rate: {payload[0]?.value != null ? fmtPct(payload[0]?.value) : '—'}</p>
        <p className="text-slate-400">N señales: {payload[0]?.payload?.n_signals}</p>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={160}>
      <AreaChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
        <defs>
          <linearGradient id="gradWr" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.25} />
            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
        <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false}
          tickFormatter={d => d?.slice(5)} interval="preserveStartEnd" />
        <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false}
          tickFormatter={v => `${v}%`} domain={[0, 100]} width={36} />
        <Tooltip content={<CustomTooltip />} />
        {/* Línea de referencia 50% */}
        <Area type="monotone" dataKey="win_rate" stroke="#3b82f6" strokeWidth={2}
          fill="url(#gradWr)" dot={false} activeDot={{ r: 3 }} connectNulls />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ─── Active Positions List ────────────────────────────────────────────────────

function ActivePositionsList({ summary, info }) {
  const count  = summary?.active_positions ?? 0
  const upnl   = summary?.unrealized_pnl   ?? 0
  const isPos  = upnl >= 0

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity size={15} className="text-blue-500" />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Posiciones IA Abiertas</span>
        {info && <InfoTooltip text={info} />}
        <span className="ml-auto text-lg font-bold text-slate-800 dark:text-white">{count}</span>
      </div>
      {count > 0 ? (
        <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
          <span className="text-xs text-slate-500 dark:text-slate-400">PnL no realizado</span>
          <span className={cn('text-sm font-bold tabular-nums', isPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
            {isPos ? '+' : ''}{fmt2(upnl)} USDT
          </span>
        </div>
      ) : (
        <p className="text-xs text-slate-400 dark:text-slate-500 text-center py-2">Sin posiciones abiertas</p>
      )}
    </div>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, subtitle, children, action, info }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-start gap-1">
          <div>
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">{title}</h3>
            {subtitle && <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
          {info && <InfoTooltip text={info} />}
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

function EmptyState({ label }) {
  return (
    <div className="h-24 flex items-center justify-center text-xs text-slate-400 dark:text-slate-600">
      {label}
    </div>
  )
}

// ─── P&L Attribution Card (Sprint 2.9) ────────────────────────────────────────

function PnlAttributionCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Atribución P&L" subtitle="Desglose por componente del sistema (Sprint 2.9)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data || data.total_trades === 0) return (
    <Section title="Atribución P&L" subtitle="Desglose por componente del sistema (Sprint 2.9)" info={info}>
      <EmptyState label="Sin trades cerrados en el período" />
    </Section>
  )

  const totalFromBuckets = Object.values(data.by_dimension?.quality_tier || {}).reduce((sum, s) => sum + (s.count || 0), 0)
  const countMismatch = totalFromBuckets !== data.total_trades

  const insights = data.insights || []
  const dims = data.by_dimension || {}

  // Pick the most informative dimensions
  const keyDims = ['quality_tier', 'market_regime', 'direction']
  const dimLabels = { quality_tier: 'Tier', market_regime: 'Régimen', direction: 'Dirección' }

  return (
    <Section title="Atribución P&L" subtitle="Desglose por componente del sistema (Sprint 2.9)" info={info}>
      {/* Insights */}
      {insights.length > 0 && (
        <div className="space-y-1.5 mb-4">
          {insights.map((insight, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px] text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/50 rounded-lg px-3 py-2">
              <TrendingUp size={12} className="text-emerald-500 mt-0.5 shrink-0" />
              <span>{insight}</span>
            </div>
          ))}
        </div>
      )}

      {/* Count mismatch warning */}
      {countMismatch && (
        <div className="mb-3 p-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
          <p className="text-[10px] text-amber-700 dark:text-amber-400">
            ⚠️ Suma de buckets ({totalFromBuckets}) ≠ total ({data.total_trades}). Algunos trades carecen de metadata (tier/régimen) y aparecen como "unknown".
          </p>
        </div>
      )}

      <p className="text-[9px] text-slate-400 dark:text-slate-500 mb-2 italic">
        ℹ️ Estos son trades reales ejecutados por bots (Position). Incluyen slippage, fees y ejecución real. No confundir con señales teóricas.
      </p>

      {/* Dimension tables */}
      <div className="space-y-3">
        {keyDims.map(dim => {
          const dimData = dims[dim]
          if (!dimData) return null
          const entries = Object.entries(dimData).sort((a, b) => (b[1].total_pnl || 0) - (a[1].total_pnl || 0))
          if (entries.length === 0) return null
          return (
            <div key={dim}>
              <p className="text-[10px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5">{dimLabels[dim]}</p>
              <div className="space-y-1">
                {entries.map(([key, stats]) => (
                  <div key={key} className="flex items-center justify-between text-xs py-1 px-2 rounded-md hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <span className="font-medium text-slate-600 dark:text-slate-400">{key}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-slate-400">{stats.count} trades</span>
                      <span className={cn('font-bold tabular-nums', stats.win_rate >= 50 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
                        {fmtPct(stats.win_rate)}
                      </span>
                      <span className={cn('font-bold tabular-nums w-16 text-right', (stats.total_pnl || 0) >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
                        {fmtPnl(stats.total_pnl)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

// ─── Rejected Signals Card (Sprint 2.5) ───────────────────────────────────────

const REJECTION_REASON_TOOLTIPS = {
  tier:      'La señal no alcanzó el tier mínimo configurado (ej. STRONG). Revisa la Matriz Tier×Status para ver si MODERATE/WEAK también son rentables.',
  status:    'El estado anti-fake (CLEAR/CAUTION/BLOCK) no está en la lista permitida del bot.',
  score:     'La puntuación de la señal está por debajo del umbral mínimo (min_score).',
  concurrent:'El bot ya tiene el máximo de posiciones abiertas permitidas (max_concurrent).',
  portfolio: 'La exposición total del portfolio excede los límites de riesgo (correlación o tamaño).',
  kelly:     'El sizing calculado por Kelly criterion es demasiado pequeño o cero para este setup.',
  rolling_beta: 'La correlación con BTC en el último tramo supera el umbral de seguridad.',
  drift:     'El modelo detecta drift estadístico: el mercado actual difiere del período de entrenamiento.',
  stacking:  'Ya existe una posición similar reciente en el mismo par/dirección (política de no apilar).',
  stale:     'La señal caducó: pasó demasiado tiempo desde su generación hasta la activación.',
  regime:    'El régimen de mercado actual bloquea este tipo de señal (ej. no operar ranging).',
  macro:     'El contexto macro (noticias, eventos) bloquea el par o dirección.',
  fundamental: 'Datos fundamentales (CFTC, unlocks) desaconsejan operar este activo.',
  session_funding: 'La tasa de funding o la sesión horaria no son favorables.',
  oi_cvd:    'Open Interest o CVD indican flujo contrario a la señal.',
  paper_divergence: 'El par está bloqueado porque paper y real divergen >15%.',
  deployment_gate: 'El sistema está en estado PAUSED o DEGRADED por métricas de riesgo.',
  unknown:   'Motivo de rechazo no categorizado (revisar logs).',
}

function RejectedSignalsCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Señales Rechazadas" subtitle="Auditoría de sesgo de supervivencia (Sprint 2.5)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data || data.total === 0) return (
    <Section title="Señales Rechazadas" subtitle="Auditoría de sesgo de supervivencia (Sprint 2.5)" info={info}>
      <EmptyState label="Sin rechazos en los últimos 30 días" />
    </Section>
  )

  const byReason = data.by_reason || {}
  const topFilters = data.top_filters || []
  const entries = Object.entries(byReason).sort((a, b) => (b[1].count || 0) - (a[1].count || 0))
  const totalSignals = data.total_signals || 0
  const rejectionRate = data.rejection_rate_pct ?? 0

  return (
    <Section title="Señales Rechazadas" subtitle="Auditoría de sesgo de supervivencia (Sprint 2.5)" info={info}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-2xl font-bold text-slate-900 dark:text-white tabular-nums">{data.total}</span>
          <span className="text-[10px] text-slate-400 ml-1.5">/ {totalSignals} señales ({rejectionRate}% rechazado)</span>
        </div>
        <span className="text-[10px] text-slate-400">30 días</span>
      </div>

      {/* Top filters warning */}
      {topFilters.length > 0 && (
        <div className="mb-3 p-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
          <p className="text-[10px] font-semibold text-amber-700 dark:text-amber-400 mb-1">⚠️ Filtros potencialmente agresivos</p>
          <p className="text-[10px] text-amber-600 dark:text-amber-300">
            {topFilters.join(', ')} — rechazan señales que habrían ganado &gt;60% del tiempo
          </p>
        </div>
      )}

      {/* Reason breakdown */}
      <div className="space-y-1.5">
        {entries.map(([reason, stats]) => {
          const maxCount = entries[0]?.[1]?.count || 1
          const pct = Math.round((stats.count / maxCount) * 100)
          const isAggressive = topFilters.includes(reason)
          const tooltip = REJECTION_REASON_TOOLTIPS[reason] || REJECTION_REASON_TOOLTIPS[reason.split('_')[0]] || 'Motivo de rechazo registrado por el activador.'
          return (
            <div key={reason} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1.5">
                  <span className={cn('font-medium', isAggressive ? 'text-amber-600 dark:text-amber-400' : 'text-slate-600 dark:text-slate-400')}>
                    {reason}
                  </span>
                  <InfoTooltip text={tooltip} />
                </div>
                <div className="flex items-center gap-2">
                  {stats.would_win_pct != null && (
                    <span className={cn('text-[10px] tabular-nums', stats.would_win_pct > 60 ? 'text-amber-500 font-semibold' : 'text-slate-400')}>
                      {stats.would_win_pct}% habrían ganado
                    </span>
                  )}
                  <span className="font-bold text-slate-800 dark:text-slate-200 tabular-nums">{stats.count}</span>
                </div>
              </div>
              <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all', isAggressive ? 'bg-amber-400' : 'bg-blue-400')}
                  style={{ width: `${Math.max(pct, 4)}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

// ─── Divergence Tracker Card (Sprint 2.1) ─────────────────────────────────────

function DivergenceCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Paper vs Real Divergence" subtitle="Validación de fills simulados (Sprint 2.1)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data || data.count === 0) {
    const paperSummary = data?.paper_summary || []
    if (paperSummary.length > 0) {
      return (
        <Section title="Paper vs Real Divergence" subtitle="Vista previa paper — sin datos reales aún" info={info}>
          <div className="mb-3 p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
            <p className="text-[10px] font-semibold text-blue-700 dark:text-blue-400">📄 Modo vista previa paper</p>
            <p className="text-[10px] text-blue-600 dark:text-blue-300">
              Aún no hay trades reales cerrados. Se muestran los fills simulados por par/dirección; la divergencia real aparecerá cuando ambos lados tengan ≥20 trades.
            </p>
          </div>
          <div className="space-y-1.5">
            {paperSummary.slice(0, 8).map((item) => (
              <div key={`${item.symbol}-${item.direction}`} className="flex items-center justify-between text-xs">
                <span className="font-medium text-slate-600 dark:text-slate-400">
                  {item.symbol} {item.direction}
                </span>
                <div className="flex items-center gap-3">
                  <span className="text-[10px] text-slate-400 tabular-nums">P{item.count}</span>
                  <span className="text-[10px] tabular-nums text-slate-500">
                    WR {item.win_rate != null ? `${item.win_rate.toFixed(1)}%` : '—'}
                  </span>
                  <span className={cn('font-bold tabular-nums', (item.avg_pnl || 0) >= 0 ? 'text-emerald-600' : 'text-red-600')}>
                    {item.avg_pnl != null ? `$${item.avg_pnl.toFixed(2)}` : '—'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )
    }

    const noPaperBots = !data?.has_paper_bots
    const noPaperTrades = data?.no_paper_trades
    const hasPaperOpenPositions = data?.has_paper_open_positions
    return (
      <Section title="Paper vs Real Divergence" subtitle="Validación de fills simulados (Sprint 2.1)" info={info}>
        <EmptyState
          label={noPaperBots
            ? "Sin bots en modo paper — activa al menos un bot en paper para comparar ejecuciones"
            : noPaperTrades
              ? "Bots paper activos — esperando primeras ejecuciones para comparar fills (mín. 20 trades cerrados)"
              : hasPaperOpenPositions
                ? "Bots paper activos — hay posiciones abiertas; la divergencia se calculará cuando se cierren más trades (mín. 20)"
                : "Sin datos de divergencia en los últimos 7 días — se requieren ≥20 trades paper y ≥20 reales cerrados"}
        />
      </Section>
    )
  }

  const items = data.items || []
  const blocked = data.blocked_symbols || []

  return (
    <Section title="Paper vs Real Divergence" subtitle="Validación de fills simulados (Sprint 2.1)" info={info}>
      {/* Blocked symbols alert */}
      {blocked.length > 0 && (
        <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-[10px] font-semibold text-red-700 dark:text-red-400 mb-1">🚫 Símbolos bloqueados por divergencia &gt;15%</p>
          <p className="text-[10px] text-red-600 dark:text-red-300">
            {blocked.join(', ')} — los bots reales no pueden operar estos pares hasta que la divergencia baje
          </p>
        </div>
      )}

      <div className="space-y-1.5">
        {items.slice(0, 8).map((item) => {
          const wd = item.weighted_divergence_pct
          const isCritical = item.is_critical
          return (
            <div key={`${item.symbol}-${item.direction}`} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className={cn('font-medium', isCritical ? 'text-red-600 dark:text-red-400' : 'text-slate-600 dark:text-slate-400')}>
                  {item.symbol} {item.direction}
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-400 tabular-nums">
                    P{item.paper_count} / R{item.real_count}
                  </span>
                  <span className={cn('font-bold tabular-nums', isCritical ? 'text-red-600' : 'text-slate-800 dark:text-slate-200')}>
                    {wd != null ? `${wd.toFixed(1)}%` : '—'}
                  </span>
                </div>
              </div>
              <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all', isCritical ? 'bg-red-400' : 'bg-emerald-400')}
                  style={{ width: `${Math.min((wd || 0) / 15 * 100, 100)}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

// ─── Confidence Decay Card (Sprint 3.7) ───────────────────────────────────────

function ConfidenceDecayCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Confidence Decay" subtitle="Calibración predicted vs realized (Sprint 3.7)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data) return (
    <Section title="Confidence Decay" subtitle="Calibración predicted vs realized (Sprint 3.7)" info={info}>
      <EmptyState label="Sin datos de calibración (mínimo 30 señales)" />
    </Section>
  )

  const pred = data.predicted_win_rate
  const real = data.realized_win_rate
  const div = data.divergence_pct
  const isAlert = data.is_alert

  return (
    <Section title="Confidence Decay" subtitle="Calibración predicted vs realized (Sprint 3.7)" info={info}>
      {isAlert && (
        <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-[10px] font-semibold text-red-700 dark:text-red-400 mb-1">⚠️ Modelo descalibrado</p>
          <p className="text-[10px] text-red-600 dark:text-red-300">{data.alert_reason}</p>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="text-center">
          <div className="text-lg font-bold text-slate-900 dark:text-white tabular-nums">
            {pred != null ? `${(pred * 100).toFixed(1)}%` : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Predicted WR</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-900 dark:text-white tabular-nums">
            {real != null ? `${(real * 100).toFixed(1)}%` : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Realized WR</div>
        </div>
        <div className="text-center">
          <div className={cn('text-lg font-bold tabular-nums', isAlert ? 'text-red-600' : 'text-slate-900 dark:text-white')}>
            {div != null ? `${div.toFixed(1)}%` : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Divergence</div>
        </div>
      </div>

      <div className="text-[10px] text-slate-400 text-center">
        Ventana: {data.total_signals} señales ({data.wins}W / {data.losses}L)
      </div>
    </Section>
  )
}

// ─── Institutional Health Card (Sprint 4.3) ───────────────────────────────────

function InstitutionalHealthCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Salud Institucional" subtitle="Sharpe · Sortino · Calmar · Ulcer · RoR (Sprint 4.3)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data || !data.total_trades) return (
    <Section title="Salud Institucional" subtitle="Sharpe · Sortino · Calmar · Ulcer · RoR (Sprint 4.3)" info={info}>
      <EmptyState label="Sin trades suficientes para métricas institucionales" />
    </Section>
  )

  const m = data
  const rows = [
    { label: 'Sharpe', value: m.sharpe_ratio, fmt: (v) => v?.toFixed(2) ?? '—', good: (v) => v != null && v >= 1.0, bad: (v) => v != null && v < 0.5 },
    { label: 'Sortino', value: m.sortino_ratio, fmt: (v) => v?.toFixed(2) ?? '—', good: (v) => v != null && v >= 1.0, bad: (v) => v != null && v < 0.5 },
    { label: 'Calmar', value: m.calmar_ratio, fmt: (v) => v?.toFixed(2) ?? '—', good: (v) => v != null && v >= 1.0, bad: (v) => v != null && v < 0.3 },
    { label: 'Ulcer Index', value: m.ulcer_index, fmt: (v) => v?.toFixed(4) ?? '—', good: (v) => v != null && v <= 0.05, bad: (v) => v != null && v > 0.10 },
    { label: 'Risk of Ruin', value: m.risk_of_ruin_pct, fmt: (v) => v != null ? `${v.toFixed(1)}%` : '—', good: (v) => v != null && v <= 5.0, bad: (v) => v != null && v > 15.0 },
    { label: 'Time to Recovery', value: m.time_to_recovery_days, fmt: (v) => v != null ? `${v.toFixed(1)}d` : '—', good: (v) => v != null && v <= 7.0, bad: (v) => v != null && v > 21.0 },
    { label: 'Max Drawdown', value: m.max_drawdown_pct, fmt: (v) => v != null ? `${v.toFixed(1)}%` : '—', good: (v) => v != null && v >= -10.0, bad: (v) => v != null && v < -25.0 },
    { label: 'Profit Factor', value: m.profit_factor, fmt: (v) => v?.toFixed(2) ?? '—', good: (v) => v != null && v >= 1.5, bad: (v) => v != null && v < 1.0 },
    { label: 'Expectancy', value: m.expectancy_pct, fmt: (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—', good: (v) => v != null && v >= 0.005, bad: (v) => v != null && v < 0.0 },
  ]

  return (
    <Section title="Salud Institucional" subtitle="Sharpe · Sortino · Calmar · Ulcer · RoR (Sprint 4.3)" info={info}>
      <div className="grid grid-cols-3 gap-3">
        {rows.map((r) => {
          const v = r.value
          const isGood = r.good(v)
          const isBad = r.bad(v)
          return (
            <div key={r.label} className="text-center p-1.5 bg-slate-50 dark:bg-slate-800/40 rounded-lg">
              <div className={cn('text-sm font-bold tabular-nums', isGood ? 'text-emerald-600' : isBad ? 'text-red-600' : 'text-slate-800 dark:text-slate-200')}>
                {r.fmt(v)}
              </div>
              <div className="text-[10px] text-slate-400">{r.label}</div>
            </div>
          )
        })}
      </div>
      <div className="mt-3 text-[10px] text-slate-400 text-center">
        {m.total_trades} trades ({m.winning_trades}W / {m.losing_trades}L) · Avg win {m.avg_win != null ? `$${m.avg_win.toFixed(2)}` : '—'} · Avg loss {m.avg_loss != null ? `$${m.avg_loss.toFixed(2)}` : '—'}
      </div>
    </Section>
  )
}

// ─── Deployment Gate Card (Sprint 4.2) ────────────────────────────────────────

function DeploymentGateCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Deployment Gate" subtitle="Estado unificado del sistema (Sprint 4.2)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )

  const state = data?.state || "HEALTHY"
  const sizing = data?.sizing_multiplier ?? 1.0
  const reasons = data?.reasons || []

  const stateColors = {
    HEALTHY:  "bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400",
    DEGRADED: "bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-400",
    PAUSED:   "bg-red-50 border-red-200 text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400",
  }

  const stateLabels = {
    HEALTHY:  "🟢 HEALTHY — Operativo al 100%",
    DEGRADED: "🟡 DEGRADED — Sizing reducido al 50%",
    PAUSED:   "🔴 PAUSED — Trading detenido",
  }

  return (
    <div className={cn("rounded-lg border px-4 py-3", stateColors[state] || stateColors.HEALTHY)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-semibold">{stateLabels[state]}</span>
          {info && <InfoTooltip text={info} />}
        </div>
        <span className="text-xs font-mono tabular-nums">sizing ×{sizing.toFixed(2)}</span>
      </div>
      {reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {reasons.map((r, i) => (
            <li key={i} className="text-[11px] opacity-90">• {r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ─── Feature Importance Drift Card (B.1) ──────────────────────────────────────

function FeatureImportanceDriftCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Feature Drift" subtitle="Degradación de features por entrenamiento (B.1)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data) return (
    <Section title="Feature Drift" subtitle="Degradación de features por entrenamiento (B.1)" info={info}>
      <EmptyState label="Sin datos de drift (requiere 2+ entrenamientos)" />
    </Section>
  )

  const decay = data.decay_by_feature || {}
  const entries = Object.entries(decay).sort((a, b) => b[1] - a[1]).slice(0, 6)
  const isAlert = data.is_alert

  return (
    <Section title="Feature Drift" subtitle="Degradación de features por entrenamiento (B.1)" info={info}>
      {isAlert && (
        <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-[10px] font-semibold text-red-700 dark:text-red-400">⚠️ {data.alert_reason}</p>
        </div>
      )}
      <div className="space-y-1.5">
        {entries.map(([feat, val]) => (
          <div key={feat} className="flex items-center justify-between text-xs">
            <span className="text-slate-600 dark:text-slate-400 truncate max-w-[60%]">{feat}</span>
            <span className={cn('font-bold tabular-nums', val > 50 ? 'text-red-600' : val > 20 ? 'text-amber-600' : 'text-slate-800 dark:text-slate-200')}>
              {val > 0 ? '+' : ''}{val.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 text-[10px] text-slate-400 text-center">
        Max decay: {data.max_decay_feature} ({data.max_decay_pct?.toFixed(1)}%)
      </div>
    </Section>
  )
}

// ─── Model Decay Card (B.2) ───────────────────────────────────────────────────

function ModelDecayCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Model Decay" subtitle="Velocidad de degradación del modelo (B.2)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data) return (
    <Section title="Model Decay" subtitle="Velocidad de degradación del modelo (B.2)" info={info}>
      <EmptyState label="Sin datos de decay (requiere 3+ registros)" />
    </Section>
  )

  const alertColors = {
    none:     'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400',
    warning:  'bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-400',
    critical: 'bg-red-50 border-red-200 text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400',
  }

  const days = data.projected_days_to_uncalibrated

  return (
    <Section title="Model Decay" subtitle="Velocidad de degradación del modelo (B.2)" info={info}>
      <div className={cn("rounded-lg border px-3 py-2 mb-3", alertColors[data.alert_level || 'none'])}>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold capitalize">{data.alert_level || 'none'}</span>
          <span className="text-[10px] font-mono">R² = {data.r_squared?.toFixed(2) ?? '—'}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="text-center">
          <div className={cn('text-lg font-bold tabular-nums', (data.decay_per_week || 0) >= 15 ? 'text-red-600' : 'text-slate-900 dark:text-white')}>
            {data.decay_per_week != null ? `${data.decay_per_week.toFixed(1)}%` : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Decay / semana</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-900 dark:text-white tabular-nums">
            {data.current_divergence != null ? `${data.current_divergence.toFixed(1)}%` : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Divergencia actual</div>
        </div>
        <div className="text-center">
          <div className={cn('text-lg font-bold tabular-nums', days != null && days <= 14 ? 'text-red-600' : 'text-slate-900 dark:text-white')}>
            {days != null ? `${Math.round(days)}d` : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Hasta descalibrado</div>
        </div>
      </div>

      {/* Projection bar */}
      {days != null && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[10px] text-slate-400">
            <span>50% threshold</span>
            <span>{Math.round(days)} días restantes</span>
          </div>
          <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all',
                days <= 14 ? 'bg-red-400' : days <= 30 ? 'bg-amber-400' : 'bg-emerald-400'
              )}
              style={{ width: `${Math.min((data.current_divergence || 0) / 50 * 100, 100)}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-2 text-[10px] text-slate-400 text-center">
        {data.record_count} registros históricos
      </div>
    </Section>
  )
}

// ─── Circuit Breaker Card ─────────────────────────────────────────────────────

function CircuitBreakerCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Circuit Breaker" subtitle="Protección contra fallos confiados" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data) return (
    <Section title="Circuit Breaker" subtitle="Protección contra fallos confiados" info={info}>
      <EmptyState label="Sin datos del circuit breaker" />
    </Section>
  )

  const stateColors = {
    CLOSED:     'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400',
    HALF_OPEN:  'bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-400',
    OPEN:       'bg-red-50 border-red-200 text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400',
  }

  return (
    <Section title="Circuit Breaker" subtitle="Protección contra fallos confiados" info={info}>
      <div className={cn("rounded-lg border px-3 py-2 mb-3", stateColors[data.state || 'CLOSED'])}>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold">{data.state || 'CLOSED'}</span>
          <span className="text-[10px]">{data.allows_trading ? 'Trading permitido' : 'Trading BLOQUEADO'}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="text-center">
          <div className={cn('text-lg font-bold tabular-nums', (data.failures || 0) >= 2 ? 'text-red-600' : 'text-slate-900 dark:text-white')}>
            {data.failures ?? 0}/3
          </div>
          <div className="text-[10px] text-slate-400">Fallos confiados</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-900 dark:text-white tabular-nums">
            {data.last_failure ? new Date(data.last_failure).toLocaleTimeString('es-ES', {hour:'2-digit', minute:'2-digit'}) : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Último fallo</div>
        </div>
      </div>
    </Section>
  )
}

// ─── Shadow Mode Card ─────────────────────────────────────────────────────────

function ShadowModeCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Shadow Mode" subtitle="Evaluación de modelos candidatos" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data) return (
    <Section title="Shadow Mode" subtitle="Evaluación de modelos candidatos" info={info}>
      <EmptyState label="Sin datos de shadow mode" />
    </Section>
  )

  return (
    <Section title="Shadow Mode" subtitle="Evaluación de modelos candidatos" info={info}>
      <div className={cn("rounded-lg border px-3 py-2 mb-3",
        data.promote
          ? 'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400'
          : 'bg-slate-50 border-slate-200 text-slate-700 dark:bg-slate-800/50 dark:border-slate-700 dark:text-slate-400'
      )}>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold">{data.promote ? 'PROMOCIÓN recomendada' : 'En evaluación'}</span>
          <span className="text-[10px]">{data.n_signals ?? 0} señales</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="text-center">
          <div className="text-lg font-bold text-slate-900 dark:text-white tabular-nums">
            {data.shadow_sharpe != null ? data.shadow_sharpe.toFixed(2) : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Shadow Sharpe</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-bold text-slate-900 dark:text-white tabular-nums">
            {data.live_sharpe != null ? data.live_sharpe.toFixed(2) : '—'}
          </div>
          <div className="text-[10px] text-slate-400">Live Sharpe</div>
        </div>
      </div>

      {data.reason && (
        <div className="text-[10px] text-slate-400 text-center">
          {data.reason}
        </div>
      )}
    </Section>
  )
}

// ─── Threshold Optimization Card (A) ──────────────────────────────────────────

function ThresholdOptimizationCard({ data, loading, info }) {
  if (loading) return (
    <Section title="Calib. de Umbrales" subtitle="Sugerencias basadas en trades históricos (A)" info={info}>
      <EmptyState label="Cargando…" />
    </Section>
  )
  if (!data || data.status !== "ok") return (
    <Section title="Calib. de Umbrales" subtitle="Sugerencias basadas en trades históricos (A)" info={info}>
      <EmptyState label={`Sin datos suficientes (${data?.trades ?? 0}/${data?.required ?? 30} trades)`} />
    </Section>
  )

  const gates = data.gates || {}
  const gateKeys = Object.keys(gates)

  return (
    <Section title="Calib. de Umbrales" subtitle="Sugerencias basadas en trades históricos (A)" info={info}>
      <div className="space-y-2">
        {gateKeys.length === 0 ? (
          <EmptyState label={`${data.trades_analyzed} trades analizados — todos los gates pasaron, sin bloqueos para calibrar`} />
        ) : (
          Object.entries(gates).map(([gate, info]) => (
            <div key={gate} className="p-2 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300 capitalize">{gate.replace('_', ' ')}</span>
                <span className="text-[10px] text-slate-400">{info.blocked_count ?? info.aborted_count ?? info.applied_count} afectados</span>
              </div>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">{info.suggestion}</p>
            </div>
          ))
        )}
      </div>
      {gateKeys.length > 0 && (
        <div className="mt-2 text-[10px] text-slate-400 text-center">
          {data.trades_analyzed} trades · WR global {data.overall_win_rate}%
        </div>
      )}
    </Section>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export default function AIDashboardTab() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [circuitBreaker, setCircuitBreaker] = useState(null)
  const [shadowMode, setShadowMode] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [{ data: d }, cb, sm] = await Promise.all([
        aiService.dashboard(),
        aiService.circuitBreaker().catch(() => ({ data: null })),
        aiService.shadowMode().catch(() => ({ data: null })),
      ])
      setData(d)
      setCircuitBreaker(cb.data)
      setShadowMode(sm.data)
      setLastRefresh(new Date())
    } catch (e) {
      setError(e?.message || 'Error al cargar el dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const perf   = data?.performance_summary
  const health = data?.model_health

  // Tendencia: diferencia win_rate señales vs últimos 7 días rolling
  const rollingData  = data?.rolling_winrate ?? []
  const lastRollingWr = rollingData.findLast?.(d => d.win_rate != null)?.win_rate
  const prevRollingWr = rollingData.findLast?.((d, i) =>
    d.win_rate != null && i < rollingData.length - 4
  )?.win_rate
  const wrTrend = lastRollingWr != null && prevRollingWr != null
    ? lastRollingWr - prevRollingWr
    : null

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800 dark:text-white flex items-center gap-2">
            <Brain size={16} className="text-violet-500" />
            Motor IA — Panel de Control
          </h2>
          {lastRefresh && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">
              Actualizado {lastRefresh.toLocaleTimeString('es-ES')}
            </p>
          )}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          Refrescar
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Deployment Gate Status (4.2) */}
      <DeploymentGateCard data={data?.deployment_gate} loading={loading} info="Indica si el sistema está operativo (HEALTHY), con precauciones (DEGRADED) o detenido (PAUSED). Se calcula automáticamente según el rendimiento reciente." />

      {/* Row 1: Ground Truth — solo métricas de trades reales ejecutados */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard
          icon={TrendingUp}
          label="PnL Acumulado (real)"
          value={loading ? '…' : fmtPnl(perf?.total_pnl)}
          sub={`${perf?.real_trades ?? 0} cerrados · ${fmtPnl(perf?.unrealized_pnl)} no realizado`}
          trend={null}
          color={perf?.total_pnl >= 0 ? 'emerald' : 'rose'}
          info="Dinero total ganado o perdido por trades ejecutados en el exchange con dinero real. Incluye posiciones cerradas y el beneficio/pérdida no realizado de las abiertas."
        />
        <KpiCard
          icon={Zap}
          label="Win Rate real"
          value={loading ? '…' : fmtPct(perf?.real_win_rate)}
          sub={`${perf?.real_trades ?? 0} trades ejecutados`}
          color="amber"
          info="Porcentaje de trades ganadores sobre el total de trades reales ejecutados. Un valor superior al 50% indica que ganas más operaciones de las que pierdes."
        />
        <KpiCard
          icon={Award}
          label="Profit Factor"
          value={loading ? '…' : (data?.institutional_health?.profit_factor?.toFixed(2) ?? '—')}
          sub={data?.institutional_health?.total_trades
            ? `${data.institutional_health.total_trades} trades base`
            : 'Sin datos suficientes'}
          color={data?.institutional_health?.profit_factor >= 1.5 ? 'emerald' : data?.institutional_health?.profit_factor >= 1.0 ? 'blue' : 'rose'}
          info="Relación entre lo que ganas de media en trades ganadores vs. lo que pierdes en los perdedores. Mayor que 1 es positivo; superior a 1.5 es muy saludable."
        />
        <KpiCard
          icon={Activity}
          label="Posiciones abiertas"
          value={loading ? '…' : (perf?.active_positions ?? 0)}
          sub={perf?.unrealized_pnl != null ? `PnL no realizado: ${fmtPnl(perf.unrealized_pnl)}` : 'Sin posiciones abiertas'}
          color={perf?.unrealized_pnl >= 0 ? 'emerald' : 'rose'}
          info="Número de operaciones actualmente abiertas en el mercado y su beneficio/pérdida flotante (aún no cerrada)."
        />
      </div>

      {/* Row 2: Modelo + Equity — motor y resultado */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ModelHealthCard health={loading ? null : health} info="Estado del modelo de inteligencia artificial que detecta señales falsas. AUC y Accuracy miden su fiabilidad; cuanto más alto, mejor filtra malas oportunidades." />
        <Section
          title="Curva de Equity IA (60 días)"
          subtitle="PnL diario y acumulado de trades ejecutados por el motor IA"
          info="Evolución de tu capital a lo largo del tiempo. Muestra el resultado diario (barras) y el acumulado (línea) de todas las operaciones del motor IA."
        >
          {loading
            ? <div className="h-52 flex items-center justify-center text-xs text-slate-400">Cargando…</div>
            : <EquityCurveChart data={data?.equity_curve} />
          }
        </Section>
      </div>

      {/* Row 3: Calidad de Señales — funnel, matriz, evolución */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Section
          title="Embudo de Señales (30d)"
          subtitle="Conversión en cada etapa del pipeline IA"
          info="Muestra cuántas oportunidades detecta la IA y cuántas llegan a ser trades reales. Cada etapa filtra las señales más débiles."
        >
          {loading
            ? <EmptyState label="Cargando…" />
            : <SignalFunnel data={data?.signal_funnel} />
          }
        </Section>

        <Section
          title="Matriz Tier × Status"
          subtitle="Win rate por combinación de calidad (30d)"
          info="Tabla que cruza la calidad de la señal (Strong, Moderate, Weak) con su estado de mercado (Clear, Caution, Block). Los números verdes son combinaciones que ganan más del 60%."
        >
          {loading
            ? <EmptyState label="Cargando…" />
            : <TierMatrix data={data?.tier_matrix} />
          }
        </Section>

        <Section
          title="Win Rate Móvil (7d)"
          subtitle="Evolución del win rate en ventana deslizante de 7 días"
          info="Tendencia de acierto de la IA calculada cada día sobre una ventana de 7 días. Permite ver si el modelo mejora o empeora con el tiempo."
        >
          {loading
            ? <EmptyState label="Cargando…" />
            : <RollingWinRateChart data={data?.rolling_winrate} />
          }
        </Section>
      </div>

      {/* Row 4: Features del Modelo — XGBoost feature importance */}
      <Section
        title="Importancia de Features (XGBoost)"
        subtitle="Qué factores ICT/SMC tienen más peso en la detección de señales falsas"
        info="Ranking de qué factores técnicos (soportes, volúmenes, sesgos...) influyen más en las decisiones de la IA. Ayuda a entender por qué entra o no en una operación."
      >
        {loading
          ? <EmptyState label="Cargando…" />
          : <FeatureImportanceChart data={data?.feature_importance} />
        }
      </Section>

      {/* Row 5: Validación / Realismo — divergencia, decay, rechazos */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <DivergenceCard data={data?.divergence_summary} loading={loading} info="Compara el resultado de operaciones simuladas (paper) frente a las reales. Si divergen mucho, el mercado real tiene deslizamiento o liquidez distinta a lo simulado." />
        <ConfidenceDecayCard data={data?.confidence_decay} loading={loading} info="Compara el porcentaje de acierto que predice la IA con el que realmente obtienes. Si la diferencia es grande, el modelo necesita recalibrarse." />
        <RejectedSignalsCard data={data?.rejected_summary} loading={loading} info="Muestra por qué la IA descartó ciertas oportunidades. Ayuda a detectar si los filtros son demasiado estrictos y están quitando señales buenas." />
      </div>

      {/* Row 6: Salud Institucional + Monitoreo — métricas + drift trackers */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <InstitutionalHealthCard data={data?.institutional_health} loading={loading} info="Métricas profesionales que evalúan la calidad de tu trading: relación riesgo/beneficio (Sharpe), pérdidas máximas (Drawdown) y probabilidad de arruinarte (Risk of Ruin)." />
        <FeatureImportanceDriftCard data={data?.feature_importance_drift} loading={loading} info="Detecta si las características del mercado han cambiado tanto que el modelo ya no las reconoce bien. Aparece tras varios reentrenamientos." />
        <ModelDecayCard data={data?.model_decay} loading={loading} info="Velocidad a la que el modelo pierde precisión. Indica cuántos días le quedan antes de necesitar un nuevo entrenamiento." />
      </div>

      {/* Row 6.5: Safety Systems — Circuit Breaker + Shadow Mode */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <CircuitBreakerCard data={circuitBreaker} loading={loading} info="Protección automática que detiene el trading tras 3 fallos consecutivos con alta confianza (≥70%). Evita que el modelo siga operando cuando el mercado ha cambiado." />
        <ShadowModeCard data={shadowMode} loading={loading} info="Compara el modelo actual (ensemble) con un candidato alternativo (XGBoost standalone). Si el candidato supera consistentemente al actual, se recomienda su promoción." />
      </div>

      {/* Row 7: Optimización — atribución + umbrales */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <PnlAttributionCard data={data?.pnl_attribution} loading={loading} info="Desglose de beneficios y pérdidas según el tipo de señal, dirección o régimen de mercado. Identifica qué estrategias aportan más a tu cuenta." />
        <ThresholdOptimizationCard data={data?.threshold_optimization} loading={loading} info="Sugerencias automáticas para ajustar los filtros de la IA basándose en tu historial de trades. Busca reducir bloqueos innecesarios." />
      </div>

      {/* Row 8: Posiciones activas */}
      <ActivePositionsList summary={loading ? null : perf} info="Resumen rápido de las operaciones que la IA tiene abiertas en este momento y su resultado flotante." />

      {/* Footer note */}
      <p className="text-[10px] text-slate-400 dark:text-slate-600 text-center pb-2">
        Win rate de señales = backtest (TP1 vs SL en OHLCV) · Win rate real = trades ejecutados en exchange · AUC del clasificador XGBoost entrenado con {health?.samples?.toLocaleString() ?? '—'} señales etiquetadas
      </p>
    </div>
  )
}

