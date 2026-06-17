/**
 * Squeeze Breakout — Detección de compresión de volatilidad + ruptura confirmada
 *
 * Motor dual: BB Width compression + ATR compression (ambos deben coincidir).
 * Rango Donchian adaptativo durante la compresión, vela de impulso para confirmar
 * ruptura, TP/SL basados en R:R y seguimiento de ciclo de vida.
 */

import BadgeComponent from './Badge.jsx'
import PanelComponent from './Panel.jsx'

// ── Helpers ────────────────────────────────────────────────────────────────────

function calcATR(candles, period) {
  const n = candles.length
  const tr = candles.map((c, i) =>
    i === 0
      ? c.high - c.low
      : Math.max(c.high - c.low, Math.abs(c.high - candles[i-1].close), Math.abs(c.low - candles[i-1].close))
  )
  const out = new Array(n).fill(null)
  if (n < period) return out
  let sum = 0
  for (let i = 0; i < period; i++) sum += tr[i]
  out[period - 1] = sum / period
  for (let i = period; i < n; i++) out[i] = (out[i-1] * (period - 1) + tr[i]) / period
  return out
}

function calcSMA(arr, len) {
  const out = new Array(arr.length).fill(null)
  for (let i = len - 1; i < arr.length; i++) {
    let s = 0, cnt = 0
    for (let j = i - len + 1; j <= i; j++) {
      if (arr[j] != null && !isNaN(arr[j])) { s += arr[j]; cnt++ }
    }
    if (cnt > 0) out[i] = s / cnt
  }
  return out
}

function calcBBWidth(candles, len, mult) {
  const closes = candles.map(c => c.close)
  return closes.map((_, i) => {
    if (i < len - 1) return null
    const sl = closes.slice(i - len + 1, i + 1)
    const mean = sl.reduce((a, b) => a + b, 0) / len
    const variance = sl.reduce((a, b) => a + (b - mean) ** 2, 0) / len
    const std = Math.sqrt(variance)
    const upper = mean + mult * std
    const lower = mean - mult * std
    return mean > 0 ? (upper - lower) / mean : 0
  })
}

// ── detect ─────────────────────────────────────────────────────────────────────

