import useBalanceStore from '@/store/balanceStore'

export function useBalance(accountId) {
  const { balances, getTotalEquity } = useBalanceStore()
  const balance = accountId ? balances[accountId] : null

  return {
    balance,
    totalEquity: getTotalEquity(),
    allBalances: balances,
  }
}
