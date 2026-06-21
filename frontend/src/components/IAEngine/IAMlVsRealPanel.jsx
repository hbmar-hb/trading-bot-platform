import { useEffect, useState } from 'react'
import { Brain, TrendingUp, AlertTriangle } from 'lucide-react'
import { cn } from '@/utils/cn'
import { aiService } from '@/services/aiService'

export default function IAMlVsRealPanel({ watchlist }) {
  const [globalStats, setGlobalStats] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    async function load() {
      try {
        const [dashRes, perfRes] = await Promise.all([
          aiService.dashboard().catch(() => ({ data: null })),
          aiService.realPerformance('total').catch(() => ({ data: null })),
        ])
        if (!cancelled) {
          setGlobalStats({
            dashboard: dashRes?.data,
            real: perfRes?.data,
          })
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  const dash = globalStats?.dashboard
  const real = globalStats?.real

  const realSummary = real?.summary || {}

  const mlWinRate = dash?.performance_summary?.signal_win_rate ?? dash?.performance_summary?.win_rate ?? dash?.rolling_winrate?.current ?? null
  const realWinRate = realSummary.win_rate ?? dash?.performance_summary?.real_win_rate ?? null
  const realTrades = realSummary.total_trades ?? dash?.performance_summary?.real_trades ?? null
  const realPnL = realSummary.total_pnl ?? null
  const slippage = dash?.execution_quality?.avg_slippage_bps ?? null

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-3">
        <Brain size={14} className="text-purple-500" />
        <h3 className="text-xs font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wide">
          ML vs Real
        </h3>
      </div>

      {loading && !globalStats && (
        <div className="text-xs text-slate-400 animate-pulse py-4 text-center">Cargando…</div>
      )}

      {!loading && !globalStats && (
        <div className="text-xs text-slate-400 py-4 text-center">Sin datos globales</div>
      )}

      {globalStats && (
        <div className="space-y-3">
          {/* Win rate comparison */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">Win rate esperado (ML)</span>
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-200 tabular-nums">
                {mlWinRate != null ? `${mlWinRate.toFixed(1)}%` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">Win rate real ejecutado</span>
              <span className={cn(
                'text-[10px] font-bold tabular-nums',
                realWinRate != null && realWinRate >= (mlWinRate ?? 0)
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400',
              )}>
                {realWinRate != null ? `${realWinRate.toFixed(0)}%` : '—'}
              </span>
            </div>
            {mlWinRate != null && realWinRate != null && (
              <div className="h-1.5 flex rounded-full overflow-hidden">
                <div
                  className="bg-blue-500 h-full"
                  style={{ width: `${Math.min(100, mlWinRate)}%` }}
                />
                <div
                  className={cn(
                    'h-full',
                    realWinRate >= mlWinRate ? 'bg-green-500' : 'bg-red-500',
                  )}
                  style={{ width: `${Math.min(100, Math.abs(realWinRate - mlWinRate))}%` }}
                />
              </div>
            )}
          </div>

          {/* Real trades summary */}
          {realTrades != null && (
            <div className="flex items-center gap-3">
              <div className="flex-1 bg-slate-50 dark:bg-slate-800 rounded p-2 text-center">
                <div className="text-[10px] text-slate-400 dark:text-slate-500">Trades reales</div>
                <div className="text-sm font-bold text-slate-700 dark:text-slate-200">{realTrades}</div>
              </div>
              <div className="flex-1 bg-slate-50 dark:bg-slate-800 rounded p-2 text-center">
                <div className="text-[10px] text-slate-400 dark:text-slate-500">PnL real</div>
                <div className={cn(
                  'text-sm font-bold tabular-nums',
                  (realPnL ?? 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400',
                )}>
                  {realPnL != null ? `${realPnL >= 0 ? '+' : ''}${realPnL.toFixed(2)} USDT` : '—'}
                </div>
              </div>
            </div>
          )}

          {/* Slippage warning */}
          {slippage != null && slippage > 5 && (
            <div className="flex items-center gap-1.5 text-[10px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 rounded px-2 py-1">
              <AlertTriangle size={11} />
              Slippage alto: {slippage.toFixed(1)} bps
            </div>
          )}

          {/* Per-symbol summary if no global data */}
          {(!realTrades || realTrades === 0) && watchlist?.length > 0 && (
            <div className="text-[10px] text-slate-400 dark:text-slate-500 leading-relaxed">
              <TrendingUp size={10} className="inline mr-1" />
              Escaneando {watchlist.length} par{watchlist.length !== 1 ? 'es' : ''}.
              Los trades reales aparecerán cuando los bots IA ejecuten señales.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
