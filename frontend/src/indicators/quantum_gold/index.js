/**
 * QUANTUM GOLD — Indicador de confluencias multi-indicador para XAUUSD.
 * Porteado desde Pine Script v5.  Toda la lógica vive en detect() (O(n) pase único),
 * render() solo dibuja lo que detect() ya calculó.
 *
 * Componentes:
 *   EMA 9 / 21 / 50 / 200  ·  Supertrend (Wilder ATR)
 *   Bollinger Bands + Squeeze  ·  RSI  ·  Volumen
 *   Filtros: tendencia, ATR mínimo, sesión Londres/NY
 */
import Badge from './Badge.jsx'
import Panel from './Panel.jsx'

// ─── Utilidades estadísticas (funciones puras) ────────────────────────────────

/** EMA estándar (factor = 2/(n+1)) */
const ema = (src, n) => {
  const k = 2 / (n + 1)
  let v = src[0]
  return src.map(x => { v = x * k + v * (1 - k); return v })
}

/** Wilder's Moving Average (RMA) — usado en ATR y RSI */
const rma = (src, n) => {
  const out = Array(n - 1).fill(null)
  let v = src.slice(0, n).reduce((a, b) => a + b, 0) / n
  out.push(v)
  for (let i = n; i < src.length; i++) { v = (v * (n - 1) + src[i]) / n; out.push(v) }
  return out
}

/** SMA simple */
const sma = (src, n) =>
  src.map((_, i) =>
    i < n - 1 ? null : src.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n
  )

/** ATR con Wilder's RMA (igual que Pine Script ta.atr) */
const calcATR = (cs, n) => {
  const tr = [cs[0].high - cs[0].low]
  for (let i = 1; i < cs.length; i++)
    tr.push(Math.max(
      cs[i].high - cs[i].low,
      Math.abs(cs[i].high - cs[i - 1].close),
      Math.abs(cs[i].low  - cs[i - 1].close),
    ))
  return rma(tr, n)
}

/** RSI con Wilder's smoothing (igual que Pine Script ta.rsi) */
const calcRSI = (src, n) => {
  if (src.length < n + 1) return src.map(() => null)
  const gains = [], losses = []
  for (let i = 1; i < src.length; i++) {
    const d = src[i] - src[i - 1]
    gains.push(d > 0 ? d : 0)
    losses.push(d < 0 ? -d : 0)
  }
  const rG = rma(gains, n), rL = rma(losses, n)
  return [null, ...rG.map((g, i) =>
    g === null ? null : rL[i] === 0 ? 100 : 100 - 100 / (1 + g / rL[i])
  )]
}

/**
 * Supertrend — implementación fiel a Pine Script ta.supertrend(factor, atrPeriod).
 * Devuelve array de {v, bull} donde bull=true significa precio sobre la línea.
 */
const calcSupertrend = (cs, n, factor) => {
  const at = calcATR(cs, n)
  let dir = -1, ub = null, lb = null
  return cs.map((c, i) => {
    if (at[i] === null) return { v: null, bull: true }
    const hl2 = (c.high + c.low) / 2
    const rUB = hl2 + factor * at[i]
    const rLB = hl2 - factor * at[i]
    const pc  = i > 0 ? cs[i - 1].close : c.close
    // Primer bar o banda se aprieta o precio cruzó — igual que Pine Script na() check
    ub = (ub === null || rUB < ub || pc > ub) ? rUB : ub
    lb = (lb === null || rLB > lb || pc < lb) ? rLB : lb
    if      (dir === 1  && c.close > ub) dir = -1
    else if (dir === -1 && c.close < lb) dir =  1
    return { v: dir === -1 ? lb : ub, bull: dir === -1 }
  })
}

/**
 * Bollinger Bands — devuelve {upper, lower, mean, width} por barra.
 * width = (upper-lower)/mean*100  (en %)
 */
const calcBB = (src, n, mult) => {
  const basis = sma(src, n)
  return src.map((_, i) => {
    if (basis[i] === null) return { upper: null, lower: null, mean: null, width: null }
    const sl   = src.slice(i - n + 1, i + 1)
    const mean = basis[i]
    const std  = Math.sqrt(sl.reduce((a, b) => a + (b - mean) ** 2, 0) / n)
    const upper = mean + mult * std
    const lower = mean - mult * std
    return { upper, lower, mean, width: mean > 0 ? (upper - lower) / mean * 100 : 0 }
  })
}

