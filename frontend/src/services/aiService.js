import api from './api'

export const aiService = {
  // On-demand scan
  analyze:      (symbol, timeframe)  => api.get('/ai/analyze',         { params: { symbol, timeframe } }),
  scan:         (symbols, timeframe) => api.get('/ai/scan',             { params: { symbols: symbols.join(','), timeframe } }),

  // Persisted results — called on page mount to restore last known state
  latestScans:  (symbols = [])       => api.get('/ai/latest-scans',     { params: { symbols: symbols.join(',') } }),

  // Watchlist persistence — sync entire watchlist to backend on every change
  getWatchlist: ()                   => api.get('/ai/watchlist'),
  syncWatchlist:(items)              => api.post('/ai/watchlist/sync',  items),

  // Signal history
  listSignals:  (limit = 50, ticker) => api.get('/ai/signals',          { params: { limit, ticker } }),
  stats:        ()                   => api.get('/ai/signals/stats'),

  // ML model
  modelStatus:  ()                   => api.get('/ai/model/status'),
  trainModel:   ()                   => api.post('/ai/model/train'),

  // AI-mode bots
  listAiBots:   ()                   => api.get('/ai/bots'),

  // Per-ticker stats and live ICT analysis (no DB write)
  statsByTicker: ()                  => api.get('/ai/signals/stats/by-ticker'),
  ictAnalysis:   (symbol, tf)        => api.get('/ai/ict-analysis', { params: { symbol, timeframe: tf } }),
}
