/**
 * ICT / SMC Engine — JavaScript puro
 * Port del indicador Pine Script "SHOWI ICT" para entornos JS.
 * Sin dependencias. Funciona con cualquier array de velas { open, high, low, close, time }.
 *
 * Uso básico:
 *   import { runICT } from './ictEngine.js'
 *   const result = runICT(candles, { atrMult: 1.5, requireSweep: true })
 *   // result = { pivots, structure, levels, fvgs, obs, entries, bias }
 */

// ─── Helpers matemáticos ────────────────────────────────────────────────────

function calculateATR(candles, period) {
  const tr = candles.map((c, i) => {
    if (i === 0) return c.high - c.low
    const pc = candles[i - 1].close
    return Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc))
  })
  const atr = []
  let sum = 0
  for (let i = 0; i < candles.length; i++) {
    if (i < period) { atr.push(null); continue }
    if (i === period) sum = tr.slice(0, period).reduce((a, b) => a + b, 0) / period
    else sum = (sum * (period - 1) + tr[i]) / period
    atr.push(sum)
  }
  return atr
}

function emaArray(candles, period) {
  const k = 2 / (period + 1)
  const arr = []
  let prev = null
  for (let i = 0; i < candles.length; i++) {
    if (i < period - 1) { arr.push(null); continue }
    if (i === period - 1) prev = candles.slice(0, period).reduce((a, b) => a + b.close, 0) / period
    else prev = candles[i].close * k + prev * (1 - k)
    arr.push(prev)
  }
  return arr
}

// ─── Detección de Pivots ────────────────────────────────────────────────────

export function ictDetectPivots(candles, pivotLen, atrValues, atrMult) {
  const highs = [], lows = []
  for (let i = pivotLen; i < candles.length - pivotLen; i++) {
    const c = candles[i]
    let isHigh = true, isLow = true
    for (let j = i - pivotLen; j <= i + pivotLen; j++) {
      if (j === i) continue
      if (candles[j].high > c.high) isHigh = false
      if (candles[j].low < c.low) isLow = false
      if (!isHigh && !isLow) break
    }
    const atr = atrValues[i] || 0
    if (isHigh) {
      const size = c.high - Math.max(candles[i - 1].close, candles[i + 1].close)
      if (size >= atrMult * atr) highs.push({ time: c.time, price: c.high, idx: i, size })
    }
    if (isLow) {
      const size = Math.min(candles[i - 1].close, candles[i + 1].close) - c.low
      if (size >= atrMult * atr) lows.push({ time: c.time, price: c.low, idx: i, size })
    }
  }
  return { highs, lows }
}

// ─── Detección de Estructura (BOS / CHoCH) ──────────────────────────────────

