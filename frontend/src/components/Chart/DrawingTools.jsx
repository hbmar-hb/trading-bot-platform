import { useEffect, useRef, useState, useCallback } from 'react'
import { Undo2, Trash2 } from 'lucide-react'

// ── Fibonacci levels ──────────────────────────────────────────────────────────
const FIB_LEVELS = [
  { r: 0,     label: '0',       color: '#94a3b8' },
  { r: 0.236, label: '23.6%',  color: '#f97316' },
  { r: 0.382, label: '38.2%',  color: '#eab308' },
  { r: 0.5,   label: '50%',    color: '#94a3b8' },
  { r: 0.618, label: '61.8%',  color: '#22c55e' },
  { r: 0.786, label: '78.6%',  color: '#3b82f6' },
  { r: 1,     label: '100%',   color: '#94a3b8' },
  { r: 1.272, label: '127.2%', color: '#8b5cf6' },
  { r: 1.618, label: '161.8%', color: '#ec4899' },
]

// ── Tool color defaults ────────────────────────────────────────────────────────
const TOOL_COLORS = {
  cursor:    '#94a3b8',
  trendline: '#f59e0b',
  hline:     '#3b82f6',
  vline:     '#3b82f6',
  hray:      '#3b82f6',
  vray:      '#3b82f6',
  rect:      '#8b5cf6',
  circle:    '#8b5cf6',
  pencil:    '#f59e0b',
  arrow:     '#22c55e',
  fibonacci: '#22c55e',
  long:      '#22c55e',
  short:     '#ef4444',
  ruler_h:   '#94a3b8',
  ruler_v:   '#94a3b8',
}

// Tools that complete after a single click (no drag needed)
const ONE_CLICK_TOOLS = new Set(['hline', 'vline'])

// ── Toolbar definition ────────────────────────────────────────────────────────
const TOOLS = [
  { id: 'cursor',    label: 'Cursor',          svg: '↖',  group: 'cursor'   },
  { id: 'trendline', label: 'Tendencia',        svg: '╱',  group: 'lines'    },
  { id: 'hline',     label: 'Línea horizontal', svg: '—',  group: 'lines'    },
  { id: 'vline',     label: 'Línea vertical',   svg: '│',  group: 'lines'    },
  { id: 'hray',      label: 'Rayo horizontal',  svg: '→',  group: 'lines'    },
  { id: 'vray',      label: 'Rayo vertical',    svg: '↓',  group: 'lines'    },
  { id: 'rect',      label: 'Rectángulo',       svg: '□',  group: 'shapes'   },
  { id: 'circle',    label: 'Círculo/Elipse',   svg: '○',  group: 'shapes'   },
  { id: 'pencil',    label: 'Lápiz',            svg: '✏',  group: 'shapes'   },
  { id: 'arrow',     label: 'Flecha',           svg: '↗',  group: 'shapes'   },
  { id: 'fibonacci', label: 'Fibonacci',        svg: 'Φ',  group: 'special'  },
  { id: 'long',      label: 'Posición larga',   svg: '▲',  group: 'position' },
  { id: 'short',     label: 'Posición corta',   svg: '▼',  group: 'position' },
  { id: 'ruler_h',   label: 'Regla %/días',     svg: '↔',  group: 'rulers'   },
  { id: 'ruler_v',   label: 'Regla vertical',   svg: '↕',  group: 'rulers'   },
]

const GROUPS = ['cursor', 'lines', 'shapes', 'special', 'position', 'rulers']

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(p) {
  if (p == null) return ''
  const n = Number(p)
  if (n >= 1000) return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n.toFixed(4)
}

function arrowHead(ctx, x1, y1, x2, y2, size = 10) {
  const a = Math.atan2(y2 - y1, x2 - x1)
  ctx.beginPath()
  ctx.moveTo(x2, y2)
  ctx.lineTo(x2 - size * Math.cos(a - Math.PI / 6), y2 - size * Math.sin(a - Math.PI / 6))
  ctx.lineTo(x2 - size * Math.cos(a + Math.PI / 6), y2 - size * Math.sin(a + Math.PI / 6))
  ctx.closePath()
  ctx.fillStyle = ctx.strokeStyle
  ctx.fill()
}

