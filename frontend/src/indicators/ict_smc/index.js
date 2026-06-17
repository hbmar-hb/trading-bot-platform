/**
 * ICT / SMC — Indicador de Smart Money Concepts
 *
 * Usa el motor avanzado de frontend/src/core/ictEngine.js para detectar
 * estructura de mercado (BOS/CHoCH), Fair Value Gaps, Order Blocks y
 * señales de entrada basadas en OB/FVG.
 */

import { runICT } from '../../core/ictEngine.js'
import BadgeComponent from './Badge.jsx'
import PanelComponent from './Panel.jsx'

const DEF_COLORS = {
  bull:    '#26c6da',
  bear:    '#ef5350',
  fvgBull: '#2962FF',
  fvgBear: '#FF6D00',
  obBull:  '#1B5E20',
  obBear:  '#FF5252',
}

function detect(candles, config) {
  return runICT(candles, config)
}

function render(chart, candleSeries, result, config, api) {
  if (!result) return

  const colors = { ...DEF_COLORS, ...(config.colors || {}) }
  const bull = colors.bull
  const bear = colors.bear

  const {
    showStructure = true,
    showFVG = true,
    showOB = true,
    showEntries = true,
  } = config

  // ── Estructura: niveles de BOS/CHoCH ───────────────────────────────────────
  if (showStructure) {
    const seen = new Set()
    for (const brk of result.structure) {
      if (!brk.valid) continue
      const key = `${brk.time}-${brk.price}`
      if (seen.has(key)) continue
      seen.add(key)
      const isBull = brk.dir === 'up'
      api.addPriceLine({
        price: brk.price,
        color: isBull ? bull : bear,
        lineWidth: 1,
        lineStyle: brk.type === 'CHoCH' ? 2 : 0,
        axisLabelVisible: true,
        title: brk.type,
      })
    }
  }

  // ── Fair Value Gaps ────────────────────────────────────────────────────────
  if (showFVG) {
    const recent = result.fvgs
      .filter(f => !f.mitigated)
      .slice(-8)
    for (const fvg of recent) {
      const color = fvg.type === 'bull' ? colors.fvgBull : colors.fvgBear
      api.addPriceLine({ price: fvg.top, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
      api.addPriceLine({ price: fvg.bottom, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
    }
  }

  // ── Order Blocks ───────────────────────────────────────────────────────────
  if (showOB) {
    const recent = result.obs
      .filter(o => !o.mitigated)
      .slice(-6)
    for (const ob of recent) {
      const color = ob.type === 'bull' ? colors.obBull : colors.obBear
      api.addPriceLine({ price: ob.top, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
      api.addPriceLine({ price: ob.bottom, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: false })
    }
  }

  // ── Señales de entrada ─────────────────────────────────────────────────────
  if (showEntries) {
    for (const entry of result.entries) {
      const isLong = entry.signal === 'long'
      api.addMarker({
        time: entry.time,
        position: isLong ? 'belowBar' : 'aboveBar',
        color: isLong ? bull : bear,
        shape: isLong ? 'arrowUp' : 'arrowDown',
        text: entry.trigger === 'ob' ? 'OB' : 'FVG',
        size: 1,
      })
    }
  }
}

export default {
  id:      'ict_smc',
  name:    'ICT / SMC',
  version: '1.0',

  defaultConfig: {
    pivotLen: 5,
    atrLen: 14,
    atrMult: 0.5,
    useTrendFilter: true,
    trendLen: 50,
    requireSweep: true,
    useMomentum: true,
    minBodySize: 0.6,
    showStructure: true,
    showFVG: true,
    showOB: true,
    showEntries: true,
    colors: { ...DEF_COLORS },
  },

  detect,
  render,
  BadgeComponent,
  PanelComponent,
}