/** Determina si el timestamp (segundos) cae en sesión Londres (08-17h UTC) o NY (13:30-21h UTC) */
const getSess = (tSec, useSess) => {
  if (!useSess) return { ok: true, lon: false, ny: false }
  const d = new Date(tSec * 1000)
  const m = d.getUTCHours() * 60 + d.getUTCMinutes()
  const lon = m >= 480 && m < 1020   // 08:00 – 17:00 UTC
  const ny  = m >= 810 && m < 1260   // 13:30 – 21:00 UTC
  return { ok: lon || ny, lon, ny }
}

// ─── detect() ─────────────────────────────────────────────────────────────────

function detect(candles, cfg) {
  const n = candles.length
  // Necesitamos al menos emaTrend + margen para que todos los indicadores estén calentados
  if (n < cfg.emaTrend + 50) return null

  const cl  = candles.map(c => c.close)
  const vol = candles.map(c => c.volume ?? 0)

  // ── Indicadores ──────────────────────────────────────────────────────────
  const E9   = ema(cl, cfg.emaFast)
  const E21  = ema(cl, cfg.emaMid)
  const E50  = ema(cl, cfg.emaSlow)
  const E200 = ema(cl, cfg.emaTrend)
  const ST   = calcSupertrend(candles, cfg.stAtrLen, cfg.stFactor)
  const RSI  = calcRSI(cl, cfg.rsiLen)
  const BB   = calcBB(cl, cfg.bbLen, cfg.bbStd)
  const VOL  = sma(vol, cfg.volLen)
  const ATR  = calcATR(candles, cfg.atrLen)

  // Squeeze activo cuando el ancho de BB < umbral (%)
  const SQ = BB.map(b => b.width !== null && b.width < cfg.bbSqzThreshold)

  // ── Señales ───────────────────────────────────────────────────────────────
  const longs  = []
  const shorts = []
  const sqPops = []   // inicio de squeeze (para marcar con diamante)

  const startBar = Math.max(cfg.emaTrend, cfg.bbLen, cfg.rsiLen, cfg.stAtrLen, 12)

  for (let i = startBar; i < n; i++) {
    const atrV = ATR[i]
    const rsiV = RSI[i]
    if (!atrV || rsiV === null) continue

    const c     = candles[i]
    const sess  = getSess(c.time, cfg.useSess)
    const atrOk = cfg.minAtrFilter === 0 || atrV > cfg.minAtrFilter
    const volOk = cfg.volMult <= 1.0 || (VOL[i] ? vol[i] > VOL[i] * cfg.volMult : false)
    const stBull = ST[i].bull

    // ── LONG ────────────────────────────────────────────────────────────────
    // macroL: price above EMA200 (structural bull context)
    const macroL  = cl[i] > E200[i] && (cfg.useTrendFilter ? E50[i] > E200[i] : true)
    // emaAlL: just require E9 > E21 — the full E21>E50 cascade lags the trigger crossover
    //   and would block signals on the exact crossover bar
    const emaAlL  = E9[i] > E21[i]
    const rsiL    = rsiV >= cfg.rsiBullLo && rsiV <= cfg.rsiBullHi
    const filtsL  = volOk && sess.ok && atrOk

    const bbBrkL  = BB[i].upper !== null && cl[i] > BB[i].upper && cl[i-1] <= BB[i-1].upper && SQ[i-1]
    const emaCrsL = E9[i-1] < E21[i-1] && E9[i] >= E21[i]
    const rsiCrsL = RSI[i-1] !== null && RSI[i-1] < 50 && rsiV >= 50 && macroL && stBull
    const trigL   = bbBrkL || emaCrsL || rsiCrsL

    if (macroL && emaAlL && stBull && rsiL && filtsL && trigL) {
      const trigL_ = bbBrkL ? 'BB' : emaCrsL ? 'EMA×' : 'RSI×'
      longs.push({
        time:  c.time,
        price: cl[i],
        sl:    cl[i] - atrV * cfg.slMult,
        tp:    cl[i] + atrV * cfg.tpMult,
        tp2:   cl[i] + atrV * cfg.tpMult * 1.5,
        trig:  trigL_,
        grade: bbBrkL ? 'A+' : emaCrsL ? 'A' : 'A-',
      })
    }

    // ── SHORT ───────────────────────────────────────────────────────────────
    // macroS: for assets in a structural bull (XAUUSD), use EMA50 as the short-side macro —
    //   price below EMA50 means local corrective bias; EMA200 would almost never be reached
    //   useTrendFilter=true adds the stricter price < EMA200 requirement
    const macroS  = cl[i] < E50[i] && (cfg.useTrendFilter ? cl[i] < E200[i] : true)
    // emaAlS: E9 < E21 is sufficient — same reason as emaAlL
    const emaAlS  = E9[i] < E21[i]
    const rsiS    = rsiV >= cfg.rsiBearLo && rsiV <= cfg.rsiBearHi
    const filtsS  = volOk && sess.ok && atrOk

    const bbBrkS  = BB[i].lower !== null && cl[i] < BB[i].lower && cl[i-1] >= BB[i-1].lower && SQ[i-1]
    const emaCrsS = E9[i-1] > E21[i-1] && E9[i] <= E21[i]
    const rsiCrsS = RSI[i-1] !== null && RSI[i-1] > 50 && rsiV <= 50 && macroS && !stBull
    const trigS   = bbBrkS || emaCrsS || rsiCrsS

    if (macroS && emaAlS && !stBull && rsiS && filtsS && trigS) {
      const trigS_ = bbBrkS ? 'BB' : emaCrsS ? 'EMA×' : 'RSI×'
      shorts.push({
        time:  c.time,
        price: cl[i],
        sl:    cl[i] + atrV * cfg.slMult,
        tp:    cl[i] - atrV * cfg.tpMult,
        tp2:   cl[i] - atrV * cfg.tpMult * 1.5,
        trig:  trigS_,
        grade: bbBrkS ? 'A+' : emaCrsS ? 'A' : 'A-',
      })
    }

    // Inicio de squeeze (primer tick)
    if (SQ[i] && !SQ[i - 1]) sqPops.push({ time: c.time })
  }

  // ── Series para render() ──────────────────────────────────────────────────
  const toLine = arr =>
    candles.map((c, i) => arr[i] != null ? { time: c.time, value: arr[i] } : null).filter(Boolean)

  const stBullLine = candles
    .map((c, i) => ST[i].bull && ST[i].v != null ? { time: c.time, value: ST[i].v } : null)
    .filter(Boolean)
  const stBearLine = candles
    .map((c, i) => !ST[i].bull && ST[i].v != null ? { time: c.time, value: ST[i].v } : null)
    .filter(Boolean)
  const bbUpLine = candles
    .map((c, i) => BB[i].upper != null ? { time: c.time, value: BB[i].upper } : null)
    .filter(Boolean)
  const bbLoLine = candles
    .map((c, i) => BB[i].lower != null ? { time: c.time, value: BB[i].lower } : null)
    .filter(Boolean)

  // ── Estado actual (última barra) ──────────────────────────────────────────
  const li      = n - 1
  const curSess = getSess(candles[li].time, cfg.useSess)
  const lastL   = longs.at(-1)
  const lastS   = shorts.at(-1)
  const lastSig = !lastL && !lastS ? null
    : !lastL  ? { ...lastS, isLong: false }
    : !lastS  ? { ...lastL, isLong: true  }
    : lastL.time >= lastS.time ? { ...lastL, isLong: true } : { ...lastS, isLong: false }

  const fBull = E9[li] > E21[li] && E21[li] > E50[li] && E50[li] > E200[li]
  const fBear = E9[li] < E21[li] && E21[li] < E50[li] && E50[li] < E200[li]
  const rr    = lastSig
    ? Math.abs(lastSig.tp - lastSig.price) / Math.abs(lastSig.price - lastSig.sl)
    : 0

  return {
    // Series de líneas
    ema9: toLine(E9), ema21: toLine(E21), ema50: toLine(E50), ema200: toLine(E200),
    stBullLine, stBearLine,
    bbUpLine, bbLoLine,
    // Señales
    longs, shorts, sqPops,
    // Estado del dashboard (badge)
    cur: {
      stBull:  ST[li].bull,
      ribbon:  fBull ? 'bull' : fBear ? 'bear' : 'mixed',
      rsi:     RSI[li] ?? 50,
      squeeze: SQ[li],
      volOk:   VOL[li] ? vol[li] > VOL[li] * cfg.volMult : false,
      atr:     ATR[li] ?? 0,
      session: curSess,
      lastSig,
      rr,
      price:   cl[li],
    },
  }
}

