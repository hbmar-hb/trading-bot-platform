import api from './api'

export const positionsService = {
  list:    (params) => api.get('/positions', { params }),
  open:    ()       => api.get('/positions/open'),
  unified: (includeManual = true) => api.get('/positions/unified', { params: { include_manual: includeManual } }),
  get:     (id)     => api.get(`/positions/${id}`),
  updateSL: (id, data) => api.patch(`/positions/${id}/sl`, data),
  updateTP: (id, tpPrices) => api.patch(`/positions/${id}/tp`, { tp_prices: tpPrices }),
  partialClose: (id, data) => api.post(`/positions/${id}/partial-close`, data),
  close:   (id)     => api.post(`/positions/${id}/close`),
  getCandles: (id, timeframe = '15m', limit = 100) => 
    api.get(`/positions/${id}/candles`, { params: { timeframe, limit } }),
  
  // Sincronizar estado con el exchange (cuando se cierra manualmente en BingX)
  syncStatus: (id) => api.post(`/positions/${id}/sync-status`),
  
  // Cerrar posiciones manuales externas (BingX)
  // account_id va como query param, el resto en body
  closeExternal: (data) => {
    const { account_id, ...body } = data
    return api.post('/positions/external/close', body, { params: { account_id } })
  },
  partialCloseExternal: (data) => {
    const { account_id, percentage, ...body } = data
    return api.post('/positions/external/partial-close', body, { params: { account_id, percentage } })
  },
}
