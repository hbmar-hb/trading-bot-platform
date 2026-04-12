import api from './api'

export const analyticsService = {
  summary:  ()      => api.get('/analytics/summary'),
  botStats: (id)    => api.get(`/analytics/bots/${id}`),
}