function detect(candles, config) {
  const n = candles.length
  const {
    squeezeLength    = 20,
    bbMult           = 2.0,
    squeezeThresh    = 0.6,
    atrCompressRatio = 0.75,
    minSqueezeBars   = 5,
    impulseMult      = 0.8,
    preventOverlap   = true,
    slBuffer         = 0.5,
    tp1RR            = 1.0,
    tp2RR            = 2.0,
    tp3RR            = 3.0,
    useVolFilter     = false,
    volMult          = 1.5,
  } = config

  const WARMUP = Math.max(squeezeLength, 50)
  if (n < WARMUP + 5) return null

  const atrPeriod = Math.max(Math.floor(squeezeLength / 2), 7)
  const atrs      = calcATR(candles, atrPeriod)
  const atrSmas   = calcSMA(atrs, squeezeLength)
  const bbWidths  = calcBBWidth(candles, squeezeLength, bbMult)
  const bbWSmas   = calcSMA(bbWidths, squeezeLength)

  const volumes = candles.map(c => c.volume ?? 0)
  const hasVol  = volumes.some(v => v > 0)
  const volSmas = calcSMA(volumes, 20)

  // ── State machine ────────────────────────────────────────────────────────────
  let sqBars = 0, sqHigh = null, sqLow = null, sqStartIdx = null
  let wasSq = false, lastBoxEndIdx = -1

  // Active trade
  let dir = 0, entry = null, sl = null, tp1 = null, tp2 = null, tp3 = null
  let tradeActive = false, entryIdx = null

  const pendingBoxes = []  // range boxes waiting for breakout
  const signals      = []  // all breakout signals
  const sqMarkers    = []  // squeeze start markers

  let lastSqActive = false, lastSqBars = 0

  for (let i = WARMUP; i < n; i++) {
    const c     = candles[i]
    const atr   = atrs[i]
    const aSma  = atrSmas[i]
    const bW    = bbWidths[i]
    const bWSma = bbWSmas[i]

    if (atr == null || aSma == null || bW == null || bWSma == null) {
      wasSq = false; continue
    }

    // Dual engine squeeze detection
    const bbSq  = bW < bWSma * squeezeThresh
    const atrC  = aSma > 0 ? atr < aSma * atrCompressRatio : false
    const isSq  = bbSq && atrC

    if (isSq) {
      if (!wasSq) {
        sqBars = 1; sqHigh = c.high; sqLow = c.low; sqStartIdx = i
        sqMarkers.push({ time: c.time })
      } else {
        sqBars++
        sqHigh = Math.max(sqHigh, c.high)
        sqLow  = Math.min(sqLow,  c.low)
      }
    } else {
      if (wasSq && sqBars >= minSqueezeBars) {
        const canCreate = !preventOverlap || sqStartIdx > lastBoxEndIdx
        if (canCreate && sqHigh != null && sqLow != null && sqHigh > sqLow) {
          const span   = sqHigh - sqLow
          const center = (sqHigh + sqLow) / 2
          const maxSp  = atr * 6
          const top    = span > maxSp ? center + atr * 3 : sqHigh
          const bottom = span > maxSp ? center - atr * 3 : sqLow
          pendingBoxes.push({
            startIdx:   sqStartIdx,
            endIdx:     i,
            startTime:  candles[sqStartIdx].time,
            endTime:    c.time,
            top, bottom,
            atr,
            sqBarCount: sqBars,
          })
          lastBoxEndIdx = i
        }
      }
      sqBars = 0; sqHigh = null; sqLow = null; sqStartIdx = null
    }
    wasSq = isSq
    lastSqActive = isSq
    lastSqBars   = isSq ? sqBars : 0

    // Volume filter
    const volOk = !useVolFilter || !hasVol ||
      (volSmas[i] != null && volumes[i] > volSmas[i] * volMult)

    // Impulse candle
    const body  = Math.abs(c.close - c.open)
    const impUp = c.close > c.open && body > atr * impulseMult
    const impDn = c.close < c.open && body > atr * impulseMult

    // TP/SL tracking for active trade (skip on entry bar)
    if (tradeActive && entryIdx !== i) {
      const prev = candles[i - 1]
      const sig  = signals[signals.length - 1]

      if (dir === 1) {
        if (tp3 != null && c.high >= tp3 && prev.high < tp3) {
          sig.result = 'win'; sig.pnl = tp3 - entry; sig.closeTime = c.time
          tradeActive = false; dir = 0
        } else if (sl != null && c.low <= sl && prev.low > sl) {
          sig.result = 'loss'; sig.pnl = sl - entry; sig.closeTime = c.time
          tradeActive = false; dir = 0
        } else {
          if (tp1 != null && !sig.tp1Hit && c.high >= tp1 && prev.high < tp1) sig.tp1Hit = c.time
          if (tp2 != null && !sig.tp2Hit && c.high >= tp2 && prev.high < tp2) sig.tp2Hit = c.time
        }
      } else if (dir === -1) {
        if (tp3 != null && c.low <= tp3 && prev.low > tp3) {
          sig.result = 'win'; sig.pnl = entry - tp3; sig.closeTime = c.time
          tradeActive = false; dir = 0
        } else if (sl != null && c.high >= sl && prev.high < sl) {
          sig.result = 'loss'; sig.pnl = entry - sl; sig.closeTime = c.time
          tradeActive = false; dir = 0
        } else {
          if (tp1 != null && !sig.tp1Hit && c.low <= tp1 && prev.low > tp1) sig.tp1Hit = c.time
          if (tp2 != null && !sig.tp2Hit && c.low <= tp2 && prev.low > tp2) sig.tp2Hit = c.time
        }
      }
    }

    // Breakout scan across pending boxes
    for (let bi = pendingBoxes.length - 1; bi >= 0; bi--) {
      const box = pendingBoxes[bi]
      box.endIdx  = i
      box.endTime = c.time

      if (c.close > box.top && impUp && volOk) {
        const ent  = c.close
        const s    = box.bottom - atr * slBuffer
        const risk = Math.abs(ent - s)
        const t1   = ent + risk * tp1RR
        const t2   = ent + risk * tp2RR
        const t3   = ent + risk * tp3RR
        const str  = 1
          + (useVolFilter && hasVol && volOk ? 1 : 0)
          + (box.sqBarCount >= minSqueezeBars * 2 ? 1 : 0)

        signals.push({ time: c.time, idx: i, dir: 1, entry: ent, sl: s, tp1: t1, tp2: t2, tp3: t3, strength: str, result: 'active', pnl: null })
        entry = ent; sl = s; tp1 = t1; tp2 = t2; tp3 = t3
        dir = 1; tradeActive = true; entryIdx = i
        pendingBoxes.splice(bi, 1)
        break

      } else if (c.close < box.bottom && impDn && volOk) {
        const ent  = c.close
        const s    = box.top + atr * slBuffer
        const risk = Math.abs(s - ent)
        const t1   = ent - risk * tp1RR
        const t2   = ent - risk * tp2RR
        const t3   = ent - risk * tp3RR
        const str  = 1
          + (useVolFilter && hasVol && volOk ? 1 : 0)
          + (box.sqBarCount >= minSqueezeBars * 2 ? 1 : 0)

        signals.push({ time: c.time, idx: i, dir: -1, entry: ent, sl: s, tp1: t1, tp2: t2, tp3: t3, strength: str, result: 'active', pnl: null })
        entry = ent; sl = s; tp1 = t1; tp2 = t2; tp3 = t3
        dir = -1; tradeActive = true; entryIdx = i
        pendingBoxes.splice(bi, 1)
        break
      }
    }
  }

  const lastSig    = signals.length > 0 ? signals[signals.length - 1] : null
  const activeTrade = tradeActive ? { dir, entry, sl, tp1, tp2, tp3 } : null

  return {
    pendingBoxes,
    signals,
    sqMarkers,
    activeTrade,
    lastSig,
    dashboard: {
      sqActive:   lastSqActive,
      sqBars:     lastSqBars,
      lastResult: lastSig?.result ?? null,
      lastPnl:    lastSig?.pnl ?? null,
      lastDir:    lastSig?.dir ?? 0,
      strength:   lastSig?.strength ?? 0,
    },
  }
}

