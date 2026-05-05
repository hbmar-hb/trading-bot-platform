/**
 * SHOWI ICT — Estructura de mercado ICT/SMC
 * Port del Pine Script "SHOWI ICT" a lightweight-charts v4.
 *
 * Detecta:
 *   A — BOS / CHoCH (cuerpo cierra al otro lado del nivel activo)
 *   F — Fake break (mecha supera pero cuerpo rechaza)
 *   HH / LH / HL / LL — etiquetas en cada swing
 */

import BadgeComponent from './Badge'
import PanelComponent from './Panel'

// ── ATR (Wilder smoothing, igual que ta.atr en Pine) ─────────────
function calcATR(candles, period) {
  const n = candles.length
  const trs = candles.map((c, i) =>
    i === 0
      ? c.high - c.low
      : Math.max(c.high - c.low, Math.abs(c.high - candles[i - 1].close), Math.abs(c.low - candles[i - 1].close))
  )
  const atrs = new Array(n).fill(0)
  const seed = trs.slice(0, Math.min(period, n)).reduce((a, b) => a + b, 0) / Math.min(period, n)
  for (let i = 0; i < period && i < n; i++) atrs[i] = seed
  for (let i = period; i < n; i++) atrs[i] = (atrs[i - 1] * (period - 1) + trs[i]) / period
  return atrs
}

// ── Pivots crudos (ta.pivothigh / ta.pivotlow) ────────────────────
function calcRawPivots(candles, pivotLen) {
  const n = candles.length
  const rawHighs = new Array(n).fill(null)
  const rawLows  = new Array(n).fill(null)
  for (let i = pivotLen; i < n - pivotLen; i++) {
    let isH = true, isL = true
    for (let j = i - pivotLen; j <= i + pivotLen; j++) {
      if (j === i) continue
      if (candles[j].high >= candles[i].high) isH = false
      if (candles[j].low  <= candles[i].low)  isL = false
    }
    if (isH) rawHighs[i] = candles[i].high
    if (isL) rawLows[i]  = candles[i].low
  }
  return { rawHighs, rawLows }
}

// ── Motor principal ───────────────────────────────────────────────
function runShowiICT(candles, config) {
  const { pivotLen, atrMult, atrLen } = config
  const n = candles.length
  if (n < pivotLen * 2 + atrLen + 5) return null

  const atrs               = calcATR(candles, atrLen)
  const { rawHighs, rawLows } = calcRawPivots(candles, pivotLen)

  // Estado (igual que las var de Pine Script)
  let activeH = null, activeL = null
  let activeHBar = -1, activeLBar = -1
  let usedH = false,  usedL  = false
  let usedFH = false, usedFL = false
  let bullBias = true
  let prevSwH = null, prevSwL = null

  const pivotLabels = []   // { time, price, label, isHigh }
  const signals     = []   // { time, type, levelPrice, levelTime, label, atr }

  for (let bar = 0; bar < n; bar++) {
    const c = candles[bar]

    // ── Confirmar pivots en este bar (el pivot real está pivotLen atrás) ──
    const pIdx = bar - pivotLen
    if (pIdx >= 1 && pIdx < n - 1) {
      if (rawHighs[pIdx] !== null) {
        const ph   = rawHighs[pIdx]
        const size = ph - Math.max(candles[pIdx + 1].close, candles[pIdx - 1].close)
        if (size >= atrMult * atrs[pIdx]) {
          prevSwH    = activeH
          activeH    = ph
          activeHBar = pIdx
          usedH      = false
          usedFH     = false
        }
      }
      if (rawLows[pIdx] !== null) {
        const pl   = rawLows[pIdx]
        const size = Math.min(candles[pIdx + 1].close, candles[pIdx - 1].close) - pl
        if (size >= atrMult * atrs[pIdx]) {
          prevSwL    = activeL
          activeL    = pl
          activeLBar = pIdx
          usedL      = false
          usedFL     = false
        }
      }
    }

    if (activeH === null && activeL === null) continue

    const atr = atrs[bar]

    // ── A: cuerpo rompe ───────────────────────────────────────────
    const bodyBreakU = activeH !== null && !usedH  && c.close > activeH
    const bodyBreakD = activeL !== null && !usedL  && c.close < activeL

    // ── F: mecha supera, cuerpo rechaza ──────────────────────────
    const fakeBreakU = activeH !== null && !usedH && !usedFH && c.high > activeH && c.close <= activeH
    const fakeBreakD = activeL !== null && !usedL && !usedFL && c.low  < activeL && c.close >= activeL

    if (bodyBreakU) {
      const isBos = bullBias
      const isHH  = prevSwH !== null && activeH > prevSwH
      pivotLabels.push({ time: candles[activeHBar].time, price: activeH, label: isHH ? 'HH' : 'LH', isHigh: true })
      signals.push({
        time: c.time, type: isBos ? 'bosU' : 'chochU',
        levelPrice: activeH, levelTime: candles[activeHBar].time,
        label: isBos ? 'A+' : 'A', atr,
      })
      usedH = true; usedFH = true
      if (!isBos) bullBias = true
    }

    if (bodyBreakD) {
      const isBos = !bullBias
      const isHL  = prevSwL !== null && activeL > prevSwL
      pivotLabels.push({ time: candles[activeLBar].time, price: activeL, label: isHL ? 'HL' : 'LL', isHigh: false })
      signals.push({
        time: c.time, type: isBos ? 'bosD' : 'chochD',
        levelPrice: activeL, levelTime: candles[activeLBar].time,
        label: isBos ? 'A-' : 'A', atr,
      })
      usedL = true; usedFL = true
      if (!isBos) bullBias = false
    }

    if (fakeBreakU) {
      signals.push({ time: c.time, type: 'fakeU', levelPrice: activeH, levelTime: candles[activeHBar].time, label: 'F', atr })
      usedFH = true
    }

    if (fakeBreakD) {
      signals.push({ time: c.time, type: 'fakeD', levelPrice: activeL, levelTime: candles[activeLBar].time, label: 'F', atr })
      usedFL = true
    }
  }

  return { signals, pivotLabels, activeH, activeL, bullBias }
}

