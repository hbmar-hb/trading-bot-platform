import api from './api'

export const optimizerService = {
  get: (botId) => api.get(`/optimizer/${botId}`),
}
