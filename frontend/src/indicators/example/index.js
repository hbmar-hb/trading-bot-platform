/**
 * ═══════════════════════════════════════════════════════════════
 *  PLANTILLA DE INDICADOR — CÓPIA ESTA CARPETA Y RENÓMBRALA
 * ═══════════════════════════════════════════════════════════════
 *
 * 1. Copia esta carpeta `example` como `frontend/src/indicators/{miId}/`
 * 2. Renombra el id, name y version
 * 3. Implementa tu lógica en detect() y render()
 * 4. (Opcional) Crea Badge.jsx y Panel.jsx si necesitas UI propia
 * 5. Recarga la app — el indicador aparecerá automáticamente en el menú
 *
 * Interfaz completa:
 *   id               : string único (sin espacios)
 *   name             : string visible para el usuario
 *   version          : string ej: "1.0"
 *   defaultConfig    : objeto con configuración inicial
 *   detect(candles, config) -> object | null
 *   render(chart, candleSeries, result, config, api) -> void
 *   BadgeComponent?  : React component
 *   PanelComponent?  : React component
 *
 * api (objeto que recibe render):
 *   api.addMarker({ time, position, color, shape, text, size })
 *   api.addPriceLine({ price, color, lineWidth, lineStyle, axisLabelVisible, title })
 *   api.addSeries(createFn)  -> devuelve la serie creada
 */

// ─── Componentes React opcionales ───────────────────────────────────────────
// Si tu indicador no necesita badge ni panel de config, puedes omitirlos.
// Descomenta y adapta si los necesitas:

// import BadgeComponent from './Badge'
// import PanelComponent from './Panel'

// ─── Indicador ──────────────────────────────────────────────────────────────
export default {
  // Metadatos
  id: 'example',
  name: 'Example Indicator',
  version: '1.0',

  // Configuración por defecto (se guarda en localStorage automáticamente)
  defaultConfig: {
    enabled: true,
    period: 14,
    threshold: 0.5,
    colors: {
      up: '#22c55e',
      down: '#ef4444',
    },
    visibility: {
      showMarkers: true,
      showLines: true,
    },
  },

  /**
   * DETECCIÓN — Función pura, sin dependencias de React ni canvas.
   * Recibe el array de velas y la config del usuario.
   * Debe retornar un objeto con los datos a dibujar, o null.
   */
  detect(candles, config) {
    if (!candles || candles.length < 20) return null

    // Ejemplo: detectar velas con cuerpo mayor al umbral × ATR
    const results = []
    for (let i = 1; i < candles.length; i++) {
      const c = candles[i]
      const body = Math.abs(c.close - c.open)
      const range = c.high - c.low
      if (range > 0 && body / range > config.threshold) {
        results.push({
          time: c.time,
          price: c.close,
          isBull: c.close > c.open,
        })
      }
    }

    return { signals: results.slice(-20) }
  },

  /**
   * RENDER — Dibuja en el canvas de lightweight-charts.
   * Recibe: chart, candleSeries, result (de detect), config, api.
   *
   * api.addMarker({ time, position, color, shape, text, size })
   * api.addPriceLine({ price, color, lineWidth, lineStyle, axisLabelVisible, title })
   * api.addSeries((chart) => chart.addLineSeries({...}))
   */
  render(chart, candleSeries, result, config, api) {
    if (!result) return
    const { colors, visibility } = config

    if (visibility.showMarkers) {
      for (const sig of result.signals) {
        api.addMarker({
          time: sig.time,
          position: sig.isBull ? 'belowBar' : 'aboveBar',
          color: sig.isBull ? colors.up : colors.down,
          shape: sig.isBull ? 'arrowUp' : 'arrowDown',
          text: sig.isBull ? 'UP' : 'DOWN',
          size: 1,
        })
      }
    }

    if (visibility.showLines) {
      // Ejemplo: dibujar una línea horizontal en el último precio
      const last = result.signals[result.signals.length - 1]
      if (last) {
        api.addPriceLine({
          price: last.price,
          color: last.isBull ? colors.up : colors.down,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: 'Example',
        })
      }
    }
  },

  // ── Componentes React (opcionales) ────────────────────────────────────────
  // Si no los defines, el sistema usará un badge/panel genérico (por implementar).
  // BadgeComponent,
  // PanelComponent,
}
