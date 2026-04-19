import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  BarChart3, Bot, CandlestickChart, FileText, Gauge, History, KeyRound,
  LogOut, Menu, Moon, MousePointerClick, Settings, Sun, TrendingUp, Users, Zap,
} from 'lucide-react'
import { cn } from '@/utils/cn'
import { useAuth } from '@/hooks/useAuth'
import useUiStore from '@/store/uiStore'
import useBalanceStore from '@/store/balanceStore'
import { optimizerService } from '@/services/optimizer'

const links = [
  { to: '/dashboard',          icon: Gauge,        label: 'Dashboard'  },
  { to: '/bots',               icon: Bot,          label: 'Bots'       },
  { to: '/positions',          icon: TrendingUp,   label: 'Posiciones' },
  { to: '/chart',              icon: CandlestickChart, label: 'Chart'  },
  { to: '/analytics',          icon: BarChart3,    label: 'Analytics'  },
  { to: '/exchange-accounts',  icon: KeyRound,     label: 'Exchanges'  },
  { to: '/exchange-trades',    icon: History,      label: 'Historial'  },
  { to: '/manual-trading',     icon: MousePointerClick, label: 'Manual'  },
  { to: '/paper-trading',      icon: FileText,     label: 'Paper'      },
  { to: '/users',              icon: Users,        label: 'Usuarios'   },
  { to: '/settings',           icon: Settings,     label: 'Ajustes'    },
]

export default function Navbar() {
  const { sidebarOpen, toggleSidebar, isDark, toggleTheme } = useUiStore()
  const { logout, user }    = useAuth()
  const totalEquity         = useBalanceStore(s => s.getTotalEquity())
  const [alertCount, setAlertCount] = useState(0)

  useEffect(() => {
    const loadAlerts = async () => {
      try {
        const res = await optimizerService.getGlobalDB()
        setAlertCount(res.data.alerts?.length || 0)
      } catch (e) {
        // Silenciar error
      }
    }
    loadAlerts()
    // Actualizar cada 60 segundos
    const interval = setInterval(loadAlerts, 60000)
    return () => clearInterval(interval)
  }, [])

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
        {links.map(({ to, icon: Icon, label }) => (
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
            <Icon size={18} className="shrink-0" />
            {sidebarOpen && <span>{label}</span>}
          </NavLink>
        ))}
        
        {/* Optimizer DB con badge de alertas */}
        <NavLink
          to="/optimizer-db"
          className={({ isActive }) => cn(
            'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
            isActive
              ? 'bg-purple-600/15 text-purple-600 dark:text-purple-400'
              : 'text-slate-600 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-gray-800'
          )}
        >
          <div className="relative">
            <Zap size={18} className="shrink-0" />
            {alertCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                {alertCount}
              </span>
            )}
          </div>
          {sidebarOpen && <span>Optimizer DB</span>}
        </NavLink>
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-slate-200 dark:border-gray-800 space-y-1">
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