export function ictDetectStructure(candles, pivots, emaValues, options) {
  const {
    useTrendFilter, requireSweep, useMomentum, minBodySize,
    useCooldown, cooldownBars,
  } = options
  const atrValues = calculateATR(candles, 14)

  let activeH = null, activeL = null
  let activeHBar = -1, activeLBar = -1
  let usedH = false, usedL = false, usedFH = false, usedFL = false
  let sweepH = false, sweepL = false
  let bullBias = true
  let prevSwH = null, prevSwL = null
  let lastSigBar = -999

  const breaks = []
  const levels = []

  const highMap = new Map()
  pivots.highs.forEach(p => highMap.set(p.idx, p))
  const lowMap = new Map()
  pivots.lows.forEach(p => lowMap.set(p.idx, p))

  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]

    if (highMap.has(i)) {
      const p = highMap.get(i)
      prevSwH = activeH
      activeH = p.price
      activeHBar = i
      usedH = false; usedFH = false; sweepH = false
    }
    if (lowMap.has(i)) {
      const p = lowMap.get(i)
      prevSwL = activeL
      activeL = p.price
      activeLBar = i
      usedL = false; usedFL = false; sweepL = false
    }

    if (activeH === null || activeL === null) continue

    const bodyBreakU = !usedH && c.close > activeH
    const bodyBreakD = !usedL && c.close < activeL
    const fakeBreakU = !usedH && !usedFH && c.high > activeH && c.close <= activeH
    const fakeBreakD = !usedL && !usedFL && c.low < activeL && c.close >= activeL

    if (fakeBreakU) { usedFH = true; sweepH = true }
    if (fakeBreakD) { usedFL = true; sweepL = true }

    const bodySz = Math.abs(c.close - c.open)
    const atr = atrValues[i] || 0
    const momentumU = !useMomentum || (bodySz >= minBodySize * atr && c.close > c.open)
    const momentumD = !useMomentum || (bodySz >= minBodySize * atr && c.close < c.open)

    const ema = emaValues[i]
    const trendU = !useTrendFilter || (ema !== null && c.close > ema)
    const trendD = !useTrendFilter || (ema !== null && c.close < ema)

    const cooldownOk = !useCooldown || (i - lastSigBar >= cooldownBars)

    const isBosU = bodyBreakU && bullBias
    const isChochU = bodyBreakU && !bullBias
    const isBosD = bodyBreakD && !bullBias
    const isChochD = bodyBreakD && bullBias

    if (bodyBreakU) {
      if ((isBosU && trendU && momentumU && cooldownOk && (!requireSweep || sweepH)) ||
          (isChochU && momentumU && cooldownOk)) {
        breaks.push({
          time: c.time, type: isBosU ? 'BOS' : 'CHoCH', dir: 'up', price: activeH,
          valid: true, isContraTrend: isChochU && !trendU, hadSweep: sweepH,
        })
        levels.push({ time: candles[activeHBar].time, price: activeH, levelType: 'high', dir: 'up', dashed: isChochU })
        usedH = true; usedFH = true; lastSigBar = i
        if (isChochU) bullBias = true
      } else {
        usedH = true; usedFH = true
      }
    }

    if (bodyBreakD) {
      if ((isBosD && trendD && momentumD && cooldownOk && (!requireSweep || sweepL)) ||
          (isChochD && momentumD && cooldownOk)) {
        breaks.push({
          time: c.time, type: isBosD ? 'BOS' : 'CHoCH', dir: 'down', price: activeL,
          valid: true, isContraTrend: isChochD && !trendD, hadSweep: sweepL,
        })
        levels.push({ time: candles[activeLBar].time, price: activeL, levelType: 'low', dir: 'down', dashed: isChochD })
        usedL = true; usedFL = true; lastSigBar = i
        if (isChochD) bullBias = false
      } else {
        usedL = true; usedFL = true
      }
    }
  }

  return { breaks, levels, bias: bullBias ? 'up' : 'down' }
}

// ─── Fair Value Gaps ────────────────────────────────────────────────────────

export function ictDetectFVGs(candles) {
  const fvgs = []
  for (let i = 1; i < candles.length - 1; i++) {
    const prev = candles[i - 1], curr = candles[i], next = candles[i + 1]
    if (prev.low > next.high)
      fvgs.push({ type: 'bull', startTime: curr.time, top: prev.low, bottom: next.high, mitigated: false, mitigateTime: null })
    if (prev.high < next.low)
      fvgs.push({ type: 'bear', startTime: curr.time, top: next.low, bottom: prev.high, mitigated: false, mitigateTime: null })
  }
  for (const fvg of fvgs) {
    const startIdx = candles.findIndex(c => c.time >= fvg.startTime)
    if (startIdx < 0) continue
    for (let i = startIdx + 1; i < candles.length; i++) {
      const c = candles[i]
      if (fvg.type === 'bull' && c.close <= fvg.bottom) { fvg.mitigated = true; fvg.mitigateTime = c.time; break }
      if (fvg.type === 'bear' && c.close >= fvg.top) { fvg.mitigated = true; fvg.mitigateTime = c.time; break }
    }
  }
  const unmitigated = fvgs.filter(f => !f.mitigated)
  const mitigated = fvgs.filter(f => f.mitigated).slice(-4)
  return [...unmitigated, ...mitigated].slice(-8)
}

// ─── Order Blocks ───────────────────────────────────────────────────────────

