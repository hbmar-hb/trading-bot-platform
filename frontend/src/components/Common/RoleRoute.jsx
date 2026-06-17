import { Navigate } from 'react-router-dom'
import useAuthStore from '@/store/authStore'

export default function RoleRoute({ children, allowedRoles }) {
  const user = useAuthStore((state) => state.user)

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (allowedRoles.includes(user.role)) {
    return children
  }

  return <Navigate to="/dashboard" replace />
}
