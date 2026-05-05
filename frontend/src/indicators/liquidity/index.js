/**
 * ═══════════════════════════════════════════════════════════════
 *  LIQUIDITY SWEEPS — EQH / EQL Detector
 * ═══════════════════════════════════════════════════════════════
 *
 * Detecta Equal Highs (EQH) y Equal Lows (EQL):
 *   - Agrupa swing highs/lows que estén dentro de una tolerancia.
 *   - Marca Sweeps cuando el precio rompe el nivel pero rechaza.
 *
 * Concepto ICT: la liquidez se acumula en dobles tops/bottoms.
 * Cuando el precio toma esa liquidez (sweep) y cierra de vuelta,
 * genera una oportunidad de entrada en contra del sweep.
 */

import BadgeComponent from './Badge'
import PanelComponent from './Panel'

export default {
  id: 'liquidity',
  name: 'Liquidity Sweeps',
  version: '1.0',

  defaultConfig: {
    lookback: 50,
    tolerancePercent: 0.05,
    minTouches: 2,
    showSweeps: true,
    showLevels: true,
    colors: {
      eqh: '#ef4444',
      eql: '#22c55e',
      sweep: '#fbbf24',
    },
  },

  detect(candles, config) {
    if (!candles || candles.length < config.lookback * 2) return null

    const { lookback, tolerancePercent, minTouches } = config
    const end = candles.length - 1
    const start = Math.max(0, end - lookback * 2)

    // 1. Detectar swings simples (mínimos locales)
    const swings = []
    for (let i = start + 1; i < end; i++) {
      const prev = candles[i - 1], curr = candles[i], next = candles[i + 1]
      if (curr.high > prev.high && curr.high > next.high) {
        swings.push({ time: curr.time, price: curr.high, type: 'high', idx: i })
      }
      if (curr.low < prev.low && curr.low < next.low) {
        swings.push({ time: curr.time, price: curr.low, type: 'low', idx: i })
      }
    }

    // 2. Agrupar por tolerancia
    const groups = []
    const used = new Set()

    for (let i = 0; i < swings.length; i++) {
      if (used.has(i)) continue
      const base = swings[i]
      const group = [base]
      const tol = base.price * (tolerancePercent / 100)

      for (let j = i + 1; j < swings.length; j++) {
        if (used.has(j)) continue
        const other = swings[j]
        if (other.type !== base.type) continue
        if (Math.abs(other.price - base.price) <= tol) {
          group.push(other)
          used.add(j)
        }
      }

      if (group.length >= minTouches) {
        groups.push({
          type: base.type,
          price: base.price,
          touches: group,
        })
      }
      used.add(i)
    }

    const eqhs = groups.filter(g => g.type === 'high')
    const eqls = groups.filter(g => g.type === 'low')

    // 3. Detectar Sweeps (rompe pero cierra de vuelta)
    const sweeps = []
    for (const eqh of eqhs) {
      for (let i = eqh.touches[eqh.touches.length - 1].idx + 1; i < candles.length; i++) {
        const c = candles[i]
        if (c.high > eqh.price && c.close < eqh.price) {
          sweeps.push({ time: c.time, price: eqh.price, type: 'eqh_sweep' })
          break
        }
      }
    }
    for (const eql of eqls) {
      for (let i = eql.touches[eql.touches.length - 1].idx + 1; i < candles.length; i++) {
        const c = candles[i]
        if (c.low < eql.price && c.close > eql.price) {
          sweeps.push({ time: c.time, price: eql.price, type: 'eql_sweep' })
          break
        }
      }
    }

    return { eqhs, eqls, sweeps }
  },

  render(chart, candleSeries, result, config, api) {
    if (!result) return
    const { colors, showLevels, showSweeps } = config

    if (showLevels) {
      for (const eqh of result.eqhs) {
        api.addPriceLine({
          price: eqh.price,
          color: colors.eqh,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `EQH (${eqh.touches.length})`,
        })
        // Marker en el primer toque
        api.addMarker({
          time: eqh.touches[0].time,
          position: 'aboveBar',
          color: colors.eqh,
          shape: 'circle',
          text: 'EQH',
          size: 0,
        })
      }
      for (const eql of result.eqls) {
        api.addPriceLine({
          price: eql.price,
          color: colors.eql,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `EQL (${eql.touches.length})`,
        })
        api.addMarker({
          time: eql.touches[0].time,
          position: 'belowBar',
          color: colors.eql,
          shape: 'circle',
          text: 'EQL',
          size: 0,
        })
      }
    }

    if (showSweeps) {
      for (const sw of result.sweeps) {
        api.addMarker({
          time: sw.time,
          position: sw.type === 'eqh_sweep' ? 'aboveBar' : 'belowBar',
          color: colors.sweep,
          shape: sw.type === 'eqh_sweep' ? 'arrowDown' : 'arrowUp',
          text: 'SWEEP',
          size: 2,
        })
      }
    }
  },

  BadgeComponent,
  PanelComponent,
}
