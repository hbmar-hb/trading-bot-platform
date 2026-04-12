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

  useEffect(() => { refresh() }, [])

  return { openPositions, loading, refresh }
}
