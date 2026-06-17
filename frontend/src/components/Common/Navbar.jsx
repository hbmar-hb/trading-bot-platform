import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  AlertOctagon, BarChart3, BookOpen, Bot, Brain, CandlestickChart, Dices, FileText, Gauge, History, KeyRound,
  LogOut, Menu, MessageSquare, Moon, MousePointerClick, Settings, ShieldAlert, Sun, TrendingUp, Users, Zap,
} from 'lucide-react'
import { cn } from '@/utils/cn'
import { useAuth } from '@/hooks/useAuth'
import useUiStore from '@/store/uiStore'
import useBalanceStore from '@/store/balanceStore'
import { optimizerService } from '@/services/optimizer'
import { chatService } from '@/services/chat'
import { killSwitchService } from '@/services/killSwitch'
import { AUTHORIZED_ROLES, PRIVILEGED_ROLES, ROLES, hasAnyRole, isAdmin } from '@/constants/roles'

const links = [
  { to: '/dashboard',          icon: Gauge,        label: 'Dashboard',  roles: AUTHORIZED_ROLES },
  { to: '/bots',               icon: Bot,          label: 'Bots',       roles: AUTHORIZED_ROLES },
  { to: '/positions',          icon: TrendingUp,   label: 'Posiciones', roles: AUTHORIZED_ROLES },
  { to: '/chart',              icon: CandlestickChart, label: 'Chart',  roles: PRIVILEGED_ROLES },
  { to: '/ai',                 icon: Brain,        label: 'IA Engine',  roles: [ROLES.ADMIN] },
  { to: '/montecarlo',         icon: Dices,        label: 'Monte Carlo', roles: PRIVILEGED_ROLES },
  { to: '/analytics',          icon: BarChart3,    label: 'Analytics',  roles: AUTHORIZED_ROLES },
  { to: '/exchange-accounts',  icon: KeyRound,     label: 'Exchanges',  roles: AUTHORIZED_ROLES },
  { to: '/exchange-trades',    icon: History,      label: 'Historial',  roles: AUTHORIZED_ROLES },
  { to: '/manual-trading',     icon: MousePointerClick, label: 'Manual', roles: AUTHORIZED_ROLES },
  { to: '/paper-trading',      icon: FileText,     label: 'Paper',      roles: PRIVILEGED_ROLES },
  { to: '/optimizer-db',       icon: Zap,          label: 'Optimizer DB', roles: PRIVILEGED_ROLES, badge: 'alerts' },
  { to: '/chat',               icon: MessageSquare, label: 'Chat',      roles: PRIVILEGED_ROLES, badge: 'mentions' },
  { to: '/users',              icon: Users,        label: 'Usuarios',   roles: [ROLES.ADMIN] },
  { to: '/admin/system',       icon: ShieldAlert,  label: 'Sistema',    roles: [ROLES.ADMIN] },
  { to: '/docs',               icon: BookOpen,     label: 'Docs',       roles: AUTHORIZED_ROLES },
  { to: '/settings',           icon: Settings,     label: 'Ajustes',    roles: AUTHORIZED_ROLES },
]

