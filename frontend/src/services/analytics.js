import api from './api'

export const analyticsService = {
  summary:           ()       => api.get('/analytics/summary'),
  botStats:          (id)     => api.get(`/analytics/bots/${id}`),
  pnlChart:          (params) => api.get('/analytics/pnl-chart', { params }),
  activityHeatmap:   (params) => api.get('/analytics/activity-heatmap', { params }),
  hourlyDistribution:(params) => api.get('/analytics/hourly-distribution', { params }),
}
