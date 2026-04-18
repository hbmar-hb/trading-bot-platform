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

  // Enriquecer posiciones con precios actuales y calcular PnL + ROI en tiempo real
  const enrichedPositions = positions.map(pos => {
    const price = prices[pos.symbol]
    const change24h = priceChanges[pos.symbol] || 0
    const entry = parseFloat(pos.entry_price)
    const qty   = parseFloat(pos.quantity)
    const lev   = parseFloat(pos.leverage || 1)

    // PnL: si hay precio live siempre recalcular (más fresco que el valor en DB)
    // Nota: BingX usa mark price internamente; aquí usamos last price → diferencia ~0.01–0.1%
    let unrealizedPnl = parseFloat(pos.unrealized_pnl || 0)
    if (price && pos.source !== 'paper' && entry > 0 && qty > 0) {
      unrealizedPnl = pos.side === 'long'
        ? (price - entry) * qty
        : (entry - price) * qty
    }

    // ROI % = PnL / margen inicial * 100
    // Margen inicial = (entry * qty) / leverage
    const margin = entry > 0 && qty > 0 ? (entry * qty) / lev : 0
    const roi = margin > 0 ? (unrealizedPnl / margin) * 100 : 0

    return {
      ...pos,
      current_price: price,
      change_24h: change24h,
      unrealized_pnl: unrealizedPnl,
      roi,       // % sobre margen (incluye efecto apalancamiento)
      margin,    // margen inicial en USDT
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
