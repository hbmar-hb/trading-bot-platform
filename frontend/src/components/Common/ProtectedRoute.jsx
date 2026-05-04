import { Navigate, useLocation } from 'react-router-dom'
import useAuthStore from '@/store/authStore'

export default function ProtectedRoute({ children }) {
  const token    = useAuthStore(s => s.token)
  const user     = useAuthStore(s => s.user)
  const { pathname } = useLocation()

  if (!token) return <Navigate to="/login" replace />
  if (user?.must_change_password && pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }
  return children
}
