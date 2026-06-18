import { create } from 'zustand'

const MAX_EVENTS = 500

export const useAiLiveStore = create((set, get) => ({
  isLive: false,
  events: [],
  latestBySymbol: {},
  stats: {
    scanned: 0,
    signals: 0,
    noSignals: 0,
    rejected: 0,
    errors: 0,
  },

  setLive: (value) => set({ isLive: value }),

  addEvent: (event) => {
    if (!event || event.type !== 'ai_scan_update') return
    set((state) => {
      const events = [event, ...state.events].slice(0, MAX_EVENTS)
      const latestBySymbol = {
        ...state.latestBySymbol,
        [`${event.symbol}:${event.timeframe}`]: event,
      }
      const stats = { ...state.stats }
      stats.scanned += 1
      if (event.status === 'SIGNAL') stats.signals += 1
      else if (event.status === 'NO_SIGNAL') stats.noSignals += 1
      else if (event.status === 'REJECTED') stats.rejected += 1
      else if (event.status === 'ERROR') stats.errors += 1
      return { events, latestBySymbol, stats }
    })
  },

  setHistory: (events) => {
    const list = Array.isArray(events) ? events : []
    list.sort((a, b) => new Date(a.scanned_at) - new Date(b.scanned_at))
    const latestBySymbol = {}
    const stats = {
      scanned: 0,
      signals: 0,
      noSignals: 0,
      rejected: 0,
      errors: 0,
    }
    list.forEach((ev) => {
      latestBySymbol[`${ev.symbol}:${ev.timeframe}`] = ev
      stats.scanned += 1
      if (ev.status === 'SIGNAL') stats.signals += 1
      else if (ev.status === 'NO_SIGNAL') stats.noSignals += 1
      else if (ev.status === 'REJECTED') stats.rejected += 1
      else if (ev.status === 'ERROR') stats.errors += 1
    })
    set({
      events: list.slice(-MAX_EVENTS).reverse(),
      latestBySymbol,
      stats,
    })
  },

  reset: () =>
    set({
      isLive: false,
      events: [],
      latestBySymbol: {},
      stats: {
        scanned: 0,
        signals: 0,
        noSignals: 0,
        rejected: 0,
        errors: 0,
      },
    }),
}))