// ── render (lightweight-charts primitives) ─────────────────────────────────────

function render(chart, candleSeries, result, config, api) {
  if (!result) return

  const { signals, sqMarkers, activeTrade } = result
  const {
    showSignals   = true,
    showCloseLbls = true,
    colors        = {},
  } = config

  const bull    = colors.bull    ?? '#00E676'
  const bear    = colors.bear    ?? '#FF5252'
  const neutral = colors.neutral ?? '#FFEB3B'

  // Squeeze start dots
  for (const m of sqMarkers) {
    api.addMarker({ time: m.time, position: 'belowBar', color: neutral, shape: 'circle', size: 0 })
  }

  // Breakout signal labels + close markers
  for (const sig of signals) {
    if (showSignals) {
      api.addLabel({
        time:          sig.time,
        text:          sig.dir === 1 ? 'Long' : 'Short',
        color:         sig.dir === 1 ? bull : bear,
        isBull:        sig.dir === 1,
        fallbackPrice: sig.entry,
      })
    }

    if (showCloseLbls && sig.closeTime) {
      if (sig.result === 'win') {
        api.addMarker({
          time:     sig.closeTime,
          position: sig.dir === 1 ? 'aboveBar' : 'belowBar',
          color:    bull,
          shape:    'circle',
          text:     '✓',
          size:     1,
        })
      } else if (sig.result === 'loss') {
        api.addMarker({
          time:     sig.closeTime,
          position: sig.dir === 1 ? 'belowBar' : 'aboveBar',
          color:    bear,
          shape:    'circle',
          text:     '✗',
          size:     1,
        })
      }
    }
  }

  // Active trade price levels
  if (activeTrade) {
    const { dir: d, entry: en, sl: slv, tp1: t1, tp2: t2, tp3: t3 } = activeTrade
    const tpColor = d === 1 ? bull : bear
    api.addPriceLine({ price: en,  color: d === 1 ? bull : bear,   lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'Entry' })
    api.addPriceLine({ price: slv, color: bear,                     lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL'    })
    api.addPriceLine({ price: t1,  color: tpColor + '99',           lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP1'   })
    api.addPriceLine({ price: t2,  color: tpColor + 'bb',           lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP2'   })
    api.addPriceLine({ price: t3,  color: tpColor,                  lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP3'   })
  }
}

// ── Default config ──────────────────────────────────────────────────────────────

const defaultConfig = {
  squeezeLength:    20,
  bbMult:           2.0,
  squeezeThresh:    0.6,
  atrCompressRatio: 0.75,
  minSqueezeBars:   5,
  impulseMult:      0.8,
  preventOverlap:   true,
  slBuffer:         0.5,
  tp1RR:            1.0,
  tp2RR:            2.0,
  tp3RR:            3.0,
  useVolFilter:     false,
  volMult:          1.5,
  showBoxes:        true,
  showCenter:       true,
  showSignals:      true,
  showCloseLbls:    true,
  colors: {
    bull:    '#00E676',
    bear:    '#FF5252',
    neutral: '#FFEB3B',
  },
}

export default {
  id:      'squeeze_breakout',
  name:    'Squeeze Breakout',
  version: '1.0',
  defaultConfig,
  detect,
  render,
  BadgeComponent,
  PanelComponent,
}
