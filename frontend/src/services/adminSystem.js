import api from './api'

export const adminSystemService = {
  getHealth: () => api.get('/admin/system/health'),
  listChecks: () => api.get('/admin/system/checks'),
  runCheck: (check) => api.post('/admin/system/run-check', { check }),
  shareLog: (report) => api.post('/admin/system/share-log', { report }),
  getShadowHistory: (limit = 20) => api.get(`/admin/system/shadow-history?limit=${limit}`),
  runShadowCheck: () => api.post('/admin/system/run-shadow-check'),
}
