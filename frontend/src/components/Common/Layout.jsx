import { useEffect } from 'react'
import Navbar from './Navbar'
import BottomNav from './BottomNav'
import ToastContainer from './ToastContainer'
import AssistantWidget from './AssistantWidget'
import useUiStore from '@/store/uiStore'
import useAuthStore from '@/store/authStore'
import { authService } from '@/services/auth'
import { cn } from '@/utils/cn'

export default function Layout({ children }) {
  const sidebarOpen = useUiStore(s => s.sidebarOpen)
  const { user, token, setUser } = useAuthStore()

  // Reload user on page refresh (Zustand doesn't persist across reloads)
  useEffect(() => {
    if (token && !user) {
      authService.me().then(r => setUser(r.data)).catch(() => {})
    }
  }, [token])

  return (
    <div className="h-screen overflow-hidden bg-slate-100 dark:bg-gray-950 text-slate-900 dark:text-gray-100">
      <Navbar />
      <ToastContainer />

      <main className={cn(
        'h-full overflow-y-auto transition-all duration-200',
        sidebarOpen ? 'md:ml-56' : 'md:ml-16',
        'pb-20 md:pb-0'
      )}>
        <div className="p-4 md:p-6 max-w-7xl mx-auto">
          {children}
        </div>
      </main>

      <BottomNav />
      <AssistantWidget />
    </div>
  )
}
