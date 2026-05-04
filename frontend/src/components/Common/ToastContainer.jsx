import { useEffect } from 'react'
import { X, Zap, AlertTriangle, Info } from 'lucide-react'
import useUiStore from '@/store/uiStore'

const icons = {
  optimizer: Zap,
  info: Info,
  warning: AlertTriangle,
  error: AlertTriangle,
}

const colors = {
  optimizer: 'bg-purple-600 border-purple-400',
  info: 'bg-blue-600 border-blue-400',
  warning: 'bg-yellow-600 border-yellow-400',
  error: 'bg-red-600 border-red-400',
}

export default function ToastContainer() {
  const notifications = useUiStore(s => s.notifications)
  const removeNotification = useUiStore(s => s.removeNotification)

  useEffect(() => {
    if (notifications.length === 0) return
    const timers = notifications.map(n =>
      setTimeout(() => removeNotification(n.id), 6000)
    )
    return () => timers.forEach(clearTimeout)
  }, [notifications])

  if (notifications.length === 0) return null

  return (
    <div className="fixed top-4 right-4 z-[100] space-y-3 w-80">
      {notifications.map(n => {
        const Icon = icons[n.type] || icons.info
        const color = colors[n.type] || colors.info
        return (
          <div
            key={n.id}
            className={`${color} text-white rounded-lg shadow-lg border p-3 flex gap-3 animate-in slide-in-from-right`}
          >
            <Icon size={20} className="shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <h4 className="font-semibold text-sm">{n.title}</h4>
              <p className="text-xs text-white/90 mt-0.5 leading-relaxed">{n.message}</p>
            </div>
            <button
              onClick={() => removeNotification(n.id)}
              className="shrink-0 opacity-70 hover:opacity-100"
            >
              <X size={16} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
