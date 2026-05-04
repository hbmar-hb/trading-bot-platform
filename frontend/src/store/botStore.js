import { create } from 'zustand'

const useBotStore = create((set, get) => ({
  bots:    [],
  loading: false,
  error:   null,

  setBots:   (bots)  => set({ bots }),
  setLoading:(v)     => set({ loading: v }),
  setError:  (e)     => set({ error: e }),

  updateBot: (updated) =>
    set({ bots: get().bots.map(b => b.id === updated.id ? updated : b) }),

  removeBot: (id) =>
    set({ bots: get().bots.filter(b => b.id !== id) }),

  addBot: (bot) =>
    set({ bots: [bot, ...get().bots] }),
}))

export default useBotStore
