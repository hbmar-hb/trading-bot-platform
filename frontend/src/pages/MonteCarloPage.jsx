/* BUILD_TIMESTAMP 1780309619 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, LineStyle } from 'lightweight-charts'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  AreaChart, Area
} from 'recharts'
import {
  Activity, Brain, ChevronDown, ChevronUp, Copy, Dices, Download, FileCode,
  History, Loader2, Play, Plus, RefreshCw, Save, Trash2, TrendingUp,
  AlertTriangle, CheckCircle2, XCircle, BarChart3, Layers, Sparkles,
  Scan, Wand2, Target, Zap, Upload, X
} from 'lucide-react'
import { montecarloService } from '@/services/montecarlo'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

// ─── Helpers ──────────────────────────────────────────────────

function fmtPct(v, dec = 2) {
  return `${(Number(v ?? 0) * 100).toFixed(dec)}%`
}

function fmtNum(v, dec = 2) {
  return Number(v ?? 0).toFixed(dec)
}

function classNames(...c) {
  return c.filter(Boolean).join(' ')
}

const TIMEFRAMES = ['1m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w','1M']

const SIMULATION_TYPES = [
  { value: 'return_shuffle', label: 'Reordenación de Retornos' },
  { value: 'bootstrap', label: 'Bootstrap con Bloques' },
  { value: 'equity_path', label: 'Caminos de Equity' },
]

// ─── Componente: Editor de Estrategia ─────────────────────────

function StrategyEditor({ strategy, onChange, onSave, onRun }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl border border-slate-200 dark:border-gray-700 overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-slate-700 dark:text-gray-200 hover:bg-slate-100 dark:hover:bg-gray-700/50"
      >
        <span className="flex items-center gap-2"><FileCode size={16} /> Editor de Estrategia</span>
        {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
      {!collapsed && (
        <div className="p-4 space-y-3">
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-400">Nombre</label>
            <input
              className="input w-full mt-1 text-sm"
              value={strategy.name || ''}
              onChange={e => onChange({ ...strategy, name: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-400">Descripción</label>
            <input
              className="input w-full mt-1 text-sm"
              value={strategy.description || ''}
              onChange={e => onChange({ ...strategy, description: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-400">Código Python (función strategy(df, params))</label>
            <textarea
              className="input w-full mt-1 text-xs font-mono h-64 resize-y"
              spellCheck={false}
              value={strategy.code || ''}
              onChange={e => onChange({ ...strategy, code: e.target.value })}
            />
          </div>
          <div className="flex gap-2">
            <button onClick={onSave} className="btn-primary text-xs flex items-center gap-1">
              <Save size={14} /> Guardar
            </button>
            <button onClick={onRun} className="btn-secondary text-xs flex items-center gap-1">
              <Play size={14} /> Ejecutar Backtest
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Componente: Parámetros de Estrategia ─────────────────────

function StrategyParams({ params, onChange }) {
  const entries = Object.entries(params || {})
  if (entries.length === 0) return null

  return (
    <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-200 mb-2 flex items-center gap-2">
        <Layers size={14} /> Parámetros
      </h3>
      <div className="grid grid-cols-2 gap-2">
        {entries.map(([key, val]) => {
          const p = typeof val === 'object' && val !== null ? val : { default: val }
          const type = p.type || (typeof p.default === 'number' ? (Number.isInteger(p.default) ? 'int' : 'float') : 'str')
          return (
            <div key={key}>
              <label className="text-[10px] text-slate-500 dark:text-gray-400 uppercase">{key}</label>
              <input
                type={type === 'bool' ? 'checkbox' : 'number'}
                className={type === 'bool' ? 'mt-1' : 'input w-full text-xs'}
                checked={type === 'bool' ? !!p.value : undefined}
                value={type !== 'bool' ? (p.value ?? p.default ?? '') : undefined}
                onChange={e => {
                  const newVal = type === 'bool' ? e.target.checked : (type === 'int' ? parseInt(e.target.value) : parseFloat(e.target.value))
                  onChange({ ...params, [key]: { ...p, value: newVal } })
                }}
              />
            </div>
          )
        })}
      </div>

    </div>
  )
}

// ─── Componente: Gráfico Equity Curve ─────────────────────────

function EquityChart({ equityCurve }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current || !equityCurve?.length) return
    let chart = null

    try {
      chart = createChart(containerRef.current, {
        layout: {
          background: { color: 'transparent' },
          textColor: '#94a3b8',
        },
        grid: {
          vertLines: { color: 'rgba(148, 163, 184, 0.1)' },
          horzLines: { color: 'rgba(148, 163, 184, 0.1)' },
        },
        rightPriceScale: { borderColor: 'rgba(148, 163, 184, 0.2)' },
        timeScale: { borderColor: 'rgba(148, 163, 184, 0.2)' },
        height: 220,
      })

      // Validacion y transformacion de datos
      console.log('[EquityChart] raw equityCurve length:', equityCurve?.length)
      console.log('[EquityChart] first point:', equityCurve?.[0])
      console.log('[EquityChart] last point:', equityCurve?.[equityCurve.length - 1])

      const rawPoints = equityCurve
        .map(p => {
          if (!p || typeof p !== 'object') return null
          const ts = p.timestamp
          const eq = p.equity
          if (ts == null || eq == null) return null
          const time = Math.floor(new Date(ts).getTime() / 1000)
          const value = parseFloat(eq)
          if (!Number.isFinite(time) || time <= 0) return null
          if (!Number.isFinite(value)) return null
          return { time, value }
        })
        .filter(Boolean)

      console.log('[EquityChart] valid points:', rawPoints.length)

      if (rawPoints.length === 0) {
        console.warn('[EquityChart] no valid points after filtering')
        chart.remove()
        return
      }

      // Ordenar y deduplicar
      const seen = new Set()
      const points = rawPoints
        .sort((a, b) => a.time - b.time)
        .filter(p => {
          if (seen.has(p.time)) return false
          seen.add(p.time)
          return true
        })

      console.log('[EquityChart] final points:', points.length)
      console.log('[EquityChart] first final:', points[0])
      console.log('[EquityChart] last final:', points[points.length - 1])

      if (points.length === 0) {
        chart.remove()
        return
      }

      const series = chart.addLineSeries({
        color: '#3b82f6',
        lineWidth: 2,
      })

      series.setData(points)
      chart.timeScale().fitContent()

      // ResizeObserver para redimensiones
      let destroyed = false
      const obs = new ResizeObserver(() => {
        if (!destroyed && containerRef.current && chart) {
          chart.applyOptions({ width: containerRef.current.clientWidth })
        }
      })
      obs.observe(containerRef.current)

      return () => {
        destroyed = true
        obs.disconnect()
        chart.remove()
      }
    } catch (err) {
      console.error('EquityChart error:', err)
      if (chart) try { chart.remove() } catch (_) {}
    }
  }, [equityCurve])

  return (
    <div className="w-full h-64 rounded-lg border border-slate-200 dark:border-gray-700 overflow-hidden">
      {equityCurve?.length ? (
        <div ref={containerRef} className="w-full h-full" />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-slate-400 dark:text-gray-500 text-sm">
          Sin datos de equity
        </div>
      )}
    </div>
  )
}

// ─── Componente: Gauge de Score ───────────────────────────────

function ScoreGauge({ score, passed }) {
  const color = passed ? '#22c55e' : score >= 50 ? '#eab308' : '#ef4444'
  const radius = 45
  const stroke = 8
  const normalized = Math.min(100, Math.max(0, score))
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (normalized / 100) * circumference * 0.75

  return (
    <div className="flex flex-col items-center">
      <svg width="120" height="110" viewBox="0 0 120 110">
        {/* Fondo del gauge */}
        <path
          d={`M 20 85 A ${radius} ${radius} 0 0 1 100 85`}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Barra de progreso */}
        <path
          d={`M 20 85 A ${radius} ${radius} 0 0 1 100 85`}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.5s ease' }}
        />
        {/* Número centrado ARRIBA del arco */}
        <text x="60" y="55" textAnchor="middle" fontSize="24" fontWeight="bold" fill={color}>
          {Math.round(normalized)}
        </text>
        {/* Texto APROBADO/RECHAZADO debajo del arco */}
        <text x="60" y="102" textAnchor="middle" fontSize="10" fill="#94a3b8">
          {passed ? 'APROBADO' : 'RECHAZADO'}
        </text>
      </svg>
    </div>
  )
}

