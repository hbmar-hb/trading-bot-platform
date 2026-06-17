import { useEffect, useState } from 'react'
import { Ban, Clock, Trophy, XCircle } from 'lucide-react'
import { cn } from '@/utils/cn'
import { aiService } from '@/services/aiService'

const REASON_LABELS = {
  stale: 'Señal expirada',
  tier: 'Tier no permitido',
  status: 'Status ML bloqueado',
  score: 'Score bajo',
  concurrent: 'Máx. posiciones abiertas',
  same_side: 'Posición mismo lado activa',
  fundamental: 'Fundamental gate',
  symbol_deployment_gate_paused: 'Símbolo pausado',
  macro: 'Contexto macro adverso',
  regime: 'Régimen de mercado',
  circuit_breaker: 'Circuit breaker abierto',
  cost_gate: 'Cost gate',
  exposure_cap: 'Límite de exposición',
  paper_divergence: 'Divergencia paper vs real',
  oi_cvd: 'OI/CVD',
  session_funding: 'Funding/sesión',
  rolling_beta: 'Beta rodante',
  wf_rejected: 'Walk-forward rechazado',
  optimal_config_missing: 'Config óptima ausente',
  symbol_deployment_gate: 'Símbolo no desplegado',
  prob_threshold: 'Umbral de probabilidad',
  montecarlo: 'Monte Carlo',
  llm_block: 'LLM block',
  llm_caution: 'LLM caution',
  longevity: 'Longevidad',
  drift: 'Model drift detectado',
  kelly: 'Kelly criterion negativo',
  portfolio: 'Límite de portfolio',
  look_ahead: 'Look-ahead bias',
  slippage: 'Slippage excesivo',
  stacking: 'Stacking policy',
  tier_status: 'Tier + status',
  'score+catr': 'Score + CATR',
  score_catr: 'Score + CATR',
  htf_conflict: 'Conflicto HTF',
  equilibrium: 'Equilibrium puro',
  liquidity_sweep: 'Sin sweep',
  asia_range: 'Rango asiático',
  killzone: 'Fuera de killzone',
  market_quality: 'Calidad de mercado',
}

function formatReason(reason) {
  return REASON_LABELS[reason] || reason?.replace(/_/g, ' ') || 'Desconocido'
}

export default function IARejectionFeed({ symbols }) {
  const [rejections, setRejections] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!symbols?.length) return

    let cancelled = false
    setLoading(true)

    async function load() {
      try {
        const results = await Promise.all(
          symbols.map(async (sym) => {
            try {
              const res = await aiService.symbolRejections(sym, { limit: 5 })
              const items = Array.isArray(res?.data?.detail)
                ? res.data.detail
                : res?.data?.detail?.items || []
              return items.map((r) => ({
                ...r,
                symbol: sym,
              }))
            } catch {
              return []
            }
          })
        )
        if (!cancelled) {
          const all = results
            .flat()
            .sort((a, b) => new Date(b.rejected_at) - new Date(a.rejected_at))
            .slice(0, 15)
          setRejections(all)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [symbols])

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3 h-full flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <Ban size={14} className="text-amber-500" />
        <h3 className="text-xs font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wide">
          Últimos descartes
        </h3>
        <span className="text-[10px] text-slate-400 dark:text-slate-500 ml-auto">
          {rejections.length} recientes
        </span>
      </div>

      {loading && rejections.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-xs text-slate-400 animate-pulse">
          Cargando rechazos…
        </div>
      )}

      {!loading && rejections.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-xs text-slate-400">
          Sin rechazos recientes
        </div>
      )}

      <div className="space-y-1.5 overflow-y-auto flex-1 min-h-0">
        {rejections.map((r, i) => (
          <div
            key={`${r.symbol}-${r.rejected_at}-${i}`}
            className="flex items-start gap-2 p-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
          >
            <div className="mt-0.5 shrink-0">
              {r.would_have_been_winner === true ? (
                <Trophy size={11} className="text-amber-500" />
              ) : r.would_have_been_winner === false ? (
                <XCircle size={11} className="text-green-500" />
              ) : (
                <Ban size={11} className="text-slate-400" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[10px] font-bold text-slate-700 dark:text-slate-200">
                  {r.symbol?.replace(/USDT$|USDC$/, '')}
                </span>
                <span className="text-[9px] text-slate-400 dark:text-slate-500">
                  {r.timeframe}
                </span>
                <span className={cn(
                  'text-[9px] font-bold px-1 py-0.5 rounded',
                  r.rejection_reason === 'stale' ? 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400' :
                  r.rejection_reason?.includes('score') || r.rejection_reason?.includes('tier') ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400' :
                  'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
                )}>
                  {formatReason(r.rejection_reason)}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[10px] text-slate-400 dark:text-slate-500 flex items-center gap-0.5">
                  <Clock size={9} />
                  {new Date(r.rejected_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
                {r.would_have_been_winner == null ? (
                  <span className="text-[9px] text-slate-400 dark:text-slate-500">
                    Pendiente de auditoría
                  </span>
                ) : (
                  <span className={cn(
                    'text-[9px] font-medium',
                    r.would_have_been_winner ? 'text-amber-600 dark:text-amber-400' : 'text-green-600 dark:text-green-400',
                  )}>
                    {r.would_have_been_winner ? 'Habría ganado' : 'Habría perdido'}
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
