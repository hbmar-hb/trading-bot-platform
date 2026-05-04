import api from './api'

export const analyticsService = {
  summary:           (params) => api.get('/analytics/summary', { params }),
  botStats:          (id)     => api.get(`/analytics/bots/${id}`),
  pnlChart:          (params) => api.get('/analytics/pnl-chart', { params }),
  activityHeatmap:   (params) => api.get('/analytics/activity-heatmap', { params }),
  hourlyDistribution:(params) => api.get('/analytics/hourly-distribution', { params }),
  tradesDetail:      (params) => api.get('/analytics/trades-detail', { params }),
}
