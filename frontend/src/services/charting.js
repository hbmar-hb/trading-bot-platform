import api from './api'

export const chartingService = {
  // Obtener datos históricos de velas
  getHistory: (params) => api.get('/charting/history', { params }),

  // Buscar símbolos disponibles
  searchSymbols: (query = '') => api.get('/charting/symbols', { params: { query } }),

  // Obtener configuración del gráfico
  getConfig: () => api.get('/charting/config'),

  // ICT/SMC indicators: FVGs, Order Blocks, CHoCH, BOS, swing structure
  getICT: (params) => api.get('/charting/ict', { params }),

  // ICT/SMC trade signal with grade (A+/A-), entry, SL, TP1/2/3
  getICTSignal: (params) => api.get('/charting/ict/signal', { params }),

  // Historical ICT signals with outcomes (TP/SL/OPEN) — cached, CPU-intensive
  getICTSignalsHistory: (params) => api.get('/charting/ict/signals-history', { params }),
}
