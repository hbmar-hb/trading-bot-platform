import { useEffect, useRef } from 'react'

function hexToRgba(hex, alpha) {
  if (!hex || !hex.startsWith('#')) return `rgba(128,128,128,${alpha})`
  const h = hex.slice(1)
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

export default function SBTCanvas({ chartRef, seriesRef, result, config, chartVersion }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const chart  = chartRef.current
    const series = seriesRef.current
    if (!canvas || !chart || !series || !result) return

    const dpr = window.devicePixelRatio || 1

    const draw = () => {
      const parent = canvas.parentElement
      if (!parent) return
      const { width: w, height: h } = parent.getBoundingClientRect()
      if (!w || !h) return

      const needW = Math.round(w * dpr)
      const needH = Math.round(h * dpr)
      if (canvas.width !== needW || canvas.height !== needH) {
        canvas.width        = needW
        canvas.height       = needH
        canvas.style.width  = `${w}px`
        canvas.style.height = `${h}px`
      }

      const ctx = canvas.getContext('2d')
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      const timeToX  = t => chart.timeScale().timeToCoordinate(t)
      const priceToY = p => series.priceToCoordinate(p)

      const cfg = config ?? {}
      const {
        showBoxes  = true,
        showCenter = true,
        colors     = {},
      } = cfg

      const bull = colors.bull ?? '#00E676'
      const bear = colors.bear ?? '#FF5252'

      if (!showBoxes) return

      const { pendingBoxes = [] } = result

      for (const box of pendingBoxes) {
        const x1 = timeToX(box.startTime)
        const x2 = timeToX(box.endTime)
        const y1 = priceToY(box.top)
        const y2 = priceToY(box.bottom)

        if (x1 == null || x2 == null || y1 == null || y2 == null) continue

        const bx = Math.min(x1, x2)
        const bw = Math.abs(x2 - x1)
        const by = Math.min(y1, y2)
        const bh = Math.abs(y2 - y1)

        if (bw < 1 || bh < 1) continue

        // Main range box
        ctx.fillStyle   = 'rgba(255,255,255,0.04)'
        ctx.fillRect(bx, by, bw, bh)
        ctx.strokeStyle = 'rgba(150,150,150,0.35)'
        ctx.lineWidth   = 1
        ctx.setLineDash([])
        ctx.strokeRect(bx, by, bw, bh)

        // Resistance zone (top half-ATR, red)
        if (box.atr > 0) {
          const rZoneBottom = priceToY(box.top - box.atr * 0.5)
          if (rZoneBottom != null) {
            const ry = Math.min(y1, rZoneBottom)
            const rh = Math.abs(rZoneBottom - y1)
            ctx.fillStyle = hexToRgba(bear, 0.12)
            ctx.fillRect(bx, ry, bw, rh)
          }

          // Support zone (bottom half-ATR, green)
          const sZoneTop = priceToY(box.bottom + box.atr * 0.5)
          if (sZoneTop != null) {
            const sy = Math.min(sZoneTop, y2)
            const sh = Math.abs(y2 - sZoneTop)
            ctx.fillStyle = hexToRgba(bull, 0.12)
            ctx.fillRect(bx, sy, bw, sh)
          }
        }

        // Center dashed line
        if (showCenter) {
          const midY = (y1 + y2) / 2
          ctx.strokeStyle = 'rgba(150,150,150,0.45)'
          ctx.lineWidth   = 1
          ctx.setLineDash([4, 3])
          ctx.beginPath()
          ctx.moveTo(bx, midY)
          ctx.lineTo(bx + bw, midY)
          ctx.stroke()
          ctx.setLineDash([])
        }
      }
    }

    let rafId = 0
    const scheduleDraw = () => {
      if (rafId) return
      rafId = requestAnimationFrame(() => { rafId = 0; draw() })
    }

    const timeScale = chart.timeScale()
    timeScale.subscribeVisibleLogicalRangeChange(scheduleDraw)
    timeScale.subscribeVisibleTimeRangeChange(scheduleDraw)
    timeScale.subscribeSizeChange(scheduleDraw)
    chart.subscribeCrosshairMove(scheduleDraw)

    const ro = new ResizeObserver(scheduleDraw)
    if (canvas.parentElement) ro.observe(canvas.parentElement)

    draw()

    return () => {
      if (rafId) cancelAnimationFrame(rafId)
      timeScale.unsubscribeVisibleLogicalRangeChange(scheduleDraw)
      timeScale.unsubscribeVisibleTimeRangeChange(scheduleDraw)
      timeScale.unsubscribeSizeChange(scheduleDraw)
      chart.unsubscribeCrosshairMove(scheduleDraw)
      ro.disconnect()
      const c = canvasRef.current
      if (c) c.getContext('2d').clearRect(0, 0, c.width, c.height)
    }
  }, [result, config, chartRef, seriesRef, chartVersion])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none"
      style={{ zIndex: 5 }}
    />
  )
}
