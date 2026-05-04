import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authService } from '@/services/auth'
import useAuthStore from '@/store/authStore'

export function useAuth() {
  const { user, token, setUser, setTokens, logout: storeLogout } = useAuthStore()
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const navigate = useNavigate()

  // Cargar perfil si hay token pero no user
  useEffect(() => {
    if (token && !user) {
      authService.me()
        .then(r => setUser(r.data))
        .catch(() => storeLogout())
    }
  }, [token])

  const login = useCallback(async (username, password) => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await authService.login({ username, password })
      setTokens(data.access_token, data.refresh_token)
      const me = await authService.me()
      setUser(me.data)
      navigate('/dashboard')
      return true
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al iniciar sesión')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    storeLogout()
    navigate('/login')
  }, [])

  return {
    user,
    isAuthenticated: !!token,
    loading,
    error,
    login,
    logout,
  }
}