// ─── Componente: Tabla de Trades ──────────────────────────────

function TradesTable({ trades }) {
  const [page, setPage] = useState(0)
  const perPage = 10
  const totalPages = Math.ceil((trades?.length || 0) / perPage)
  const pageTrades = trades?.slice(page * perPage, (page + 1) * perPage) || []

  return (
    <div className="overflow-auto max-h-64">
      <table className="w-full text-xs">
        <thead className="bg-slate-100 dark:bg-gray-700/50 text-slate-600 dark:text-gray-300 sticky top-0">
          <tr>
            <th className="px-2 py-1 text-left">#</th>
            <th className="px-2 py-1 text-left">Dir</th>
            <th className="px-2 py-1 text-right">Entrada</th>
            <th className="px-2 py-1 text-right">Salida</th>
            <th className="px-2 py-1 text-right">PnL%</th>
            <th className="px-2 py-1 text-right">Razón</th>
          </tr>
        </thead>
        <tbody>
          {pageTrades.map((t, i) => (
            <tr key={i} className="border-b border-slate-100 dark:border-gray-700/50">
              <td className="px-2 py-1 text-slate-500">{page * perPage + i + 1}</td>
              <td className="px-2 py-1">
                <span className={t.direction === 1 ? 'text-green-500' : 'text-red-500'}>
                  {t.direction === 1 ? 'LONG' : 'SHORT'}
                </span>
              </td>
              <td className="px-2 py-1 text-right font-mono">{fmtNum(t.entry_price, 2)}</td>
              <td className="px-2 py-1 text-right font-mono">{fmtNum(t.exit_price, 2)}</td>
              <td className={classNames('px-2 py-1 text-right font-mono', t.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400')}>
                {fmtPct(t.pnl_pct)}
              </td>
              <td className="px-2 py-1 text-right text-slate-500">{t.close_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 mt-2">
          <button disabled={page === 0} onClick={() => setPage(p => p - 1)} className="text-xs px-2 py-1 rounded bg-slate-200 dark:bg-gray-700 disabled:opacity-30">Prev</button>
          <span className="text-xs text-slate-500 py-1">{page + 1}/{totalPages}</span>
          <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)} className="text-xs px-2 py-1 rounded bg-slate-200 dark:bg-gray-700 disabled:opacity-30">Next</button>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// PÁGINA PRINCIPAL
// ═══════════════════════════════════════════════════════════════

export default function MonteCarloPage() {
  // ── Estado: Estrategias ──
  const [strategies, setStrategies] = useState([])
  const [selectedStrategy, setSelectedStrategy] = useState(null)
  const [strategyForm, setStrategyForm] = useState({ name: '', description: '', code: '', parameters: {}, indicators: [] })
  const [loadingStrategies, setLoadingStrategies] = useState(false)
  const [savingStrategy, setSavingStrategy] = useState(false)

  // ── Estado: Backtest ──
  const [backtestConfig, setBacktestConfig] = useState({
    symbol: 'BTC/USDT:USDT',
    timeframe: '1h',
    from_date: '',
    to_date: '',
    initial_capital: 10000,
    fee_rate: 0.0006,
    slippage_pct: 0.0,
  })
  const [backtestResult, setBacktestResult] = useState(null)
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [backtests, setBacktests] = useState([])

  // ── Estado: Simulación ──
  const [simConfig, setSimConfig] = useState({
    simulation_type: 'return_shuffle',
    n_simulations: 10000,
    save_equity_curves: true,
  })
  const [simResult, setSimResult] = useState(null)
  const [simLoading, setSimLoading] = useState(false)

  // ── Estado: Símbolos ──
  const [symbols, setSymbols] = useState([])

  // ── Estado: IA Engine ──
  const [aiPanelOpen, setAiPanelOpen] = useState(false)
  const [aiWatchlist, setAiWatchlist] = useState([])
  const [aiScanLoading, setAiScanLoading] = useState(false)
  const [aiEvalLoading, setAiEvalLoading] = useState(false)
  const [aiRecalLoading, setAiRecalLoading] = useState(false)
  const [aiEvalResult, setAiEvalResult] = useState(null)
  const [aiSelectedSymbol, setAiSelectedSymbol] = useState('')
  const [aiConfig, setAiConfig] = useState({
    timeframe: '1h',
    lookback_days: 90,
    recalibrate: false,
  })
  const [symbolSuggestions, setSymbolSuggestions] = useState([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const symbolInputRef = useRef(null)
  const suggestionsRef = useRef(null)

  // ── Estado: IA Batch Evaluation ──
  const [aiBatchSymbols, setAiBatchSymbols] = useState([])
  const [aiBatchResults, setAiBatchResults] = useState(null)
  const [aiBatchLoading, setAiBatchLoading] = useState(false)
  const [aiBatchTab, setAiBatchTab] = useState('single') // 'single' | 'batch'
  const [mcSetupBaseEnabled, setMcSetupBaseEnabled] = useState(true)
  const [batchSymbolInput, setBatchSymbolInput] = useState('')
  const [batchSuggestions, setBatchSuggestions] = useState([])
  const [showBatchSuggestions, setShowBatchSuggestions] = useState(false)
  const batchInputRef = useRef(null)
  const batchSuggestionsRef = useRef(null)

  // ── Carga inicial ──
  useEffect(() => {
    console.log('[MC] MonteCarloPage mounted, loading data...')
    loadStrategies()
    loadSymbols()
  }, [])

  // ── Cerrar dropdowns al hacer click fuera ──
  useEffect(() => {
    function handleClickOutside(event) {
      if (suggestionsRef.current && !suggestionsRef.current.contains(event.target) &&
          symbolInputRef.current && !symbolInputRef.current.contains(event.target)) {
        setShowSuggestions(false)
      }
      if (batchSuggestionsRef.current && !batchSuggestionsRef.current.contains(event.target) &&
          batchInputRef.current && !batchInputRef.current.contains(event.target)) {
        setShowBatchSuggestions(false)
      }
    }
    // Fechas por defecto: últimos 90 días
    const to = new Date()
    const from = new Date()
    from.setDate(from.getDate() - 90)
    setBacktestConfig(prev => ({
      ...prev,
      from_date: from.toISOString().split('T')[0],
      to_date: to.toISOString().split('T')[0],
    }))
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  async function loadStrategies() {
    setLoadingStrategies(true)
    try {
      const res = await montecarloService.getStrategies()
      console.log('[MC] strategies response:', typeof res.data, Array.isArray(res.data), res.data)
      setStrategies(Array.isArray(res.data) ? res.data : [])
      if (res.data?.length > 0 && !selectedStrategy) {
        selectStrategy(res.data[0])
      }
    } catch (e) {
      console.error('Error cargando estrategias:', e)
    } finally {
      setLoadingStrategies(false)
    }
  }

  async function loadSymbols() {
    try {
      const res = await montecarloService.getSymbols()
      console.log('[MC] symbols response:', res.data)
      const list = Array.isArray(res.data?.symbols) ? res.data.symbols : (Array.isArray(res.data) ? res.data : [])
      setSymbols(list)
    } catch (e) {
      console.error('Error cargando símbolos:', e)
      setSymbols([])
    }
  }

  function selectStrategy(s) {
    setSelectedStrategy(s)
    setStrategyForm({
      name: s.name || '',
      description: s.description || '',
      code: s.code || '',
      parameters: s.parameters || {},
      indicators: s.indicators || [],
    })
    setBacktestResult(null)
    setSimResult(null)
  }

  async function saveStrategy() {
    setSavingStrategy(true)
    try {
      if (selectedStrategy?.id) {
        await montecarloService.updateStrategy(selectedStrategy.id, strategyForm)
      } else {
        await montecarloService.createStrategy(strategyForm)
      }
      await loadStrategies()
    } catch (e) {
      alert('Error guardando estrategia: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSavingStrategy(false)
    }
  }

  async function deleteStrategy(id) {
    if (!confirm('¿Eliminar esta estrategia?')) return
    try {
      await montecarloService.deleteStrategy(id)
      await loadStrategies()
      setSelectedStrategy(null)
      setStrategyForm({ name: '', description: '', code: '', parameters: {}, indicators: [] })
      setBacktestResult(null)
      setSimResult(null)
    } catch (e) {
      alert('Error eliminando estrategia')
    }
  }

  async function newStrategy() {
    try {
      const res = await montecarloService.getStrategyTemplate()
      const tpl = res.data
      setSelectedStrategy(null)
      setBacktestResult(null)
      setSimResult(null)
      setStrategyForm({
        name: tpl.name + ' (copia)',
        description: tpl.description,
        code: tpl.code,
        parameters: tpl.parameters,
        indicators: tpl.indicators,
      })
    } catch (e) {
      // fallback
      setSelectedStrategy(null)
      setBacktestResult(null)
      setSimResult(null)
      setStrategyForm({
        name: 'Nueva Estrategia',
        description: '',
        code: 'def strategy(df, params):\n    signal = pd.Series(0, index=df.index)\n    return pd.DataFrame({"signal": signal})\n',
        parameters: {},
        indicators: [],
      })
    }
  }

  // ── IA Engine ──
  async function loadAIWatchlist() {
    setAiScanLoading(true)
    try {
      const res = await montecarloService.scanAI({
        strategy_id: selectedStrategy?.id,
        lookback_days: Number(aiConfig.lookback_days) || 90,
      })
      setAiWatchlist(res.data?.evaluations || [])
    } catch (e) {
      console.error('Error escaneando watchlist:', e)
    } finally {
      setAiScanLoading(false)
    }
  }

  async function evaluateAI() {
    if (!selectedStrategy?.id) {
      alert('Guarda primero la estrategia')
      return
    }
    if (!aiSelectedSymbol) {
      alert('Selecciona un símbolo')
      return
    }
    setAiEvalLoading(true)
    try {
      const res = await montecarloService.evaluateAI({
        strategy_id: selectedStrategy.id,
        symbol: aiSelectedSymbol,
        timeframe: aiConfig.timeframe,
        lookback_days: Number(aiConfig.lookback_days) || 90,
        recalibrate: aiConfig.recalibrate,
      })
      setAiEvalResult(res.data)
    } catch (e) {
      alert('Error en evaluación IA: ' + (e.response?.data?.detail || e.message))
    } finally {
      setAiEvalLoading(false)
    }
  }

  async function recalibrateAI() {
    if (!selectedStrategy?.id || !aiSelectedSymbol) return
    setAiRecalLoading(true)
    try {
      const res = await montecarloService.recalibrateAI({
        strategy_id: selectedStrategy.id,
        symbol: aiSelectedSymbol,
        timeframe: aiConfig.timeframe,
        lookback_days: Number(aiConfig.lookback_days) || 90,
      })
      // Merge recalibration results into eval result
      setAiEvalResult(prev => prev ? { ...prev, recalibration: res.data } : null)
    } catch (e) {
      alert('Error recalibrando: ' + (e.response?.data?.detail || e.message))
    } finally {
      setAiRecalLoading(false)
    }
  }

  async function runBatchEval() {
    if (!selectedStrategy?.id) {
      alert('Guarda primero la estrategia')
      return
    }
    if (!aiBatchSymbols.length) {
      alert('Selecciona al menos un par')
      return
    }
    setAiBatchLoading(true)
    try {
      const evaluations = aiBatchSymbols.map(sym => ({
        symbol: sym,
        timeframe: aiConfig.timeframe,
      }))
      const res = await montecarloService.evalBatch({
        strategy_id: selectedStrategy.id,
        evaluations,
        lookback_days: Number(aiConfig.lookback_days) || 90,
        recalibrate: aiConfig.recalibrate,
      })
      setAiBatchResults(res.data?.results || [])
    } catch (e) {
      alert('Error en evaluación batch: ' + (e.response?.data?.detail || e.message))
    } finally {
      setAiBatchLoading(false)
    }
  }

  function normalizeSymbol(raw) {
    if (!raw) return ''
    const s = raw.toUpperCase().trim()
    // Ya formato CCXT
    if (s.includes('/') && s.includes(':')) return s
    if (s.includes('/')) {
      const base = s.split('/')[0]
      const quote = s.split('/')[1].replace(':USDT', '').replace(':USDC', '')
      if (quote === 'USDT' || quote === 'USDC') return `${base}/${quote}:${quote}`
      return s
    }
    // Formato compacto: BTCUSDT, BTC-USDT, BTC_USDT
    for (const quote of ['USDT', 'USDC', 'BTC', 'ETH', 'USD']) {
      if (s.endsWith(quote)) {
        const base = s.slice(0, -quote.length).replace(/[-_]/g, '')
        if (quote === 'USDT' || quote === 'USDC') return `${base}/${quote}:${quote}`
        return `${base}/${quote}:${quote}`
      }
    }
    return s
  }

  function filterSymbols(query) {
    if (!query) return []
    const q = query.toUpperCase()
    return (symbols || []).filter(s =>
      (s.symbol || '').toUpperCase().includes(q) ||
      (s.description || '').toUpperCase().includes(q)
    ).slice(0, 8)
  }

  function toggleBatchSymbol(symbol) {
    setAiBatchSymbols(prev =>
      prev.includes(symbol)
        ? prev.filter(s => s !== symbol)
        : [...prev, symbol]
    )
  }

  async function applyEvalToBot(result, botId) {
    if (!botId) {
      alert('Selecciona un bot para aplicar')
      return
    }
    try {
      const res = await montecarloService.applyEvalToBot({
        bot_id: botId,
        symbol: result.symbol,
        timeframe: result.timeframe,
        strategy_id: selectedStrategy.id,
        setup_base: mcSetupBaseEnabled,
      })
      alert(res.data?.message || 'Bot actualizado')
    } catch (e) {
      const detail = e.response?.data?.detail || e.response?.data?.message || e.message
      alert('Error aplicando config: ' + (typeof detail === 'object' ? JSON.stringify(detail) : detail))
    }
  }

  async function runBacktest() {
    if (!selectedStrategy?.id) {
      alert('Guarda primero la estrategia')
      return
    }
    setBacktestLoading(true)
    try {
      // Extraer valores planos de parámetros
      const params = {}
      Object.entries(strategyForm.parameters || {}).forEach(([k, v]) => {
        params[k] = typeof v === 'object' && v !== null ? (v.value ?? v.default) : v
      })

      const req = {
        ...backtestConfig,
        from_date: new Date(backtestConfig.from_date).toISOString(),
        to_date: new Date(backtestConfig.to_date + 'T23:59:59').toISOString(),
        parameters: params,
      }

      const res = await montecarloService.runBacktest(selectedStrategy.id, req)
      setBacktestResult(res.data)
    } catch (e) {
      console.error('[MC] Backtest error:', e.response?.data || e.message)
      alert('Error en backtest: ' + (e.response?.data?.detail || e.message))
    } finally {
      setBacktestLoading(false)
    }
  }

  async function runSimulation() {
    if (!backtestResult?.id) {
      alert('Ejecuta primero un backtest')
      return
    }
    setSimLoading(true)
    try {
      const res = await montecarloService.runSimulation(backtestResult.id, {
        simulation_type: simConfig.simulation_type,
        n_simulations: simConfig.n_simulations,
        save_equity_curves: simConfig.save_equity_curves,
      })
      setSimResult(res.data)
    } catch (e) {
      alert('Error en simulación: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSimLoading(false)
    }
  }

  // ── Datos para gráficos de distribución ──
  const ddDistribution = useMemo(() => {
    if (!simResult?.result?.percentiles?.max_drawdown) return []
    const p = simResult.result.percentiles.max_drawdown
    return [
      { name: 'p5 (peor)', value: Math.abs(Math.min(0, p.p5)) * 100 },
      { name: 'p50 (mediana)', value: Math.abs(Math.min(0, p.p50)) * 100 },
      { name: 'p95 (mejor)', value: Math.abs(Math.min(0, p.p95)) * 100 },
      { name: 'Original', value: Math.abs(Math.min(0, simResult.result.original_metrics.max_drawdown)) * 100 },
    ]
  }, [simResult])

  const cagrDistribution = useMemo(() => {
    if (!simResult?.result?.percentiles?.cagr) return []
    const p = simResult.result.percentiles.cagr
    return [
      { name: 'p5 (peor)', value: Math.max(0, p.p5) * 100 },
      { name: 'p50 (mediana)', value: Math.max(0, p.p50) * 100 },
      { name: 'p95 (mejor)', value: p.p95 * 100 },
      { name: 'Original', value: Math.max(0, simResult.result.original_metrics.cagr) * 100 },
    ]
  }, [simResult])

  // ── Render ──
  return (
    <div className="space-y-4 p-4 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
          <Dices size={28} className="text-blue-500" />
          Monte Carlo
        </h1>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setAiPanelOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold transition-colors"
          >
            <Sparkles size={14} />
            IA ENGINE
          </button>
          <div className="text-xs text-slate-500 dark:text-gray-400">
            Validación estadística de estrategias
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* ── Panel Izquierdo: Estrategias ── */}
        <div className="lg:col-span-3 space-y-3">
          {/* Lista */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-3">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200 flex items-center gap-1">
                <Brain size={14} /> Estrategias
              </h2>
              <div className="flex items-center gap-2">
                <label className="text-xs flex items-center gap-1 text-blue-500 hover:text-blue-600 cursor-pointer">
                  <Upload size={14} />
                  <span>Adjuntar .py</span>
                  <input
                    type="file"
                    accept=".py"
                    className="hidden"
                    onChange={e => {
                      const file = e.target.files?.[0]
                      if (!file) return
                      const reader = new FileReader()
                      reader.onload = ev => {
                        const code = String(ev.target?.result || '')
                        setSelectedStrategy(null)
                        setStrategyForm(prev => ({
                          ...prev,
                          name: file.name.replace(/\.py$/, ''),
                          code,
                          description: `Estrategia cargada desde ${file.name}`,
                        }))
                      }
                      reader.readAsText(file)
                      e.target.value = ''
                    }}
                  />
                </label>
                <button onClick={newStrategy} className="text-xs flex items-center gap-1 text-blue-500 hover:text-blue-600">
                  <Plus size={14} /> Nueva
                </button>
              </div>
            </div>
            {loadingStrategies ? (
              <LoadingSpinner />
            ) : (
              <div className="space-y-1 max-h-48 overflow-auto">
                {Array.isArray(strategies) && strategies.map(s => (
                  <div
                    key={s.id}
                    onClick={() => selectStrategy(s)}
                    className={classNames(
                      'flex items-center justify-between px-2 py-1.5 rounded cursor-pointer text-xs',
                      selectedStrategy?.id === s.id
                        ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                        : 'hover:bg-slate-50 dark:hover:bg-gray-700/50 text-slate-700 dark:text-gray-300'
                    )}
                  >
                    <span className="truncate">{s.name}</span>
                    <button
                      onClick={e => { e.stopPropagation(); deleteStrategy(s.id) }}
                      className="text-slate-400 hover:text-red-500"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
                {strategies.length === 0 && (
                  <p className="text-xs text-slate-400 text-center py-4">No hay estrategias</p>
                )}
              </div>
            )}
          </div>

          {/* Editor */}
          <StrategyEditor
            strategy={strategyForm}
            onChange={setStrategyForm}
            onSave={saveStrategy}
            onRun={runBacktest}
          />

          {/* Parámetros */}
          <StrategyParams
            params={strategyForm.parameters}
            onChange={p => setStrategyForm(prev => ({ ...prev, parameters: p }))}
          />
        </div>

        {/* ── Panel Central: Backtest ── */}
        <div className="lg:col-span-5 space-y-3">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200 mb-3 flex items-center gap-2">
              <BarChart3 size={16} /> Configuración Backtest
            </h2>
            <div className="grid grid-cols-2 gap-2 mb-3">
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Símbolo</label>
                <select
                  className="input w-full text-xs"
                  value={backtestConfig.symbol}
                  onChange={e => setBacktestConfig(p => ({ ...p, symbol: e.target.value }))}
                >
                  {Array.isArray(symbols) && symbols.map(s => (
                    <option key={s.symbol} value={s.symbol}>{s.description || s.symbol}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Timeframe</label>
                <select
                  className="input w-full text-xs"
                  value={backtestConfig.timeframe}
                  onChange={e => setBacktestConfig(p => ({ ...p, timeframe: e.target.value }))}
                >
                  {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Desde</label>
                <input
                  type="date"
                  className="input w-full text-xs"
                  value={backtestConfig.from_date}
                  onChange={e => setBacktestConfig(p => ({ ...p, from_date: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Hasta</label>
                <input
                  type="date"
                  className="input w-full text-xs"
                  value={backtestConfig.to_date}
                  onChange={e => setBacktestConfig(p => ({ ...p, to_date: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Capital Inicial</label>
                <input
                  type="number"
                  className="input w-full text-xs"
                  value={backtestConfig.initial_capital}
                  onChange={e => setBacktestConfig(p => ({ ...p, initial_capital: Number(e.target.value) }))}
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Fee %</label>
                <input
                  type="number"
                  step="0.0001"
                  className="input w-full text-xs"
                  value={backtestConfig.fee_rate}
                  onChange={e => setBacktestConfig(p => ({ ...p, fee_rate: Number(e.target.value) }))}
                />
              </div>
            </div>
            <button
              onClick={runBacktest}
              disabled={backtestLoading || !selectedStrategy}
              className="btn-primary w-full text-xs flex items-center justify-center gap-1"
            >
              {backtestLoading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {backtestLoading ? 'Ejecutando...' : 'Ejecutar Backtest'}
            </button>
          </div>

          {/* Resultados Backtest */}
          {backtestResult && (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200 flex items-center gap-2">
                  <TrendingUp size={16} /> Resultados Backtest
                </h2>
                <span className={classNames('text-xs px-2 py-0.5 rounded-full', backtestResult.status === 'completed' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300')}>
                  {backtestResult.status}
                </span>
              </div>

              {/* Métricas */}
              <div className="grid grid-cols-4 gap-2">
                {[
                  { label: 'Trades', value: backtestResult.metrics.total_trades },
                  { label: 'Win Rate', value: fmtPct(backtestResult.metrics.win_rate) },
                  { label: 'Sharpe', value: fmtNum(backtestResult.metrics.sharpe_ratio) },
                  { label: 'Max DD', value: fmtPct(backtestResult.metrics.max_drawdown_pct) },
                  { label: 'CAGR', value: fmtPct(backtestResult.metrics.cagr) },
                  { label: 'Profit Factor', value: backtestResult.metrics.profit_factor ?? '-' },
                  { label: 'Expectancy', value: fmtPct(backtestResult.metrics.expectancy) },
                  { label: 'Retorno Total', value: fmtPct(backtestResult.metrics.total_return_pct) },
                ].map(m => (
                  <div key={m.label} className="bg-slate-50 dark:bg-gray-700/30 rounded p-2 text-center">
                    <p className="text-[10px] text-slate-500 dark:text-gray-400">{m.label}</p>
                    <p className="text-sm font-bold font-mono text-slate-800 dark:text-gray-100">{m.value}</p>
                  </div>
                ))}
              </div>

              {/* Equity Curve */}
              <EquityChart equityCurve={backtestResult.equity_curve} />

              {/* Trades */}
              <TradesTable trades={backtestResult.trades} />
            </div>
          )}
        </div>

        {/* ── Panel Derecho: Monte Carlo ── */}
        <div className="lg:col-span-4 space-y-3">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-gray-200 mb-3 flex items-center gap-2">
              <Dices size={16} /> Simulación Monte Carlo
            </h2>
            <div className="grid grid-cols-2 gap-2 mb-3">
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Tipo</label>
                <select
                  className="input w-full text-xs"
                  value={simConfig.simulation_type}
                  onChange={e => setSimConfig(p => ({ ...p, simulation_type: e.target.value }))}
                >
                  {SIMULATION_TYPES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 dark:text-gray-400">Simulaciones</label>
                <input
                  type="number"
                  step="1000"
                  min="100"
                  max="50000"
                  className="input w-full text-xs"
                  value={simConfig.n_simulations}
                  onChange={e => setSimConfig(p => ({ ...p, n_simulations: Number(e.target.value) }))}
                />
              </div>
            </div>
            <button
              onClick={runSimulation}
              disabled={simLoading || !backtestResult}
              className="btn-primary w-full text-xs flex items-center justify-center gap-1"
            >
              {simLoading ? <Loader2 size={14} className="animate-spin" /> : <Dices size={14} />}
              {simLoading ? 'Simulando...' : 'Ejecutar Simulación'}
            </button>
          </div>

          {/* Resultados Simulación */}
          {simResult && (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-4 space-y-4">
              {/* Gauge */}
              <div className="flex justify-center">
                <ScoreGauge
                  score={simResult.validation.score}
                  passed={simResult.validation.passed}
                />
              </div>

              {/* Recomendación */}
              <div className={classNames(
                'text-xs p-2 rounded-lg',
                simResult.validation.passed
                  ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300'
                  : 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300'
              )}>
                {simResult.validation.passed
                  ? <span className="flex items-center gap-1"><CheckCircle2 size={14} /> Estrategia válida. Puede operar.</span>
                  : <span className="flex items-center gap-1"><AlertTriangle size={14} /> {simResult.validation.failures.join(', ')}</span>
                }
              </div>

              {/* Métricas Fijas (invariantes a permutación) */}
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-slate-50 dark:bg-gray-700/30 rounded p-2">
                  <p className="text-[10px] text-slate-500 dark:text-gray-400">Sharpe Ratio</p>
                  <p className="text-sm font-bold font-mono text-slate-700 dark:text-gray-200">
                    {fmtNum(simResult.result.original_metrics.sharpe, 2)}
                  </p>
                  <p className="text-[9px] text-slate-400 dark:text-gray-500">invariante al orden</p>
                </div>
                <div className="bg-slate-50 dark:bg-gray-700/30 rounded p-2">
                  <p className="text-[10px] text-slate-500 dark:text-gray-400">Win Rate</p>
                  <p className="text-sm font-bold font-mono text-slate-700 dark:text-gray-200">
                    {fmtPct(simResult.result.original_metrics.win_rate)}
                  </p>
                  <p className="text-[9px] text-slate-400 dark:text-gray-500">invariante al orden</p>
                </div>
              </div>

              {/* Métricas con Distribución (variantes a permutación) */}
              <div>
                <h3 className="text-xs font-semibold text-slate-600 dark:text-gray-300 mb-2">Métricas Sensibles al Orden</h3>

                {/* Max Drawdown */}
                {ddDistribution.length > 0 && (
                  <div className="mb-3">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs text-slate-500 dark:text-gray-400">Max Drawdown (%)</span>
                      <span className="text-[10px] font-mono text-slate-400">
                        p5: {fmtNum(Math.abs(simResult.result.percentiles.max_drawdown?.p5 || 0) * 100, 1)}% | 
                        p50: {fmtNum(Math.abs(simResult.result.percentiles.max_drawdown?.p50 || 0) * 100, 1)}% | 
                        p95: {fmtNum(Math.abs(simResult.result.percentiles.max_drawdown?.p95 || 0) * 100, 1)}%
                      </span>
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={ddDistribution} barCategoryGap="20%">
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.2} />
                        <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} />
                        <YAxis tick={{ fontSize: 10 }} axisLine={false} width={40} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: 8, fontSize: 12 }}
                          itemStyle={{ color: '#e2e8f0' }}
                          formatter={(v) => [`${Number(v).toFixed(2)}%`, 'Drawdown']}
                        />
                        <Bar dataKey="value" fill="#ef4444" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* CAGR */}
                {cagrDistribution.length > 0 && (
                  <div>
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs text-slate-500 dark:text-gray-400">CAGR (%)</span>
                      <span className="text-[10px] font-mono text-slate-400">
                        p5: {fmtNum((simResult.result.percentiles.cagr?.p5 || 0) * 100, 1)}% | 
                        p50: {fmtNum((simResult.result.percentiles.cagr?.p50 || 0) * 100, 1)}% | 
                        p95: {fmtNum((simResult.result.percentiles.cagr?.p95 || 0) * 100, 1)}%
                      </span>
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={cagrDistribution} barCategoryGap="20%">
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.2} />
                        <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} />
                        <YAxis tick={{ fontSize: 10 }} axisLine={false} width={40} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: 8, fontSize: 12 }}
                          itemStyle={{ color: '#e2e8f0' }}
                          formatter={(v) => [`${Number(v).toFixed(2)}%`, 'CAGR']}
                        />
                        <Bar dataKey="value" fill="#22c55e" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>

              {/* Probabilidades */}
              <div>
                <h3 className="text-xs font-semibold text-slate-600 dark:text-gray-300 mb-2">Probabilidades Clave</h3>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { label: 'Profit > 0', value: simResult.result.probabilities.profit, good: true },
                    { label: 'Sharpe > 1', value: simResult.result.probabilities.sharpe_above_1, good: true },
                    { label: 'DD < 20%', value: simResult.result.probabilities.dd_below_20pct, good: true },
                    { label: 'Ruina (DD>50%)', value: simResult.result.probabilities.ruin, good: false },
                  ].map(p => (
                    <div key={p.label} className="bg-slate-50 dark:bg-gray-700/30 rounded p-2">
                      <p className="text-[10px] text-slate-500 dark:text-gray-400">{p.label}</p>
                      <p className={classNames(
                        'text-sm font-bold font-mono',
                        p.good
                          ? (p.value >= 0.5 ? 'text-green-500' : 'text-yellow-500')
                          : (p.value <= 0.05 ? 'text-green-500' : 'text-red-500')
                      )}>
                        {fmtPct(p.value)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Checks */}
              <div>
                <h3 className="text-xs font-semibold text-slate-600 dark:text-gray-300 mb-2">Validación de Umbrales</h3>
                <div className="space-y-1">
                  {Object.entries(simResult.validation.checks).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between text-xs">
                      <span className="text-slate-600 dark:text-gray-300 capitalize">{k.replace(/_/g, ' ')}</span>
                      {v
                        ? <CheckCircle2 size={14} className="text-green-500" />
                        : <XCircle size={14} className="text-red-500" />
                      }
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    {/* ═══════════════════════════════════════════════════════════════
        IA ENGINE MODAL
    ═══════════════════════════════════════════════════════════════ */}
    {aiPanelOpen && (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-slate-200 dark:border-gray-700 shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-auto">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-gray-800">
            <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Sparkles size={22} className="text-purple-500" />
              IA ENGINE — Evaluación Inteligente
            </h2>
            <button onClick={() => setAiPanelOpen(false)} className="text-slate-400 hover:text-slate-600 dark:hover:text-gray-300">
              <XCircle size={20} />
            </button>
          </div>

          <div className="p-4 space-y-4">
            {/* Tabs: Individual vs Batch */}
            <div className="flex gap-2 border-b border-slate-200 dark:border-gray-700 pb-2">
              <button
                onClick={() => setAiBatchTab('single')}
                className={classNames(
                  'px-3 py-1.5 text-xs font-semibold rounded-t-lg transition-colors',
                  aiBatchTab === 'single'
                    ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 border-b-2 border-purple-500'
                    : 'text-slate-500 dark:text-gray-400 hover:text-slate-700'
                )}
              >
                Evaluación Individual
              </button>
              <button
                onClick={() => setAiBatchTab('batch')}
                className={classNames(
                  'px-3 py-1.5 text-xs font-semibold rounded-t-lg transition-colors',
                  aiBatchTab === 'batch'
                    ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 border-b-2 border-purple-500'
                    : 'text-slate-500 dark:text-gray-400 hover:text-slate-700'
                )}
              >
                Evaluación Múltiple
              </button>
            </div>

            {aiBatchTab === 'single' ? (
              <>
                {/* Paso 1: Selección de par */}
                <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-200 flex items-center gap-2">
                      <Scan size={16} /> 1. Selecciona Par / Timeframe
                    </h3>
                    <button
                      onClick={loadAIWatchlist}
                      disabled={aiScanLoading || !selectedStrategy}
                      className="btn-secondary text-xs flex items-center gap-1"
                    >
                      {aiScanLoading ? <Loader2 size={12} className="animate-spin" /> : <Scan size={12} />}
                      Escanear Watchlist
                    </button>
                  </div>

                  {/* Input manual con autocompletado */}
                  <div className="grid grid-cols-1 gap-2 mb-3">
                    <div className="flex gap-2">
                      <div className="relative w-full" ref={suggestionsRef}>
                        <input
                          ref={symbolInputRef}
                          type="text"
                          placeholder="Escribe par ej: BTCUSDT o BTC/USDT:USDT"
                          className="input w-full text-sm"
                          value={aiSelectedSymbol}
                          onChange={e => {
                            const val = e.target.value.toUpperCase()
                            setAiSelectedSymbol(val)
                            setSymbolSuggestions(filterSymbols(val))
                            setShowSuggestions(true)
                          }}
                          onFocus={() => {
                            if (aiSelectedSymbol) {
                              setSymbolSuggestions(filterSymbols(aiSelectedSymbol))
                              setShowSuggestions(true)
                            }
                          }}
                          onKeyDown={e => {
                            if (e.key === 'Enter' && symbolSuggestions.length > 0) {
                              const first = symbolSuggestions[0]
                              setAiSelectedSymbol(first.symbol)
                              setShowSuggestions(false)
                            }
                            if (e.key === 'Escape') {
                              setShowSuggestions(false)
                            }
                          }}
                        />
                        {showSuggestions && symbolSuggestions.length > 0 && (
                          <div className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                            {symbolSuggestions.map(s => (
                              <button
                                key={s.symbol}
                                type="button"
                                onClick={() => {
                                  setAiSelectedSymbol(s.symbol)
                                  setShowSuggestions(false)
                                }}
                                className="w-full text-left px-3 py-2 text-xs hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors"
                              >
                                <span className="font-mono font-semibold">{s.symbol}</span>
                                <span className="text-slate-400 ml-2">{s.description}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                      <select
                        className="input w-32 text-sm shrink-0"
                        value={aiConfig.timeframe}
                        onChange={e => setAiConfig(p => ({ ...p, timeframe: e.target.value }))}
                      >
                        {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                      </select>
                    </div>
                    <select
                      className="input w-full text-sm"
                      value={aiSelectedSymbol}
                      onChange={e => setAiSelectedSymbol(e.target.value)}
                    >
                      <option value="">— O selecciona de la lista —</option>
                      {Array.isArray(symbols) && symbols.map(s => (
                        <option key={s.symbol} value={s.symbol}>{s.description || s.symbol}</option>
                      ))}
                    </select>
                  </div>

                  {/* Watchlist grid */}
                  {aiWatchlist.length > 0 && (
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                      {Array.isArray(aiWatchlist) && aiWatchlist.map(item => (
                        <button
                          key={item.symbol}
                          onClick={() => {
                            setAiSelectedSymbol(item.symbol)
                            setAiConfig(p => ({ ...p, timeframe: item.timeframe }))
                          }}
                          className={classNames(
                            'text-left p-2 rounded-lg border text-xs transition-all',
                            aiSelectedSymbol === item.symbol
                              ? 'border-purple-500 bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300'
                              : 'border-slate-200 dark:border-gray-700 hover:bg-slate-100 dark:hover:bg-gray-700/50'
                          )}
                        >
                          <div className="font-bold">{item.symbol}</div>
                          <div className="text-slate-500 dark:text-gray-400">{item.timeframe}</div>
                          {item.latest_scan?.score && (
                            <div className="mt-1 font-mono text-[10px]">
                              Score: {item.latest_scan.score}
                            </div>
                          )}
                          <div className={classNames('text-[10px] mt-0.5', item.ai_score >= 75 ? 'text-green-500' : item.ai_score >= 50 ? 'text-yellow-500' : 'text-red-500')}>
                            IA: {item.ai_score}/100
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                {/* BATCH: Selección múltiple de pares */}
                <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-200 flex items-center gap-2">
                      <Scan size={16} /> 1. Selecciona Pares + Timeframe
                    </h3>
                    <div className="text-xs text-slate-500">
                      {aiBatchSymbols.length} seleccionados
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-2 mb-3">
                    <div className="flex gap-2">
                      <div className="relative w-full" ref={batchSuggestionsRef}>
                        <input
                          ref={batchInputRef}
                          type="text"
                          placeholder="Añade par ej: BTCUSDT o BTC/USDT:USDT"
                          className="input w-full text-sm"
                          value={batchSymbolInput}
                          onChange={e => {
                            const val = e.target.value.toUpperCase()
                            setBatchSymbolInput(val)
                            setBatchSuggestions(filterSymbols(val))
                            setShowBatchSuggestions(true)
                          }}
                          onFocus={() => {
                            if (batchSymbolInput) {
                              setBatchSuggestions(filterSymbols(batchSymbolInput))
                              setShowBatchSuggestions(true)
                            }
                          }}
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              const sym = batchSymbolInput.trim()
                              if (sym) {
                                const normalized = batchSuggestions.length > 0 ? batchSuggestions[0].symbol : normalizeSymbol(sym)
                                if (normalized && !aiBatchSymbols.includes(normalized)) {
                                  setAiBatchSymbols(prev => [...prev, normalized])
                                }
                              }
                              setBatchSymbolInput('')
                              setShowBatchSuggestions(false)
                            }
                            if (e.key === 'Escape') {
                              setShowBatchSuggestions(false)
                            }
                          }}
                        />
                        {showBatchSuggestions && batchSuggestions.length > 0 && (
                          <div className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                            {batchSuggestions.map(s => (
                              <button
                                key={s.symbol}
                                type="button"
                                onClick={() => {
                                  if (!aiBatchSymbols.includes(s.symbol)) {
                                    setAiBatchSymbols(prev => [...prev, s.symbol])
                                  }
                                  setBatchSymbolInput('')
                                  setShowBatchSuggestions(false)
                                }}
                                className="w-full text-left px-3 py-2 text-xs hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors"
                              >
                                <span className="font-mono font-semibold">{s.symbol}</span>
                                <span className="text-slate-400 ml-2">{s.description}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                      <select
                        className="input w-32 text-sm shrink-0"
                        value={aiConfig.timeframe}
                        onChange={e => setAiConfig(p => ({ ...p, timeframe: e.target.value }))}
                      >
                        {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
                      </select>
                    </div>
                    {aiBatchSymbols.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {aiBatchSymbols.map(sym => (
                          <span key={sym} className="inline-flex items-center gap-1 text-[10px] bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 px-1.5 py-0.5 rounded">
                            {sym}
                            <button onClick={() => toggleBatchSymbol(sym)} className="hover:text-red-500">×</button>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="max-h-48 overflow-y-auto border border-slate-200 dark:border-gray-700 rounded-lg">
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1 p-2">
                      {Array.isArray(symbols) && symbols.map(s => (
                        <label
                          key={s.symbol}
                          className={classNames(
                            'flex items-center gap-1.5 p-1.5 rounded cursor-pointer text-xs transition-all',
                            aiBatchSymbols.includes(s.symbol)
                              ? 'bg-purple-100 dark:bg-purple-900/20 border border-purple-300'
                              : 'hover:bg-slate-100 dark:hover:bg-gray-700/50'
                          )}
                        >
                          <input
                            type="checkbox"
                            checked={aiBatchSymbols.includes(s.symbol)}
                            onChange={() => toggleBatchSymbol(s.symbol)}
                            className="accent-purple-500"
                          />
                          <span className="truncate">{s.description || s.symbol}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={() => setAiBatchSymbols([])}
                      className="btn-secondary text-xs px-2 py-1"
                    >
                      Limpiar
                    </button>
                    <button
                      onClick={() => setAiBatchSymbols(symbols.map(s => s.symbol))}
                      className="btn-secondary text-xs px-2 py-1"
                    >
                      Seleccionar todos
                    </button>
                    <button
                      onClick={runBatchEval}
                      disabled={aiBatchLoading || !selectedStrategy || aiBatchSymbols.length === 0}
                      className="btn-primary text-xs flex items-center gap-1 ml-auto"
                    >
                      {aiBatchLoading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                      {aiBatchLoading ? 'Evaluando...' : 'EVALUAR SELECCIONADOS'}
                    </button>
                  </div>
                </div>

                {/* BATCH: Resultados comparativos */}
                {aiBatchResults && aiBatchResults.length > 0 && (
                  <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-200 flex items-center gap-2">
                        <BarChart3 size={16} /> Resultados Comparativos
                      </h3>
                      <button
                        onClick={() => setAiBatchResults(null)}
                        className="text-[10px] text-slate-500 hover:text-red-500 border border-slate-200 dark:border-gray-700 hover:border-red-300 rounded px-2 py-1 flex items-center gap-1 transition-colors"
                      >
                        <X size={10} /> Limpiar resultados
                      </button>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-slate-200 dark:border-gray-700 text-slate-500 dark:text-gray-400">
                            <th className="text-left py-2 px-1">Par</th>
                            <th className="text-center py-2 px-1">AI Score</th>
                            <th className="text-center py-2 px-1">MC Score</th>
                            <th className="text-center py-2 px-1">Joint</th>
                            <th className="text-center py-2 px-1">Estado</th>
                            <th className="text-right py-2 px-1">Acción</th>
                          </tr>
                        </thead>
                        <tbody>
                          {aiBatchResults.map((r, idx) => (
                            <tr key={idx} className="border-b border-slate-100 dark:border-gray-800">
                              <td className="py-2 px-1 font-mono">{r.symbol}</td>
                              <td className="text-center py-2 px-1">{r.ai_score.toFixed(1)}</td>
                              <td className="text-center py-2 px-1">{r.mc_score.toFixed(1)}</td>
                              <td className="text-center py-2 px-1 font-bold">
                                <span className={r.joint_score >= 60 ? 'text-green-500' : 'text-red-500'}>
                                  {r.joint_score.toFixed(1)}
                                </span>
                              </td>
                              <td className="text-center py-2 px-1">
                                {r.passed ? (
                                  <span className="text-green-500 text-[10px] bg-green-100 dark:bg-green-900/20 px-1.5 py-0.5 rounded">OPERAR</span>
                                ) : (
                                  <span className="text-red-500 text-[10px] bg-red-100 dark:bg-red-900/20 px-1.5 py-0.5 rounded">NO</span>
                                )}
                              </td>
                              <td className="text-right py-2 px-1">
                                <div className="flex items-center gap-2 justify-end">
                                  <label className="flex items-center gap-1 text-[10px] text-slate-500 dark:text-gray-400 cursor-pointer">
                                    <input
                                      type="checkbox"
                                      checked={mcSetupBaseEnabled}
                                      onChange={e => setMcSetupBaseEnabled(e.target.checked)}
                                      className="rounded"
                                    />
                                    Setup Base IA
                                  </label>
                                  <button
                                    onClick={() => {
                                      const botId = prompt(`¿A qué bot quieres aplicar ${r.symbol} ${r.timeframe}?\n\nIntroduce el nombre del bot o su UUID:`)
                                      if (botId) applyEvalToBot(r, botId)
                                    }}
                                    className={classNames(
                                      "text-[10px] px-2 py-1 rounded",
                                      r.joint_score >= 60
                                        ? "bg-purple-600 hover:bg-purple-700 text-white"
                                        : "bg-slate-400 hover:bg-slate-500 text-white"
                                    )}
                                  >
                                    Aplicar a Bot
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {/* Paso 2: Configuración */}
            <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-gray-200 mb-3 flex items-center gap-2">
                <Target size={16} /> 2. Configuración
              </h3>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-[10px] text-slate-500 dark:text-gray-400">Lookback (días)</label>
                  <input
                    type="number"
                    min="30"
                    max="180"
                    className="input w-full text-xs"
                    value={aiConfig.lookback_days}
                    onChange={e => {
                      const raw = e.target.value
                      if (raw === '') {
                        setAiConfig(p => ({ ...p, lookback_days: '' }))
                      } else {
                        const num = Number(raw)
                        if (!Number.isNaN(num)) {
                          setAiConfig(p => ({ ...p, lookback_days: num }))
                        }
                      }
                    }}
                  />
                </div>
                <div className="flex items-center gap-2 pt-4">
                  <input
                    type="checkbox"
                    id="recalibrate"
                    checked={aiConfig.recalibrate}
                    onChange={e => setAiConfig(p => ({ ...p, recalibrate: e.target.checked }))}
                  />
                  <label htmlFor="recalibrate" className="text-xs text-slate-600 dark:text-gray-300 cursor-pointer">
                    Recalibrar automáticamente
                  </label>
                </div>
                <div className="flex flex-col gap-1">
                  <button
                    onClick={evaluateAI}
                    disabled={aiEvalLoading || !selectedStrategy || !aiSelectedSymbol}
                    className="btn-primary w-full text-xs flex items-center justify-center gap-1"
                  >
                    {aiEvalLoading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                    {aiEvalLoading ? 'Evaluando...' : 'EVALUAR'}
                  </button>
                  {aiEvalResult && (
                    <button
                      onClick={() => setAiEvalResult(null)}
                      className="w-full text-xs text-slate-500 hover:text-red-500 border border-slate-200 dark:border-gray-700 hover:border-red-300 rounded px-2 py-1 flex items-center justify-center gap-1 transition-colors"
                    >
                      <X size={12} /> Limpiar resultados
                    </button>
                  )}
                  {(!selectedStrategy || !aiSelectedSymbol) && (
                    <p className="text-[10px] text-red-400 text-center">
                      {!selectedStrategy && !Array.isArray(strategies)
                        ? 'Cargando estrategias...'
                        : !selectedStrategy && strategies.length === 0
                        ? 'Crea una estrategia en el panel izquierdo'
                        : !selectedStrategy
                        ? 'Selecciona una estrategia del panel izquierdo'
                        : !aiSelectedSymbol
                        ? 'Selecciona un par'
                        : ''}
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Paso 3: Resultados */}
            {aiEvalResult && (
              <div className="space-y-4">
                {/* Joint Score */}
                <div className="flex justify-center">
                  <div className="text-center">
                    <ScoreGauge
                      score={aiEvalResult.joint_score}
                      passed={aiEvalResult.joint_score >= 60}
                    />
                    <p className={classNames(
                      'text-sm font-bold mt-1',
                      aiEvalResult.joint_score >= 75 ? 'text-green-500' :
                      aiEvalResult.joint_score >= 50 ? 'text-yellow-500' : 'text-red-500'
                    )}>
                      {aiEvalResult.recommendation}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {/* Columna IA */}
                  <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-3">
                    <h4 className="text-xs font-bold text-slate-700 dark:text-gray-200 mb-2 flex items-center gap-1">
                      <Brain size={14} className="text-blue-500" /> Señal IA
                    </h4>
                    {aiEvalResult.ai_signal?.status === 'NO_SIGNAL' ? (
                      <p className="text-xs text-slate-500">Sin señal activa</p>
                    ) : aiEvalResult.ai_signal ? (
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-500">Score</span>
                          <span className="font-mono font-bold">{aiEvalResult.ai_signal.score}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Dirección</span>
                          <span className={aiEvalResult.ai_signal.direction === 'long' ? 'text-green-500' : 'text-red-500'}>
                            {aiEvalResult.ai_signal.direction?.toUpperCase()}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Tier</span>
                          <span>{aiEvalResult.ai_signal.quality_tier}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Status</span>
                          <span>{aiEvalResult.ai_signal.anti_fake_status}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Prob. Éxito</span>
                          <span className="font-mono">{fmtPct(aiEvalResult.ai_signal.success_probability)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Entry</span>
                          <span className="font-mono">{fmtNum(aiEvalResult.ai_signal.entry_price)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">SL</span>
                          <span className="font-mono text-red-400">{fmtNum(aiEvalResult.ai_signal.stop_loss)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">TP1</span>
                          <span className="font-mono text-green-400">{fmtNum(aiEvalResult.ai_signal.take_profit_1)}</span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">No disponible</p>
                    )}
                    <div className="mt-2 pt-2 border-t border-slate-100 dark:border-gray-700">
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-500">AI Score</span>
                        <span className="font-bold">{aiEvalResult.ai_score}/100</span>
                      </div>
                    </div>
                  </div>

                  {/* Columna Backtest */}
                  <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-3">
                    <h4 className="text-xs font-bold text-slate-700 dark:text-gray-200 mb-2 flex items-center gap-1">
                      <TrendingUp size={14} className="text-green-500" /> Backtest Estrategia
                    </h4>
                    {aiEvalResult.backtest?.metrics ? (
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-500">Trades</span>
                          <span className="font-mono">{aiEvalResult.backtest.metrics.total_trades}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Win Rate</span>
                          <span className={classNames('font-mono', aiEvalResult.backtest.metrics.win_rate >= 0.5 ? 'text-green-500' : 'text-red-500')}>
                            {fmtPct(aiEvalResult.backtest.metrics.win_rate)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Sharpe</span>
                          <span className="font-mono">{fmtNum(aiEvalResult.backtest.metrics.sharpe_ratio)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Max DD</span>
                          <span className="font-mono text-red-400">{fmtPct(aiEvalResult.backtest.metrics.max_drawdown_pct)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">CAGR</span>
                          <span className="font-mono">{fmtPct(aiEvalResult.backtest.metrics.cagr)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Profit Factor</span>
                          <span className="font-mono">{aiEvalResult.backtest.metrics.profit_factor ?? '-'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Expectancy</span>
                          <span className="font-mono">{fmtPct(aiEvalResult.backtest.metrics.expectancy)}</span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">Sin datos de backtest</p>
                    )}
                  </div>

                  {/* Columna Monte Carlo */}
                  <div className="bg-white dark:bg-gray-800 rounded-xl border border-slate-200 dark:border-gray-700 p-3">
                    <h4 className="text-xs font-bold text-slate-700 dark:text-gray-200 mb-2 flex items-center gap-1">
                      <Dices size={14} className="text-purple-500" /> Monte Carlo
                    </h4>
                    {aiEvalResult.monte_carlo?.validation ? (
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-slate-500">Score MC</span>
                          <span className="font-mono font-bold">{aiEvalResult.monte_carlo.validation.score}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Aprobado</span>
                          <span className={aiEvalResult.monte_carlo.validation.passed ? 'text-green-500' : 'text-red-500'}>
                            {aiEvalResult.monte_carlo.validation.passed ? 'SÍ' : 'NO'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Prob. Profit</span>
                          <span className="font-mono">{fmtPct(aiEvalResult.monte_carlo.result?.probabilities?.profit)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Prob. Ruina</span>
                          <span className={classNames('font-mono', (aiEvalResult.monte_carlo.result?.probabilities?.ruin || 0) < 0.05 ? 'text-green-500' : 'text-red-500')}>
                            {fmtPct(aiEvalResult.monte_carlo.result?.probabilities?.ruin)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Sharpe p5</span>
                          <span className="font-mono">{fmtNum(aiEvalResult.monte_carlo.result?.percentiles?.sharpe?.p5)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">MaxDD p5</span>
                          <span className="font-mono text-red-400">{fmtPct(aiEvalResult.monte_carlo.result?.percentiles?.max_drawdown?.p5)}</span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">Sin simulación MC</p>
                    )}
                  </div>
                </div>

                {/* Aplicar a Bot — Evaluación Individual */}
                {selectedStrategy?.id && (
                  <div className="flex flex-col items-center gap-2 py-3">
                    {aiEvalResult.joint_score < 60 && (
                      <p className="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/20 px-2 py-1 rounded">
                        ⚠️ Joint score bajo ({aiEvalResult.joint_score.toFixed(1)}). Aplicar con precaución.
                      </p>
                    )}
                    <div className="flex items-center justify-center gap-3">
                      <label className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-gray-400 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={mcSetupBaseEnabled}
                          onChange={e => setMcSetupBaseEnabled(e.target.checked)}
                          className="rounded"
                        />
                        Setup Base IA
                      </label>
                      <button
                        onClick={() => {
                          const botId = prompt(`¿A qué bot quieres aplicar ${aiEvalResult.ai_signal?.symbol || aiSelectedSymbol} ${aiEvalResult.ai_signal?.timeframe || aiConfig.timeframe}?\n\nIntroduce el nombre del bot o su UUID:`)
                          if (botId) {
                            applyEvalToBot({
                              symbol: aiEvalResult.ai_signal?.symbol || aiSelectedSymbol,
                              timeframe: aiEvalResult.ai_signal?.timeframe || aiConfig.timeframe,
                            }, botId)
                          }
                        }}
                        className={classNames(
                          "text-xs px-3 py-1.5 rounded flex items-center gap-1",
                          aiEvalResult.joint_score >= 60
                            ? "bg-purple-600 hover:bg-purple-700 text-white"
                            : "bg-slate-400 hover:bg-slate-500 text-white"
                        )}
                      >
                        <Target size={12} /> Aplicar a Bot
                      </button>
                    </div>
                  </div>
                )}

                {/* Recalibración */}
                {aiEvalResult.joint_score < 60 && (
                  <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl border border-slate-200 dark:border-gray-700 p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-semibold text-slate-700 dark:text-gray-200 flex items-center gap-2">
                        <Wand2 size={16} className="text-purple-500" /> Recalibración Automática
                      </h4>
                      <button
                        onClick={recalibrateAI}
                        disabled={aiRecalLoading}
                        className="btn-secondary text-xs flex items-center gap-1"
                      >
                        {aiRecalLoading ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />}
                        {aiRecalLoading ? 'Recalibrando...' : 'Forzar Recalibración'}
                      </button>
                    </div>

                    {aiEvalResult.recalibration && (
                      <div className="space-y-2">
                        <p className="text-xs text-slate-600 dark:text-gray-300">
                          Joint Score después: <span className="font-bold">{aiEvalResult.recalibration.joint_score_after}</span>
                          {' — '}
                          <span className={aiEvalResult.recalibration.recommendation_after?.includes('OPERAR') ? 'text-green-500' : 'text-yellow-500'}>
                            {aiEvalResult.recalibration.recommendation_after}
                          </span>
                        </p>

                        {/* Tabla comparativa de parámetros */}
                        <div className="overflow-auto">
                          <table className="w-full text-xs">
                            <thead className="bg-slate-100 dark:bg-gray-700/50">
                              <tr>
                                <th className="px-2 py-1 text-left">Parámetro</th>
                                <th className="px-2 py-1 text-right">Antes</th>
                                <th className="px-2 py-1 text-right">Después</th>
                              </tr>
                            </thead>
                            <tbody>
                              {Object.entries(aiEvalResult.recalibration.best_params || {}).map(([k, v]) => (
                                <tr key={k} className="border-b border-slate-100 dark:border-gray-700/50">
                                  <td className="px-2 py-1 text-slate-600 dark:text-gray-300">{k}</td>
                                  <td className="px-2 py-1 text-right font-mono text-slate-500">
                                    {typeof strategyForm.parameters[k] === 'object'
                                      ? (strategyForm.parameters[k]?.value ?? strategyForm.parameters[k]?.default)
                                      : strategyForm.parameters[k]}
                                  </td>
                                  <td className="px-2 py-1 text-right font-mono text-purple-500 font-bold">
                                    {typeof v === 'number' ? v.toFixed(2) : v}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>

                        {/* Métricas recalibradas */}
                        {aiEvalResult.recalibration.metrics && (
                          <div className="grid grid-cols-4 gap-2 mt-2">
                            {[
                              { label: 'Win Rate', value: fmtPct(aiEvalResult.recalibration.metrics.win_rate) },
                              { label: 'Sharpe', value: fmtNum(aiEvalResult.recalibration.metrics.sharpe_ratio) },
                              { label: 'Max DD', value: fmtPct(aiEvalResult.recalibration.metrics.max_drawdown_pct) },
                              { label: 'Trades', value: aiEvalResult.recalibration.metrics.total_trades },
                            ].map(m => (
                              <div key={m.label} className="bg-white dark:bg-gray-700/30 rounded p-1.5 text-center">
                                <p className="text-[10px] text-slate-500">{m.label}</p>
                                <p className="text-xs font-bold font-mono">{m.value}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    )}
    </div>
  )
}