// ─── render() ─────────────────────────────────────────────────────────────────

function render(chart, candleSeries, result, cfg, api) {
  const { longs, shorts, sqPops, cur } = result
  const { colors, showEmas, showLevels } = cfg
  const bull = cur.stBull

  // EMA Ribbon — colores dinámicos según dirección del Supertrend
  if (showEmas) {
    const ribbon = [
      [result.ema9,   bull ? '#00E5FF' : '#FF6B6B', 1, 'EMA 9'  ],
      [result.ema21,  bull ? '#4ECDC4' : '#FF8E53', 1, 'EMA 21' ],
      [result.ema50,  bull ? '#45B7D1' : '#C0392B', 2, 'EMA 50' ],
      [result.ema200, '#FFD700',                     2, 'EMA 200'],
    ]
    for (const [data, color, lw, title] of ribbon) {
      const s = api.addSeries(ch => ch.addLineSeries({
        color, lineWidth: lw,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        title,
      }))
      s?.setData(data)
    }
  }

  // Supertrend — dos series (verde bull / roja bear)
  for (const [data, color, title] of [
    [result.stBullLine, '#00E676', 'ST Bull'],
    [result.stBearLine, '#FF1744', 'ST Bear'],
  ]) {
    const s = api.addSeries(ch => ch.addLineSeries({
      color, lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      title,
    }))
    s?.setData(data)
  }

  // Bollinger Bands
  for (const [data, title] of [
    [result.bbUpLine, 'BB Upper'],
    [result.bbLoLine, 'BB Lower'],
  ]) {
    const s = api.addSeries(ch => ch.addLineSeries({
      color: 'rgba(136,136,136,0.35)', lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      title,
    }))
    s?.setData(data)
  }

  // Etiquetas LONG — misma presentación que ICT (rectángulo de color + triángulo)
  for (const sig of longs) {
    api.addLabel({
      time:          sig.time,
      text:          `${sig.grade} ${sig.trig}`,
      color:         colors.long,
      isBull:        true,
      fallbackPrice: sig.price,
    })
  }

  // Etiquetas SHORT
  for (const sig of shorts) {
    api.addLabel({
      time:          sig.time,
      text:          `${sig.grade} ${sig.trig}`,
      color:         colors.short,
      isBull:        false,
      fallbackPrice: sig.price,
    })
  }

  // Diamantes de squeeze (inicio de compresión)
  for (const m of sqPops) {
    api.addMarker({
      time: m.time, position: 'bottom',
      color: colors.squeeze, shape: 'circle', size: 0,
    })
  }

  // SL / TP de la última señal activa
  if (showLevels && cur.lastSig) {
    const { sl, tp, tp2 } = cur.lastSig
    api.addPriceLine({ price: sl,  color: colors.sl, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL'  })
    api.addPriceLine({ price: tp,  color: colors.tp, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP1' })
    if (tp2 !== undefined)
      api.addPriceLine({ price: tp2, color: colors.tp, lineWidth: 1, lineStyle: 3, axisLabelVisible: true, title: 'TP2' })
  }
}

// ─── Plugin ───────────────────────────────────────────────────────────────────

export default {
  id:      'quantum_gold',
  name:    '⚡ Quantum Gold',
  version: '1.0',

  defaultConfig: {
    // EMA Ribbon
    emaFast:  9,
    emaMid:   21,
    emaSlow:  50,
    emaTrend: 200,
    showEmas: true,
    // Supertrend
    stAtrLen: 10,
    stFactor: 3.0,
    // Bollinger Bands
    bbLen:          20,
    bbStd:          2.0,
    bbSqzThreshold: 0.9,
    // RSI — zonas ampliadas para funcionar en HTF (1h/4h)
    rsiLen:    14,
    rsiBullLo: 45,
    rsiBullHi: 75,
    rsiBearLo: 25,
    rsiBearHi: 55,
    // Volumen — 1.0 = desactivado (solo requiere volumen positivo)
    volLen:  20,
    volMult: 1.0,
    // ATR / Niveles
    atrLen:     14,
    tpMult:     2.0,
    slMult:     1.0,
    showLevels: true,
    // Filtros — useTrendFilter=false: macro solo exige precio > EMA200 (sin E50 > EMA200)
    useTrendFilter: false,
    minAtrFilter:   3.0,
    useSess:        false,
    // Colores
    colors: {
      long:    '#00E676',
      short:   '#FF1744',
      squeeze: '#FFD700',
      sl:      '#FF1744',
      tp:      '#00E676',
    },
  },

  detect,
  render,
  BadgeComponent: Badge,
  PanelComponent: Panel,
}
