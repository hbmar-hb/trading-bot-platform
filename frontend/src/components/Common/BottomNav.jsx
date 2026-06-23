import { NavLink } from 'react-router-dom'
import { BarChart3, BookOpen, Bot, Dices, Gauge, KeyRound, MousePointerClick, Settings, TrendingUp } from 'lucide-react'
import { cn } from '@/utils/cn'
import { useAuth } from '@/hooks/useAuth'
import { AUTHORIZED_ROLES, ROLES, hasAnyRole } from '@/constants/roles'

const links = [
  { to: '/dashboard',         icon: Gauge,      label: 'Inicio',     roles: AUTHORIZED_ROLES },
  { to: '/bots',              icon: Bot,        label: 'Bots',       roles: AUTHORIZED_ROLES },
  { to: '/positions',         icon: TrendingUp, label: 'Posiciones', roles: AUTHORIZED_ROLES },
  { to: '/manual-trading',    icon: MousePointerClick, label: 'Manual', roles: AUTHORIZED_ROLES },
  { to: '/exchange-accounts', icon: KeyRound,   label: 'Exchanges',  roles: AUTHORIZED_ROLES },
  { to: '/montecarlo',        icon: Dices,      label: 'Monte',      roles: [ROLES.DEVELOPER] },
  { to: '/analytics',         icon: BarChart3,  label: 'Analytics',  roles: AUTHORIZED_ROLES },
  { to: '/docs',              icon: BookOpen,   label: 'Docs',       roles: AUTHORIZED_ROLES },
  { to: '/settings',          icon: Settings,   label: 'Ajustes',    roles: AUTHORIZED_ROLES },
]

export default function BottomNav() {
  const { user } = useAuth()
  const visibleLinks = links.filter(l => hasAnyRole(user, l.roles))

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 bg-white dark:bg-gray-900 border-t border-slate-200 dark:border-gray-800 md:hidden">
      <div className="flex">
        {visibleLinks.map(({ to, icon: Icon, label }) => (
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
