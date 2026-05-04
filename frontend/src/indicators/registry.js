/**
 * Indicator Registry — Sistema de descubrimiento automático de indicadores
 *
 * Cada indicador debe vivir en su propia carpeta bajo `src/indicators/{id}/`
 * y exportar por defecto un objeto que cumpla la interfaz IndicatorDef.
 *
 * Interfaz mínima:
 *   id          : string  único
 *   name        : string  nombre visible
 *   version     : string  ej: "1.0"
 *   defaultConfig: object  config por defecto (persistible en localStorage)
 *   detect(candles, config) -> { ... } | null
 *   render(chart, candleSeries, result, config, refs) -> void
 *
 * Opcional:
 *   BadgeComponent : React component  — badge flotante sobre el chart
 *   PanelComponent : React component  — panel de configuración
 *
 * Vite hace auto-descubrimiento con import.meta.glob.
 */

const modules = import.meta.glob('./*/index.js', { eager: true })

export const indicators = Object.values(modules)
  .map(m => m.default)
  .filter(Boolean)
  .sort((a, b) => a.name.localeCompare(b.name))

export function getIndicator(id) {
  return indicators.find(ind => ind.id === id)
}
