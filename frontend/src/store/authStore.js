import { create } from 'zustand'

const useAuthStore = create((set) => ({
  user:  null,
  token: localStorage.getItem('access_token'),

  setUser:  (user)  => set({ user }),
  setToken: (token) => {
    localStorage.setItem('access_token', token)
    set({ token })
  },
  setTokens: (access, refresh) => {
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
    set({ token: access })
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ user: null, token: null })
  },
  isAuthenticated: () => !!localStorage.getItem('access_token'),
}))

export default useAuthStore
