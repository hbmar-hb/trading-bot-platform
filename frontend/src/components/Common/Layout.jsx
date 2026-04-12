import Navbar from './Navbar'
import BottomNav from './BottomNav'
import useUiStore from '@/store/uiStore'
import { cn } from '@/utils/cn'

export default function Layout({ children }) {
  const sidebarOpen = useUiStore(s => s.sidebarOpen)

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-gray-950 text-slate-900 dark:text-gray-100">
      <Navbar />

      <main className={cn(
        'transition-all duration-200 min-h-screen',
        sidebarOpen ? 'md:ml-56' : 'md:ml-16',
        'pb-20 md:pb-0'
      )}>
        <div className="p-4 md:p-6 max-w-7xl mx-auto">
          {children}
        </div>
      </main>

      <BottomNav />
    </div>
  )
}
