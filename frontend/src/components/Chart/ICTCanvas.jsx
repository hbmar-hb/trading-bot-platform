import { useEffect, useRef } from 'react'
import { DEFAULT_ICT_CONFIG } from './ICTConfigPanel'
import { hexToRgba } from './colorHelpers'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function applyDash(ctx, style) {
  if (style === 'dashed') ctx.setLineDash([6, 3])
  else if (style === 'dotted') ctx.setLineDash([2, 2])
  else ctx.setLineDash([])
}

function pill(ctx, text, x, y, color, bgAlpha = 0.4) {
  ctx.font = 'bold 8.5px ui-sans-serif,system-ui,sans-serif'
  const tw = ctx.measureText(text).width
  const pad = 3.5
  ctx.fillStyle = `rgba(15,23,42,${bgAlpha})`
  ctx.fillRect(x, y - 9, tw + pad * 2, 11)
  ctx.fillStyle = color
  ctx.fillText(text, x + pad, y)
}

function rrect(ctx, x, y, w, h, r) {
  const R = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + R, y)
  ctx.lineTo(x + w - R, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + R)
  ctx.lineTo(x + w, y + h - R)
  ctx.quadraticCurveTo(x + w, y + h, x + w - R, y + h)
  ctx.lineTo(x + R, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - R)
  ctx.lineTo(x, y + R)
  ctx.quadraticCurveTo(x, y, x + R, y)
  ctx.closePath()
}

function fmtPrice(p) {
  if (p >= 10000) return p.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  if (p >= 1000)  return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (p >= 10)    return p.toFixed(4)
  return p.toFixed(6)
}

function box(ctx, x, y, w, h, fill, stroke, strokeW = 1) {
  ctx.fillStyle = fill
  ctx.fillRect(x, y, w, h)
  if (stroke) {
    ctx.strokeStyle = stroke
    ctx.lineWidth = strokeW
    ctx.setLineDash([])
    ctx.strokeRect(x, y, w, h)
  }
}

function freshnessAlpha(baseAlpha, leftMs, maxRightMs, decayBars = 60, barMsEstimate = 300_000) {
  if (!maxRightMs || maxRightMs <= leftMs) return baseAlpha
  const barsOld = Math.max(0, (maxRightMs - leftMs) / barMsEstimate)
  return Math.max(0.12, baseAlpha * Math.exp(-barsOld / decayBars))
}

function verticalGradient(ctx, x, y1, y2, colorTop, colorBottom) {
  const g = ctx.createLinearGradient(0, y1, 0, y2)
  g.addColorStop(0, colorTop)
  g.addColorStop(1, colorBottom)
  return g
}

function drawGlowLine(ctx, x1, y, x2, color, width, glowAlpha = 0.55, blur = 8) {
  ctx.save()
  ctx.strokeStyle = 'transparent'
  ctx.lineWidth = width
  ctx.shadowColor = hexToRgba(color, glowAlpha)
  ctx.shadowBlur = blur
  ctx.shadowOffsetX = 0
  ctx.shadowOffsetY = 0
  ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke()
  ctx.restore()
}

function parseRgbaAlpha(rgba) {
  const m = rgba.match(/rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*([\d.]+)\s*)?\)/)
  return m && m[1] ? parseFloat(m[1]) : 1
}

/**
 * ICTCanvas — canvas overlay for the Smart Money Engine output.
 * Props: chartRef, seriesRef, data (SmeOutput), config (ICT config), signal, historySignals
 */
