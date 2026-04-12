import api from './api'

export const chartingService = {
  // Obtener datos históricos de velas
  getHistory: (params) => api.get('/charting/history', { params }),
  
  // Buscar símbolos disponibles
  searchSymbols: (query = '') => api.get('/charting/symbols', { params: { query } }),
  
  // Obtener configuración del gráfico
  getConfig: () => api.get('/charting/config'),
}
