import api from './api'

export const tradingSignalsService = {
  list: (params = {}) => api.get('/trading-signals', { params }),
  get: (id) => api.get(`/trading-signals/${id}`),
  stats: (days = 7) => api.get('/trading-signals/stats/summary', { params: { days } }),
}
