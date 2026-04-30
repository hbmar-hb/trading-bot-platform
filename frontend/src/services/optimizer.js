import api from './api'

export const optimizerService = {
  get: (botId, tradeLimit) => api.get(`/optimizer/${botId}`, { params: tradeLimit ? { trade_limit: tradeLimit } : undefined }),
  apply: (botId, params) => api.post(`/optimizer/${botId}/apply`, { params }),
  getAutoStatus: (botId) => api.get(`/optimizer/${botId}/auto-status`),
  toggleAuto: (botId, enabled) => api.post(`/optimizer/${botId}/auto-toggle`, { enabled }),
  updateAutoConfig: (botId, config) => api.post(`/optimizer/${botId}/auto-config`, config),
  runAuto: (botId) => api.post(`/optimizer/${botId}/auto-run`),
  runAutoDryRun: (botId) => api.post(`/optimizer/${botId}/auto-run?dry_run=true`),
  getEffectivenessDashboard: (botId) => api.get(`/optimizer/${botId}/effectiveness-dashboard`),
  getGlobalDB: () => api.get('/optimizer/db/global'),
}
