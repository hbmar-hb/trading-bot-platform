import api from './api'

export const optimizerService = {
  get: (botId) => api.get(`/optimizer/${botId}`),
  apply: (botId, params) => api.post(`/optimizer/${botId}/apply`, { params }),
  getAutoStatus: (botId) => api.get(`/optimizer/${botId}/auto-status`),
  toggleAuto: (botId, enabled) => api.post(`/optimizer/${botId}/auto-toggle`, { enabled }),
  updateAutoConfig: (botId, config) => api.post(`/optimizer/${botId}/auto-config`, config),
  runAuto: (botId) => api.post(`/optimizer/${botId}/auto-run`),
  getEffectivenessDashboard: (botId) => api.get(`/optimizer/${botId}/effectiveness-dashboard`),
  getGlobalDB: () => api.get('/optimizer/db/global'),
}
