import { useEffect, useRef } from 'react'
import { BASE_URL } from '@/services/api'
import useBalanceStore  from '@/store/balanceStore'
import usePositionStore from '@/store/positionStore'
import useUiStore       from '@/store/uiStore'

// Derivar URL WebSocket del host actual para que funcione en cualquier dominio
const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

const RECONNECT_DELAY = 3000

export function useWebSocket() {
  const ws      = useRef(null)
  const timer   = useRef(null)
  const token   = localStorage.getItem('access_token')

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

  function connect() {
    const socket = new WebSocket(`${WS_URL}/ws?token=${token}`)
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

    socket.onclose = () => {
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
    }
  }
}
