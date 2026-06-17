import { Bot, RefreshCw, ScanLine, TrendingDown, TrendingUp, X, Zap } from 'lucide-react'
import { cn } from '@/utils/cn'
import IAConfluenceBars from './IAConfluenceBars'

const fmtPrice = (n) =>
  n == null ? '—' : n >= 1 ? n.toFixed(n >= 100 ? 2 : 4) : n.toPrecision(4)

const baseOf = (sym) => sym.replace(/USDT$|USDC$/, '').replace(/^1000/, '')

function BiasTag({ bias }) {
  if (!bias) return null
  const bull = bias === 'bull'
  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide',
      bull
        ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400'
        : 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
    )}>
      {bull ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
      {bull ? 'Bull' : 'Bear'}
    </span>
  )
}

function QualityBadge({ tier, status, successProbability }) {
  const map = {
    STRONG: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400',
    MODERATE: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400',
    WEAK:   'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400',
  }
  return (
    <span className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded', map[tier] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400')}>
      {tier}
      {successProbability != null && (
        <span className="opacity-70 ml-1">({(successProbability * 100).toFixed(0)}%)</span>
      )}
    </span>
  )
}

/**
 * Build a human-readable rejection reason from the scan context.
 */
function buildRejectionReason(result) {
  const ctx = result?.context || {}

  if (ctx.reason && typeof ctx.reason === 'string') return ctx.reason

  if (ctx.gate) {
    const gateMap = {
      HTF_CONFLICT: 'Conflicto HTF — dirección contraria al sesgo macro',
      LIQUIDITY_SWEEP: 'Sin sweep de liquidez confirmado',
      ASIA_RANGE: 'Precio dentro del rango asiático — esperar ruptura',
      KILLZONE: 'Fuera de killzone operable',
      EQUILIBRIUM: 'Precio en equilibrium — NO TRADE según SMC',
      CIRCUIT_BREAKER: 'Circuit breaker abierto',
      MARKET_QUALITY: `Calidad de mercado baja: ${ctx.market_quality || ''}`,
    }
    return gateMap[ctx.gate] || `Gate bloqueado: ${ctx.gate}`
  }

  if (ctx.circuit_breaker) return 'Circuit breaker abierto — escaneo pausado'
  if (ctx.market_quality) return `Calidad de mercado baja: ${ctx.market_quality}`
  if (ctx.htf_conflict) return `Conflicto HTF — sesgo alto ${ctx.htf_conflict} contrario`
  if (ctx.macro_blocked) return `Contexto macro adverso: ${(ctx.macro_warnings || []).join(', ') || 'restricción general'}`
  if (ctx.regime_blocked) return `Régimen de mercado desfavorable: ${ctx.regime_reason || ''}`

  // Heuristic fallbacks based on context fields
  if (ctx.pd_position != null) {
    const pd = ctx.pd_position
    if (pd > 0.45 && pd < 0.55) return 'Precio en equilibrium puro — sin discount/premium claro'
  }

  if (!ctx.last_break && !ctx.bias) return 'Sin estructura ICT identificable'
  if (!ctx.active_ob && !ctx.active_fvgs) return 'Sin zona de interés (OB/FVG) activa'

  return 'Sin confluencia suficiente'
}

