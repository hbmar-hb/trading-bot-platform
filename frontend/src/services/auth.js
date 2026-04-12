import api from './api'

export const authService = {
  login:          (data) => api.post('/auth/login', data),
  login2fa:       (data) => api.post('/auth/2fa/login', data),
  refresh:        (data) => api.post('/auth/refresh', data),
  me:             ()     => api.get('/auth/me'),
  changePassword: (data) => api.post('/auth/change-password', data),
  setup2fa:       ()     => api.post('/auth/2fa/setup'),
  verify2fa:      (data) => api.post('/auth/2fa/verify', data),
  disable2fa:     (data) => api.post('/auth/2fa/disable', data),
}
