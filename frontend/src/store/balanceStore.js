import { create } from 'zustand'

const useBalanceStore = create((set, get) => ({
  // account_id → { total_equity, available_balance }
  balances: {},

  updateBalance: (accountId, data) =>
    set({ balances: { ...get().balances, [accountId]: data } }),

  getTotalEquity: () =>
    Object.values(get().balances)
      .reduce((sum, b) => sum + (b.total_equity || 0), 0),
}))

export default useBalanceStore