// ── Core render function ──────────────────────────────────────────────────────
function renderDrawing(ctx, d, toXY, W, H, isDark) {
  const { type, points, style } = d
  if (!points?.length) return

  const col = style?.color ?? '#f59e0b'
  const bgLabel = isDark ? 'rgba(15,23,42,0.85)' : 'rgba(241,245,249,0.9)'

  ctx.save()
  ctx.strokeStyle = col
  ctx.lineWidth   = style?.lineWidth ?? 1.5
  ctx.globalAlpha = 0.92
  ctx.lineCap     = 'round'
  ctx.lineJoin    = 'round'

  switch (type) {

    // ── Trend line (extended across full canvas) ──────────────────────────────
    case 'trendline': {
      if (points.length < 2) break
      const p1 = toXY(points[0].time, points[0].price)
      const p2 = toXY(points[1].time, points[1].price)
      if (p1.x == null || p2.x == null) break
      const dx = p2.x - p1.x
      if (Math.abs(dx) < 0.5) {
        ctx.beginPath(); ctx.moveTo(p1.x, 0); ctx.lineTo(p1.x, H); ctx.stroke()
      } else {
        const slope = (p2.y - p1.y) / dx
        ctx.beginPath()
        ctx.moveTo(0, p1.y - slope * p1.x)
        ctx.lineTo(W, p1.y + slope * (W - p1.x))
        ctx.stroke()
      }
      ctx.fillStyle = col
      ctx.beginPath(); ctx.arc(p1.x, p1.y, 3, 0, Math.PI * 2); ctx.fill()
      ctx.beginPath(); ctx.arc(p2.x, p2.y, 3, 0, Math.PI * 2); ctx.fill()
      break
    }

    // ── Horizontal line (full width) ──────────────────────────────────────────
    case 'hline': {
      const py = toXY(null, points[0].price)
      if (py.y == null) break
      ctx.beginPath(); ctx.moveTo(0, py.y); ctx.lineTo(W, py.y); ctx.stroke()
      const label = fmt(points[0].price)
      ctx.font = '10px monospace'
      const tw = ctx.measureText(label).width
      ctx.fillStyle = bgLabel; ctx.fillRect(W - tw - 14, py.y - 10, tw + 10, 14)
      ctx.fillStyle = col; ctx.fillText(label, W - tw - 9, py.y + 1)
      break
    }

    // ── Vertical line (full height, dashed) ───────────────────────────────────
    case 'vline': {
      const px = toXY(points[0].time, null)
      if (px.x == null) break
      ctx.setLineDash([6, 4])
      ctx.beginPath(); ctx.moveTo(px.x, 0); ctx.lineTo(px.x, H); ctx.stroke()
      ctx.setLineDash([])
      break
    }

    // ── Horizontal ray (extends right or left) ────────────────────────────────
    case 'hray': {
      const p1 = toXY(points[0].time, points[0].price)
      if (p1.x == null) break
      const goRight = points.length < 2 || points[1].time >= points[0].time
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(goRight ? W : 0, p1.y); ctx.stroke()
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(p1.x, p1.y, 3, 0, Math.PI * 2); ctx.fill()
      break
    }

    // ── Vertical ray (extends down or up) ─────────────────────────────────────
    case 'vray': {
      const p1 = toXY(points[0].time, points[0].price)
      if (p1.x == null) break
      const goDown = points.length < 2 || points[1].price <= points[0].price
      ctx.setLineDash([6, 4])
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p1.x, goDown ? H : 0); ctx.stroke()
      ctx.setLineDash([])
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(p1.x, p1.y, 3, 0, Math.PI * 2); ctx.fill()
      break
    }

    // ── Rectangle ─────────────────────────────────────────────────────────────
    case 'rect': {
      if (points.length < 2) break
      const p1 = toXY(points[0].time, points[0].price)
      const p2 = toXY(points[1].time, points[1].price)
      if (p1.x == null || p2.x == null) break
      const x = Math.min(p1.x, p2.x), y = Math.min(p1.y, p2.y)
      const w = Math.abs(p2.x - p1.x), h = Math.abs(p2.y - p1.y)
      ctx.fillStyle = col + '22'; ctx.fillRect(x, y, w, h)
      ctx.strokeRect(x, y, w, h)
      break
    }

    // ── Circle / Ellipse ──────────────────────────────────────────────────────
    case 'circle': {
      if (points.length < 2) break
      const p1 = toXY(points[0].time, points[0].price)
      const p2 = toXY(points[1].time, points[1].price)
      if (p1.x == null || p2.x == null) break
      const cx = (p1.x + p2.x) / 2, cy = (p1.y + p2.y) / 2
      const rx = Math.abs(p2.x - p1.x) / 2, ry = Math.abs(p2.y - p1.y) / 2
      ctx.beginPath()
      ctx.ellipse(cx, cy, Math.max(rx, 1), Math.max(ry, 1), 0, 0, Math.PI * 2)
      ctx.fillStyle = col + '22'; ctx.fill(); ctx.stroke()
      break
    }

    // ── Freehand pencil ───────────────────────────────────────────────────────
    case 'pencil': {
      if (points.length < 2) break
      ctx.beginPath()
      let started = false
      for (const pt of points) {
        const p = toXY(pt.time, pt.price)
        if (p.x == null) { started = false; continue }
        if (!started) { ctx.moveTo(p.x, p.y); started = true } else ctx.lineTo(p.x, p.y)
      }
      ctx.stroke()
      break
    }

    // ── Arrow ─────────────────────────────────────────────────────────────────
    case 'arrow': {
      if (points.length < 2) break
      const p1 = toXY(points[0].time, points[0].price)
      const p2 = toXY(points[1].time, points[1].price)
      if (p1.x == null || p2.x == null) break
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke()
      arrowHead(ctx, p1.x, p1.y, p2.x, p2.y)
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(p1.x, p1.y, 3, 0, Math.PI * 2); ctx.fill()
      break
    }

    // ── Fibonacci retracement ─────────────────────────────────────────────────
    case 'fibonacci': {
      if (points.length < 2) break
      const p1 = toXY(points[0].time, points[0].price)
      const p2 = toXY(points[1].time, points[1].price)
      if (p1.x == null || p2.x == null) break
      const xStart = Math.min(p1.x, p2.x)
      const xEnd   = W - 118
      const priceH = Math.max(points[0].price, points[1].price)
      const priceL = Math.min(points[0].price, points[1].price)
      const range  = priceH - priceL

      // Vertical connector
      ctx.globalAlpha = 0.35; ctx.strokeStyle = '#94a3b8'; ctx.setLineDash([2, 3])
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p1.x, p2.y); ctx.stroke()
      ctx.setLineDash([]); ctx.globalAlpha = 0.9

      for (const { r, label, color } of FIB_LEVELS) {
        const fibPrice = priceH - range * r
        const py = toXY(null, fibPrice)
        if (py.y == null) continue

        // Shaded band for golden zone
        if (r === 0.618) {
          const pyPrev = toXY(null, priceH - range * 0.5)
          if (pyPrev.y != null) {
            ctx.fillStyle = color + '18'
            ctx.fillRect(xStart, Math.min(py.y, pyPrev.y), xEnd - xStart, Math.abs(py.y - pyPrev.y))
          }
        }

        ctx.strokeStyle = color
        ctx.lineWidth   = (r === 0 || r === 1) ? 1.8 : 1
        ctx.setLineDash(r === 0.5 ? [5, 4] : [])
        ctx.beginPath(); ctx.moveTo(xStart, py.y); ctx.lineTo(xEnd, py.y); ctx.stroke()
        ctx.setLineDash([])
        ctx.font = 'bold 10px monospace'
        ctx.fillStyle = color
        ctx.fillText(`${label}  ${fmt(fibPrice)}`, xEnd + 4, py.y + 4)
      }

      ctx.lineWidth = 1.5
      ctx.fillStyle = '#94a3b8'
      ctx.beginPath(); ctx.arc(p1.x, p1.y, 4, 0, Math.PI * 2); ctx.fill()
      ctx.beginPath(); ctx.arc(p2.x, p2.y, 4, 0, Math.PI * 2); ctx.fill()
      break
    }

    // ── Long / Short position ─────────────────────────────────────────────────
    case 'long':
    case 'short': {
      if (points.length < 2) break
      const isLong = type === 'long'
      const entry  = points[0].price
      const tp     = points[1].price
      const dist   = Math.abs(tp - entry)
      const sl     = isLong ? entry - dist : entry + dist

      const pE  = toXY(points[0].time, entry)
      const pTP = toXY(null, tp)
      const pSL = toXY(null, sl)
      if (pE.x == null || pE.y == null) break

      const xS = pE.x, xE = W - 92

      // TP zone
      if (pTP.y != null) {
        ctx.fillStyle = (isLong ? '#22c55e' : '#ef4444') + '2a'
        ctx.fillRect(xS, Math.min(pE.y, pTP.y), xE - xS, Math.abs(pTP.y - pE.y))
        ctx.strokeStyle = isLong ? '#22c55e' : '#ef4444'; ctx.lineWidth = 1.5; ctx.setLineDash([])
        ctx.beginPath(); ctx.moveTo(xS, pTP.y); ctx.lineTo(xE, pTP.y); ctx.stroke()
        ctx.font = 'bold 10px sans-serif'; ctx.fillStyle = isLong ? '#22c55e' : '#ef4444'
        ctx.fillText(`TP  ${fmt(tp)}`, xE + 4, pTP.y + 4)
      }

      // SL zone
      if (pSL.y != null) {
        ctx.fillStyle = (!isLong ? '#22c55e' : '#ef4444') + '2a'
        ctx.fillRect(xS, Math.min(pE.y, pSL.y), xE - xS, Math.abs(pSL.y - pE.y))
        ctx.strokeStyle = !isLong ? '#22c55e' : '#ef4444'; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4])
        ctx.beginPath(); ctx.moveTo(xS, pSL.y); ctx.lineTo(xE, pSL.y); ctx.stroke()
        ctx.setLineDash([])
        ctx.font = 'bold 10px sans-serif'; ctx.fillStyle = !isLong ? '#22c55e' : '#ef4444'
        ctx.fillText(`SL  ${fmt(sl)}`, xE + 4, pSL.y + 4)
      }

      // Entry line
      ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 2; ctx.setLineDash([])
      ctx.beginPath(); ctx.moveTo(xS, pE.y); ctx.lineTo(xE, pE.y); ctx.stroke()
      ctx.font = 'bold 10px sans-serif'; ctx.fillStyle = '#f59e0b'
      ctx.fillText(`Entry  ${fmt(entry)}`, xE + 4, pE.y + 4)

      // Label + R/R
      if (pTP.y != null && dist > 0) {
        const pct = ((dist / entry) * 100).toFixed(2)
        ctx.font = 'bold 12px sans-serif'
        ctx.fillStyle = isLong ? '#22c55e' : '#ef4444'
        ctx.fillText(isLong ? '▲ LONG' : '▼ SHORT', xS + 6, pE.y - 8)
        ctx.font = '10px sans-serif'; ctx.fillStyle = isDark ? '#94a3b8' : '#64748b'
        ctx.fillText(`R/R 1:1  ±${pct}%`, xS + 6, (pE.y + pTP.y) / 2)
      }
      break
    }

    // ── Horizontal ruler (% change + days) ───────────────────────────────────
    case 'ruler_h': {
      if (points.length < 2) break
      const p1 = toXY(points[0].time, points[0].price)
      const p2 = toXY(points[1].time, points[1].price)
      if (p1.x == null || p2.x == null) break
      const diff = points[1].price - points[0].price
      const pct  = ((diff / points[0].price) * 100).toFixed(2)
      const days = Math.round(Math.abs(points[1].time - points[0].time) / 86400)
      const up   = diff >= 0
      const rcol = up ? '#22c55e' : '#ef4444'

      ctx.strokeStyle = rcol; ctx.lineWidth = 2; ctx.setLineDash([])
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p1.y); ctx.stroke()
      for (const px of [p1.x, p2.x]) {
        ctx.beginPath(); ctx.moveTo(px, p1.y - 6); ctx.lineTo(px, p1.y + 6); ctx.stroke()
      }

      // Dashed drops to second price level
      ctx.globalAlpha = 0.4; ctx.setLineDash([3, 3])
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p1.x, p2.y); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(p2.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke()
      ctx.fillStyle = rcol
      ctx.beginPath(); ctx.arc(p1.x, p2.y, 3, 0, Math.PI * 2); ctx.fill()
      ctx.beginPath(); ctx.arc(p2.x, p2.y, 3, 0, Math.PI * 2); ctx.fill()
      ctx.globalAlpha = 0.92; ctx.setLineDash([])

      const label = `${up ? '+' : ''}${pct}%  ${days}d`
      ctx.font = 'bold 11px sans-serif'
      const tw   = ctx.measureText(label).width
      const midX = (p1.x + p2.x) / 2
      ctx.fillStyle = bgLabel
      if (ctx.roundRect) {
        ctx.beginPath(); ctx.roundRect(midX - tw / 2 - 7, p1.y - 20, tw + 14, 16, 4); ctx.fill()
      } else {
        ctx.fillRect(midX - tw / 2 - 7, p1.y - 20, tw + 14, 16)
      }
      ctx.fillStyle = rcol; ctx.fillText(label, midX - tw / 2, p1.y - 8)
      break
    }

    // ── Vertical ruler (% price range) ────────────────────────────────────────
    case 'ruler_v': {
      if (points.length < 2) break
      const p1 = toXY(points[0].time, points[0].price)
      const p2 = toXY(points[1].time, points[1].price)
      if (p1.x == null || p2.x == null) break
      const diff = Math.abs(points[1].price - points[0].price)
      const pct  = ((diff / Math.min(points[0].price, points[1].price)) * 100).toFixed(2)

      ctx.strokeStyle = '#94a3b8'; ctx.lineWidth = 2; ctx.setLineDash([])
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p1.x, p2.y); ctx.stroke()
      for (const py of [p1.y, p2.y]) {
        ctx.beginPath(); ctx.moveTo(p1.x - 6, py); ctx.lineTo(p1.x + 6, py); ctx.stroke()
      }

      const label = `${pct}%`
      ctx.font = 'bold 10px sans-serif'
      const tw   = ctx.measureText(label).width
      const midY = (p1.y + p2.y) / 2
      ctx.fillStyle = bgLabel; ctx.fillRect(p1.x + 9, midY - 8, tw + 8, 14)
      ctx.fillStyle = '#94a3b8'; ctx.fillText(label, p1.x + 13, midY + 3)
      break
    }
  }

  ctx.restore()
}

