import { useCallback, useEffect, useState } from 'react'
import { botsService } from '@/services/bots'
import useBotStore from '@/store/botStore'

export function useBots() {
  const { bots, loading, setBots, setLoading, updateBot, removeBot, addBot } = useBotStore()

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await botsService.list()
      setBots(data)
    } catch { /* noop */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    refresh()
    // Polling fallback cada 30s por si el WS se cae
    const interval = setInterval(refresh, 30000)
    return () => clearInterval(interval)
  }, [])

  const toggleStatus = useCallback(async (bot) => {
    const next = bot.status === 'active' ? 'paused' : 'active'
    const { data } = await botsService.setStatus(bot.id, next)
    updateBot(data)
    return data
  }, [])

  const deleteBot = useCallback(async (id) => {
    await botsService.delete(id)
    removeBot(id)
  }, [])

  return { bots, loading, refresh, toggleStatus, deleteBot, addBot, updateBot }
}
