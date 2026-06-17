import { useEffect, useRef } from 'react'
import { authService } from '@/services/auth'
import useAuthStore  from '@/store/authStore'
import useBalanceStore  from '@/store/balanceStore'
import usePositionStore from '@/store/positionStore'
import useUiStore       from '@/store/uiStore'

// Derivar URL WebSocket del host actual para que funcione en cualquier dominio
const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

const RECONNECT_DELAY = 3000

export function useWebSocket() {
  const ws      = useRef(null)
  const timer   = useRef(null)
  const token   = useAuthStore(s => s.token)
  const setToken = useAuthStore(s => s.setToken)
  const logout   = useAuthStore(s => s.logout)

  const { updatePrice, updatePosition } = usePositionStore()
  const { updateBalance }               = useBalanceStore()
  const { addNotification }             = useUiStore()

  useEffect(() => {
    if (!token) return
    connect()
    return () => {
      clearTimeout(timer.current)
      ws.current?.close()
    }
  }, [token])

  async function refreshAndReconnect() {
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) {
      logout()
      return
    }
    try {
      const { data } = await authService.refresh({ refresh_token: refreshToken })
      if (data.access_token) {
        setToken(data.access_token)
        if (data.refresh_token) {
          localStorage.setItem('refresh_token', data.refresh_token)
        }
        connect()
        return
      }
    } catch {
      // refresh fallido -> logout
    }
    logout()
  }

  function connect() {
    const currentToken = useAuthStore.getState().token
    if (!currentToken) return

    const socket = new WebSocket(`${WS_URL}/ws?token=${currentToken}`)
    ws.current = socket

    socket.onopen = () => {
      clearTimeout(timer.current)
    }

    socket.onmessage = ({ data }) => {
      try {
        const msg = JSON.parse(data)
        dispatch(msg)
      } catch { /* ignore malformed */ }
    }

    socket.onclose = (event) => {
      // 1008 = policy violation (token inválido/expirado) en el backend.
      // Algunos proxies reportan 403 antes del handshake; en el navegador
      // el close code puede ser 1006. Intentamos refresh una sola vez.
      if (event.code === 1008 || event.code === 1006) {
        refreshAndReconnect()
        return
      }
      timer.current = setTimeout(connect, RECONNECT_DELAY)
    }

    socket.onerror = () => socket.close()
  }

  function dispatch(msg) {
    switch (msg.type) {
      case 'price_update':
        updatePrice(msg.symbol, msg.price, msg.change_24h || 0)
        break
      case 'position_update':
        updatePosition(msg)
        break
      case 'balance_update':
        updateBalance(msg.account_id, {
          total_equity:      msg.total_equity,
          available_balance: msg.available_balance,
        })
        break
      case 'notification':
        addNotification({
          type: msg.notification_type || 'info',
          title: msg.title || 'Notificacion',
          message: msg.message || '',
        })
        break
    }
  }
}
