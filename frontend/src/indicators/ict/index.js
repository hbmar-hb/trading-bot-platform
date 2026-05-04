import { runICT } from '@/core/ictEngine'
import BadgeComponent from './Badge'
import PanelComponent from './Panel'

/**
 * ICT / SMC Concepts — Indicador de ejemplo y producción.
 * Formato estándar que sirve como base para cualquier indicador nuevo.
 */

export default {
  // ── Metadatos ──────────────────────────────────────────────────────────────
  id: 'ict',
  name: 'ICT / SMC Concepts',
  version: '1.0',

  // ── Configuración por defecto (persistida en localStorage) ─────────────────
  defaultConfig: {
    signals: true,
    showSwingAreas: false,
    tradingOverlay: false,
    tradingDashboard: 'top_right',
    proFilters: {
      enabled: true,
      trendFilter: true,
      requireSweep: true,
      momentumFilter: true,
      cooldown: true,
      cooldownBars: 5,
      pivotLen: 5,
      atrMult: 0.5,
      trendLen: 50,
    },
    colors: {
      signalLong: '#22c55e',
      signalShort: '#ef4444',
      signalContra: '#fbbf24',
      dashboardBg: 'rgba(0,0,0,0.7)',
      overlayBull: '#26c6da',
      overlayBear: '#ef5350',
    },
    visibility: {
      bosChoch: true,
      orderBlocks: true,
      fairValueGaps: true,
      pivots: false,
      entries: true,
      levels: true,
    },
  },

  // ── Detección (pura, sin dependencias de UI) ──────────────────────────────
  detect(candles, config) {
    const pf = config.proFilters
    return runICT(candles, {
      useTrendFilter: pf.enabled && pf.trendFilter,
      requireSweep: pf.enabled && pf.requireSweep,
      useMomentum: pf.enabled && pf.momentumFilter,
      useCooldown: pf.enabled && pf.cooldown,
      cooldownBars: pf.cooldownBars,
      pivotLen: pf.pivotLen,
      atrMult: pf.atrMult,
      trendLen: pf.trendLen,
    })
  },

  // ── Renderizado en el canvas de lightweight-charts ─────────────────────────
  // api = { addMarker(m), addPriceLine(opts), addSeries(createFn) }
  render(chart, candleSeries, result, config, api) {
    if (!result) return
    const vis = config.visibility
    const cols = config.colors

    // ── BOS / CHoCH markers ─────────────────────────────────────────────────
    if (vis.bosChoch) {
      for (const b of result.structure.slice(-20)) {
        const isUp = b.dir === 'up'
        const isBos = b.type === 'BOS'
        const baseColor = isBos
          ? (isUp ? cols.signalLong : cols.signalShort)
          : (isUp ? cols.overlayBull : cols.overlayBear)
        const finalColor = b.isContraTrend ? cols.signalContra : baseColor
        const shape = isBos ? 'square' : (isUp ? 'arrowUp' : 'arrowDown')
        const text = isBos ? (isUp ? 'B+' : 'B-') : 'CH'

        api.addMarker({
          time: b.time,
          position: isUp ? 'aboveBar' : 'belowBar',
          color: finalColor,
          shape,
          text,
          size: b.isContraTrend ? 3 : 2,
        })
      }
    }

    // ── Pivot markers ───────────────────────────────────────────────────────
    if (vis.pivots) {
      for (const p of result.pivots.highs.slice(-6))
        api.addMarker({ time: p.time, position: 'aboveBar', color: '#94a3b8', shape: 'circle', text: 'H', size: 1 })
      for (const p of result.pivots.lows.slice(-6))
        api.addMarker({ time: p.time, position: 'belowBar', color: '#94a3b8', shape: 'circle', text: 'L', size: 1 })
    }

    // ── BUY / SELL entry signals ────────────────────────────────────────────
    if (vis.entries) {
      for (const entry of result.entries) {
        const isLong = entry.signal === 'long'
        api.addMarker({
          time: entry.time,
          position: isLong ? 'belowBar' : 'aboveBar',
          color: entry.contraTrend ? cols.signalContra : (isLong ? cols.signalLong : cols.signalShort),
          shape: isLong ? 'arrowUp' : 'arrowDown',
          text: `${isLong ? 'BUY' : 'SELL'}${entry.contraTrend ? '⚠' : ''} (${entry.trigger.toUpperCase()})`,
          size: 2,
        })
      }
    }

    // ── FVG zones ───────────────────────────────────────────────────────────
    if (vis.fairValueGaps) {
      for (const fvg of result.fvgs) {
        const color = fvg.type === 'bull'
          ? (fvg.mitigated ? '#14532d' : cols.signalLong)
          : (fvg.mitigated ? '#7f1d1d' : cols.signalShort)
        const lw = fvg.mitigated ? 1 : 2
        try {
          api.addPriceLine({ price: fvg.top, color, lineWidth: lw, lineStyle: 2, axisLabelVisible: !fvg.mitigated, title: fvg.type === 'bull' ? 'FVG↑' : 'FVG↓' })
          api.addPriceLine({ price: fvg.bottom, color, lineWidth: lw, lineStyle: 2, axisLabelVisible: false, title: '' })
        } catch {}
        api.addMarker({
          time: fvg.startTime,
          position: fvg.type === 'bull' ? 'belowBar' : 'aboveBar',
          color: fvg.type === 'bull' ? '#22c55e' : '#ef4444',
          shape: 'triangle',
          text: '',
          size: 0,
        })
      }
    }

    // ── Order Block zones ───────────────────────────────────────────────────
    if (vis.orderBlocks) {
      for (const ob of result.obs) {
        const color = ob.type === 'bull'
          ? (ob.mitigated ? '#1e3a8a' : cols.overlayBull)
          : (ob.mitigated ? '#78350f' : cols.overlayBear)
        const lw = ob.mitigated ? 1 : 2
        try {
          api.addPriceLine({ price: ob.top, color, lineWidth: lw, lineStyle: 0, axisLabelVisible: !ob.mitigated, title: ob.type === 'bull' ? 'OB↑' : 'OB↓' })
          api.addPriceLine({ price: ob.bottom, color, lineWidth: lw, lineStyle: 2, axisLabelVisible: false, title: '' })
        } catch {}
        api.addMarker({
          time: ob.time,
          position: ob.type === 'bull' ? 'belowBar' : 'aboveBar',
          color: ob.type === 'bull' ? '#3b82f6' : '#f59e0b',
          shape: 'square',
          text: '',
          size: 0,
        })
      }
    }

    // ── Active structure levels ─────────────────────────────────────────────
    if (vis.levels && result.levels.length > 0) {
      for (const lvl of result.levels.slice(-4)) {
        const color = lvl.dir === 'up' ? '#22c55e44' : '#ef444444'
        api.addPriceLine({ price: lvl.price, color, lineWidth: 1, lineStyle: lvl.dashed ? 2 : 1, axisLabelVisible: false, title: '' })
      }
    }
  },

  // ── Componentes React (opcionales) ────────────────────────────────────────
  BadgeComponent,
  PanelComponent,
}
