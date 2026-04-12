import api from './api'

export const usersService = {
  list:          ()           => api.get('/users'),
  create:        (data)       => api.post('/users', data),
  update:        (id, data)   => api.patch(`/users/${id}`, data),
  resetPassword: (id, data)   => api.post(`/users/${id}/reset-password`, data),
  delete:        (id)         => api.delete(`/users/${id}`),
}
