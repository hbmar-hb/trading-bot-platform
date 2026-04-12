import { NavLink } from 'react-router-dom'
import { BarChart3, Bot, Gauge, KeyRound, MousePointerClick, Settings, TrendingUp } from 'lucide-react'
import { cn } from '@/utils/cn'

const links = [
  { to: '/dashboard',         icon: Gauge,      label: 'Inicio'    },
  { to: '/bots',              icon: Bot,        label: 'Bots'      },
  { to: '/positions',         icon: TrendingUp, label: 'Posiciones'},
  { to: '/manual-trading',    icon: MousePointerClick, label: 'Manual' },
  { to: '/exchange-accounts', icon: KeyRound,   label: 'Exchanges' },
  { to: '/analytics',         icon: BarChart3,  label: 'Analytics' },
  { to: '/settings',          icon: Settings,   label: 'Ajustes'   },
]

export default function BottomNav() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 bg-white dark:bg-gray-900 border-t border-slate-200 dark:border-gray-800 md:hidden">
      <div className="flex">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => cn(
              'flex-1 flex flex-col items-center justify-center py-2 gap-0.5 text-xs transition-colors',
              isActive
                ? 'text-blue-600 dark:text-blue-400'
                : 'text-slate-500 dark:text-gray-500'
            )}
          >
            <Icon size={20} />
            <span className="text-[10px] leading-tight">{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
