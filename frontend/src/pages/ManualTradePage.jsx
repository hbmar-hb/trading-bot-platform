import { useEffect, useState, useCallback, useRef } from 'react'
import { TrendingDown, TrendingUp, X, ChevronDown, ChevronUp, Loader2, AlertCircle, CheckCircle, Plus, Minus, Calculator, BarChart3, ShieldCheck, ExternalLink } from 'lucide-react'
import { createChart, CrosshairMode } from 'lightweight-charts'
import { manualTradeService } from '@/services/manualTrade'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import { paperTradingService } from '@/services/paperTrading'
import { usePrice } from '@/hooks/usePrice'
import usePositionStore from '@/store/positionStore'
import api from '@/services/api'

// ── Symbol Search Component (from BotEditPage) ───────────────
function SymbolSearch({ value, onChange, accountId, accountType }) {
  const [markets, setMarkets]   = useState([])
  const [loading, setLoading]   = useState(false)
  const [query,   setQuery]     = useState(value || '')
  const [open,    setOpen]      = useState(false)
  const ref = useRef(null)

  // Cargar mercados cuando cambia la cuenta
  useEffect(() => {
    if (accountType === 'paper') {
      // En modo paper, cargamos mercados de Binance (más común)
      setLoading(true)
      exchangeAccountsService.marketsByExchange('binance')
        .then(r => setMarkets(r.data || []))
        .catch(() => setMarkets([]))
        .finally(() => setLoading(false))
      return
    }
    
    if (!accountId) { setMarkets([]); return }
    setLoading(true)
    exchangeAccountsService.markets(accountId)
      .then(r => setMarkets(r.data || []))
      .catch(() => setMarkets([]))
      .finally(() => setLoading(false))
  }, [accountId, accountType])

  // Sincronizar query si el valor externo cambia
  useEffect(() => { setQuery(value || '') }, [value])

  // Cerrar al click fuera
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filtered = query.length < 1
    ? markets.slice(0, 50)
    : markets.filter(s => s.toLowerCase().includes(query.toLowerCase())).slice(0, 50)

  const handleSelect = (symbol) => {
    const upperSymbol = symbol.toUpperCase()
    setQuery(upperSymbol)
    onChange(upperSymbol)
    setOpen(false)
  }

  const handleInputChange = (e) => {
    const upperValue = e.target.value.toUpperCase()
    setQuery(upperValue)
    onChange(upperValue)
    setOpen(true)
  }

  return (
    <div ref={ref} className="relative">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={handleInputChange}
          onFocus={() => setOpen(true)}
          className="input font-mono pr-8 uppercase"
          placeholder={accountId ? 'Busca o escribe el símbolo…' : 'Selecciona primero una cuenta'}
          disabled={!accountId}
        />
        {loading && (
          <Loader2 size={14} className="animate-spin absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 dark:text-gray-500" />
        )}
      </div>

      {open && accountId && filtered.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full max-h-56 overflow-y-auto bg-white dark:bg-gray-900 border border-slate-300 dark:border-gray-700 rounded-lg shadow-xl">
          {filtered.map(s => (
            <li
              key={s}
              onMouseDown={() => handleSelect(s)}
              className={`px-3 py-2 text-sm font-mono cursor-pointer hover:bg-slate-100 dark:hover:bg-gray-800 ${
                s === value ? 'text-blue-600 dark:text-blue-400' : 'text-slate-900 dark:text-gray-200'
              }`}
            >
              {s}
            </li>
          ))}
        </ul>
      )}

      {!loading && accountId && markets.length === 0 && (
        <p className="text-xs text-slate-500 dark:text-gray-500 mt-1">No se pudieron cargar los mercados — escribe el símbolo manualmente</p>
      )}
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-xs text-slate-500 dark:text-gray-400 mb-1">{label}</label>
      {children}
      {hint && <p className="text-xs text-slate-500 dark:text-gray-500 mt-1">{hint}</p>}
    </div>
  )
}

