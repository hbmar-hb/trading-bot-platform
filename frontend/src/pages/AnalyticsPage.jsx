import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { analyticsService } from '@/services/analytics'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

function StatBox({ label, value, color = '' }) {
  return (
    <div className="card text-center">
      <p className={`text-2xl font-bold font-mono mb-1 ${color}`}>{value}</p>
      <p className="text-xs text-slate-500 dark:text-gray-400">{label}</p>
    </div>
  )
}

function EquityChart({ data, isDark }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || !data?.length) return

    const bgColor = isDark ? '#030712' : '#ffffff'
    const textColor = isDark ? '#9ca3af' : '#64748b'
    const gridColor = isDark ? '#1f2937' : '#e2e8f0'

    const chart = createChart(ref.current, {
      layout:     { background: { color: bgColor }, textColor: textColor },
      grid:       { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      timeScale:  { borderColor: gridColor },
      rightPriceScale: { borderColor: gridColor },
      height: 250,
    })

    const series = chart.addLineSeries({ color: '#3b82f6', lineWidth: 2 })
    series.setData(
      data.map(p => ({
        time:  Math.floor(new Date(p.timestamp).getTime() / 1000),
        value: parseFloat(p.cumulative_pnl),
      }))
    )
    chart.timeScale().fitContent()

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: ref.current.clientWidth })
    })
    observer.observe(ref.current)

    return () => { chart.remove(); observer.disconnect() }
  }, [data, isDark])

  return <div ref={ref} className="w-full" />
}

export default function AnalyticsPage() {
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isDark, setIsDark] = useState(false)

  useEffect(() => {
    // Detectar tema actual
    const checkDark = () => {
      setIsDark(document.documentElement.classList.contains('dark'))
    }
    checkDark()
    
    // Observar cambios
    const observer = new MutationObserver(checkDark)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    analyticsService.summary()
      .then(r => setSummary(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>
  if (!summary) return <p className="text-slate-500 dark:text-gray-400">No se pudieron cargar las estadísticas.</p>

  const g = summary.global_stats
  const winPct = (g.win_rate * 100).toFixed(1)

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-slate-900 dark:text-white">Analytics</h1>

      {/* Stats globales */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatBox label="Trades totales"     value={g.total_trades} />
        <StatBox label="Win rate"           value={`${winPct}%`}
          color={g.win_rate >= 0.5 ? 'text-green-400' : 'text-red-400'}
        />
        <StatBox label="PnL total"
          value={`${parseFloat(g.total_pnl) >= 0 ? '+' : ''}${parseFloat(g.total_pnl).toFixed(2)} USDT`}
        />
        <StatBox label="Mejor trade"       value={`+${parseFloat(g.best_trade).toFixed(2)}`} />
      </div>

      {/* Curva de equity */}
      {summary.equity_curve.length > 0 && (
        <div className="card">
          <h2 className="font-semibold mb-4 text-slate-900 dark:text-gray-100">Curva de Equity</h2>
          <EquityChart data={summary.equity_curve} isDark={isDark} />
        </div>
      )}

      {/* Por bot */}
      <div className="card">
        <h2 className="font-semibold mb-4 text-slate-900 dark:text-gray-100">Por bot</h2>
        {summary.by_bot.length === 0 ? (
          <p className="text-slate-500 dark:text-gray-400 text-sm">Sin datos</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 dark:text-gray-400 border-b border-slate-200 dark:border-gray-800">
                <th className="pb-2 pr-4">Bot</th>
                <th className="pb-2 pr-4">Símbolo</th>
                <th className="pb-2 pr-4">Trades</th>
                <th className="pb-2 pr-4">Win rate</th>
                <th className="pb-2">PnL</th>
              </tr>
            </thead>
            <tbody>
              {summary.by_bot.map(bot => (
                <tr key={bot.bot_id} className="border-b border-slate-200 dark:border-gray-800/50">
                  <td className="py-2.5 pr-4 font-medium text-slate-900 dark:text-gray-100">{bot.bot_name}</td>
                  <td className="py-2.5 pr-4 text-slate-500 dark:text-gray-400">{bot.symbol}</td>
                  <td className="py-2.5 pr-4 text-slate-900 dark:text-gray-100">{bot.total_trades}</td>
                  <td className="py-2.5 pr-4">
                    <span className={bot.win_rate >= 0.5 ? 'text-green-400' : 'text-red-400'}>
                      {(bot.win_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-2.5">
                    <span className={`font-mono ${parseFloat(bot.total_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {parseFloat(bot.total_pnl) >= 0 ? '+' : ''}{parseFloat(bot.total_pnl).toFixed(2)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
