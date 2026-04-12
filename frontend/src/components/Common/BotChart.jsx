import { useEffect, useRef, useCallback } from 'react'
import { createChart, LineStyle, CrosshairMode } from 'lightweight-charts'

/**
 * BotChart — Candlestick chart with entry/SL/TP price lines.
 *
 * Props:
 *   candles   — array of { time, open, high, low, close, volume }
 *   position  — open Position object or null
 *   height    — chart height in px (default 380)
 */
export default function BotChart({ candles = [], position = null, height = 380 }) {
  const containerRef = useRef(null)
  const chartRef     = useRef(null)
  const seriesRef    = useRef(null)

  // Build price lines from position
  const buildPriceLines = useCallback((series, pos) => {
    if (!pos) return

    const isLong = pos.side === 'long'

    // Entry
    series.createPriceLine({
      price:     pos.entry_price,
      color:     '#3b82f6',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: `Entrada ${isLong ? '▲' : '▼'}`,
    })

    // Stop Loss
    if (pos.current_sl_price) {
      series.createPriceLine({
        price:     pos.current_sl_price,
        color:     '#ef4444',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'SL',
      })
    }

    // Take Profits
    const tpColors = ['#22c55e', '#86efac', '#bbf7d0', '#dcfce7']
    const tps = Array.isArray(pos.current_tp_prices) ? pos.current_tp_prices : []
    tps.forEach((tp, i) => {
      if (tp.hit) return
      series.createPriceLine({
        price:     tp.price,
        color:     tpColors[i] ?? '#22c55e',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `TP${tp.level ?? i + 1} ${tp.close_percent}%`,
      })
    })
  }, [])

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: '#111827' },
        textColor:  '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#374151',
      },
      timeScale: {
        borderColor:      '#374151',
        timeVisible:      true,
        secondsVisible:   false,
      },
    })

    const series = chart.addCandlestickSeries({
      upColor:      '#22c55e',
      downColor:    '#ef4444',
      borderVisible: false,
      wickUpColor:   '#22c55e',
      wickDownColor: '#ef4444',
    })

    chartRef.current  = chart
    seriesRef.current = series

    // Resize observer
    const ro = new ResizeObserver(entries => {
      const { width } = entries[0].contentRect
      chart.applyOptions({ width })
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current  = null
      seriesRef.current = null
    }
  }, [height])

  // Update candles
  useEffect(() => {
    const series = seriesRef.current
    if (!series || !candles.length) return
    // lightweight-charts requires data sorted ascending by time
    const sorted = [...candles].sort((a, b) => a.time - b.time)
    series.setData(sorted)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  // Update price lines whenever position changes
  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    // Remove all existing price lines then re-add
    series.dataByIndex  // no-op — just ensure series is valid
    // lightweight-charts v4: no bulk-remove API; recreate series data keeps lines,
    // so we re-apply candles to wipe old lines then redraw position lines.
    if (candles.length) {
      const sorted = [...candles].sort((a, b) => a.time - b.time)
      series.setData(sorted)
    }
    buildPriceLines(series, position)
  }, [position, candles, buildPriceLines])

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden"
      style={{ height }}
    />
  )
}
