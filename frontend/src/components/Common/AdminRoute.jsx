import { Navigate } from 'react-router-dom'
import useAuthStore from '@/store/authStore'
import { isAtLeastAdmin } from '@/constants/roles'

export default function AdminRoute({ children }) {
  const user = useAuthStore(s => s.user)
  if (!isAtLeastAdmin(user)) return <Navigate to="/dashboard" replace />
  return children
}
