import api from './api'

export const montecarloService = {
  // Estrategias
  getStrategies: () => api.get('/montecarlo/strategies'),
  createStrategy: (data) => api.post('/montecarlo/strategies', data),
  updateStrategy: (id, data) => api.put(`/montecarlo/strategies/${id}`, data),
  deleteStrategy: (id) => api.delete(`/montecarlo/strategies/${id}`),

  // Backtest
  runBacktest: (strategyId, data) => api.post(`/montecarlo/strategies/${strategyId}/backtest`, data),
  getBacktests: (strategyId) => api.get('/montecarlo/backtests', { params: strategyId ? { strategy_id: strategyId } : {} }),

  // Simulación Monte Carlo
  runSimulation: (backtestId, data) => api.post(`/montecarlo/backtests/${backtestId}/simulate`, data),
  getSimulations: (backtestId) => api.get('/montecarlo/simulations', { params: backtestId ? { backtest_id: backtestId } : {} }),

  // Validación en vivo
  validateLive: (data) => api.post('/montecarlo/validate-live', data),

  // Utilidades
  getIndicators: () => api.get('/montecarlo/indicators'),
  getStrategyTemplate: () => api.get('/montecarlo/strategy-template'),
  getSymbols: () => api.get('/montecarlo/symbols'),

  // IA Engine Integration
  evaluateAI: (data) => api.post('/montecarlo/ai-engine/eval', data),
  scanAI: (data) => api.post('/montecarlo/ai-engine/scan', data),
  recalibrateAI: (data) => api.post('/montecarlo/ai-engine/recalibrate', data),

  // IA Engine Batch Evaluation
  evalBatch: (data) => api.post('/montecarlo/ai-engine/eval-batch', data),
  applyEvalToBot: (data) => api.post('/montecarlo/bots/apply-eval', data),
}
