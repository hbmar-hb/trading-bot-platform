import api from './api'

export const usersService = {
  list:           ()           => api.get('/users'),
  onlineStatus:   ()           => api.get('/users/online-status'),
  create:         (data)       => api.post('/users', data),
  update:         (id, data)   => api.patch(`/users/${id}`, data),
  sendResetEmail: (id)         => api.post(`/users/${id}/send-reset-email`),
  delete:         (id)         => api.delete(`/users/${id}`),
}
