import api from './api'

export const paperTradingService = {
  list: () => api.get('/paper-trading/'),
  create: (data) => api.post('/paper-trading/', data),
  get: (id) => api.get(`/paper-trading/${id}`),
  update: (id, data) => api.patch(`/paper-trading/${id}`, data),
  delete: (id) => api.delete(`/paper-trading/${id}`),
  reset: (id) => api.post(`/paper-trading/${id}/reset`),
  getBalance: (id) => api.get(`/paper-trading/${id}/balance`),
}
