import { useEffect, useState } from 'react'
import { Brain, AlertTriangle } from 'lucide-react'
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

  // Theoretical = backtest/signal outcomes (AISignal.outcome, ideal reference)
  const mlWinRate = dash?.performance_summary?.signal_win_rate ?? null
  const avgScore = dash?.performance_summary?.avg_score ?? null
  const signals30d = dash?.performance_summary?.signals_30d ?? null

  // Real = actually executed ExchangeTrade + paper Position realized PnL
  const realSummary = real?.summary || {}
  const realWinRate = realSummary.win_rate ?? dash?.performance_summary?.real_win_rate ?? null
  const realTrades = realSummary.total_trades ?? dash?.performance_summary?.real_trades ?? null
  const realPnL = realSummary.total_pnl ?? null

  const mlLabel = 'Win rate señales/backtest (teórico)'
  const realLabel = 'Win rate trades ejecutados (real)'

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-3">
        <Brain size={14} className="text-purple-500" />
        <h3 className="text-xs font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wide">
          Teórico vs Real
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
          {/* Theoretical block */}
          <div className="space-y-1.5">
            <div className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
              Teórico (backtest señales)
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">Win rate</span>
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-200 tabular-nums">
                {mlWinRate != null ? `${mlWinRate.toFixed(1)}%` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">Score medio</span>
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-200 tabular-nums">
                {avgScore != null ? avgScore.toFixed(1) : '—'}
              </span>
            </div>
            {signals30d != null && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-slate-500 dark:text-slate-400">Señales 30d</span>
                <span className="text-[10px] font-bold text-slate-700 dark:text-slate-200 tabular-nums">
                  {signals30d}
                </span>
              </div>
            )}
          </div>

          {/* Real block */}
          <div className="space-y-1.5 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
              Real (trades ejecutados)
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">Win rate</span>
              <span className={cn(
                'text-[10px] font-bold tabular-nums',
                realWinRate != null && realWinRate >= (mlWinRate ?? 0)
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400',
              )}>
                {realWinRate != null ? `${realWinRate.toFixed(1)}%` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">Trades cerrados</span>
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-200 tabular-nums">
                {realTrades != null ? realTrades : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500 dark:text-slate-400">PnL total</span>
              <span className={cn(
                'text-[10px] font-bold tabular-nums',
                (realPnL ?? 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400',
              )}>
                {realPnL != null ? `${realPnL >= 0 ? '+' : ''}${realPnL.toFixed(2)} USDT` : '—'}
              </span>
            </div>
          </div>

          {/* Visual comparison bar */}
          {mlWinRate != null && realWinRate != null && (
            <div className="space-y-1">
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
              <div className="flex justify-between text-[9px] text-slate-400 dark:text-slate-500">
                <span>0%</span>
                <span>Teórico {mlWinRate.toFixed(0)}% · Real {realWinRate.toFixed(0)}%</span>
                <span>100%</span>
              </div>
            </div>
          )}

          {/* Guidance when no real trades yet */}
          {(!realTrades || realTrades === 0) && watchlist?.length > 0 && (
            <div className="text-[10px] text-slate-400 dark:text-slate-500 leading-relaxed">
              <AlertTriangle size={10} className="inline mr-1" />
              Escaneando {watchlist.length} par{watchlist.length !== 1 ? 'es' : ''}.
              Los trades reales aparecerán cuando los bots IA ejecuten señales.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