function Section({ title, children, expanded, onToggle }) {
  return (
    <div className="border border-slate-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between p-3 bg-slate-50 dark:bg-gray-800/50 hover:bg-slate-100 dark:hover:bg-gray-800 transition-colors"
      >
        <span className="text-sm font-medium text-slate-700 dark:text-gray-300">{title}</span>
        {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
      </button>
      {expanded && <div className="p-3 space-y-3">{children}</div>}
    </div>
  )
}

function PositionBadge({ position, onClose, onCancelLimit, closing }) {
  if (!position) return null
  const isPending = position.status === 'pending_limit'
  const isLong = position.side === 'long'
  const pnl = parseFloat(position.unrealized_pnl || 0)
  return (
    <div className={`rounded-xl border p-4 flex items-center justify-between gap-4 ${
      isPending
        ? 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800'
        : isLong
          ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
          : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
    }`}>
      <div className="flex items-center gap-3">
        {isLong
          ? <TrendingUp size={20} className={`shrink-0 ${isPending ? 'text-yellow-600 dark:text-yellow-400' : 'text-green-600 dark:text-green-400'}`} />
          : <TrendingDown size={20} className={`shrink-0 ${isPending ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400'}`} />
        }
        <div>
          <p className="text-sm font-semibold text-slate-800 dark:text-white flex items-center gap-2">
            {position.side.toUpperCase()} {position.symbol}
            {isPending && <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200">LIMIT PENDIENTE</span>}
          </p>
          <p className="text-xs text-slate-500 dark:text-gray-400">
            {isPending ? 'Precio limit' : 'Entrada'}: ${parseFloat(position.entry_price).toFixed(6)} · Qty: {parseFloat(position.quantity).toFixed(4)} · x{position.leverage}
          </p>
          {position.current_sl_price && (
            <p className="text-xs text-orange-500">
              SL: ${parseFloat(position.current_sl_price).toFixed(6)}
            </p>
          )}
          {!isPending && pnl !== 0 && (
            <p className={`text-xs font-mono ${pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              PnL: {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} USDT
            </p>
          )}
        </div>
      </div>
      {isPending ? (
        <button
          onClick={onCancelLimit}
          disabled={closing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-yellow-600 hover:bg-yellow-700 text-white disabled:opacity-50 transition-colors"
        >
          {closing ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />}
          Cancelar
        </button>
      ) : (
        <button
          onClick={onClose}
          disabled={closing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 transition-colors"
        >
          {closing ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />}
          Cerrar
        </button>
      )}
    </div>
  )
}

// ── Chart Component ───────────────────────────────────────────

const TIMEFRAMES = [
  { value: '1m',  label: '1m',  intervalMs: 10_000,  candleSeconds: 60 },
  { value: '5m',  label: '5m',  intervalMs: 15_000,  candleSeconds: 300 },
  { value: '15m', label: '15m', intervalMs: 30_000,  candleSeconds: 900 },
  { value: '1h',  label: '1h',  intervalMs: 60_000,  candleSeconds: 3600 },
  { value: '4h',  label: '4h',  intervalMs: 120_000, candleSeconds: 14400 },
  { value: '1d',  label: '1D',  intervalMs: 300_000, candleSeconds: 86400 },
]

function MiniChart({ symbol, isDark }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  // Candles stored in a ref to avoid triggering chart recreation on every update
  const lastCandlesRef = useRef([])
  const [loading, setLoading] = useState(false)
  const [timeframe, setTimeframe] = useState('15m')
  const prices = usePositionStore(s => s.prices)
  const currentPrice = symbol ? prices[symbol] : null
  const tf = TIMEFRAMES.find(t => t.value === timeframe) || TIMEFRAMES[2]

  // Create chart once — recreate only when theme changes, NOT on candle updates
  useEffect(() => {
    if (!containerRef.current) return

    const bgColor = isDark ? '#111827' : '#ffffff'
    const textColor = isDark ? '#9ca3af' : '#64748b'
    const gridColor = isDark ? '#1f2937' : '#e2e8f0'

    // Tear down any existing chart before creating a new one
    if (chartRef.current) {
      try { chartRef.current.remove() } catch (_) {}
      chartRef.current = null
      seriesRef.current = null
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 250,
      layout: { background: { color: bgColor }, textColor },
      grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: isDark ? '#374151' : '#cbd5e1' },
      timeScale: { borderColor: isDark ? '#374151' : '#cbd5e1', timeVisible: true },
    })

    const series = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    })

    chartRef.current = chart
    seriesRef.current = series

    // Repopulate data if we already have candles (e.g. theme toggle)
    if (lastCandlesRef.current.length > 0) {
      series.setData(lastCandlesRef.current)
      chart.timeScale().fitContent()
    }

    const ro = new ResizeObserver(entries => {
      if (!chartRef.current) return
      try { chartRef.current.applyOptions({ width: entries[0].contentRect.width }) } catch (_) {}
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      // Capture local ref before nulling so cleanup closes over the right instance
      const c = chartRef.current
      chartRef.current = null
      seriesRef.current = null
      if (c) { try { c.remove() } catch (_) {} }
    }
  }, [isDark]) // Only recreate on theme change

  // Fetch candles when symbol or timeframe changes — update series directly, never recreate chart
  useEffect(() => {
    // Only fetch when symbol looks like a complete exchange symbol (contains '/')
    if (!symbol || !symbol.includes('/')) {
      lastCandlesRef.current = []
      if (seriesRef.current) { try { seriesRef.current.setData([]) } catch (_) {} }
      return
    }

    let cancelled = false
    setLoading(true)

    const fetchCandles = async () => {
      try {
        const res = await api.get(`/manual-trade/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${tf.value}&limit=100`)
        if (cancelled) return
        const data = (res.data || [])
          .filter(c => c && c.time != null && c.open != null)
          .sort((a, b) => a.time - b.time)
        lastCandlesRef.current = data
        if (seriesRef.current && data.length > 0) {
          seriesRef.current.setData(data)
          chartRef.current?.timeScale().fitContent()
        }
      } catch (_) {
        // Silently ignore — could be a transient error or partial symbol
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchCandles()
    const interval = setInterval(fetchCandles, tf.intervalMs)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [symbol, timeframe])

  // Real-time last-candle update from WebSocket price feed
  useEffect(() => {
    if (!currentPrice || !seriesRef.current) return
    const candles = lastCandlesRef.current
    if (candles.length === 0) return

    const lastCandle = candles[candles.length - 1]
    const now = Math.floor(Date.now() / 1000)
    const candleTime = Math.floor(now / tf.candleSeconds) * tf.candleSeconds

    if (lastCandle.time === candleTime) {
      try {
        seriesRef.current.update({
          ...lastCandle,
          close: currentPrice,
          high: Math.max(lastCandle.high, currentPrice),
          low: Math.min(lastCandle.low, currentPrice),
        })
      } catch (_) {}
    }
  }, [currentPrice])

  // Always keep the chart div mounted so containerRef is available for the chart creation effect.
  // Overlay placeholders on top with absolute positioning.
  return (
    <div className="space-y-2">
      {/* Header: title + timeframe selector */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-300 flex items-center gap-2">
          <BarChart3 size={16} /> Gráfico {symbol && `— ${symbol.toUpperCase()}`}
        </h3>
        <div className="flex gap-1">
          {TIMEFRAMES.map(t => (
            <button
              key={t.value}
              onClick={() => setTimeframe(t.value)}
              className={`px-2 py-0.5 text-xs rounded font-mono transition-colors ${
                timeframe === t.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 dark:bg-gray-800 text-slate-600 dark:text-gray-400 hover:bg-slate-200 dark:hover:bg-gray-700'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart area */}
      <div className="relative w-full rounded-lg overflow-hidden" style={{ height: 250 }}>
        {/* Chart container — always in DOM */}
        <div ref={containerRef} className="w-full h-full" />

        {/* No symbol overlay */}
        {!symbol && (
          <div className="absolute inset-0 bg-slate-100 dark:bg-gray-900 flex items-center justify-center">
            <p className="text-sm text-slate-400 dark:text-gray-500">Selecciona un símbolo para ver el gráfico</p>
          </div>
        )}

        {/* Loading overlay */}
        {loading && symbol && (
          <div className="absolute inset-0 bg-slate-100/80 dark:bg-gray-900/80 flex items-center justify-center">
            <Loader2 size={24} className="animate-spin text-blue-500" />
          </div>
        )}
      </div>
    </div>
  )
}

// ── Adopt Modal ──────────────────────────────────────────────

function AdoptModal({ position, exchangeAccountId, onClose, onAdopted }) {
  const [slPct, setSlPct] = useState(2)
  const [takeProfits, setTakeProfits] = useState([{ profit_percent: 2, close_percent: 50 }])
  const [trailingEnabled, setTrailingEnabled] = useState(false)
  const [trailingActivation, setTrailingActivation] = useState(1)
  const [trailingCallback, setTrailingCallback] = useState(0.5)
  const [breakevenEnabled, setBreakevenEnabled] = useState(false)
  const [breakevenActivation, setBreakevenActivation] = useState(1)
  const [breakevenLock, setBreakevenLock] = useState(0.2)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleAdopt = async () => {
    setLoading(true)
    setError(null)
    try {
      await manualTradeService.adoptPosition({
        exchange_account_id: exchangeAccountId,
        symbol: position.symbol,
        side: position.side,
        sl_percentage: slPct,
        take_profits: takeProfits.filter(tp => tp.profit_percent && tp.close_percent),
        trailing_config: trailingEnabled
          ? { enabled: true, activation_profit: trailingActivation, callback_rate: trailingCallback }
          : null,
        breakeven_config: breakevenEnabled
          ? { enabled: true, activation_profit: breakevenActivation, lock_profit: breakevenLock }
          : null,
      })
      onAdopted()
    } catch (e) {
      setError(e?.response?.data?.detail || 'Error al adoptar la posición')
    } finally {
      setLoading(false)
    }
  }

  const slPrice = position.side === 'long'
    ? position.entry_price * (1 - slPct / 100)
    : position.entry_price * (1 + slPct / 100)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-md overflow-y-auto max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b border-slate-200 dark:border-gray-700">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <ShieldCheck size={20} className="text-blue-500" />
              Adoptar posición
            </h2>
            <p className="text-sm text-slate-500 dark:text-gray-400">
              {position.side === 'long' ? '🟢 LONG' : '🔴 SHORT'} {position.symbol} · Entrada: ${position.entry_price.toFixed(4)}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 dark:hover:text-gray-300">
            <X size={20} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Stop Loss */}
          <div>
            <label className="block text-xs text-slate-500 dark:text-gray-400 mb-1">Stop Loss %</label>
            <input
              type="number" min="0.1" step="0.1"
              className="input w-full"
              value={slPct}
              onChange={e => setSlPct(Number(e.target.value))}
            />
            <p className="text-xs text-red-500 mt-1">
              SL se colocará a ${slPrice.toFixed(4)}
            </p>
          </div>

          {/* Take Profits */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs text-slate-500 dark:text-gray-400">Take Profits</label>
              <button
                type="button"
                onClick={() => setTakeProfits(tp => [...tp, { profit_percent: 3, close_percent: 25 }])}
                className="text-xs text-blue-500 hover:underline flex items-center gap-1"
              >
                <Plus size={12} /> Añadir TP
              </button>
            </div>
            {takeProfits.map((tp, i) => (
              <div key={i} className="flex gap-2 items-center mb-2">
                <input
                  type="number" min="0.1" step="0.1" placeholder="Profit %"
                  className="input flex-1 text-sm"
                  value={tp.profit_percent}
                  onChange={e => setTakeProfits(tps => tps.map((t, j) => j === i ? { ...t, profit_percent: Number(e.target.value) } : t))}
                />
                <input
                  type="number" min="1" max="100" step="1" placeholder="Cierre %"
                  className="input flex-1 text-sm"
                  value={tp.close_percent}
                  onChange={e => setTakeProfits(tps => tps.map((t, j) => j === i ? { ...t, close_percent: Number(e.target.value) } : t))}
                />
                {takeProfits.length > 1 && (
                  <button onClick={() => setTakeProfits(tps => tps.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-500">
                    <Minus size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Trailing Stop */}
          <div className="border border-slate-200 dark:border-gray-700 rounded-lg p-3">
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-gray-300 cursor-pointer">
              <input type="checkbox" checked={trailingEnabled} onChange={e => setTrailingEnabled(e.target.checked)} />
              Trailing Stop
            </label>
            {trailingEnabled && (
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Activación %</label>
                  <input type="number" min="0.1" step="0.1" className="input w-full mt-1" value={trailingActivation} onChange={e => setTrailingActivation(Number(e.target.value))} />
                </div>
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Callback %</label>
                  <input type="number" min="0.1" step="0.1" className="input w-full mt-1" value={trailingCallback} onChange={e => setTrailingCallback(Number(e.target.value))} />
                </div>
              </div>
            )}
          </div>

          {/* Breakeven */}
          <div className="border border-slate-200 dark:border-gray-700 rounded-lg p-3">
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-gray-300 cursor-pointer">
              <input type="checkbox" checked={breakevenEnabled} onChange={e => setBreakevenEnabled(e.target.checked)} />
              Breakeven
            </label>
            {breakevenEnabled && (
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Activación %</label>
                  <input type="number" min="0.1" step="0.1" className="input w-full mt-1" value={breakevenActivation} onChange={e => setBreakevenActivation(Number(e.target.value))} />
                </div>
                <div>
                  <label className="text-xs text-slate-500 dark:text-gray-400">Lock profit %</label>
                  <input type="number" min="0" step="0.1" className="input w-full mt-1" value={breakevenLock} onChange={e => setBreakevenLock(Number(e.target.value))} />
                </div>
              </div>
            )}
          </div>

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg p-3">
              <AlertCircle size={16} /> {error}
            </div>
          )}

          <button
            onClick={handleAdopt}
            disabled={loading}
            className="w-full py-3 rounded-xl font-semibold text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : <ShieldCheck size={18} />}
            Adoptar y activar gestión
          </button>
        </div>
      </div>
    </div>
  )
}

// ── External Positions Section ────────────────────────────────

function ExternalPositionsSection({ exchangeAccountId, onAdopted }) {
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(false)
  const [adoptTarget, setAdoptTarget] = useState(null)
  const [expanded, setExpanded] = useState(false)

  const load = useCallback(async () => {
    if (!exchangeAccountId) return
    setLoading(true)
    try {
      const res = await manualTradeService.getExternalPositions(exchangeAccountId)
      setPositions(res.data?.external_positions || [])
      if ((res.data?.external_positions || []).length > 0) setExpanded(true)
    } catch {
      setPositions([])
    } finally {
      setLoading(false)
    }
  }, [exchangeAccountId])

  useEffect(() => { load() }, [load])

  if (!exchangeAccountId) return null

  return (
    <>
      {adoptTarget && (
        <AdoptModal
          position={adoptTarget}
          exchangeAccountId={exchangeAccountId}
          onClose={() => setAdoptTarget(null)}
          onAdopted={() => {
            setAdoptTarget(null)
            load()
            onAdopted?.()
          }}
        />
      )}

      <div className="card">
        <button
          type="button"
          onClick={() => setExpanded(e => !e)}
          className="w-full flex items-center justify-between"
        >
          <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-300 flex items-center gap-2">
            <ExternalLink size={16} className="text-orange-500" />
            Posiciones externas (BingX nativo)
            {positions.length > 0 && (
              <span className="bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 text-xs px-2 py-0.5 rounded-full">
                {positions.length}
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={e => { e.stopPropagation(); load() }}
              className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-gray-300"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : '↻ Actualizar'}
            </button>
            {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
          </div>
        </button>

        {expanded && (
          <div className="mt-4">
            {loading && positions.length === 0 ? (
              <div className="flex items-center justify-center py-6 text-slate-400">
                <Loader2 size={20} className="animate-spin mr-2" /> Consultando exchange...
              </div>
            ) : positions.length === 0 ? (
              <p className="text-sm text-slate-400 dark:text-gray-500 text-center py-4">
                No hay posiciones externas sin gestión
              </p>
            ) : (
              <div className="space-y-2">
                <p className="text-xs text-slate-500 dark:text-gray-400 mb-3">
                  Estas posiciones están abiertas en BingX pero no están siendo gestionadas por la plataforma.
                  Al adoptarlas podrás configurar SL, TP, trailing y breakeven.
                </p>
                {positions.map((p, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between bg-slate-50 dark:bg-gray-800 rounded-lg p-3"
                  >
                    <div className="flex items-center gap-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                        p.side === 'long'
                          ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                          : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                      }`}>
                        {p.side.toUpperCase()}
                      </span>
                      <div>
                        <p className="text-sm font-mono font-medium text-slate-900 dark:text-white">{p.symbol}</p>
                        <p className="text-xs text-slate-500 dark:text-gray-400">
                          Entrada: ${p.entry_price.toFixed(4)} · Qty: {p.quantity}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={`text-sm font-mono font-semibold ${
                        p.unrealized_pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                      }`}>
                        {p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl.toFixed(2)} USDT
                      </span>
                      <button
                        onClick={() => setAdoptTarget(p)}
                        className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors flex items-center gap-1"
                      >
                        <ShieldCheck size={13} /> Adoptar
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

// ── Main Component ────────────────────────────────────────────

export default function ManualTradePage() {
  // Accounts
  const [realAccounts, setRealAccounts] = useState([])
  const [paperAccounts, setPaperAccounts] = useState([])
  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [selectedAccountType, setSelectedAccountType] = useState('real')
  const [loadingAccounts, setLoadingAccounts] = useState(true)

  // Form state
  const [symbol, setSymbol] = useState('')
  const [leverage, setLeverage] = useState(10)
  const [sizingType, setSizingType] = useState('percentage')
  const [sizingValue, setSizingValue] = useState(5)
  const [slPct, setSlPct] = useState(2)
  const [orderType, setOrderType] = useState('market') // 'market' | 'limit'
  const [limitPrice, setLimitPrice] = useState('')

  // Take Profits
  const [takeProfits, setTakeProfits] = useState([{ profit_percent: 2, close_percent: 25 }])
  const [tpExpanded, setTpExpanded] = useState(false)

  // Trailing Stop
  const [trailingEnabled, setTrailingEnabled] = useState(false)
  const [trailingActivation, setTrailingActivation] = useState(1)
  const [trailingCallback, setTrailingCallback] = useState(0.5)
  const [trailingExpanded, setTrailingExpanded] = useState(false)

  // Breakeven
  const [breakevenEnabled, setBreakevenEnabled] = useState(false)
  const [breakevenActivation, setBreakevenActivation] = useState(1)
  const [breakevenLock, setBreakevenLock] = useState(0.2)
  const [breakevenExpanded, setBreakevenExpanded] = useState(false)

  // Dynamic SL
  const [dynamicEnabled, setDynamicEnabled] = useState(false)
  const [dynamicStep, setDynamicStep] = useState(1)
  const [dynamicMaxSteps, setDynamicMaxSteps] = useState(3)
  const [dynamicExpanded, setDynamicExpanded] = useState(false)

  // Position tracking
  const [position, setPosition] = useState(null)
  const [loading, setLoading] = useState(false)
  const [closing, setClosing] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Theme detection
  const [isDark, setIsDark] = useState(false)

  const price = usePrice(symbol)

  // Detect theme
  useEffect(() => {
    const checkDark = () => setIsDark(document.documentElement.classList.contains('dark'))
    checkDark()
    const observer = new MutationObserver(checkDark)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])

  // Cargar cuentas reales
  useEffect(() => {
    const loadRealAccounts = async () => {
      try {
        const res = await exchangeAccountsService.list()
        console.log('Cuentas reales:', res.data)
        const accounts = (res.data || []).filter(a => a.is_active !== false)
        setRealAccounts(accounts)
        if (accounts.length > 0 && !selectedAccountId) {
          setSelectedAccountId(accounts[0].id)
          setSelectedAccountType('real')
        }
      } catch (e) {
        console.error('Error cargando cuentas reales:', e)
      }
    }
    loadRealAccounts()
  }, [])

  // Cargar cuentas paper
  useEffect(() => {
    const loadPaperAccounts = async () => {
      try {
        const res = await paperTradingService.list()
        console.log('Cuentas paper:', res.data)
        const accounts = res.data || []
        setPaperAccounts(accounts)
        if (accounts.length > 0 && !selectedAccountId && realAccounts.length === 0) {
          setSelectedAccountId(accounts[0].id)
          setSelectedAccountType('paper')
        }
      } catch (e) {
        console.error('Error cargando cuentas paper:', e)
      } finally {
        setLoadingAccounts(false)
      }
    }
    loadPaperAccounts()
  }, [realAccounts])

  // Obtener cuenta seleccionada
  const selectedAccount = selectedAccountType === 'real'
    ? realAccounts.find(a => a.id === selectedAccountId)
    : paperAccounts.find(a => a.id === selectedAccountId)

  // Cargar posición abierta
  const loadPosition = useCallback(async () => {
    if (!selectedAccountId || !symbol.trim()) { setPosition(null); return }
    try {
      const params = selectedAccountType === 'paper'
        ? { paper_balance_id: selectedAccountId }
        : { exchange_account_id: selectedAccountId }
      const { data } = await manualTradeService.getPosition(symbol.trim().toUpperCase(), params)
      setPosition(data.position)
    } catch {
      setPosition(null)
    }
  }, [selectedAccountId, selectedAccountType, symbol])

  useEffect(() => {
    loadPosition()
  }, [loadPosition])

  // Calcular métricas de la operación
  const calculateMetrics = () => {
    if (!price || !sizingValue) return null
    
    const currentPrice = price
    const stopPrice = currentPrice * (1 - slPct / 100)
    const riskAmount = sizingType === 'percentage' 
      ? (sizingValue / 100) * 10000
      : sizingValue
    
    const margin = riskAmount / leverage
    const riskDistance = Math.abs(currentPrice - stopPrice)
    const quantity = riskAmount / currentPrice
    const maxLoss = quantity * riskDistance * leverage
    
    return {
      currentPrice,
      stopPrice,
      margin: margin.toFixed(2),
      quantity: quantity.toFixed(4),
      maxLoss: maxLoss.toFixed(2),
      riskDistance: riskDistance.toFixed(6),
    }
  }

  const metrics = calculateMetrics()

  const buildPayload = (action) => {
    const base = {
      symbol: symbol.trim().toUpperCase(),
      action,
      leverage,
      position_sizing_type: sizingType,
      position_value: sizingValue,
      initial_sl_percentage: slPct,
      take_profits: takeProfits.filter(tp => tp.profit_percent && tp.close_percent),
      order_type: orderType,
    }
    
    // Añadir precio limit si corresponde
    if (orderType === 'limit' && limitPrice) {
      base.limit_price = parseFloat(limitPrice)
    }
    
    if (selectedAccountType === 'paper') {
      return { ...base, paper_balance_id: selectedAccountId }
    }
    return { ...base, exchange_account_id: selectedAccountId }
  }

  const execute = async (action) => {
    if (!selectedAccountId || !symbol.trim()) return
    setLoading(true)
    setFeedback(null)
    try {
      await manualTradeService.execute(buildPayload(action))
      const isLimit = orderType === 'limit'
      setFeedback({ type: 'ok', msg: isLimit ? `Orden limit ${action.toUpperCase()} enviada — pendiente de ejecución en el exchange` : `${action.toUpperCase()} enviado — procesando...` })
      // Poll for position a few times so feedback resolves
      for (let i = 0; i < 4; i++) {
        await new Promise(r => setTimeout(r, 2000))
        await loadPosition()
      }
    } catch (err) {
      setFeedback({ type: 'error', msg: err.response?.data?.detail || 'Error al ejecutar' })
    } finally {
      setLoading(false)
    }
  }

  const handleClose = async () => {
    if (!position) return
    setClosing(true)
    setFeedback(null)
    try {
      await manualTradeService.execute(buildPayload('close'))
      setFeedback({ type: 'ok', msg: 'Cierre enviado — procesando...' })
      setTimeout(loadPosition, 3000)
    } catch (err) {
      setFeedback({ type: 'error', msg: err.response?.data?.detail || 'Error al cerrar' })
    } finally {
      setClosing(false)
    }
  }

  const handleCancelLimit = async () => {
    if (!position?.id) return
    setClosing(true)
    setFeedback(null)
    try {
      await api.delete(`/positions/${position.id}/cancel-limit`)
      setFeedback({ type: 'ok', msg: 'Orden limit cancelada' })
      setPosition(null)
    } catch (err) {
      setFeedback({ type: 'error', msg: err.response?.data?.detail || 'Error al cancelar' })
    } finally {
      setClosing(false)
    }
  }

  const addTpLevel = () => setTakeProfits(prev => [...prev, { profit_percent: '', close_percent: 25 }])
  const updateTp = (i, field, val) => setTakeProfits(prev => prev.map((tp, idx) => idx === i ? { ...tp, [field]: val } : tp))
  const removeTp = (i) => setTakeProfits(prev => prev.filter((_, idx) => idx !== i))

  const canTrade = selectedAccountId && symbol.trim() && !loading && !position

  // Combinar todas las cuentas para el select
  const allAccounts = [
    ...realAccounts.map(a => ({ ...a, type: 'real' })),
    ...paperAccounts.map(a => ({ ...a, type: 'paper' }))
  ]

  return (
    <div className="max-w-5xl mx-auto space-y-5 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <BarChart3 size={24} className="text-blue-500" />
            Trading Manual
          </h1>
          <p className="text-sm text-slate-500 dark:text-gray-400">
            Opera manualmente con todas las herramientas de gestión de riesgo
          </p>
        </div>
      </div>

      {/* Posición activa */}
      <PositionBadge position={position} onClose={handleClose} onCancelLimit={handleCancelLimit} closing={closing} />

      {/* Feedback */}
      {feedback && (
        <div className={`flex items-center gap-2 text-sm px-4 py-3 rounded-lg ${
          feedback.type === 'ok'
            ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'
            : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
        }`}>
          {feedback.type === 'ok' ? <CheckCircle size={16} className="shrink-0" /> : <AlertCircle size={16} className="shrink-0" />}
          {feedback.msg}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Columna izquierda - Configuración */}
        <div className="space-y-4">
          {/* Cuenta y Símbolo */}
          <div className="card space-y-4">
            {/* Cuenta */}
            <div>
              <label className="block text-xs text-slate-500 dark:text-gray-400 mb-1">
                Cuenta 
                <button 
                  onClick={() => window.location.reload()} 
                  className="ml-2 text-blue-500 text-[10px] hover:underline"
                >
                  (Recargar)
                </button>
              </label>
              {loadingAccounts ? (
                <div className="input w-full flex items-center gap-2 text-slate-400">
                  <Loader2 size={14} className="animate-spin" /> Cargando...
                </div>
              ) : allAccounts.length === 0 ? (
                <div className="p-3 bg-slate-100 dark:bg-gray-800 rounded-lg text-sm space-y-2">
                  <p className="text-slate-500">No hay cuentas disponibles.</p>
                  <p className="text-xs text-slate-400">
                    Reales: {realAccounts.length} | Paper: {paperAccounts.length}
                  </p>
                  <a href="#/exchange-accounts" className="text-blue-500 hover:underline inline-block">
                    → Ir a Cuentas de Exchange
                  </a>
                </div>
              ) : (
                <select
                  className="input w-full"
                  value={`${selectedAccountType}:${selectedAccountId}`}
                  onChange={e => {
                    const [type, id] = e.target.value.split(':')
                    setSelectedAccountType(type)
                    setSelectedAccountId(id)
                  }}
                >
                  <optgroup label="Cuentas Reales">
                    {realAccounts.map(a => (
                      <option key={`real:${a.id}`} value={`real:${a.id}`}>
                        🏦 {a.exchange?.toUpperCase()} — {a.label}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Paper Trading">
                    {paperAccounts.map(a => (
                      <option key={`paper:${a.id}`} value={`paper:${a.id}`}>
                        📄 {a.label}
                      </option>
                    ))}
                  </optgroup>
                </select>
              )}
            </div>

            {/* Símbolo */}
            <Field label="Símbolo" hint="Selecciona de la lista o escribe manualmente">
              <div className="flex gap-2 items-center">
                <div className="flex-1">
                  <SymbolSearch
                    value={symbol}
                    onChange={setSymbol}
                    accountId={selectedAccountId}
                    accountType={selectedAccountType}
                  />
                </div>
                {price && (
                  <span className="text-sm font-mono text-slate-700 dark:text-gray-300 whitespace-nowrap bg-slate-100 dark:bg-gray-800 px-3 py-2 rounded">
                    ${price.toFixed(price < 1 ? 6 : 2)}
                  </span>
                )}
              </div>
            </Field>
          </div>

          {/* Configuración básica */}
          <div className="card space-y-4">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-300 flex items-center gap-2">
              <Calculator size={16} /> Configuración
            </h3>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Apalancamiento" hint="1-125x">
                <input
                  type="number" min="1" max="125"
                  className="input w-full"
                  value={leverage}
                  onChange={e => setLeverage(Number(e.target.value))}
                />
              </Field>

              <Field label="Stop Loss %" hint="Distancia desde entrada">
                <input
                  type="number" min="0.1" step="0.1"
                  className="input w-full"
                  value={slPct}
                  onChange={e => setSlPct(Number(e.target.value))}
                />
              </Field>
            </div>

            {/* Tipo de orden */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Tipo de orden">
                <select
                  className="input w-full"
                  value={orderType}
                  onChange={e => setOrderType(e.target.value)}
                >
                  <option value="market">🚀 Mercado (Market)</option>
                  <option value="limit">⏳ Límite (Limit)</option>
                </select>
              </Field>

              {orderType === 'limit' && (
                <Field label="Precio Limit" hint="Precio de entrada deseado">
                  <input
                    type="number" min="0.000001" step="0.000001"
                    className="input w-full"
                    value={limitPrice}
                    onChange={e => setLimitPrice(e.target.value)}
                    placeholder={price ? price.toFixed(price < 1 ? 6 : 2) : '0.00'}
                  />
                </Field>
              )}
            </div>
            
            {orderType === 'limit' && limitPrice && price && (
              <div className={`p-2 rounded-lg text-xs ${
                (parseFloat(limitPrice) > price && parseFloat(limitPrice) / price > 1.02) ||
                (parseFloat(limitPrice) < price && price / parseFloat(limitPrice) > 1.02)
                  ? 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-400 border border-yellow-200'
                  : 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'
              }`}>
                {parseFloat(limitPrice) > price 
                  ? `📈 El precio limit (${parseFloat(limitPrice).toFixed(price < 1 ? 6 : 2)}) está por encima del mercado (${price.toFixed(price < 1 ? 6 : 2)}). Se ejecutará cuando baje.`
                  : parseFloat(limitPrice) < price
                    ? `📉 El precio limit (${parseFloat(limitPrice).toFixed(price < 1 ? 6 : 2)}) está por debajo del mercado (${price.toFixed(price < 1 ? 6 : 2)}). Se ejecutará cuando suba.`
                    : `✅ El precio limit está muy cerca del precio actual.`
                }
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <Field label="Tipo de posición">
                <select
                  className="input w-full"
                  value={sizingType}
                  onChange={e => setSizingType(e.target.value)}
                >
                  <option value="percentage">% del balance</option>
                  <option value="fixed">USDT fijo</option>
                </select>
              </Field>

              <Field label={sizingType === 'percentage' ? 'Porcentaje %' : 'Importe USDT'}>
                <input
                  type="number" min="0.1" step="0.1"
                  className="input w-full"
                  value={sizingValue}
                  onChange={e => setSizingValue(Number(e.target.value))}
                />
              </Field>
            </div>
          </div>

          {/* Take Profits */}
          <Section title="Take Profits" expanded={tpExpanded} onToggle={() => setTpExpanded(!tpExpanded)}>
            <div className="space-y-2">
              {takeProfits.map((tp, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <span className="text-xs text-slate-500 w-8">TP{i + 1}</span>
                  <input
                    type="number" placeholder="% profit" min="0.1" step="0.1"
                    className="input flex-1 text-sm"
                    value={tp.profit_percent}
                    onChange={e => updateTp(i, 'profit_percent', e.target.value)}
                  />
                  <input
                    type="number" placeholder="% cierre" min="1" max="100"
                    className="input w-24 text-sm"
                    value={tp.close_percent}
                    onChange={e => updateTp(i, 'close_percent', e.target.value)}
                  />
                  <button onClick={() => removeTp(i)} className="p-1.5 text-slate-400 hover:text-red-400 rounded">
                    <Minus size={14} />
                  </button>
                </div>
              ))}
              <button onClick={addTpLevel} className="flex items-center gap-1 text-xs text-blue-500 hover:text-blue-400">
                <Plus size={14} /> Añadir TP
              </button>
            </div>
          </Section>

          {/* Trailing Stop */}
          <Section title="Trailing Stop" expanded={trailingExpanded} onToggle={() => setTrailingExpanded(!trailingExpanded)}>
            <label className="flex items-center gap-3 mb-3">
              <input
                type="checkbox"
                checked={trailingEnabled}
                onChange={e => setTrailingEnabled(e.target.checked)}
                className="rounded border-slate-300"
              />
              <span className="text-sm text-slate-700 dark:text-gray-300">Activar trailing stop</span>
            </label>
            {trailingEnabled && (
              <div className="grid grid-cols-2 gap-4">
                <Field label="Activación %" hint="Profit para activar">
                  <input
                    type="number" min="0.1" step="0.1"
                    className="input w-full"
                    value={trailingActivation}
                    onChange={e => setTrailingActivation(Number(e.target.value))}
                  />
                </Field>
                <Field label="Callback %" hint="Distancia del SL al precio">
                  <input
                    type="number" min="0.1" step="0.1"
                    className="input w-full"
                    value={trailingCallback}
                    onChange={e => setTrailingCallback(Number(e.target.value))}
                  />
                </Field>
              </div>
            )}
          </Section>

          {/* Breakeven */}
          <Section title="Breakeven" expanded={breakevenExpanded} onToggle={() => setBreakevenExpanded(!breakevenExpanded)}>
            <label className="flex items-center gap-3 mb-3">
              <input
                type="checkbox"
                checked={breakevenEnabled}
                onChange={e => setBreakevenEnabled(e.target.checked)}
                className="rounded border-slate-300"
              />
              <span className="text-sm text-slate-700 dark:text-gray-300">Mover SL a breakeven</span>
            </label>
            {breakevenEnabled && (
              <div className="grid grid-cols-2 gap-4">
                <Field label="Activación %" hint="Profit para activar">
                  <input
                    type="number" min="0.1" step="0.1"
                    className="input w-full"
                    value={breakevenActivation}
                    onChange={e => setBreakevenActivation(Number(e.target.value))}
                  />
                </Field>
                <Field label="Lock profit %" hint="Sobre entrada">
                  <input
                    type="number" min="0" step="0.1"
                    className="input w-full"
                    value={breakevenLock}
                    onChange={e => setBreakevenLock(Number(e.target.value))}
                  />
                </Field>
              </div>
            )}
          </Section>

          {/* Dynamic SL */}
          <Section title="Stop Loss Dinámico" expanded={dynamicExpanded} onToggle={() => setDynamicExpanded(!dynamicExpanded)}>
            <label className="flex items-center gap-3 mb-3">
              <input
                type="checkbox"
                checked={dynamicEnabled}
                onChange={e => setDynamicEnabled(e.target.checked)}
                className="rounded border-slate-300"
              />
              <span className="text-sm text-slate-700 dark:text-gray-300">Mover SL por pasos</span>
            </label>
            {dynamicEnabled && (
              <div className="grid grid-cols-2 gap-4">
                <Field label="Paso %" hint="Cada cuánto mover SL">
                  <input
                    type="number" min="0.1" step="0.1"
                    className="input w-full"
                    value={dynamicStep}
                    onChange={e => setDynamicStep(Number(e.target.value))}
                  />
                </Field>
                <Field label="Pasos máximos" hint="0 = ilimitado">
                  <input
                    type="number" min="0" step="1"
                    className="input w-full"
                    value={dynamicMaxSteps}
                    onChange={e => setDynamicMaxSteps(Number(e.target.value))}
                  />
                </Field>
              </div>
            )}
          </Section>
        </div>

        {/* Columna derecha - Gráfico y Métricas */}
        <div className="space-y-4">
          {/* Gráfico */}
          <div className="card space-y-3">
            <MiniChart symbol={symbol} isDark={isDark} />
          </div>

          {/* Métricas */}
          {metrics && (
            <div className="card space-y-3">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-300 flex items-center gap-2">
                <Calculator size={16} /> Preview de la operación
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-100 dark:bg-gray-800 rounded-lg p-3">
                  <p className="text-xs text-slate-500 dark:text-gray-400">Precio entrada (est.)</p>
                  <p className="font-mono text-slate-900 dark:text-white">${metrics.currentPrice.toFixed(price < 1 ? 6 : 2)}</p>
                </div>
                <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3">
                  <p className="text-xs text-red-500 dark:text-red-400">Stop Loss</p>
                  <p className="font-mono text-red-600 dark:text-red-400">${metrics.stopPrice.toFixed(price < 1 ? 6 : 2)}</p>
                </div>
                <div className="bg-slate-100 dark:bg-gray-800 rounded-lg p-3">
                  <p className="text-xs text-slate-500 dark:text-gray-400">Cantidad estimada</p>
                  <p className="font-mono text-slate-900 dark:text-white">{metrics.quantity}</p>
                </div>
                <div className="bg-slate-100 dark:bg-gray-800 rounded-lg p-3">
                  <p className="text-xs text-slate-500 dark:text-gray-400">Margen requerido</p>
                  <p className="font-mono text-slate-900 dark:text-white">${metrics.margin}</p>
                </div>
              </div>
              <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3 border border-red-200 dark:border-red-800">
                <p className="text-xs text-red-500 dark:text-red-400">Pérdida máxima estimada</p>
                <p className="font-mono text-lg text-red-600 dark:text-red-400">-${metrics.maxLoss} USDT</p>
              </div>
              {takeProfits.length > 0 && takeProfits[0].profit_percent && (
                <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 border border-green-200 dark:border-green-800">
                  <p className="text-xs text-green-500 dark:text-green-400">Ganancia potencial (TP1)</p>
                  <p className="font-mono text-lg text-green-600 dark:text-green-400">
                    +${(parseFloat(metrics.quantity) * metrics.currentPrice * parseFloat(takeProfits[0].profit_percent) / 100 * leverage).toFixed(2)} USDT
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Botones de acción */}
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => execute('long')}
              disabled={!canTrade}
              className="flex items-center justify-center gap-2 py-4 rounded-xl font-semibold text-white bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? <Loader2 size={20} className="animate-spin" /> : <TrendingUp size={20} />}
              LONG
            </button>
            <button
              onClick={() => execute('short')}
              disabled={!canTrade}
              className="flex items-center justify-center gap-2 py-4 rounded-xl font-semibold text-white bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? <Loader2 size={20} className="animate-spin" /> : <TrendingDown size={20} />}
              SHORT
            </button>
          </div>

          {position && (
            <p className="text-center text-xs text-slate-400 dark:text-gray-500 bg-slate-100 dark:bg-gray-800 rounded-lg p-3">
              Ya tienes una posición abierta en este par. Ciérrala antes de abrir una nueva.
            </p>
          )}

          {!selectedAccountId && (
            <p className="text-center text-xs text-slate-400 dark:text-gray-500 bg-slate-100 dark:bg-gray-800 rounded-lg p-3">
              Selecciona una cuenta para empezar a operar
            </p>
          )}
        </div>
      </div>

    </div>
  )
}
