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

  // Heuristic validation dashboard
  heuristicValidation: (params = {}) => api.get('/ai/heuristic-validation', { params }),

  // Macro context
  macroContext: (ticker) => api.get('/ai/macro-context', { params: { ticker } }),

  // Portfolio summary
  portfolioSummary: () => api.get('/portfolio/summary'),

  // Optimal AI config for a ticker
  optimalConfig: (ticker, timeframe) => api.get('/ai/optimal-config', { params: { ticker, timeframe } }),

  // Real executed trades stats for a ticker (with optional mode: real|paper|total)
  symbolRealStats: (symbol, mode = 'real') => api.get(`/ai/symbol-real-stats/${symbol}`, { params: { mode } }),

  // Global backtest comparison (all symbols)
  backtestComparison: (days = 60) => api.get('/ai/backtest-comparison', { params: { days } }),

  // Backtest vs real+paper comparison curve
  symbolBacktestComparison: (symbol, days = 60) => api.get(`/ai/symbol-backtest-comparison/${symbol}`, { params: { days } }),

  // Rejected signals for a symbol (detailed list + summary)
  symbolRejections: (symbol, params = {}) => api.get(`/ai/symbol-rejections/${symbol}`, { params }),

  // Global real performance (all IA trades, with optional mode: real|paper|total)
  realPerformance: (mode = 'total') => api.get('/ai/real-performance', { params: { mode } }),

  // Aggregated dashboard (model health + equity curve + funnel + tier matrix)
  dashboard: () => api.get('/ai/dashboard'),

  // LLM signal diagnosis (Kimi) — admin only
  signalDiagnosis: (signalId) => api.get(`/ai/signals/${signalId}/diagnosis`),

  // Free signal context — any authenticated user
  signalContext: (signalId) => api.get(`/ai/signals/${signalId}/context`),

  // Risk & Safety
  circuitBreaker: () => api.get('/ai/circuit-breaker'),
  shadowMode:     () => api.get('/ai/shadow-mode'),

  // Engine Control — unified evaluated signals, charts, autonomy evidence
  engineControl: (days = 30) => api.get('/ai/engine-control', { params: { days } }),
}
