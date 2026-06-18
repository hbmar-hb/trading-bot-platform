import { useMemo } from 'react'
import { Bot, Clock, RefreshCw, ScanLine, ShieldAlert } from 'lucide-react'
import { cn } from '@/utils/cn'

export default function IAStatusBar({
  isScanning,
  autoRefresh,
  onToggleAutoRefresh,
  lastScan,
  countdown,
  aiBots,
  onScanAll,
  watchlistLength,
}) {
  const aiBotCount = aiBots?.length ?? 0
  const aiSymbols = useMemo(() => {
    const syms = new Set()
    aiBots?.forEach((b) => {
      if (b.symbol) syms.add(b.symbol.replace(/USDT$|USDC$/, ''))
    })
    return Array.from(syms)
  }, [aiBots])

  const circuitOpen = false // Could be wired to aiService.circuitBreaker() later

  const ageText = useMemo(() => {
    if (!lastScan) return ''
    const mins = Math.floor((Date.now() - lastScan.getTime()) / 60000)
    if (mins < 1) return ' — justo ahora'
    if (mins < 60) return ` — hace ${mins}m`
    const hours = Math.floor(mins / 60)
    return ` — hace ${hours}h ${mins % 60}m`
  }, [lastScan])

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-4 flex-wrap">
        {/* Engine state */}
        <div className="flex items-center gap-2">
          <span className={cn(
            'w-2.5 h-2.5 rounded-full shrink-0',
            circuitOpen ? 'bg-red-500' : isScanning ? 'bg-blue-500 animate-pulse' : 'bg-emerald-500',
          )} />
          <span className={cn(
            'text-sm font-bold',
            circuitOpen ? 'text-red-600 dark:text-red-400' : isScanning ? 'text-blue-700 dark:text-blue-400' : 'text-slate-700 dark:text-slate-200',
          )}>
            {circuitOpen ? 'Motor PAUSADO' : isScanning ? 'Escaneando mercado…' : 'Motor activo'}
          </span>
        </div>

        {/* Last scan + countdown */}
        {!isScanning && lastScan && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Último scan: {lastScan.toLocaleTimeString()}{ageText}
          </span>
        )}
        {autoRefresh && countdown != null && (
          <span className="text-xs text-slate-500 dark:text-slate-400 tabular-nums">
            Próximo: <strong className="text-slate-700 dark:text-slate-200">{Math.floor(countdown / 60)}:{String(countdown % 60).padStart(2, '0')}</strong>
          </span>
        )}

        {/* AI Bots badge */}
        {aiBotCount > 0 && (
          <div className="flex items-center gap-1.5 text-xs">
            <Bot size={13} className="text-blue-500" />
            <span className="font-semibold text-slate-700 dark:text-slate-200">{aiBotCount}</span>
            <span className="text-slate-500 dark:text-slate-400">bot{aiBotCount !== 1 ? 's' : ''} IA</span>
            {aiSymbols.length > 0 && (
              <span className="text-[10px] text-slate-400 dark:text-slate-500 ml-1">
                ({aiSymbols.join(', ')})
              </span>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={onScanAll}
            disabled={isScanning || !watchlistLength}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors',
              isScanning
                ? 'bg-slate-100 border-slate-300 text-slate-400 cursor-not-allowed'
                : 'bg-blue-600 border-blue-600 text-white hover:bg-blue-700',
            )}
          >
            {isScanning ? <RefreshCw size={12} className="animate-spin" /> : <ScanLine size={12} />}
            {isScanning ? 'Escaneando…' : `Escanear todo (${watchlistLength})`}
          </button>

          <button
            onClick={onToggleAutoRefresh}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors',
              autoRefresh
                ? 'bg-blue-100 border-blue-300 text-blue-700 dark:bg-blue-600/20 dark:border-blue-500/40 dark:text-blue-400'
                : 'bg-slate-100 border-slate-300 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-700',
            )}
          >
            <Clock size={12} />
            Auto {autoRefresh ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {/* Progress bar for auto-scan */}
      {autoRefresh && countdown != null && !isScanning && (
        <div className="w-full">
          <div className="h-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-400 dark:bg-blue-500 rounded-full transition-all duration-1000"
              style={{ width: `${((300 - countdown) / 300) * 100}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
