import api from './api'

export const optimizerService = {
  get: (botId) => api.get(`/optimizer/${botId}`),
  apply: (botId, params) => api.post(`/optimizer/${botId}/apply`, { params }),
}