export default function IAWatchlistCard({
  entry,
  result,
  scanning,
  tickerStats,
  aiBotNames,
  onRemove,
  onChangeTimeframe,
  onScanOne,
  onSelect,
  isSelected,
  timeframes = ['auto', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w'],
}) {
  const { symbol, timeframe, resolved_timeframe } = entry
  const status = result?.status
  const isSignal = status === 'SIGNAL'
  const isError = status === 'ERROR'
  const isNoSignal = !isSignal && !isError && !!result
  const hasAiBot = aiBotNames?.length > 0
  const direction = result?.direction

  const htfBias = result?.context?.htf_bias || result?.features?.htf_bias
  const htfAligned = result?.features?.htf_aligned

  return (
    <div
      onClick={() => { if (!scanning) onSelect(symbol, timeframe) }}
      className={cn(
        'bg-white dark:bg-slate-900 border rounded-lg p-3 cursor-pointer select-none transition-shadow relative',
        'border-slate-200 dark:border-slate-700',
        !scanning && 'hover:shadow-md hover:border-slate-300 dark:hover:border-slate-600',
        scanning && 'opacity-70 cursor-wait',
        isSignal && direction === 'long'  && 'ring-1 ring-green-500/40 border-green-200 dark:border-green-500/30',
        isSignal && direction === 'short' && 'ring-1 ring-red-500/40 border-red-200 dark:border-red-500/30',
        hasAiBot && !isSignal && 'ring-1 ring-blue-400/30',
        isSelected && 'ring-2 ring-blue-500 dark:ring-blue-400',
      )}
    >
      {/* Selection checkmark */}
      {isSelected && (
        <div className="absolute -top-2 -right-2 z-10">
          <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white shadow-md">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          </span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-2 mb-2.5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <span className="font-bold text-slate-900 dark:text-white text-sm truncate">{baseOf(symbol)}</span>
          <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0">USDT</span>

          {hasAiBot && (
            <span
              title={`Bot IA activo: ${aiBotNames.join(', ')}`}
              className="flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400 shrink-0"
            >
              <Bot size={8} />IA
            </span>
          )}

          {/* HTF Bias tag */}
          {htfBias && (
            <BiasTag bias={htfBias} />
          )}
          {htfAligned === false && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400 shrink-0">
              HTF ×
            </span>
          )}
        </div>

        <div className="flex flex-col items-end gap-0.5">
          <select
            value={timeframe}
            onChange={(e) => onChangeTimeframe(symbol, e.target.value)}
            className={cn(
              'text-xs border rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500',
              'bg-slate-100 text-slate-700 border-slate-300',
              'dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600',
            )}
          >
            {timeframes.map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
          {timeframe === 'auto' && resolved_timeframe && (
            <span className="text-[9px] font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 px-1 rounded">
              → {resolved_timeframe}
            </span>
          )}
        </div>

        <button
          onClick={() => onScanOne(symbol, timeframe)}
          disabled={scanning}
          title="Re-escanear"
          className="p-1 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 disabled:opacity-30 transition-colors"
        >
          <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
        </button>
        <button
          onClick={() => onRemove(symbol)}
          title="Eliminar"
          className="p-1 text-slate-400 hover:text-red-500 transition-colors"
        >
          <X size={12} />
        </button>
      </div>

      {/* Timestamp */}
      {result?.scannedAt && !scanning && (
        <div className="text-[10px] text-slate-400 dark:text-slate-600 mb-1.5 tabular-nums">
          {new Date(result.scannedAt).toLocaleTimeString()}
        </div>
      )}

      {/* SCANNING state */}
      {scanning && (
        <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500 animate-pulse py-3">
          <RefreshCw size={14} className="animate-spin" />
          Analizando {baseOf(symbol)}…
        </div>
      )}

      {/* NO SIGNAL state — prominently show WHY it was discarded */}
      {!scanning && isNoSignal && (
        <div className="space-y-2">
          {/* Rejection reason — BIG and clear */}
          <div className="flex items-start gap-2">
            <div className="mt-0.5 shrink-0">
              <Zap size={14} className="text-amber-500" />
            </div>
            <div>
              <div className="text-xs font-semibold text-amber-700 dark:text-amber-400">
                Sin señal
              </div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
                {buildRejectionReason(result)}
              </div>
            </div>
          </div>

          {/* Mini ICT context */}
          <div className="flex items-center gap-2 flex-wrap">
            {result.context?.bias && <BiasTag bias={result.context.bias} />}
            {result.context?.last_break && (
              <span className="text-[10px] font-bold text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 px-1.5 py-0.5 rounded">
                {result.context.last_break}
              </span>
            )}
            {result.context?.active_ob && (
              <span className="text-[10px] font-semibold text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-500/10 px-1.5 py-0.5 rounded">OB</span>
            )}
            {result.context?.active_fvgs > 0 && (
              <span className="text-[10px] text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
                {result.context.active_fvgs} FVG
              </span>
            )}
          </div>

          {result.context?.last_close && (
            <div className="font-mono text-[10px] text-slate-400">${fmtPrice(result.context.last_close)}</div>
          )}

          {/* Show confluence bars even for NO_SIGNAL — reveals what's missing */}
          <IAConfluenceBars
            components={result.components || {}}
            features={result.features || {}}
            score={result.score}
            direction={direction}
          />
        </div>
      )}

      {/* ERROR state */}
      {!scanning && status === 'ERROR' && (
        <div className="text-xs text-red-500 dark:text-red-400 py-2">
          Error al obtener datos del exchange
        </div>
      )}

      {/* SIGNAL state — full detail */}
      {!scanning && isSignal && (
        <div className="space-y-2.5">
          {/* Direction + Score row */}
          <div className="flex items-center justify-between">
            <span className={cn(
              'flex items-center gap-1.5 text-sm font-bold',
              direction === 'long' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400',
            )}>
              {direction === 'long' ? <TrendingUp size={15} /> : <TrendingDown size={15} />}
              {direction?.toUpperCase()}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-700 dark:text-slate-200">
                Score {result.score ?? 0}
              </span>
              {result.quality_tier && (
                <QualityBadge
                  tier={result.quality_tier}
                  status={result.anti_fake_status}
                  successProbability={result.success_probability}
                />
              )}
            </div>
          </div>

          {/* ML Probability */}
          {result.success_probability != null && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">Prob. ML:</span>
              <div className="flex-1 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full',
                    result.success_probability >= 0.6 ? 'bg-emerald-500' :
                    result.success_probability >= 0.4 ? 'bg-yellow-500' : 'bg-red-500',
                  )}
                  style={{ width: `${(result.success_probability * 100).toFixed(0)}%` }}
                />
              </div>
              <span className={cn(
                'text-[10px] font-bold tabular-nums',
                result.success_probability >= 0.6 ? 'text-emerald-600 dark:text-emerald-400' :
                result.success_probability >= 0.4 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400',
              )}>
                {(result.success_probability * 100).toFixed(0)}%
              </span>
            </div>
          )}

          {/* Confluence breakdown */}
          <IAConfluenceBars
            components={result.components || {}}
            features={result.features || {}}
            score={result.score}
            direction={direction}
          />

          {/* Entry zone */}
          <div className="flex items-center gap-3 text-[10px] text-slate-400 font-mono">
            <span>SL {fmtPrice(result.stop_loss)}</span>
            <span>·</span>
            <span>TP1 {fmtPrice(result.take_profit_1)}</span>
            <span>·</span>
            <span>Entry {fmtPrice(result.entry_price)}</span>
          </div>
        </div>
      )}

      {/* No data yet */}
      {!scanning && !result && (
        <div className="text-xs text-blue-500 dark:text-blue-400 flex items-center gap-1.5 py-2">
          <ScanLine size={12} />
          Sin datos — pulsa para ver gráfico
        </div>
      )}

      {/* Footer — backtest stats */}
      <div className="mt-2.5 pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center gap-3 text-[10px] flex-wrap">
        {tickerStats ? (
          <>
            <span className="text-slate-500 dark:text-slate-400">
              <span className="font-bold text-slate-700 dark:text-slate-200">{tickerStats.total ?? 0}</span>
              {' '}señal{tickerStats.total !== 1 ? 'es' : ''} sim
            </span>
            {tickerStats.win_rate != null && (
              <span className={cn(
                'text-slate-500 dark:text-slate-400',
                tickerStats.win_rate >= 55 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400',
              )}>
                Win <span className="font-bold">{tickerStats.win_rate}%</span>
              </span>
            )}
            {tickerStats.avg_score != null && (
              <span className="text-slate-400 dark:text-slate-500">
                Score <span className="font-semibold text-slate-600 dark:text-slate-300">{tickerStats.avg_score}</span>
              </span>
            )}
          </>
        ) : (
          <span className="text-slate-400 dark:text-slate-600">Sin stats aún</span>
        )}

        {/* ML status badge */}
        {(result?.ml_status || result?.anti_fake_status) ? (
          <span className={cn(
            'ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded',
            (result.ml_status || result.anti_fake_status) === 'CLEAR'   ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400' :
            (result.ml_status || result.anti_fake_status) === 'CAUTION' ? 'bg-yellow-500/20 text-yellow-600 dark:text-yellow-400' :
                                                                          'bg-red-500/20 text-red-600 dark:text-red-400',
          )}>
            {result.success_probability != null ? 'ML ' : 'XGB '}{(result.ml_status || result.anti_fake_status)}
          </span>
        ) : (
          <span className="ml-auto text-[9px] text-slate-400 dark:text-slate-600">→ detalle</span>
        )}
      </div>
    </div>
  )
}
