import { cn } from '@/utils/cn'

/**
 * Visual breakdown of the 5 V2.1 confluence pillars.
 * Uses result.components (descriptive strings) and result.features (booleans/values)
 * to show which structural pillars are present and their contribution.
 */

const PILLARS = [
  {
    key: 'htf_bias',
    label: 'HTF Bias',
    maxPoints: 20,
    checkActive: (components) =>
      !!(components?.htf_bias || components?.htf_alignment),
    checkConflict: (features) => features?.htf_aligned === false,
    checkMissing: (features) => features?.htf_aligned == null,
  },
  {
    key: 'sweep',
    label: 'Liquidez',
    maxPoints: 25,
    checkActive: (components, features) =>
      !!(components?.sweep || components?.liquidity_sweep || features?.sweep_detected),
    checkConflict: () => false,
    checkMissing: () => false,
  },
  {
    key: 'structure',
    label: 'Estructura',
    maxPoints: 20,
    checkActive: (components) =>
      !!(components?.structure_CHoCH || components?.structure_BOS || components?.break_type),
    checkConflict: () => false,
    checkMissing: () => false,
  },
  {
    key: 'poi',
    label: 'POI / Zona',
    maxPoints: 20,
    checkActive: (components, features) =>
      !!(components?.trigger_OB || components?.trigger_FVG || components?.ob || components?.fvg ||
         features?.trigger === 'ob' || features?.trigger === 'fvg'),
    checkConflict: () => false,
    checkMissing: () => false,
  },
  {
    key: 'pd_array',
    label: 'PD Array',
    maxPoints: 15,
    checkActive: (components) =>
      !!(components?.pd_array || components?.pd_position),
    checkConflict: (features) => {
      const pd = features?.pd_position ?? 0.5
      return pd > 0.6 || pd < 0.4
    },
    checkMissing: () => false,
  },
]

export default function IAConfluenceBars({ components, features, score, direction }) {
  const timingMult = features?.timing_multiplier ?? 1.0
  const timingComponents = features?.timing_components ?? []
  const hasTimingBonus = timingMult > 1.0
  const hasTimingPenalty = timingMult < 1.0

  return (
    <div className="space-y-1.5">
      {PILLARS.map((pillar) => {
        const active = pillar.checkActive(components, features)
        const conflict = pillar.checkConflict(features)
        const missing = pillar.checkMissing(features)

        let fillPct = 0
        if (active && !conflict) fillPct = 100
        else if (active && conflict) fillPct = 30
        else if (missing) fillPct = 0
        else fillPct = 0

        const barColor = conflict
          ? 'bg-red-500'
          : active
            ? direction === 'long'
              ? 'bg-green-500'
              : 'bg-red-500'
            : 'bg-slate-300 dark:bg-slate-600'

        const labelColor = conflict
          ? 'text-red-600 dark:text-red-400'
          : active
            ? 'text-slate-700 dark:text-slate-200'
            : 'text-slate-400 dark:text-slate-500'

        return (
          <div key={pillar.key} className="flex items-center gap-2">
            <span className={cn('text-[10px] font-medium w-16 shrink-0 tabular-nums', labelColor)}>
              {pillar.label}
            </span>
            <div className="flex-1 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full transition-all duration-500', barColor)}
                style={{ width: `${fillPct}%` }}
              />
            </div>
            <span className={cn('text-[10px] w-8 text-right tabular-nums', labelColor)}>
              {active && !conflict ? `+${pillar.maxPoints}` : conflict ? '×' : '—'}
            </span>
          </div>
        )
      })}

      {/* Timing multiplier badge */}
      {(hasTimingBonus || hasTimingPenalty || timingComponents.length > 0) && (
        <div className="flex items-center gap-2 pt-0.5">
          <span className="text-[10px] font-medium w-16 shrink-0 text-slate-500 dark:text-slate-400">
            Timing
          </span>
          <div className="flex items-center gap-1">
            <span className={cn(
              'text-[10px] font-bold px-1.5 py-0.5 rounded tabular-nums',
              hasTimingBonus
                ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400'
                : hasTimingPenalty
                  ? 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400'
                  : 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400',
            )}>
              ×{timingMult.toFixed(2)}
            </span>
            {timingComponents.map((tc) => (
              <span
                key={tc}
                className="text-[9px] text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded"
              >
                {tc}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Depth badge */}
      {features?.confluence_depth != null && (
        <div className="flex items-center justify-between pt-0.5">
          <span className="text-[10px] text-slate-400 dark:text-slate-500">
            Score total
          </span>
          <span className="text-[10px] font-bold text-slate-700 dark:text-slate-200 tabular-nums">
            {score ?? 0}/100  ·  {features.confluence_depth}/5 pilares
          </span>
        </div>
      )}
    </div>
  )
}
