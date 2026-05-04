import { useEffect, useState } from 'react'
import { Bell, BellOff, X, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react'

// Componente de alertas de precio para posiciones
export function usePositionAlerts(position, currentPrice) {
  const [alerts, setAlerts] = useState([])
  const [notifications, setNotifications] = useState([])
  
  useEffect(() => {
    if (!position || !currentPrice) return
    
    const price = parseFloat(currentPrice)
    const slPrice = parseFloat(position.current_sl_price || 0)
    const tpPrices = position.current_tp_prices?.map(tp => parseFloat(tp.price)) || []
    const entryPrice = parseFloat(position.entry_price)
    
    const newAlerts = []
    
    // Alerta de SL cercano (dentro del 2%)
    if (slPrice > 0) {
      const distanceToSL = Math.abs(price - slPrice) / slPrice * 100
      if (distanceToSL < 2) {
        newAlerts.push({
          type: 'warning',
          message: `¡Cerca del Stop Loss! (${distanceToSL.toFixed(2)}%)`,
          icon: AlertTriangle,
          color: 'text-red-400',
          bg: 'bg-red-500/10 border-red-500/30'
        })
      }
    }
    
    // Alerta de TP cercano
    tpPrices.forEach((tp, i) => {
      const distanceToTP = Math.abs(price - tp) / tp * 100
      if (distanceToTP < 1) {
        newAlerts.push({
          type: 'success',
          message: `¡Cerca de TP${i+1}! (${distanceToTP.toFixed(2)}%)`,
          icon: TrendingUp,
          color: 'text-green-400',
          bg: 'bg-green-500/10 border-green-500/30'
        })
      }
    })
    
    // Alerta de breakeven (para posiciones en profit)
    const pnlPercent = position.side === 'long' 
      ? ((price - entryPrice) / entryPrice) * 100
      : ((entryPrice - price) / entryPrice) * 100
      
    if (pnlPercent > 0 && pnlPercent < 1) {
      newAlerts.push({
        type: 'info',
        message: 'Cerca de breakeven - Considera mover SL',
        icon: Bell,
        color: 'text-blue-400',
        bg: 'bg-blue-500/10 border-blue-500/30'
      })
    }
    
    // Alerta de tendencia contraria
    if (position.side === 'long' && pnlPercent < -2) {
      newAlerts.push({
        type: 'danger',
        message: 'Pérdidas superan el 2% - Revisa tu análisis',
        icon: TrendingDown,
        color: 'text-red-400',
        bg: 'bg-red-500/20 border-red-500/50'
      })
    } else if (position.side === 'short' && pnlPercent < -2) {
      newAlerts.push({
        type: 'danger',
        message: 'Pérdidas superan el 2% - Revisa tu análisis',
        icon: TrendingDown,
        color: 'text-red-400',
        bg: 'bg-red-500/20 border-red-500/50'
      })
    }
    
    setAlerts(newAlerts)
  }, [position, currentPrice])
  
  // Solicitar permiso de notificaciones
  const requestNotificationPermission = async () => {
    if ('Notification' in window) {
      const permission = await Notification.requestPermission()
      return permission === 'granted'
    }
    return false
  }
  
  // Enviar notificación push
  const sendNotification = (title, body) => {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, {
        body,
        icon: '/favicon.svg',
        badge: '/favicon.svg',
        tag: `position-${position?.id}`,
        requireInteraction: true
      })
    }
  }
  
  return { alerts, requestNotificationPermission, sendNotification }
}

// Componente visual de alertas
export function PositionAlertBanner({ alerts, onDismiss }) {
  if (alerts.length === 0) return null
  
  return (
    <div className="space-y-2 mb-4">
      {alerts.map((alert, i) => (
        <div 
          key={i} 
          className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${alert.bg} animate-pulse`}
        >
          <alert.icon size={18} className={alert.color} />
          <span className={`flex-1 text-sm font-medium ${alert.color}`}>
            {alert.message}
          </span>
          <button 
            onClick={() => onDismiss?.(i)}
            className="p-1 hover:bg-white/10 rounded transition-colors"
          >
            <X size={14} className={alert.color} />
          </button>
        </div>
      ))}
    </div>
  )
}

// Configuración de alertas personalizadas
export function AlertSettings({ position, onSave }) {
  const [settings, setSettings] = useState({
    slAlert: true,
    tpAlert: true,
    breakevenAlert: true,
    lossAlert: true,
    customPrice: '',
    customAlert: false
  })
  
  return (
    <div className="card p-4 space-y-4">
      <h3 className="font-medium text-gray-300 flex items-center gap-2">
        <Bell size={16} />
        Configuración de Alertas
      </h3>
      
      <div className="space-y-3">
        <label className="flex items-center justify-between cursor-pointer">
          <span className="text-sm text-gray-400">Alertar cerca del SL (2%)</span>
          <input 
            type="checkbox" 
            checked={settings.slAlert}
            onChange={(e) => setSettings({...settings, slAlert: e.target.checked})}
            className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600"
          />
        </label>
        
        <label className="flex items-center justify-between cursor-pointer">
          <span className="text-sm text-gray-400">Alertar cerca de TP (1%)</span>
          <input 
            type="checkbox" 
            checked={settings.tpAlert}
            onChange={(e) => setSettings({...settings, tpAlert: e.target.checked})}
            className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600"
          />
        </label>
        
        <label className="flex items-center justify-between cursor-pointer">
          <span className="text-sm text-gray-400">Alertar pérdidas > 2%</span>
          <input 
            type="checkbox" 
            checked={settings.lossAlert}
            onChange={(e) => setSettings({...settings, lossAlert: e.target.checked})}
            className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-600"
          />
        </label>
      </div>
      
      <div className="pt-3 border-t border-gray-700">
        <label className="text-sm text-gray-400 block mb-2">Alerta de precio personalizado</label>
        <div className="flex gap-2">
          <input 
            type="number"
            step="0.0000000001"
            placeholder="Precio objetivo"
            value={settings.customPrice}
            onChange={(e) => setSettings({...settings, customPrice: e.target.value})}
            className="input flex-1"
          />
          <button 
            onClick={() => onSave?.(settings)}
            className="btn-primary"
          >
            Guardar
          </button>
        </div>
      </div>
    </div>
  )
}
