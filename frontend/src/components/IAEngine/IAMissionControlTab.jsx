import { useMemo } from 'react'
import IAStatusBar from './IAStatusBar'
import IAWatchlistCard from './IAWatchlistCard'
import IARejectionFeed from './IARejectionFeed'
import IAMlVsRealPanel from './IAMlVsRealPanel'

const TIMEFRAMES = ['auto', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w']

export default function IAMissionControlTab({
  watchlist,
  results,
  scanning,
  tickerStats,
  aiBots,
  selected,
  autoRefresh,
  lastScan,
  countdown,
  isAnyScanning,
  onSelect,
  onRemove,
  onChangeTimeframe,
  onScanOne,
  onScanAll,
  onToggleAutoRefresh,
}) {
  const aiBotsBySymbol = useMemo(() => {
    const map = {}
    aiBots?.forEach((bot) => {
      // Normalize CCXT symbol "XRP/USDT:USDT" to compact "XRPUSDT"
      const sym = bot.symbol
        ?.replace(/\/([^:]+):[^:]+$/, '$1')
        .replace('/', '')
      if (!sym) return
      if (!map[sym]) map[sym] = []
      map[sym].push(bot.bot_name)
    })
    return map
  }, [aiBots])

  const symbolsForRejections = useMemo(
    () => watchlist.map((e) => e.symbol),
    [watchlist]
  )

  return (
    <div className="space-y-4">
      {/* Status Bar */}
      <IAStatusBar
        isScanning={isAnyScanning}
        autoRefresh={autoRefresh}
        onToggleAutoRefresh={onToggleAutoRefresh}
        lastScan={lastScan}
        countdown={countdown}
        aiBots={aiBots}
        onScanAll={onScanAll}
        watchlistLength={watchlist.length}
      />

      {/* Main content grid */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
        {/* Watchlist cards — takes 3/4 on XL */}
        <div className="xl:col-span-3">
          {watchlist.length === 0 ? (
            <div className="text-center py-16 text-slate-400 dark:text-slate-600 border border-dashed border-slate-200 dark:border-slate-700 rounded-lg">
              <p className="text-sm">Sin pares en watchlist</p>
              <p className="text-xs mt-1">Añade símbolos desde el selector superior</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {watchlist.map((entry) => (
                <IAWatchlistCard
                  key={entry.symbol}
                  entry={entry}
                  result={results[entry.symbol]}
                  scanning={!!scanning[entry.symbol]}
                  tickerStats={tickerStats[entry.symbol] ?? null}
                  aiBotNames={aiBotsBySymbol[entry.symbol] ?? null}
                  onRemove={onRemove}
                  onChangeTimeframe={onChangeTimeframe}
                  onScanOne={onScanOne}
                  onSelect={onSelect}
                  isSelected={selected?.symbol === entry.symbol}
                  timeframes={TIMEFRAMES}
                />
              ))}
            </div>
          )}
        </div>

        {/* Side panels — takes 1/4 on XL */}
        <div className="xl:col-span-1 space-y-4">
          <div className="h-80">
            <IARejectionFeed symbols={symbolsForRejections} />
          </div>
          <IAMlVsRealPanel watchlist={watchlist} />
        </div>
      </div>
    </div>
  )
}
