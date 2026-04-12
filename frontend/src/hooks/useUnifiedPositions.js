import { useCallback, useEffect, useState } from 'react'
import { positionsService } from '@/services/positions'
import usePositionStore from '@/store/positionStore'

export function useUnifiedPositions() {
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)
  const prices = usePositionStore(s => s.prices)
  const priceChanges = usePositionStore(s => s.priceChanges)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await positionsService.unified(true) // includeManual = true
      setPositions(data)
    } catch (err) {
      console.error('Error loading unified positions:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Enriquecer posiciones con precios actuales y calcular PnL en tiempo real
  const enrichedPositions = positions.map(pos => {
    const price = prices[pos.symbol]
    const change24h = priceChanges[pos.symbol] || 0
    
    // Calcular PnL unrealizado basado en precio actual (para posiciones que no lo tienen)
    let unrealizedPnl = pos.unrealized_pnl
    if (price && pos.source !== 'paper') {
      const entry = parseFloat(pos.entry_price)
      const qty = parseFloat(pos.quantity)
      const currentPnl = pos.side === 'long' 
        ? (price - entry) * qty
        : (entry - price) * qty
      // Usar el calculado si el de la API es 0 o no existe
      if (!unrealizedPnl || unrealizedPnl === 0) {
        unrealizedPnl = currentPnl
      }
    }
    
    return {
      ...pos,
      current_price: price,
      change_24h: change24h,
      unrealized_pnl: unrealizedPnl,
    }
  })

  return {
    positions: enrichedPositions,
    loading,
    refresh,
    // Contadores por tipo (sin solapamientos)
    counts: {
      bot: positions.filter(p => p.source === 'bot' && p.status !== 'pending_limit').length,
      app_manual: positions.filter(p => p.source === 'app_manual' && p.status !== 'pending_limit').length,
      paper: positions.filter(p => p.source === 'paper').length,
      manual: positions.filter(p => p.source === 'manual' && p.status !== 'pending_limit').length,
      pending_limit: positions.filter(p => p.status === 'pending_limit').length,
      total: positions.length,
    }
  }
}
