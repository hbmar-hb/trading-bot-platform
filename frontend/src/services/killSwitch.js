import api from './api'

export const killSwitchService = {
  trigger: () => api.post('/portfolio/kill-switch'),
}
