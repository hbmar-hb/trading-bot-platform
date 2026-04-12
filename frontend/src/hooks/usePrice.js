import usePositionStore from '@/store/positionStore'

/**
 * Devuelve el precio en tiempo real de un símbolo desde el store de WebSocket.
 * El price monitor normaliza los símbolos (BTCUSDT → BTC/USDT:USDT),
 * por eso buscamos tanto el símbolo exacto como las variantes normalizadas.
 */
export function usePrice(symbol) {
  const prices = usePositionStore(s => s.prices)

  if (!symbol) return null

  const sym = symbol.trim().toUpperCase()

  // Buscar por símbolo exacto primero
  if (prices[sym] !== undefined) return prices[sym]

  // Intentar formato CCXT: BTCUSDT → BTC/USDT:USDT
  if (sym.endsWith('USDT')) {
    const base = sym.slice(0, -4)
    const ccxt = `${base}/USDT:USDT`
    if (prices[ccxt] !== undefined) return prices[ccxt]
  }

  return null
}
