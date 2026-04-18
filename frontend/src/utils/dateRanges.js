/**
 * Utilidades para cálculo consistente de rangos de fechas
 * Usado en Dashboard, Analytics y ExchangeTrades para mantener consistencia
 */

/**
 * Convierte Date a string YYYY-MM-DD en UTC
 */
export function toISODate(date) {
  return date.toISOString().slice(0, 10)
}

/**
 * Obtiene el rango de fechas para un período dado en días
 * @param {number} days - Número de días hacia atrás (incluyendo hoy)
 * @returns {{from: string, to: string}} Objeto con fechas en formato YYYY-MM-DD
 * 
 * Ejemplos:
 * - days=1 → Solo hoy
 * - days=7 → Desde hace 6 días hasta hoy (7 días total)
 * - days=30 → Desde hace 29 días hasta hoy (30 días total)
 */
export function getDateRange(days) {
  const today = new Date()
  const from = new Date(today)
  from.setDate(today.getDate() - (days - 1))
  
  return {
    from: toISODate(from),
    to: toISODate(today)
  }
}

/**
 * Presets comunes para filtros de fecha
 */
export const DATE_PRESETS = {
  today:   { days: 1,  label: 'Hoy' },
  '7d':    { days: 7,  label: 'Últ. 7d' },
  '30d':   { days: 30, label: 'Últ. 30d' },
  '90d':   { days: 90, label: 'Últ. 90d' },
  '365d':  { days: 365, label: 'Últ. año' },
}

/**
 * Obtiene el rango de fechas para un preset
 * @param {string} presetKey - Clave del preset (today, 7d, 30d, etc.)
 * @returns {{from: string, to: string, days: number} | null}
 */
export function getPresetRange(presetKey) {
  const preset = DATE_PRESETS[presetKey]
  if (!preset) return null
  
  const range = getDateRange(preset.days)
  return {
    ...range,
    days: preset.days
  }
}

/**
 * Calcula timestamp en milisegundos desde epoch para el inicio del rango
 * Útil para endpoints que esperan timestamp (como exchange-trades)
 */
export function getRangeTimestamp(days) {
  const now = Date.now()
  return now - (days * 24 * 60 * 60 * 1000)
}