export default function ICTCanvas({ chartRef, seriesRef, data, config, signal, historySignals, chartVersion }) {
  const canvasRef = useRef(null)
  const cfg = config ?? DEFAULT_ICT_CONFIG

  useEffect(() => {
    const canvas = canvasRef.current
    const chart  = chartRef.current
    const series = seriesRef.current
    if (!canvas || !chart || !series || !data) return

    const dpr = window.devicePixelRatio || 1

    const draw = () => {
      const parent = canvas.parentElement
      if (!parent) return
      const { width: w, height: h } = parent.getBoundingClientRect()
      if (w === 0 || h === 0) return

      const needW = Math.round(w * dpr)
      const needH = Math.round(h * dpr)
      if (canvas.width !== needW || canvas.height !== needH) {
        canvas.width        = needW
        canvas.height       = needH
        canvas.style.width  = w + 'px'
        canvas.style.height = h + 'px'
      }

      const ctx = canvas.getContext('2d')
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      const toX = (ms) => chart.timeScale().timeToCoordinate(ms / 1000)
      const toY = (price) => series.priceToCoordinate(price)

      const fc = cfg.fvg ?? {}
      const oc = cfg.ob ?? {}
      const sc = cfg.structure ?? {}
      const fibc = cfg.fib ?? {}
      const mtfCfg = cfg.multiTimeframe ?? {}
      const sigCfg = cfg.signal ?? {}

      const maxRightMs = data.timestamp || 0
      const boxX = (leftMs, rightMs) => {
        const effectiveRight = (maxRightMs > leftMs) ? Math.min(rightMs, maxRightMs) : rightMs
        let lx = toX(leftMs), rx = toX(effectiveRight)
        if (lx == null && rx == null) return null
        lx = lx ?? 0; rx = rx ?? w
        if (rx < 0 || lx > w) return null
        return [Math.max(0, lx), Math.min(w, rx)]
      }

      const boxes = data.boxes ?? []
      const lines = data.lines ?? []
      const labels = data.labels ?? []

      // ── DRAW LAYER 1: Boxes (FVG / OB / IFVG / OTE) ─────────────────────────
      for (const b of boxes) {
        const y1 = toY(b.top), y2 = toY(b.bottom)
        if (y1 == null || y2 == null) continue
        const top = Math.min(y1, y2), height = Math.abs(y2 - y1)
        if (height < 1) continue
        const xs = boxX(b.left, b.right)
        if (!xs) continue
        const [x1, x2] = xs, bw = x2 - x1

        if (b.type === 'FVG') {
          if (fc.showFVG === false) continue
          const baseColor = b.direction === 'bull' ? (fc.colorBull || '#2962FF') : (fc.colorBear || '#FF6D00')
          const fillAlpha = freshnessAlpha(fc.alphaFill ?? 0.18, b.left, maxRightMs)
          box(ctx, x1, top, bw, height, hexToRgba(baseColor, fillAlpha), hexToRgba(baseColor, 0.7), 0.5)
          if (fc.showMidline !== false && b.show_midline) {
            const my = toY(b.midline)
            if (my != null) {
              ctx.strokeStyle = hexToRgba(baseColor, 0.35)
              ctx.lineWidth = 1
              ctx.setLineDash([4, 3])
              ctx.beginPath(); ctx.moveTo(x1, my); ctx.lineTo(x2, my); ctx.stroke()
              ctx.setLineDash([])
            }
          }
          if (fc.showLabel !== false && height > 10) {
            const label = b.direction === 'bull' ? 'BISI' : 'SIBI'
            pill(ctx, label, x1 + 3, top + 9, hexToRgba(baseColor, 1))
          }
        } else if (b.type === 'IFVG') {
          if (fc.showIFVG === false) continue
          const baseColor = fc.colorIFVG || '#a855f7'
          const fillAlpha = freshnessAlpha(fc.alphaFill ?? 0.18, b.left, maxRightMs)
          box(ctx, x1, top, bw, height, hexToRgba(baseColor, fillAlpha * 0.6), hexToRgba(baseColor, 0.8), 0.5)
          if (height > 10) pill(ctx, 'IFVG', x1 + 3, top + 9, hexToRgba(baseColor, 1))
        } else if (b.type === 'OB') {
          if (oc.showOB === false) continue
          const baseColor = b.direction === 'bull' ? (oc.colorBull || '#1B5E20') : (oc.colorBear || '#FF5252')
          const fillAlpha = freshnessAlpha(oc.alphaFill ?? 0.22, b.left, maxRightMs)
          box(ctx, x1, top, bw, height, hexToRgba(baseColor, fillAlpha), hexToRgba(baseColor, 0.8), 1)
          if (oc.showMidline !== false && b.show_midline) {
            const my = toY(b.midline)
            if (my != null && my >= top && my <= top + height) {
              ctx.strokeStyle = hexToRgba(baseColor, 0.35)
              ctx.lineWidth = 1
              ctx.setLineDash([5, 3])
              ctx.beginPath(); ctx.moveTo(x1, my); ctx.lineTo(x2, my); ctx.stroke()
              ctx.setLineDash([])
            }
          }
          if (oc.showLabel !== false && height > 10) {
            const tag = `${b.timeframe} OB`
            pill(ctx, tag, x1 + 3, top + 9, hexToRgba(baseColor, 1))
          }
        } else if (b.type === 'OTE') {
          if (fibc.showOTE === false) continue
          const baseColor = fibc.oteColor || '#FFD600'
          const alpha = parseRgbaAlpha(b.bg_color || hexToRgba(baseColor, 0.2))
          box(ctx, x1, top, bw, height, hexToRgba(baseColor, alpha), 'transparent', 0)
          if (height > 10) pill(ctx, 'OTE', x1 + 3, top + 9, hexToRgba(baseColor, 0.9))
        }
      }

      // ── DRAW LAYER 2: Lines (BOS / CHoCH / Internal / Fib / Strong-Weak) ────
      const showSwing = sc.showSwingStruct !== false
      const showInternal = sc.showInternalStruct !== false
      const showStrongWeak = sc.showStrongWeak !== false
      const showFib = fibc.showFib !== false

      for (const line of lines) {
        const y = toY(line.price)
        if (y == null || y < -5 || y > h + 5) continue
        const xs = boxX(line.start_time, line.end_time)
        if (!xs) continue
        const [x1, x2] = xs

        let visible = false
        let lineColor = line.color
        let isChoch = false
        if (line.type === 'BOS' || line.type === 'CHoCH') {
          visible = showSwing
          if (line.type === 'CHoCH') isChoch = true
        } else if (line.type === 'INTERNAL_BOS' || line.type === 'INTERNAL_CHoCH') {
          visible = showInternal
          if (line.type === 'INTERNAL_CHoCH') isChoch = true
        } else if (line.type === 'FIB') {
          visible = showFib
        } else if (line.type === 'STRONG' || line.type === 'WEAK') {
          visible = showStrongWeak
        }
        if (!visible) continue

        const lineW = line.line_width ?? 1
        if (isChoch) drawGlowLine(ctx, x1, y, x2, lineColor, lineW * 2, 0.5, 10)
        ctx.strokeStyle = hexToRgba(lineColor, 0.9)
        ctx.lineWidth = lineW
        applyDash(ctx, line.line_style)
        ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke()
        ctx.setLineDash([])
        if (line.show_label && line.label) {
          pill(ctx, line.label, x1 + 5, y - 2, lineColor, 0.65)
        }
      }

      // ── DRAW LAYER 3: Labels (HH / HL / LH / LL) ────────────────────────────
      if (sc.showSwingLabels !== false) {
        ctx.textAlign = 'center'
        for (const lb of labels) {
          const y = toY(lb.price), x = toX(lb.time)
          if (y == null || x == null || x < -20 || x > w + 20) continue
          const isHigh = lb.style === 'label_down'
          const color = lb.text_color || (isHigh ? sc.colorBear || '#FF5252' : sc.colorBull || '#1B5E20')
          ctx.font = 'bold 8.5px ui-sans-serif,system-ui,sans-serif'
          const tw = ctx.measureText(lb.text).width + 6
          ctx.fillStyle = hexToRgba(color, 0.85)
          ctx.beginPath()
          if (isHigh) {
            ctx.moveTo(x, y - 4)
            ctx.lineTo(x - 3, y - 9)
            ctx.lineTo(x + 3, y - 9)
          } else {
            ctx.moveTo(x, y + 4)
            ctx.lineTo(x - 3, y + 9)
            ctx.lineTo(x + 3, y + 9)
          }
          ctx.closePath(); ctx.fill()
          const oy = isHigh ? y - 22 : y + 11
          ctx.fillStyle = 'rgba(15,23,42,0.45)'
          ctx.fillRect(x - tw / 2, oy, tw, 11)
          ctx.fillStyle = color
          ctx.fillText(lb.text, x, oy + 8.5)
        }
        ctx.textAlign = 'left'
      }

      // ── DRAW LAYER 4: Active signal ─────────────────────────────────────────
      const minScore = sigCfg.minScore ?? 4
      const minRR = sigCfg.minRR ?? 1.2
      const signalRR = signal?.risk_reward_1 ?? 0
      if (
        signal &&
        signal.direction !== 'none' &&
        sigCfg.showSignal !== false &&
        signal.confluence_score >= minScore &&
        signalRR >= minRR
      ) {
        const isLong = signal.direction === 'long'
        const longColor  = sigCfg.longColor  || '#22c55e'
        const shortColor = sigCfg.shortColor || '#ef4444'
        const entryColor = sigCfg.entryColor || '#e2e8f0'
        const slColor    = sigCfg.slColor    || '#f87171'
        const tpColor    = sigCfg.tpColor    || '#4ade80'
        const gradeColor = isLong ? longColor : shortColor
        const numTPs = sigCfg.numTPs ?? 5
        const entryY = toY(signal.entry_price)
        const slY    = (sigCfg.showSL !== false) ? toY(signal.stop_loss) : null
        const tp1Y   = (sigCfg.showTP1 !== false && numTPs >= 1) ? toY(signal.take_profit_1) : null
        const tp2Y   = (sigCfg.showTP2 !== false && numTPs >= 2) ? toY(signal.take_profit_2) : null
        const tp3Y   = (sigCfg.showTP3 !== false && numTPs >= 3) ? toY(signal.take_profit_3) : null
        const tp4Y   = (sigCfg.showTP4 !== false && numTPs >= 4 && signal.take_profit_4 != null) ? toY(signal.take_profit_4) : null
        const tp5Y   = (sigCfg.showTP5 !== false && numTPs >= 5 && signal.take_profit_5 != null) ? toY(signal.take_profit_5) : null

        const signalX = signal.entry_time ? toX(signal.entry_time) : null
        const signalOnScreen = signalX == null || signalX <= w + 20
        const lineStartX = (signalOnScreen && signalX != null && signalX >= 0 && signalX < w) ? signalX : 0

        const gradientZone = (ya, yb, color, opacity) => {
          if (ya == null || yb == null) return
          const top = Math.min(ya, yb), ht = Math.abs(yb - ya)
          if (ht < 1) return
          const grad = verticalGradient(ctx, lineStartX, top, top + ht,
            hexToRgba(color, opacity),
            hexToRgba(color, 0.02))
          ctx.fillStyle = grad
          ctx.fillRect(lineStartX, top, w - lineStartX, ht)
        }
        if (signalOnScreen && entryY != null && slY != null) gradientZone(entryY, slY, slColor, 0.10)
        if (signalOnScreen && entryY != null && tp1Y != null) gradientZone(entryY, tp1Y, tpColor, 0.06)

        const signalLine = (y, color, lineW, dashArr, label, price) => {
          if (y == null || y < -15 || y > h + 15) return
          ctx.strokeStyle = hexToRgba(color, 0.9); ctx.lineWidth = lineW
          ctx.setLineDash(dashArr)
          ctx.beginPath(); ctx.moveTo(lineStartX, y); ctx.lineTo(w, y); ctx.stroke()
          ctx.setLineDash([])
          const txt = `${label}  ${fmtPrice(price)}`
          ctx.font = 'bold 9px ui-sans-serif,system-ui,sans-serif'
          const tw = ctx.measureText(txt).width, pad = 5
          const tW = tw + pad * 2, tH = 15
          const tX = w - tW - 3, tY = y - tH / 2
          ctx.fillStyle = hexToRgba(color, 0.15)
          rrect(ctx, tX, tY, tW, tH, 3); ctx.fill()
          ctx.strokeStyle = hexToRgba(color, 0.7); ctx.lineWidth = 0.8
          rrect(ctx, tX, tY, tW, tH, 3); ctx.stroke()
          ctx.fillStyle = color; ctx.textAlign = 'left'
          ctx.fillText(txt, tX + pad, tY + tH - 3.5)
        }

        if (signalOnScreen) {
          if (tp5Y != null) signalLine(tp5Y, tpColor, 1,   [3, 4], `TP5 ${(signal.risk_reward_5 ?? 0).toFixed(1)}R`, signal.take_profit_5)
          if (tp4Y != null) signalLine(tp4Y, tpColor, 1,   [3, 4], `TP4 ${(signal.risk_reward_4 ?? 0).toFixed(1)}R`, signal.take_profit_4)
          if (tp3Y != null) signalLine(tp3Y, tpColor, 1,   [5, 4], `TP3 ${(signal.risk_reward_3 ?? 0).toFixed(1)}R`, signal.take_profit_3)
          if (tp2Y != null) signalLine(tp2Y, tpColor, 1.5, [5, 4], `TP2 ${(signal.risk_reward_2 ?? 0).toFixed(1)}R`, signal.take_profit_2)
          if (tp1Y != null) signalLine(tp1Y, tpColor, 2,   [5, 4], `TP1 ${(signal.risk_reward_1 ?? 0).toFixed(1)}R`, signal.take_profit_1)
          if (slY  != null) signalLine(slY,  slColor, 2,   [],     'SL',                                              signal.stop_loss)
          signalLine(entryY, entryColor, 1.5, [], `BE / ${signal.grade}`, signal.entry_price)
        }

        const grade = signal.grade || (isLong ? 'LONG' : 'SHORT')
        if (signalOnScreen && entryY != null) {
          const SZ  = 12
          const OFF = 26
          const arrowY = isLong ? entryY + OFF : entryY - OFF
          const arrowCX = signalX ?? lineStartX + 30
          ctx.fillStyle = 'rgba(15,23,42,0.35)'
          ctx.beginPath()
          if (isLong) {
            ctx.moveTo(arrowCX, arrowY - SZ + 1)
            ctx.lineTo(arrowCX - SZ * 0.75 - 1, arrowY + SZ * 0.5 + 1)
            ctx.lineTo(arrowCX + SZ * 0.75 + 1, arrowY + SZ * 0.5 + 1)
          } else {
            ctx.moveTo(arrowCX, arrowY + SZ - 1)
            ctx.lineTo(arrowCX - SZ * 0.75 - 1, arrowY - SZ * 0.5 - 1)
            ctx.lineTo(arrowCX + SZ * 0.75 + 1, arrowY - SZ * 0.5 - 1)
          }
          ctx.closePath(); ctx.fill()
          ctx.fillStyle = gradeColor
          ctx.beginPath()
          if (isLong) {
            ctx.moveTo(arrowCX, arrowY - SZ)
            ctx.lineTo(arrowCX - SZ * 0.75, arrowY + SZ * 0.5)
            ctx.lineTo(arrowCX + SZ * 0.75, arrowY + SZ * 0.5)
          } else {
            ctx.moveTo(arrowCX, arrowY + SZ)
            ctx.lineTo(arrowCX - SZ * 0.75, arrowY - SZ * 0.5)
            ctx.lineTo(arrowCX + SZ * 0.75, arrowY - SZ * 0.5)
          }
          ctx.closePath(); ctx.fill()
          ctx.font = 'bold 10px ui-sans-serif,system-ui,sans-serif'
          const gw = ctx.measureText(grade).width + 10
          const gh = 17
          const gxRaw = arrowCX + SZ + 6
          const gx = Math.min(gxRaw, w - gw - 8)
          const gy = arrowY - gh / 2
          ctx.fillStyle   = 'rgba(15,23,42,0.45)'
          ctx.strokeStyle = hexToRgba(gradeColor, 0.5)
          ctx.lineWidth   = 1
          rrect(ctx, gx, gy, gw, gh, 3)
          ctx.fill(); ctx.stroke()
          ctx.fillStyle = gradeColor
          ctx.textAlign = 'left'
          ctx.fillText(grade, gx + 5, gy + gh - 4)
          const scoreTxt = `Confluencia: ${signal.confluence_score}/9`
          ctx.font = '7.5px ui-sans-serif,system-ui,sans-serif'
          const sW = ctx.measureText(scoreTxt).width + 6
          const sX = gx, sY = gy - 11
          ctx.fillStyle = 'rgba(15,23,42,0.4)'
          ctx.fillRect(sX, sY, sW, 9)
          ctx.fillStyle = hexToRgba(gradeColor, 0.85)
          ctx.fillText(scoreTxt, sX + 3, sY + 7.5)
        }
      }

      // ── DRAW LAYER 5: Historical signals ────────────────────────────────────
      const hSigs = historySignals?.signals ?? []
      if (sigCfg.showHistory !== false && hSigs.length > 0) {
        const histTpColor = sigCfg.tpColor    || '#4ade80'
        const histSlColor = sigCfg.slColor    || '#f87171'
        const histOpenColor = sigCfg.entryColor ? hexToRgba(sigCfg.entryColor, 0.7) : '#94a3b8'
        for (const hs of hSigs) {
          if (hs.confluence_score < minScore) continue
          const isLong = hs.direction === 'long'
          const hx = toX(hs.entry_time)
          if (hx == null || hx < -20 || hx > w + 20) continue
          const hy = toY(hs.entry_price)
          if (hy == null) continue
          const outcome = hs.outcome?.toUpperCase()
          const color = outcome === 'SL' || outcome === 'STOP' ? histSlColor
            : outcome === 'OPEN' || outcome === 'PENDING' ? histOpenColor
            : outcome?.startsWith('TP') ? histTpColor
            : '#94a3b8'
          const SZ  = 5
          const OFF = 16
          const arrowY = isLong ? hy + OFF : hy - OFF
          ctx.fillStyle = hexToRgba(color, 0.85)
          ctx.beginPath()
          if (isLong) {
            ctx.moveTo(hx,            arrowY - SZ)
            ctx.lineTo(hx - SZ * 0.7, arrowY + SZ * 0.5)
            ctx.lineTo(hx + SZ * 0.7, arrowY + SZ * 0.5)
          } else {
            ctx.moveTo(hx,            arrowY + SZ)
            ctx.lineTo(hx - SZ * 0.7, arrowY - SZ * 0.5)
            ctx.lineTo(hx + SZ * 0.7, arrowY - SZ * 0.5)
          }
          ctx.closePath(); ctx.fill()
          const badgeTxt = `${hs.grade}·${hs.outcome}`
          ctx.font = 'bold 8px ui-sans-serif,system-ui,sans-serif'
          const bw = ctx.measureText(badgeTxt).width + 7
          const bh = 13
          const bxRaw = hx + SZ + 4
          const bx = Math.min(bxRaw, w - bw - 4)
          const by = arrowY - bh / 2
          ctx.fillStyle = 'rgba(15,23,42,0.45)'
          ctx.strokeStyle = hexToRgba(color, 0.5); ctx.lineWidth = 0.8
          rrect(ctx, bx, by, bw, bh, 2); ctx.fill(); ctx.stroke()
          ctx.fillStyle = hexToRgba(color, 0.95); ctx.textAlign = 'left'
          ctx.fillText(badgeTxt, bx + 3.5, by + bh - 3.5)
        }
        const stats = historySignals?.stats
        if (stats && stats.total > 0) {
          const winPct  = Math.round((stats.win_rate ?? 0) * 100)
          const line1   = `Historial ICT: ${stats.total} señales`
          const line2   = `✓ ${stats.wins} (${winPct}%)   ✗ ${stats.losses}${stats.open > 0 ? `   ? ${stats.open}` : ''}`
          ctx.font = '9px ui-sans-serif,system-ui,sans-serif'
          const mw = Math.max(ctx.measureText(line1).width, ctx.measureText(line2).width) + 14
          const mh = 30
          const mx = 8, my = h - mh - 8
          ctx.fillStyle = 'rgba(15,23,42,0.35)'
          rrect(ctx, mx, my, mw, mh, 4); ctx.fill()
          ctx.fillStyle = 'rgba(226,232,240,0.6)'; ctx.textAlign = 'left'
          ctx.fillText(line1, mx + 7, my + 11)
          ctx.font = 'bold 9px ui-sans-serif,system-ui,sans-serif'
          ctx.fillStyle = hexToRgba(stats.win_rate >= 0.5 ? histTpColor : histSlColor, 0.85)
          ctx.fillText(line2, mx + 7, my + 23)
          ctx.textAlign = 'left'
        }
      }

      // ── HTF bias badge ──────────────────────────────────────────────────────
      const htfBias = data?.htf_bias
      if (htfBias && htfBias.direction !== 'neutral') {
        const tf = (htfBias.timeframe || 'HTF').toUpperCase()
        const biasText = `HTF ${tf} ${htfBias.direction.toUpperCase()} ${(htfBias.strength * 100).toFixed(0)}%`
        ctx.font = 'bold 10px ui-sans-serif,system-ui,sans-serif'
        const bW = ctx.measureText(biasText).width + 12
        const bH = 18
        const bX = w - bW - 8
        const bY = 30
        const biasColor = htfBias.direction === 'bull' ? '#4ade80' : '#f87171'
        ctx.fillStyle = 'rgba(15,23,42,0.45)'
        rrect(ctx, bX, bY, bW, bH, 4); ctx.fill()
        ctx.strokeStyle = hexToRgba(biasColor, 0.5); ctx.lineWidth = 0.8
        rrect(ctx, bX, bY, bW, bH, 4); ctx.stroke()
        ctx.fillStyle = biasColor; ctx.textAlign = 'left'
        ctx.fillText(biasText, bX + 6, bY + bH - 5)
        ctx.textAlign = 'left'
      }

      // ── PD position badge ───────────────────────────────────────────────────
      const pd = data?.pd_position
      if (typeof pd === 'number') {
        const pdText = `PD ${pd.toFixed(2)}`
        ctx.font = 'bold 10px ui-sans-serif,system-ui,sans-serif'
        const pdW = ctx.measureText(pdText).width + 12
        const pdH = 18
        const pdX = w - pdW - 8
        const pdY = 8
        const pdColor = pd > 0.6 ? '#f87171' : (pd < 0.4 ? '#4ade80' : '#94a3b8')
        ctx.fillStyle = 'rgba(15,23,42,0.45)'
        rrect(ctx, pdX, pdY, pdW, pdH, 4); ctx.fill()
        ctx.strokeStyle = hexToRgba(pdColor, 0.5); ctx.lineWidth = 0.8
        rrect(ctx, pdX, pdY, pdW, pdH, 4); ctx.stroke()
        ctx.fillStyle = pdColor; ctx.textAlign = 'left'
        ctx.fillText(pdText, pdX + 6, pdY + pdH - 5)
        ctx.textAlign = 'left'
      }
    }

    // Debounce redraws via requestAnimationFrame so rapid chart events
    // (scroll, zoom, kinetic scroll) stay synced without over-painting.
    let rafId = 0
    const scheduleDraw = () => {
      if (rafId) return
      rafId = requestAnimationFrame(() => {
        rafId = 0
        draw()
      })
    }

    const timeScale = chart.timeScale()
    timeScale.subscribeVisibleLogicalRangeChange(scheduleDraw)
    timeScale.subscribeVisibleTimeRangeChange(scheduleDraw)
    timeScale.subscribeSizeChange(scheduleDraw)
    chart.subscribeCrosshairMove(scheduleDraw)

    let ptrDown = false
    const onPtrDown = () => { ptrDown = true }
    const onPtrMove = () => { if (ptrDown) scheduleDraw() }
    const onPtrUp   = () => { ptrDown = false; scheduleDraw() }
    canvas.addEventListener('pointerdown', onPtrDown)
    canvas.addEventListener('pointermove', onPtrMove)
    canvas.addEventListener('pointerup',   onPtrUp)
    canvas.addEventListener('pointerleave', onPtrUp)

    const ro = new ResizeObserver(scheduleDraw)
    if (canvas.parentElement) ro.observe(canvas.parentElement)

    draw()

    return () => {
      if (rafId) cancelAnimationFrame(rafId)
      timeScale.unsubscribeVisibleLogicalRangeChange(scheduleDraw)
      timeScale.unsubscribeVisibleTimeRangeChange(scheduleDraw)
      timeScale.unsubscribeSizeChange(scheduleDraw)
      chart.unsubscribeCrosshairMove(scheduleDraw)
      canvas.removeEventListener('pointerdown', onPtrDown)
      canvas.removeEventListener('pointermove', onPtrMove)
      canvas.removeEventListener('pointerup',   onPtrUp)
      canvas.removeEventListener('pointerleave', onPtrUp)
      ro.disconnect()
      const c = canvasRef.current
      if (c) c.getContext('2d').clearRect(0, 0, c.width, c.height)
    }
  }, [data, config, signal, historySignals, chartRef, seriesRef, chartVersion])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none"
      style={{ zIndex: 5 }}
    />
  )
}
