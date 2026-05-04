import { useWebSocket } from '@/hooks/useWebSocket'
import AppRoutes from '@/routes'

export default function App() {
  useWebSocket()   // conecta WebSocket globalmente una sola vez
  return <AppRoutes />
}
