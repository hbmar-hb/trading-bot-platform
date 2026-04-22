import { useCallback, useEffect } from 'react'
import { positionsService } from '@/services/positions'
import usePositionStore from '@/store/positionStore'

export function usePositions() {
  const { openPositions, loading, setOpenPositions, setLoading } = usePositionStore()

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await positionsService.open()
      setOpenPositions(data)
    } catch { /* noop */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    refresh()
    // Polling fallback cada 15s por si el WS se cae
    const interval = setInterval(refresh, 15000)
    return () => clearInterval(interval)
  }, [])

  return { openPositions, loading, refresh }
}
