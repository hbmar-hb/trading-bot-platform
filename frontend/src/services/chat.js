import api from './api'

export const chatService = {
  listRooms:    ()                   => api.get('/chat/rooms'),
  createRoom:   (data)               => api.post('/chat/rooms', data),
  deleteRoom:   (id)                 => api.delete(`/chat/rooms/${id}`),
  listMessages: (roomId, limit = 50) => api.get(`/chat/rooms/${roomId}/messages?limit=${limit}`),
  sendMessage:  (data)               => api.post('/chat/messages', data),
  searchGifs:   (q)                  => api.get(`/chat/gifs?q=${encodeURIComponent(q)}`),
  addMember:    (roomId, userId)     => api.post(`/chat/rooms/${roomId}/members`, { user_id: userId }),
  removeMember: (roomId, userId)     => api.delete(`/chat/rooms/${roomId}/members/${userId}`),
  listMentions: ()                   => api.get('/chat/mentions'),
  markMentionRead: (id)              => api.post(`/chat/mentions/${id}/read`),
  markRoomMentionsRead: (roomId)     => api.post(`/chat/rooms/${roomId}/mentions/read`),
}
