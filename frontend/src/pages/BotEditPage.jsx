import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, Check, Copy, Eye, EyeOff, Loader2, Plus, Trash2 } from 'lucide-react'
import { botsService } from '@/services/bots'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import { paperTradingService } from '@/services/paperTrading'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

/* ─── Webhook display ─────────────────────────────────────── */
function WebhookUrlDisplay({ botId, secret }) {
  const [copied, setCopied] = useState(null)
  const [showSecret, setShowSecret] = useState(false)
  const [customHost, setCustomHost] = useState('')

  const origin = window.location.origin
  const isLocal = origin.includes('localhost') || origin.includes('127.0.0.1') || origin.includes('192.168.')
  const effectiveOrigin = customHost.trim() || origin
  const url = `${effectiveOrigin}/webhook/${botId}`

  const copy = (text, key) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 1500)
  }

  return (
    <div className="card space-y-3 mt-6">
      <h3 className="font-semibold text-sm text-slate-700 dark:text-gray-300">Webhook TradingView</h3>

      {/* Aviso si es localhost */}
      {isLocal && (
        <div className="flex items-start gap-2 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
          <AlertTriangle size={15} className="text-amber-400 shrink-0 mt-0.5" />
          <div className="text-xs text-amber-700 dark:text-amber-300 space-y-1">
            <p className="font-medium">Estás en localhost — TradingView no puede alcanzar esta URL.</p>
            <p>Usa un dominio público (ngrok, VPS, etc.) e introdúcelo abajo para generar la URL correcta.</p>
          </div>
        </div>
      )}

      {/* Campo para dominio público */}
      {isLocal && (
        <div>
          <p className="text-xs text-slate-500 dark:text-gray-400 mb-1">Dominio público (ngrok / VPS)</p>
          <input
            type="text"
            placeholder="https://abc123.ngrok-free.app"
            value={customHost}
            onChange={e => setCustomHost(e.target.value.replace(/\/$/, ''))}
            className="w-full bg-white dark:bg-gray-800 border border-slate-300 dark:border-gray-700 text-xs text-slate-700 dark:text-gray-300 rounded px-3 py-2"
          />
        </div>
      )}

      <div>
        <p className="text-xs text-slate-500 dark:text-gray-400 mb-1">URL del Webhook</p>
        <div className="flex items-center gap-2">
          <code className={`flex-1 border rounded px-3 py-2 text-xs font-mono truncate ${
            isLocal && !customHost
              ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-300'
              : 'bg-slate-100 dark:bg-gray-900 border-slate-300 dark:border-gray-700 text-blue-600 dark:text-blue-300'
          }`}>
            {url}
          </code>
          <button onClick={() => copy(url, 'url')} className="btn-ghost p-2">
            {copied === 'url' ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
          </button>
        </div>
      </div>

      <div>
        <p className="text-xs text-slate-500 dark:text-gray-400 mb-1">Secret</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 bg-slate-100 dark:bg-gray-900 border border-slate-300 dark:border-gray-700 rounded px-3 py-2 text-xs font-mono text-yellow-600 dark:text-yellow-300 truncate">
            {showSecret ? secret : '•'.repeat(32)}
          </code>
          <button onClick={() => setShowSecret(s => !s)} className="btn-ghost p-2">
            {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
          <button onClick={() => copy(secret, 'secret')} className="btn-ghost p-2">
            {copied === 'secret' ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
          </button>
        </div>
      </div>

      <div className="pt-1 space-y-2">
        <p className="text-xs text-slate-500 dark:text-gray-400">Mensajes para TradingView (copia y pega en el campo "Message" de la alerta):</p>
        {['long', 'short', 'close'].map(action => {
          const json = JSON.stringify({ secret, action, price: '{{close}}' })
          return (
            <div key={action} className="flex items-center gap-2">
              <span className="text-xs text-slate-500 dark:text-gray-400 w-10 shrink-0">{action}</span>
              <code className="flex-1 bg-slate-100 dark:bg-gray-900 border border-slate-300 dark:border-gray-700 rounded px-3 py-1.5 text-xs font-mono text-slate-700 dark:text-gray-300 truncate">
                {json}
              </code>
              <button onClick={() => copy(json, action)} className="btn-ghost p-1.5 shrink-0">
                {copied === action ? <Check size={13} className="text-green-400" /> : <Copy size={13} />}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ─── Symbol search ───────────────────────────────────────── */
function SymbolSearch({ value, onChange, accountId, paperMode }) {
  const [markets, setMarkets]   = useState([])
  const [loading, setLoading]   = useState(false)
  const [query,   setQuery]     = useState(value || '')
  const [open,    setOpen]      = useState(false)
  const ref = useRef(null)

  // Cargar mercados cuando cambia la cuenta
  // Para paper trading, usamos la primera cuenta real disponible o un exchange por defecto
  useEffect(() => {
    if (paperMode) {
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
  }, [accountId, paperMode])

  // Sincronizar query si el valor externo cambia (modo edición)
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
    setQuery(symbol)
    onChange(symbol)
    setOpen(false)
  }

  const handleInputChange = (e) => {
    setQuery(e.target.value)
    onChange(e.target.value)
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
          className="input font-mono pr-8"
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

/* ─── Take profits list ───────────────────────────────────── */
function TakeProfitsList({ value, onChange }) {
  const add = () => onChange([...value, { profit_percent: '', close_percent: '' }])
  const remove = i => onChange(value.filter((_, idx) => idx !== i))
  const update = (i, field, v) => {
    const next = [...value]
    next[i] = { ...next[i], [field]: v }
    onChange(next)
  }

  return (
    <div className="space-y-3">
      {value.map((tp, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="flex-1">
            <label className="text-xs text-slate-500 dark:text-gray-400">% precio desde entrada</label>
            <input
              type="number" step="0.1" min="0.1"
              value={tp.profit_percent}
              onChange={e => update(i, 'profit_percent', e.target.value)}
              className="input mt-1"
              placeholder="2.0"
            />
          </div>
          <div className="flex-1">
            <label className="text-xs text-slate-500 dark:text-gray-400">% posición a cerrar</label>
            <input
              type="number" step="1" min="1" max="100"
              value={tp.close_percent}
              onChange={e => update(i, 'close_percent', e.target.value)}
              className="input mt-1"
              placeholder="30"
            />
          </div>
          <button onClick={() => remove(i)} className="btn-ghost p-2 mt-5 text-red-400 hover:text-red-300">
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      <button onClick={add} className="flex items-center gap-1.5 text-sm text-blue-600 dark:text-blue-400 hover:text-blue-500 dark:hover:text-blue-300">
        <Plus size={14} /> Añadir nivel
      </button>
      {value.length > 0 && (
        <p className="text-xs text-slate-500 dark:text-gray-400">
          Suma de cierre: {value.reduce((s, tp) => s + (parseFloat(tp.close_percent) || 0), 0).toFixed(0)}%
        </p>
      )}
    </div>
  )
}

/* ─── Field helpers ───────────────────────────────────────── */
function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">{label}</label>
      {children}
      {hint && <p className="text-xs text-slate-500 dark:text-gray-400 mt-1">{hint}</p>}
    </div>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <div
        onClick={() => onChange(!checked)}
        className={`w-10 h-5 rounded-full transition-colors ${checked ? 'bg-blue-600' : 'bg-slate-300 dark:bg-gray-700'} relative`}
      >
        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-5' : 'translate-x-0.5'}`} />
      </div>
      <span className="text-sm text-slate-700 dark:text-gray-300">{label}</span>
    </label>
  )
}

/* ─── Default / flatten / build ──────────────────────────── */
const DEFAULT = {
  bot_name: '',
  symbol: '',
  exchange_account_id: '',
  paper_balance_id: '',
  account_type: 'real', // 'real' o 'paper'
  timeframe: '1h',
  leverage: 1,
  position_sizing_type: 'percentage',
  position_value: '',
  initial_sl_percentage: '',
  take_profits: [],
  trailing_enabled: false,
  trailing_activation: '',
  trailing_callback: '',
  breakeven_enabled: false,
  breakeven_activation: '',
  breakeven_lock: '',
  dynamic_enabled: false,
  dynamic_step: '',
  dynamic_max_steps: 0,
  signal_confirmation_minutes: 0,
}

function flattenBot(bot) {
  const tr = bot.trailing_config ?? {}
  const be = bot.breakeven_config ?? {}
  const dy = bot.dynamic_sl_config ?? {}
  const isPaper = bot.is_paper_trading || !!bot.paper_balance_id
  return {
    bot_name: bot.bot_name ?? '',
    symbol: bot.symbol ?? '',
    exchange_account_id: bot.exchange_account_id ?? '',
    paper_balance_id: bot.paper_balance_id ?? '',
    account_type: isPaper ? 'paper' : 'real',
    timeframe: bot.timeframe ?? '1h',
    leverage: bot.leverage ?? 1,
    position_sizing_type: bot.position_sizing_type ?? 'percentage',
    position_value: bot.position_value ?? '',
    initial_sl_percentage: bot.initial_sl_percentage ?? '',
    take_profits: (bot.take_profits ?? []).map(tp => ({
      profit_percent: tp.profit_percent ?? '',
      close_percent:  tp.close_percent  ?? '',
    })),
    trailing_enabled:    tr.enabled ?? false,
    trailing_activation: tr.activation_profit ?? '',
    trailing_callback:   tr.callback_rate ?? '',
    breakeven_enabled:    be.enabled ?? false,
    breakeven_activation: be.activation_profit ?? '',
    breakeven_lock:       be.lock_profit ?? '',
    dynamic_enabled:      dy.enabled ?? false,
    dynamic_step:         dy.step_percent ?? '',
    dynamic_max_steps:    dy.max_steps ?? 0,
    signal_confirmation_minutes: bot.signal_confirmation_minutes ?? 0,
  }
}

function buildPayload(f) {
  const payload = {
    bot_name: f.bot_name,
    symbol: f.symbol.trim(),
    timeframe: f.timeframe,
    leverage: parseInt(f.leverage),
    position_sizing_type: f.position_sizing_type,
    position_value: parseFloat(f.position_value),
    initial_sl_percentage: parseFloat(f.initial_sl_percentage),
    take_profits: f.take_profits.map(tp => ({
      profit_percent: parseFloat(tp.profit_percent),
      close_percent:  parseFloat(tp.close_percent),
    })),
    trailing_config: {
      enabled:            f.trailing_enabled,
      activation_profit:  parseFloat(f.trailing_activation) || 0,
      callback_rate:      parseFloat(f.trailing_callback) || 0,
    },
    breakeven_config: {
      enabled:            f.breakeven_enabled,
      activation_profit:  parseFloat(f.breakeven_activation) || 0,
      lock_profit:        parseFloat(f.breakeven_lock) || 0,
    },
    dynamic_sl_config: {
      enabled:      f.dynamic_enabled,
      step_percent: parseFloat(f.dynamic_step) || 0,
      max_steps:    parseInt(f.dynamic_max_steps) || 0,
    },
  }
  
  payload.signal_confirmation_minutes = parseInt(f.signal_confirmation_minutes) || 0

  // Agregar solo el tipo de cuenta correspondiente
  if (f.account_type === 'paper') {
    payload.paper_balance_id = f.paper_balance_id
  } else {
    payload.exchange_account_id = f.exchange_account_id
  }
  
  return payload
}

/* ─── Tabs ────────────────────────────────────────────────── */
const TABS = ['Básico', 'Capital / SL', 'Take Profits', 'Trailing Stop', 'Breakeven', 'Stop dinámico', 'Señales']

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d', '3d', '1w']

/* ─── Main page ───────────────────────────────────────────── */
export default function BotEditPage() {
  const { botId } = useParams()
  const navigate  = useNavigate()
  const isEdit    = !!botId

  const [tab, setTab]           = useState(0)
  const [form, setForm]         = useState(DEFAULT)
  const [accounts, setAccounts] = useState([])
  const [paperAccounts, setPaperAccounts] = useState([])
  const [botData, setBotData]   = useState(null)
  const [loading, setLoading]   = useState(isEdit)
  const [saving, setSaving]     = useState(false)
  const [error, setError]       = useState(null)

  useEffect(() => {
    // Cargar ambos tipos de cuentas
    exchangeAccountsService.list()
      .then(r => setAccounts(r.data || []))
      .catch(() => setAccounts([]))
    
    paperTradingService.list()
      .then(r => setPaperAccounts(r.data || []))
      .catch(() => setPaperAccounts([]))
    
    if (isEdit) {
      botsService.get(botId)
        .then(r => { setBotData(r.data); setForm(flattenBot(r.data)) })
        .catch(() => setError('No se pudo cargar el bot'))
        .finally(() => setLoading(false))
    }
  }, [botId, isEdit])

  const set = (field, value) => setForm(f => ({ ...f, [field]: value }))

  const handleSubmit = async () => {
    // Validación básica antes de enviar
    if (!form.bot_name.trim())         return setError('El nombre del bot es obligatorio')
    if (!form.symbol.trim())           return setError('El símbolo es obligatorio')
    if (form.account_type === 'real' && !form.exchange_account_id) {
      return setError('Selecciona una cuenta de exchange')
    }
    if (form.account_type === 'paper' && !form.paper_balance_id) {
      return setError('Selecciona una cuenta de paper trading')
    }
    if (!form.position_value)          return setError('El capital por operación es obligatorio')
    if (!form.initial_sl_percentage)   return setError('El stop loss inicial es obligatorio')

    setSaving(true)
    setError(null)
    try {
      const payload = buildPayload(form)
      if (isEdit) {
        await botsService.update(botId, payload)
      } else {
        await botsService.create(payload)
      }
      navigate('/bots')
    } catch (e) {
      const detail = e.response?.data?.detail
      if (Array.isArray(detail)) {
        // Errores de validación Pydantic: [{loc, msg, type}, ...]
        setError(detail.map(d => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(' · '))
      } else {
        setError(detail || 'Error al guardar el bot')
      }
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-xl font-bold text-slate-900 dark:text-white">{isEdit ? `Editar: ${botData?.bot_name}` : 'Nuevo bot'}</h1>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-0 overflow-x-auto border-b border-slate-200 dark:border-gray-800">
        {TABS.map((t, i) => (
          <button
            key={t}
            onClick={() => setTab(i)}
            className={`px-4 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
              tab === i
                ? 'border-blue-500 text-slate-900 dark:text-white'
                : 'border-transparent text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-300'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="space-y-5">

        {/* ── Tab 0: Básico ── */}
        {tab === 0 && (
          <>
            <Field label="Nombre del bot">
              <input
                type="text" value={form.bot_name}
                onChange={e => set('bot_name', e.target.value)}
                className="input" placeholder="Mi bot BTC" required
              />
            </Field>

            {/* Selector de tipo de cuenta */}
            <Field label="Modo de trading">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => set('account_type', 'real')}
                  className={`flex-1 py-2 px-4 rounded-lg border transition-colors ${
                    form.account_type === 'real'
                      ? 'bg-blue-600 border-blue-500 text-white'
                      : 'bg-slate-100 dark:bg-gray-800 border-slate-300 dark:border-gray-700 text-slate-700 dark:text-gray-400 hover:bg-slate-200 dark:hover:bg-gray-700'
                  }`}
                >
                  <span className="text-sm font-medium">🏦 Real</span>
                  <span className="block text-xs opacity-80">Con dinero real</span>
                </button>
                <button
                  type="button"
                  onClick={() => set('account_type', 'paper')}
                  className={`flex-1 py-2 px-4 rounded-lg border transition-colors ${
                    form.account_type === 'paper'
                      ? 'bg-purple-600 border-purple-500 text-white'
                      : 'bg-slate-100 dark:bg-gray-800 border-slate-300 dark:border-gray-700 text-slate-700 dark:text-gray-400 hover:bg-slate-200 dark:hover:bg-gray-700'
                  }`}
                >
                  <span className="text-sm font-medium">📄 Paper</span>
                  <span className="block text-xs opacity-80">Simulación sin riesgo</span>
                </button>
              </div>
            </Field>

            <Field label="Símbolo" hint="Futuros perpetuos — ejemplo: BTCUSDT">
              <SymbolSearch
                value={form.symbol}
                onChange={v => set('symbol', v)}
                accountId={form.exchange_account_id}
                paperMode={form.account_type === 'paper'}
              />
            </Field>

            {/* Selector de cuenta según el tipo */}
            {form.account_type === 'real' ? (
              <Field label="Cuenta de exchange">
                {!Array.isArray(accounts) || accounts.length === 0 ? (
                  <div className="text-sm text-slate-500 dark:text-gray-400 space-y-2">
                    <p>No tienes cuentas de exchange configuradas.</p>
                    <button 
                      onClick={() => navigate('/exchange-accounts')} 
                      className="text-blue-600 dark:text-blue-400 hover:underline"
                    >
                      Añadir cuenta real →
                    </button>
                  </div>
                ) : (
                  <select
                    value={form.exchange_account_id}
                    onChange={e => set('exchange_account_id', e.target.value)}
                    className="input"
                  >
                    <option value="">Seleccionar cuenta…</option>
                    {accounts.map(acc => (
                      <option key={acc.id} value={acc.id}>
                        {acc.label} ({acc.exchange})
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            ) : (
              <Field label="Cuenta de Paper Trading">
                {!Array.isArray(paperAccounts) || paperAccounts.length === 0 ? (
                  <div className="text-sm text-slate-500 dark:text-gray-400 space-y-2">
                    <p>No tienes cuentas de paper trading.</p>
                    <button 
                      onClick={() => navigate('/paper-trading')} 
                      className="text-purple-600 dark:text-purple-400 hover:underline"
                    >
                      Crear cuenta paper →
                    </button>
                  </div>
                ) : (
                  <select
                    value={form.paper_balance_id}
                    onChange={e => set('paper_balance_id', e.target.value)}
                    className="input"
                  >
                    <option value="">Seleccionar cuenta paper…</option>
                    {paperAccounts.map(acc => (
                      <option key={acc.id} value={acc.id}>
                        {acc.label} ({parseFloat(acc.available_balance).toFixed(0)} USDT disponibles)
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            )}

            <div className="flex gap-4">
              <Field label="Timeframe">
                <select
                  value={form.timeframe}
                  onChange={e => set('timeframe', e.target.value)}
                  className="input"
                >
                  {TIMEFRAMES.map(tf => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
              </Field>

              <Field label="Apalancamiento">
                <input
                  type="number" min="1" max="125" step="1"
                  value={form.leverage}
                  onChange={e => set('leverage', e.target.value)}
                  className="input"
                />
              </Field>
            </div>

          </>
        )}

        {/* ── Tab 1: Capital / SL ── */}
        {tab === 1 && (
          <>
            <Field label="Tipo de capital">
              <div className="flex gap-4">
                {[['percentage', '% del balance'], ['fixed', 'USDT fijo']].map(([val, lbl]) => (
                  <label key={val} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio" name="position_sizing_type"
                      checked={form.position_sizing_type === val}
                      onChange={() => set('position_sizing_type', val)}
                      className="accent-blue-500"
                    />
                    <span className="text-sm text-slate-700 dark:text-gray-300">{lbl}</span>
                  </label>
                ))}
              </div>
            </Field>

            <Field
              label={form.position_sizing_type === 'fixed' ? 'Capital por operación (USDT)' : 'Capital por operación (%)'}
            >
              <input
                type="number" min="0" step={form.position_sizing_type === 'fixed' ? '1' : '0.1'}
                value={form.position_value}
                onChange={e => set('position_value', e.target.value)}
                className="input w-48"
                placeholder={form.position_sizing_type === 'fixed' ? '100' : '2.5'}
              />
            </Field>

            <Field label="Stop loss inicial (%)" hint="Distancia desde el precio de entrada">
              <input
                type="number" min="0.1" max="100" step="0.1"
                value={form.initial_sl_percentage}
                onChange={e => set('initial_sl_percentage', e.target.value)}
                className="input w-48"
                placeholder="1.5"
              />
            </Field>
          </>
        )}

        {/* ── Tab 2: Take Profits ── */}
        {tab === 2 && (
          <TakeProfitsList
            value={form.take_profits}
            onChange={tps => set('take_profits', tps)}
          />
        )}

        {/* ── Tab 3: Trailing Stop ── */}
        {tab === 3 && (
          <>
            <Toggle
              label="Activar trailing stop"
              checked={form.trailing_enabled}
              onChange={v => set('trailing_enabled', v)}
            />
            {form.trailing_enabled && (
              <>
                <Field
                  label="Activación (% de beneficio desde entrada)"
                  hint="El trailing empieza a seguir el precio al llegar a este % de ganancia"
                >
                  <input
                    type="number" min="0.1" step="0.1"
                    value={form.trailing_activation}
                    onChange={e => set('trailing_activation', e.target.value)}
                    className="input w-48"
                    placeholder="1.0"
                  />
                </Field>
                <Field label="Callback rate (%)" hint="% de retroceso desde el máximo para activar el cierre">
                  <input
                    type="number" min="0.1" step="0.1"
                    value={form.trailing_callback}
                    onChange={e => set('trailing_callback', e.target.value)}
                    className="input w-48"
                    placeholder="0.5"
                  />
                </Field>
              </>
            )}
          </>
        )}

        {/* ── Tab 4: Breakeven ── */}
        {tab === 4 && (
          <>
            <Toggle
              label="Activar breakeven"
              checked={form.breakeven_enabled}
              onChange={v => set('breakeven_enabled', v)}
            />
            {form.breakeven_enabled && (
              <>
                <Field
                  label="Activación (% de beneficio)"
                  hint="Mueve el SL a breakeven al alcanzar este % de ganancia"
                >
                  <input
                    type="number" min="0.1" step="0.1"
                    value={form.breakeven_activation}
                    onChange={e => set('breakeven_activation', e.target.value)}
                    className="input w-48"
                    placeholder="0.5"
                  />
                </Field>
                <Field label="Lock profit (%)" hint="% adicional a fijar sobre la entrada (p.ej. 0.1 = SL en entrada + 0.1%)">
                  <input
                    type="number" min="0" step="0.05"
                    value={form.breakeven_lock}
                    onChange={e => set('breakeven_lock', e.target.value)}
                    className="input w-48"
                    placeholder="0.1"
                  />
                </Field>
              </>
            )}
          </>
        )}

        {/* ── Tab 6: Señales ── */}
        {tab === 6 && (
          <>
            <div className="bg-slate-50 dark:bg-gray-800/60 rounded-xl p-4 space-y-1 mb-2">
              <p className="text-xs text-slate-500 dark:text-gray-400">
                Cuando TradingView envía una alerta, el bot puede esperar N minutos antes de ejecutar
                la orden. Durante esa espera, si el precio se mueve en contra de la señal, la operación
                se cancela automáticamente — filtrando señales falsas o reversiones rápidas.
                Las señales de cierre (<code className="font-mono">close</code>) siempre se ejecutan de inmediato.
              </p>
            </div>

            <Field
              label="Delay de confirmación (minutos)"
              hint="0 = ejecución inmediata. Recomendado: 2–5 min para timeframes de 15m/1h/4h."
            >
              <div className="flex items-center gap-3">
                <input
                  type="number" min="0" max="60" step="1"
                  value={form.signal_confirmation_minutes}
                  onChange={e => set('signal_confirmation_minutes', e.target.value)}
                  className="input w-32"
                  placeholder="0"
                />
                <span className="text-sm text-slate-500 dark:text-gray-400">minutos</span>
              </div>
            </Field>

            {parseInt(form.signal_confirmation_minutes) > 0 && (
              <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 px-4 py-3 space-y-1">
                <p className="text-xs font-medium text-blue-400">Cómo funciona con {form.signal_confirmation_minutes} min activos</p>
                <ol className="text-xs text-slate-500 dark:text-gray-400 space-y-1 list-decimal list-inside">
                  <li>TradingView envía la alerta → se registra y TradingView recibe OK inmediato</li>
                  <li>El bot espera {form.signal_confirmation_minutes} min sin ejecutar</li>
                  <li>Transcurrido el tiempo, compara el precio actual con el precio de la alerta</li>
                  <li>LONG: si el precio bajó → señal cancelada (falsa). Si sigue arriba → ejecuta</li>
                  <li>SHORT: si el precio subió → señal cancelada (falsa). Si sigue abajo → ejecuta</li>
                </ol>
              </div>
            )}
          </>
        )}

        {/* ── Tab 5: Stop dinámico ── */}
        {tab === 5 && (
          <>
            <Toggle
              label="Activar stop dinámico por pasos"
              checked={form.dynamic_enabled}
              onChange={v => set('dynamic_enabled', v)}
            />
            {form.dynamic_enabled && (
              <>
                <Field
                  label="Paso (%)"
                  hint="Mueve el SL cada vez que el precio avanza este % a favor"
                >
                  <input
                    type="number" min="0.1" step="0.1"
                    value={form.dynamic_step}
                    onChange={e => set('dynamic_step', e.target.value)}
                    className="input w-48"
                    placeholder="0.5"
                  />
                </Field>
                <Field label="Pasos máximos" hint="0 = ilimitado">
                  <input
                    type="number" min="0" step="1"
                    value={form.dynamic_max_steps}
                    onChange={e => set('dynamic_max_steps', e.target.value)}
                    className="input w-32"
                    placeholder="0"
                  />
                </Field>
              </>
            )}
          </>
        )}
      </div>

      {/* Webhook display (only when editing) */}
      {isEdit && botData?.webhook_secret && (
        <WebhookUrlDisplay botId={botId} secret={botData.webhook_secret} />
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={handleSubmit}
          disabled={saving}
          className="btn-primary"
        >
          {saving ? 'Guardando…' : isEdit ? 'Guardar cambios' : 'Crear bot'}
        </button>
        <button onClick={() => navigate('/bots')} className="btn-ghost">
          Cancelar
        </button>
      </div>
    </div>
  )
}
