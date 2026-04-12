import api from './api'

export const exchangeAccountsService = {
  list:    ()           => api.get('/exchange-accounts'),
  get:     (id)         => api.get(`/exchange-accounts/${id}`),
  create:  (data)       => api.post('/exchange-accounts', data),
  update:  (id, data)   => api.patch(`/exchange-accounts/${id}`, data),
  delete:  (id)         => api.delete(`/exchange-accounts/${id}`),
  test:    (id)         => api.post(`/exchange-accounts/${id}/test`),
  verifyCredentials: (id) => api.post(`/exchange-accounts/${id}/verify-credentials`),
  markets: (id)         => api.get(`/exchange-accounts/${id}/markets`),
  marketsByExchange: (exchange) => api.get(`/exchange-accounts/markets-by-exchange/${exchange}`),
}