export default function Navbar() {
  const { sidebarOpen, toggleSidebar, isDark, toggleTheme } = useUiStore()
  const { logout, user }    = useAuth()
  const totalEquity         = useBalanceStore(s => s.getTotalEquity())
  const [alertCount, setAlertCount] = useState(0)
  const [mentionCount, setMentionCount] = useState(0)

  useEffect(() => {
    if (!hasAnyRole(user, PRIVILEGED_ROLES)) return
    const loadAlerts = async () => {
      try {
        const res = await optimizerService.getGlobalDB()
        setAlertCount(res.data.alerts?.length || 0)
      } catch (e) {
        // Silenciar error
      }
    }
    loadAlerts()
    const interval = setInterval(loadAlerts, 60000)
    return () => clearInterval(interval)
  }, [user])

  useEffect(() => {
    if (!hasAnyRole(user, PRIVILEGED_ROLES)) return
    const loadMentions = async () => {
      try {
        const res = await chatService.listMentions()
        setMentionCount(res.data.length || 0)
      } catch (e) {
        // Silenciar error
      }
    }
    loadMentions()
    const interval = setInterval(loadMentions, 10000)
    return () => clearInterval(interval)
  }, [user])

  const visibleLinks = links.filter(l => hasAnyRole(user, l.roles))

  return (
    <aside className={cn(
      'fixed left-0 top-0 h-full flex-col transition-all duration-200 z-40',
      'bg-white dark:bg-gray-900 border-r border-slate-200 dark:border-gray-800',
      'hidden md:flex',
      sidebarOpen ? 'w-56' : 'w-16'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-gray-800">
        {sidebarOpen && (
          <span className="text-sm font-bold text-slate-900 dark:text-white truncate">Trading Bots</span>
        )}
        <button
          onClick={toggleSidebar}
          className="text-slate-500 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white p-1 rounded"
        >
          <Menu size={18} />
        </button>
      </div>

      {/* Balance */}
      {sidebarOpen && totalEquity > 0 && (
        <div className="mx-3 mt-3 px-3 py-2 rounded-lg bg-slate-100 dark:bg-gray-800">
          <p className="text-xs text-slate-500 dark:text-gray-500">Equity total</p>
          <p className="text-sm font-mono font-semibold text-slate-900 dark:text-white">
            ${totalEquity.toFixed(2)}
          </p>
        </div>
      )}

      {/* Links */}
      <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
        {visibleLinks.map(({ to, icon: Icon, label, badge }) => {
          const count = badge === 'alerts' ? alertCount : badge === 'mentions' ? mentionCount : 0
          return (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => cn(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-blue-600/15 text-blue-600 dark:text-blue-400'
                  : 'text-slate-600 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-gray-800'
              )}
            >
              <div className="relative">
                <Icon size={18} className="shrink-0" />
                {count > 0 && (
                  <span className={cn(
                    'absolute -top-1.5 -right-1.5 w-4 h-4 text-white text-[10px] font-bold rounded-full flex items-center justify-center',
                    badge === 'alerts' ? 'bg-red-500' : 'bg-blue-500'
                  )}>
                    {badge === 'mentions' ? '@' : count}
                  </span>
                )}
              </div>
              {sidebarOpen && <span>{label}</span>}
            </NavLink>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-slate-200 dark:border-gray-800 space-y-1">
        {/* Kill Switch: solo admin */}
        {isAdmin(user) && (
          <button
            onClick={async () => {
              if (!confirm('🚨 KILL SWITCH\n\n¿Estás seguro de que quieres cerrar TODAS las posiciones abiertas y pausar todos los bots?\n\nEsta acción no se puede deshacer.')) return
              try {
                const { data } = await killSwitchService.trigger()
                // eslint-disable-next-line no-console
                console.log('Kill Switch activado', data)
              } catch (e) {
                // eslint-disable-next-line no-console
                console.error('Error en Kill Switch', e)
              }
            }}
            className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm bg-red-600 hover:bg-red-700 text-white transition-colors"
          >
            <AlertOctagon size={18} className="shrink-0" />
            {sidebarOpen && <span>Kill Switch</span>}
          </button>
        )}

        {/* Toggle tema */}
        <button
          onClick={toggleTheme}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-slate-500 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-gray-800 transition-colors"
        >
          {isDark
            ? <Sun  size={18} className="shrink-0" />
            : <Moon size={18} className="shrink-0" />
          }
          {sidebarOpen && <span>{isDark ? 'Modo claro' : 'Modo oscuro'}</span>}
        </button>

        {sidebarOpen && user && (
          <p className="text-xs text-slate-500 dark:text-gray-500 px-1 truncate">{user.username}</p>
        )}

        <button
          onClick={logout}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-slate-500 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-slate-100 dark:hover:bg-gray-800 transition-colors"
        >
          <LogOut size={18} className="shrink-0" />
          {sidebarOpen && <span>Salir</span>}
        </button>
      </div>
    </aside>
  )
}