export function ictDetectOrderBlocks(candles, structure) {
  const obs = []
  for (const brk of structure) {
    const brkIdx = candles.findIndex(c => c.time >= brk.time)
    if (brkIdx < 0) continue
    const start = Math.max(0, brkIdx - 20)
    if (brk.dir === 'up') {
      for (let i = brkIdx - 1; i >= start; i--) {
        if (candles[i].close < candles[i].open) {
          obs.push({ type: 'bull', time: candles[i].time, top: candles[i].high, bottom: candles[i].low, mitigated: false, mitigateTime: null })
          break
        }
      }
    } else {
      for (let i = brkIdx - 1; i >= start; i--) {
        if (candles[i].close > candles[i].open) {
          obs.push({ type: 'bear', time: candles[i].time, top: candles[i].high, bottom: candles[i].low, mitigated: false, mitigateTime: null })
          break
        }
      }
    }
  }
  for (const ob of obs) {
    const startIdx = candles.findIndex(c => c.time >= ob.time)
    if (startIdx < 0) continue
    for (let i = startIdx + 1; i < candles.length; i++) {
      const c = candles[i]
      if (ob.type === 'bull' && c.close <= ob.bottom) { ob.mitigated = true; ob.mitigateTime = c.time; break }
      if (ob.type === 'bear' && c.close >= ob.top) { ob.mitigated = true; ob.mitigateTime = c.time; break }
    }
  }
  const unmitigated = obs.filter(o => !o.mitigated)
  const mitigated = obs.filter(o => o.mitigated).slice(-3)
  return [...unmitigated, ...mitigated].slice(-6)
}

// ─── Entradas (toque OB/FVG) ────────────────────────────────────────────────

export function ictDetectEntries(candles, structure, obs, fvgs) {
  const entries = []
  const validBreaks = structure.filter(b => b.valid)
  for (let bIdx = 0; bIdx < validBreaks.length; bIdx++) {
    const brk = validBreaks[bIdx]
    const brkCandleIdx = candles.findIndex(c => c.time >= brk.time)
    if (brkCandleIdx < 0) continue
    const dir = brk.dir
    const obType = dir === 'up' ? 'bull' : 'bear'
    const fvgType = dir === 'up' ? 'bull' : 'bear'

    const activeOb = obs
      .filter(ob => ob.type === obType && !ob.mitigated && candles.findIndex(c => c.time >= ob.time) <= brkCandleIdx)
      .slice(-1)[0] ?? null

    const nextBrkCandleIdx = bIdx + 1 < validBreaks.length
      ? candles.findIndex(c => c.time >= validBreaks[bIdx + 1].time)
      : candles.length

    let fired = false
    for (let i = brkCandleIdx + 1; i < nextBrkCandleIdx && i < candles.length && !fired; i++) {
      const c = candles[i]
      if (activeOb && c.low <= activeOb.top && c.high >= activeOb.bottom) {
        entries.push({ time: c.time, signal: dir === 'up' ? 'long' : 'short', trigger: 'ob', contraTrend: brk.isContraTrend })
        fired = true
        break
      }
      const recentFvgs = fvgs.filter(f => f.type === fvgType && !f.mitigated && f.startTime < c.time)
      for (const fvg of recentFvgs.slice().reverse()) {
        if (c.low <= fvg.top && c.high >= fvg.bottom) {
          entries.push({ time: c.time, signal: dir === 'up' ? 'long' : 'short', trigger: 'fvg', contraTrend: brk.isContraTrend })
          fired = true
          break
        }
      }
    }
  }
  return entries
}

// ─── Orquestador principal ──────────────────────────────────────────────────

export function runICT(candles, options = {}) {
  if (!candles || candles.length < 50) return null
  const opts = {
    pivotLen: 5,
    atrLen: 14,
    atrMult: 0.5,
    useTrendFilter: true,
    trendLen: 50,
    requireSweep: true,
    useMomentum: true,
    minBodySize: 0.6,
    useCooldown: true,
    cooldownBars: 5,
    ...options,
  }
  const atrValues = calculateATR(candles, opts.atrLen)
  const emaValues = opts.useTrendFilter ? emaArray(candles, opts.trendLen) : []
  const pivots = ictDetectPivots(candles, opts.pivotLen, atrValues, opts.atrMult)
  const { breaks, levels, bias } = ictDetectStructure(candles, pivots, emaValues, opts)
  const fvgs = ictDetectFVGs(candles)
  const obs = ictDetectOrderBlocks(candles, breaks)
  const entries = ictDetectEntries(candles, breaks, obs, fvgs)
  return { pivots, structure: breaks, levels, fvgs, obs, entries, bias }
}

// ─── Ejemplo de uso standalone (Node / Browser) ─────────────────────────────
// const candles = [
//   { time: 0, open: 100, high: 101, low: 99, close: 100.5 },
//   ...
// ]
// const result = runICT(candles, { atrMult: 1.5, requireSweep: false })
// console.log(result.structure) // BOS/CHoCH array