// ── Colores por defecto ───────────────────────────────────────────
const DEF_COLORS = {
  bull:  '#26c6da',
  bear:  '#ef5350',
  fake:  '#ff9800',
}

export default {
  id:      'showi_ict',
  name:    'SHOWI ICT',
  version: '1.0',

  defaultConfig: {
    pivotLen: 5,
    atrMult:  1.5,
    atrLen:   14,
    showHHHL:    true,
    showSignals: true,
    showFakes:   true,
    showLevels:  true,
    colors: { ...DEF_COLORS },
  },

  detect(candles, config) {
    return runShowiICT(candles, config)
  },

  render(chart, candleSeries, result, config, api) {
    if (!result) return
    const { colors, showHHHL, showSignals, showFakes, showLevels } = config
    const bull = colors.bull || DEF_COLORS.bull
    const bear = colors.bear || DEF_COLORS.bear
    const fake = colors.fake || DEF_COLORS.fake

    // ── Niveles activos ───────────────────────────────────────────
    if (showLevels) {
      if (result.activeH !== null) {
        api.addPriceLine({ price: result.activeH, color: bull, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'H activo' })
      }
      if (result.activeL !== null) {
        api.addPriceLine({ price: result.activeL, color: bear, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'L activo' })
      }
    }

    // ── Etiquetas HH / LH / HL / LL en los pivots ────────────────
    if (showHHHL) {
      for (const p of result.pivotLabels) {
        api.addMarker({
          time:     p.time,
          position: p.isHigh ? 'aboveBar' : 'belowBar',
          color:    p.isHigh ? bull : bear,
          shape:    'circle',
          text:     p.label,
          size:     0,
        })
      }
    }

    // ── Señales A y F ─────────────────────────────────────────────
    for (const sig of result.signals) {
      const isBull = sig.type === 'bosU' || sig.type === 'chochU'
      const isBear = sig.type === 'bosD' || sig.type === 'chochD'
      const isFake = sig.type === 'fakeU' || sig.type === 'fakeD'
      const isFakeUp = sig.type === 'fakeU'

      if (isFake && showFakes) {
        api.addMarker({
          time:     sig.time,
          position: isFakeUp ? 'aboveBar' : 'belowBar',
          color:    fake,
          shape:    'circle',
          text:     'F',
          size:     1,
        })
      }

      if ((isBull || isBear) && showSignals) {
        api.addLabel({
          time:          sig.time,
          text:          sig.label,
          color:         isBull ? bull : bear,
          isBull,
          fallbackPrice: sig.levelPrice,
        })
      }
    }
  },

  BadgeComponent,
  PanelComponent,
}
