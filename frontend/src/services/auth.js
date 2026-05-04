import api from './api'

export const authService = {
  login:              (data) => api.post('/auth/login', data),
  login2fa:           (data) => api.post('/auth/2fa/login', data),
  refresh:            (data) => api.post('/auth/refresh', data),
  me:                 ()     => api.get('/auth/me'),
  updateMe:           (data) => api.patch('/auth/me', data),
  testTelegram:       ()     => api.post('/auth/test-telegram'),
  changePassword:     (data) => api.post('/auth/change-password', data),
  setup2fa:           ()     => api.post('/auth/2fa/setup'),
  verify2fa:          (data) => api.post('/auth/2fa/verify', data),
  disable2fa:         (data) => api.post('/auth/2fa/disable', data),
  forgotPassword:     (data) => api.post('/auth/forgot-password', data),
  resetPassword:      (data) => api.post('/auth/reset-password', data),
  verifyEmail:        (data) => api.post('/auth/verify-email', data),
  resendVerification: (data) => api.post('/auth/resend-verification', data),
}
