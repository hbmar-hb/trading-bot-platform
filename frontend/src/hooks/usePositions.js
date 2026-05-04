import { useCallback, useEffect, useRef } from 'react'
import { positionsService } from '@/services/positions'
import usePositionStore from '@/store/positionStore'

export function usePositions() {
  const { openPositions, loading, setOpenPositions, setLoading } = usePositionStore()
  const hasLoadedOnce = useRef(false)

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const { data } = await positionsService.open()
      setOpenPositions(data)
      hasLoadedOnce.current = true
    } catch { /* noop */ }
    finally { if (!silent) setLoading(false) }
  }, [])

  useEffect(() => {
    refresh(false) // Primera carga: loading visible
    // Polling fallback cada 15s: actualización silenciosa (sin spinner)
    const interval = setInterval(() => refresh(true), 15000)
    return () => clearInterval(interval)
  }, [])

  return { openPositions, loading, refresh }
}
