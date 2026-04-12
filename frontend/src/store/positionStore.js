import { create } from 'zustand'

const usePositionStore = create((set, get) => ({
  openPositions:   [],
  prices:          {},   // symbol → price
  priceChanges:    {},   // symbol → change_24h (porcentaje)
  loading:         false,

  setOpenPositions: (positions) => set({ openPositions: positions }),
  setLoading:       (v)         => set({ loading: v }),

  updatePrice: (symbol, price, change24h = 0) =>
    set({ 
      prices: { ...get().prices, [symbol]: price },
      priceChanges: { ...get().priceChanges, [symbol]: change24h }
    }),

  updatePosition: (updated) =>
    set({
      openPositions: get().openPositions.map(p =>
        p.id === updated.position_id ? { ...p, ...updated } : p
      )
    }),
}))

export default usePositionStore
