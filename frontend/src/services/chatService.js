import api from './api'

export const chatService = {
  getRooms:    ()              => api.get('/chat/rooms'),
  createRoom:  (data)         => api.post('/chat/rooms', data),
  deleteRoom:  (roomId)       => api.delete(`/chat/rooms/${roomId}`),
  getMessages: (roomId, limit = 50) => api.get(`/chat/rooms/${roomId}/messages`, { params: { limit } }),
}
