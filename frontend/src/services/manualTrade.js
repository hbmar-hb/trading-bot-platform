import api from './api'

export const manualTradeService = {
  getAccounts: () =>
    api.get('/manual-trade/accounts'),

  getPosition: (symbol, params = {}) =>
    api.get('/manual-trade/position', { params: { symbol, ...params } }),

  execute: (data) =>
    api.post('/manual-trade/execute', data),

  getCandles: (symbol, timeframe = '15m', limit = 100) =>
    api.get('/manual-trade/candles', { params: { symbol, timeframe, limit } }),

  getExternalPositions: (exchangeAccountId = null) =>
    api.get('/manual-trade/external-positions', exchangeAccountId ? { params: { exchange_account_id: exchangeAccountId } } : {}),

  adoptPosition: (data) =>
    api.post('/manual-trade/adopt', data),
}
