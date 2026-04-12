import api from './api'

export const botsService = {
  list:         ()          => api.get('/bots'),
  get:          (id)        => api.get(`/bots/${id}`),
  create:       (data)      => api.post('/bots', data),
  update:       (id, data)  => api.put(`/bots/${id}`, data),
  setStatus:    (id, status)=> api.patch(`/bots/${id}/status`, { status }),
  delete:       (id)        => api.delete(`/bots/${id}`),
}
