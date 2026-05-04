import api from './api'

export const exchangeTradesService = {
  /**
   * Sincroniza trades desde el exchange
   * @param {string} accountId - ID de la cuenta de exchange
   * @param {number} days - Días de historial a sincronizar (default: 30)
   */
  sync: (accountId, days = 30) => 
    api.post(`/exchange-trades/sync/${accountId}?days=${days}`),

  /**
   * Lista trades importados con filtros
   * @param {Object} params - Filtros
   * @param {string} params.accountId - Filtrar por cuenta
   * @param {string} params.botId - Filtrar por bot
   * @param {string} params.source - 'bot' | 'manual' | undefined (todos)
   * @param {string} params.symbol - Filtrar por símbolo
   * @param {number} params.days - Días de historial
   * @param {number} params.limit - Límite de resultados
   */
  list: (params = {}) => {
    const query = new URLSearchParams()
    if (params.accountId) query.append('account_id', params.accountId)
    if (params.botId) query.append('bot_id', params.botId)
    if (params.source) query.append('source', params.source)
    if (params.symbol) query.append('symbol', params.symbol)
    if (params.days) query.append('days', params.days)
    if (params.limit) query.append('limit', params.limit)
    
    return api.get(`/exchange-trades?${query.toString()}`)
  },

  /**
   * Obtiene estadísticas de trades separadas por source
   * @param {Object} params - Parámetros
   * @param {string} params.accountId - ID de cuenta
   * @param {number} params.days - Días de historial
   */
  stats: (params = {}) => {
    const query = new URLSearchParams()
    if (params.accountId) query.append('account_id', params.accountId)
    if (params.days) query.append('days', params.days)
    
    return api.get(`/exchange-trades/stats?${query.toString()}`)
  },

  /**
   * Importa trades desde un archivo exportado de BingX (CSV o XLSX).
   * @param {string} accountId - ID de la cuenta de exchange
   * @param {FormData} formData - FormData con campo 'file'
   */
  importCsv: (accountId, formData) =>
    api.post(`/exchange-trades/import-csv/${accountId}`, formData),
}