// ── Main component ────────────────────────────────────────────────────────────
export default function DrawingTools({ chartRef, candleSeriesRef, isDark, symbol, chartVersion }) {
  const canvasRef         = useRef(null)
  const drawingsRef       = useRef([])
  const inProgressRef     = useRef(null)
  const activeToolRef     = useRef('cursor')
  const rafRef            = useRef(null)
  const subscribedChart   = useRef(null)

  const [activeTool, setActiveTool] = useState('cursor')
  const [, forceUpdate]             = useState(0)   // triggers re-render for toolbar badge

  const storageKey = `chart_drawings_${symbol ?? 'default'}`

  // ── Persist / load ───────────────────────────────────────────────────────────
  const save = useCallback((ds) => {
    drawingsRef.current = ds
    forceUpdate(n => n + 1)
    try { localStorage.setItem(storageKey, JSON.stringify(ds)) } catch {}
  }, [storageKey])

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '[]')
      drawingsRef.current = saved
    } catch { drawingsRef.current = [] }
  }, [storageKey])

  // ── Render ────────────────────────────────────────────────────────────────────
  const render = useCallback(() => {
    const canvas = canvasRef.current
    const chart  = chartRef.current
    const series = candleSeriesRef.current
    if (!canvas || !chart || !series) return
    const dpr = window.devicePixelRatio || 1
    const ctx = canvas.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, canvas.offsetWidth, canvas.offsetHeight)
    const toXY = (time, price) => ({
      x: time  != null ? chart.timeScale().timeToCoordinate(time)  : null,
      y: price != null ? series.priceToCoordinate(price) : null,
    })
    const all = [...drawingsRef.current, ...(inProgressRef.current ? [inProgressRef.current] : [])]
    for (const d of all) renderDrawing(ctx, d, toXY, canvas.offsetWidth, canvas.offsetHeight, isDark)
  }, [chartRef, candleSeriesRef, isDark])

  const scheduleRender = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(render)
  }, [render])

  // ── Subscribe to chart scroll/zoom whenever chart instance changes ────────────
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (subscribedChart.current && subscribedChart.current !== chart) {
      try { subscribedChart.current.timeScale().unsubscribeVisibleLogicalRangeChange(scheduleRender) } catch {}
    }
    if (subscribedChart.current !== chart) {
      chart.timeScale().subscribeVisibleLogicalRangeChange(scheduleRender)
      subscribedChart.current = chart
    }
    scheduleRender()
    return () => {
      if (chart) {
        try { chart.timeScale().unsubscribeVisibleLogicalRangeChange(scheduleRender) } catch {}
        subscribedChart.current = null
      }
    }
  }, [chartVersion, scheduleRender]) // chartVersion bumps when chart is recreated

  // ── Also redraw when the price scale (Y axis) is dragged ─────────────────────
  // LWC does not expose a price-scale-change event, so we piggyback on mousemove.
  // scheduleRender is debounced via rAF so this stays at ≤60fps.
  useEffect(() => {
    const onMove = () => scheduleRender()
    window.addEventListener('mousemove', onMove, { passive: true })
    return () => window.removeEventListener('mousemove', onMove)
  }, [scheduleRender])

  // ── Canvas resize (Retina-aware) ──────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ro = new ResizeObserver(() => {
      const dpr = window.devicePixelRatio || 1
      const w = canvas.offsetWidth
      const h = canvas.offsetHeight
      canvas.width        = Math.round(w * dpr)
      canvas.height       = Math.round(h * dpr)
      canvas.style.width  = w + 'px'
      canvas.style.height = h + 'px'
      scheduleRender()
    })
    ro.observe(canvas)
    return () => ro.disconnect()
  }, [scheduleRender])

  // ── Sync active tool to ref ────────────────────────────────────────────────────
  useEffect(() => { activeToolRef.current = activeTool }, [activeTool])

  // ── Coordinate helpers ────────────────────────────────────────────────────────
  const toChartCoords = useCallback((e) => {
    const canvas = canvasRef.current
    const chart  = chartRef.current
    const series = candleSeriesRef.current
    if (!canvas || !chart || !series) return null
    const rect = canvas.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    return {
      time:  chart.timeScale().coordinateToTime(x),
      price: series.coordinateToPrice(y),
    }
  }, [chartRef, candleSeriesRef])

  // ── Mouse handlers ────────────────────────────────────────────────────────────
  const handleMouseDown = useCallback((e) => {
    const tool = activeToolRef.current
    if (tool === 'cursor') return
    e.preventDefault()
    const coords = toChartCoords(e)
    if (!coords || coords.time == null || coords.price == null) return
    inProgressRef.current = {
      id:     String(Date.now()),
      type:   tool,
      points: [{ time: coords.time, price: coords.price }],
      style:  { color: TOOL_COLORS[tool] ?? '#f59e0b', lineWidth: 1.5 },
      complete: false,
    }
    scheduleRender()
  }, [toChartCoords, scheduleRender])

  const handleMouseMove = useCallback((e) => {
    const d = inProgressRef.current
    if (!d) return
    const coords = toChartCoords(e)
    if (!coords || coords.time == null || coords.price == null) return
    if (d.type === 'pencil') {
      inProgressRef.current = { ...d, points: [...d.points, { time: coords.time, price: coords.price }] }
    } else {
      inProgressRef.current = { ...d, points: [d.points[0], { time: coords.time, price: coords.price }] }
    }
    scheduleRender()
  }, [toChartCoords, scheduleRender])

  const handleMouseUp = useCallback(() => {
    const d = inProgressRef.current
    if (!d) return
    inProgressRef.current = null

    // One-click tools complete immediately; two-point tools need a second point
    if (!ONE_CLICK_TOOLS.has(d.type) && d.points.length < 2) {
      scheduleRender(); return
    }

    save([...drawingsRef.current, { ...d, complete: true }])
    scheduleRender()
  }, [save, scheduleRender])

  // ── Keyboard shortcuts ─────────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') {
        setActiveTool('cursor')
        inProgressRef.current = null
        scheduleRender()
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        save(drawingsRef.current.slice(0, -1))
        scheduleRender()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [save, scheduleRender])

  const undo     = () => { save(drawingsRef.current.slice(0, -1)); scheduleRender() }
  const clearAll = () => { save([]); scheduleRender() }

  const isActive = activeTool !== 'cursor'

  // ── Toolbar ───────────────────────────────────────────────────────────────────
  const groups = GROUPS.map(g => TOOLS.filter(t => t.group === g))

  return (
    <>
      {/* Top horizontal toolbar */}
      <div className="absolute left-0 right-0 top-0 z-20 pointer-events-none">
        <div
          className="flex flex-row items-center bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm border-b border-slate-200 dark:border-gray-700 shadow-sm pointer-events-auto w-full h-10 px-1 overflow-x-auto"
          style={{ scrollbarWidth: 'none' }}
        >
          {groups.map((groupTools, gi) => (
            <div key={gi} className="flex flex-row items-center shrink-0">
              {gi > 0 && <div className="self-stretch flex items-center mx-0.5"><div className="w-px h-5 bg-slate-100 dark:bg-gray-700/60" /></div>}
              {groupTools.map(tool => (
                <button
                  key={tool.id}
                  title={`${tool.label}${tool.id !== 'cursor' ? ' (Esc para salir)' : ''}`}
                  onClick={() => setActiveTool(prev => (prev === tool.id && tool.id !== 'cursor') ? 'cursor' : tool.id)}
                  className={`flex items-center justify-center w-8 h-8 mx-0.5 rounded-lg text-sm font-bold transition-all select-none ${
                    activeTool === tool.id
                      ? 'bg-blue-600 text-white shadow-sm'
                      : tool.id === 'long'
                      ? 'text-green-500 hover:bg-green-50 dark:hover:bg-green-900/20'
                      : tool.id === 'short'
                      ? 'text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20'
                      : 'text-slate-600 dark:text-gray-400 hover:bg-slate-100 dark:hover:bg-gray-700'
                  }`}
                >
                  {tool.svg}
                </button>
              ))}
            </div>
          ))}

          {/* Undo / Clear all */}
          <div className="self-stretch flex items-center mx-0.5 shrink-0"><div className="w-px h-5 bg-slate-100 dark:bg-gray-700/60" /></div>
          <button
            onClick={undo}
            title="Deshacer último (Ctrl+Z)"
            className="flex items-center justify-center w-8 h-8 mx-0.5 rounded-lg text-slate-500 dark:text-gray-400 hover:bg-slate-100 dark:hover:bg-gray-700 transition-colors shrink-0"
          >
            <Undo2 size={13} />
          </button>
          <button
            onClick={clearAll}
            title="Borrar todos los dibujos"
            className="flex items-center justify-center w-8 h-8 mx-0.5 rounded-lg text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors shrink-0"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Canvas overlay (intercepts events only when a drawing tool is active) */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        style={{
          pointerEvents: isActive ? 'all' : 'none',
          cursor:        isActive ? 'crosshair' : 'default',
          zIndex: 5,
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      />
    </>
  )
}
