import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, Check, Copy, Eye, EyeOff, Loader2, Plus, Rocket, Sparkles, Trash2 } from 'lucide-react'
import { botsService } from '@/services/bots'
import { exchangeAccountsService } from '@/services/exchangeAccounts'
import { paperTradingService } from '@/services/paperTrading'
import { aiService } from '@/services/aiService'
import LoadingSpinner from '@/components/Common/LoadingSpinner'
import useAuthStore from '@/store/authStore'
import { isDeveloper } from '@/constants/roles'

/* ─── Auto-config button ────────────────────────────────── */
function AutoConfigButton({ symbol, onApply }) {
  const [loading, setLoading] = useState(false)
  const [explanation, setExplanation] = useState(null)
  const [open, setOpen] = useState(false)

  const handleClick = async () => {
    if (!symbol) return
    setLoading(true)
    try {
      const res = await aiService.optimalConfig(symbol)
      const { config, explanation: exp } = res.data
      onApply(config)
      setExplanation(exp)
      setOpen(true)
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      alert('No se pudo calcular la configuración óptima: ' + msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        disabled={loading || !symbol}
        className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors bg-violet-100 border-violet-300 text-violet-700 hover:bg-violet-200 dark:bg-violet-500/20 dark:border-violet-500/40 dark:text-violet-400 dark:hover:bg-violet-500/30 disabled:opacity-50"
      >
        {loading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
        {loading ? 'Analizando…' : 'Auto'}
      </button>

      {open && explanation && (
        <div className="absolute top-full right-0 mt-2 z-30 w-80 rounded-xl shadow-xl border bg-white border-slate-200 dark:bg-gray-900 dark:border-gray-700 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-bold text-slate-800 dark:text-white">✨ Configuración aplicada</p>
            <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xs">✕</button>
          </div>
          <div className="text-xs text-slate-600 dark:text-slate-300 space-y-1">
            <p><strong>Score mínimo:</strong> {explanation.best_score_threshold} (WR {explanation.best_score_win_rate}%)</p>
            <p><strong>Señales analizadas:</strong> {explanation.total_signals} · WR global {explanation.overall_win_rate}%</p>
            <p><strong>Tiers incluidos:</strong> {explanation.tier_stats ? Object.entries(explanation.tier_stats).filter(([,v]) => v.win_rate >= 45).map(([k]) => k).join(', ') : '—'}</p>
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/50 rounded p-2">
            La configuración se ha calculado a partir del histórico real de señales de este activo. Revisa los valores antes de guardar.
          </div>
        </div>
      )}
    </div>
  )
}

/* ─── Webhook display ─────────────────────────────────────── */
function WebhookUrlDisplay({ botId, secret }) {
  const [copied, setCopied] = useState(null)
  const [showSecret, setShowSecret] = useState(false)
  const [customHost, setCustomHost] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  const origin = window.location.origin
  const isLocal = origin.includes('localhost') || origin.includes('127.0.0.1') || origin.includes('192.168.')
  const effectiveOrigin = customHost.trim() || origin
  const url = `${effectiveOrigin}/webhook`

  const copy = (text, key) => {
    const done = () => { setCopied(key); setTimeout(() => setCopied(null), 1500) }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done))
    } else {
      fallbackCopy(text, done)
    }
  }

  const fallbackCopy = (text, done) => {
    const el = document.createElement('textarea')
    el.value = text
    el.style.cssText = 'position:fixed;opacity:0;pointer-events:none'
    document.body.appendChild(el)
    el.focus()
    el.select()
    try { document.execCommand('copy'); done() } catch (_) {}
    document.body.removeChild(el)
  }

  const mask = '•••••••••••••••••••••••••••••••••'
  const message = (action) => JSON.stringify({
    bot_id: botId,
    secret: showSecret ? secret : mask,
    action,
    price: '{{close}}',
    strategy: 'QUANTUM'
  }, null, 2)

  const realMessage = (action) => JSON.stringify({
    bot_id: botId,
    secret,
    action,
    price: '{{close}}',
    strategy: 'QUANTUM'
  })

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
        <p className="text-xs text-slate-500 dark:text-gray-400 mb-1">URL del Webhook (la misma para todos tus bots)</p>
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

      <div className="flex items-center gap-2">
        <button
          onClick={async () => {
            setTesting(true); setTestResult(null)
            try {
              const { data } = await botsService.testWebhook(botId)
              setTestResult({ type: 'success', message: data.message || 'Webhook de prueba OK' })
            } catch (err) {
              setTestResult({ type: 'error', message: err.response?.data?.detail || 'Error al probar el webhook' })
            } finally {
              setTesting(false)
            }
          }}
          disabled={testing || isLocal}
          className="btn-primary text-sm flex items-center gap-2 disabled:opacity-50"
          title={isLocal ? 'No disponible en localhost' : 'Enviar señal de prueba al bot'}
        >
          {testing ? <Loader2 size={14} className="animate-spin" /> : <Rocket size={14} />}
          {testing ? 'Probando…' : 'Probar webhook'}
        </button>
        {isLocal && (
          <span className="text-xs text-amber-600 dark:text-amber-400">No disponible en localhost</span>
        )}
      </div>

      {testResult && (
        <div className={`border rounded-lg px-4 py-3 text-sm ${
          testResult.type === 'error'
            ? 'bg-red-500/10 border-red-500/30 text-red-400'
            : 'bg-green-500/10 border-green-500/30 text-green-400'
        }`}>
          {testResult.message}
        </div>
      )}

      <div>
        <p className="text-xs text-slate-500 dark:text-gray-400 mb-1">Secret de este bot</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 bg-slate-100 dark:bg-gray-900 border border-slate-300 dark:border-gray-700 rounded px-3 py-2 text-xs font-mono text-yellow-600 dark:text-yellow-300 truncate">
            {showSecret ? secret : mask}
          </code>
          <button onClick={() => setShowSecret(s => !s)} className="btn-ghost p-2" title={showSecret ? 'Ocultar secret' : 'Mostrar secret'}>
            {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
          <button onClick={() => copy(secret, 'secret')} className="btn-ghost p-2" title="Copiar secret">
            {copied === 'secret' ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
          </button>
        </div>
        {!showSecret && (
          <p className="text-[10px] text-slate-500 dark:text-gray-500 mt-1">
            Pulsa el ojo para revelar el secret. No lo compartas públicamente.
          </p>
        )}
      </div>

      <div className="pt-1 space-y-3">
        <p className="text-xs text-slate-500 dark:text-gray-400">
          Mensajes para TradingView (copia y pega en el campo "Message" de cada alerta):
        </p>
        {['long', 'short', 'close'].map(action => (
          <div key={action} className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-600 dark:text-gray-300 capitalize">{action}</span>
              <button onClick={() => copy(realMessage(action), action)} className="btn-ghost p-1.5 shrink-0 text-xs flex items-center gap-1" title="Copiar mensaje completo">
                {copied === action ? <Check size={13} className="text-green-400" /> : <Copy size={13} />}
                <span className="hidden sm:inline">Copiar</span>
              </button>
            </div>
            <pre className="w-full bg-slate-100 dark:bg-gray-900 border border-slate-300 dark:border-gray-700 rounded px-3 py-2 text-[11px] font-mono text-slate-700 dark:text-gray-300 overflow-x-auto whitespace-pre-wrap">
              {message(action)}
            </pre>
          </div>
        ))}
      </div>

      <div className="pt-2 border-t border-slate-200 dark:border-gray-800">
        <p className="text-[10px] text-slate-500 dark:text-gray-500">
          <strong>Nota:</strong> La URL es la misma para todos los bots. El <code>bot_id</code> dentro del mensaje identifica a qué bot va dirigida la señal.
        </p>
      </div>
    </div>
  )
}

/* ─── Symbol input with datalist (for alert-only bots) ────── */
// "SOL/USDT:USDT" -> "SOLUSDT"
const toCompactSymbol = (s) =>
  typeof s === 'string'
    ? s.replace(/\/([^:]+):[^:]+$/, '$1').replace('/', '').toUpperCase()
    : s



/* ─── Symbol search ───────────────────────────────────────── */
function SymbolSearch({ value, onChange, accountId, paperMode, alertsOnly, exchange }) {
  const [markets, setMarkets]   = useState([])
  const [loading, setLoading]   = useState(false)
  const [query,   setQuery]     = useState(value || '')
  const [open,    setOpen]      = useState(false)
  const ref = useRef(null)

  const loadExchangeMarkets = (exchangeName = 'bingx') => {
    setLoading(true)
    exchangeAccountsService.marketsByExchange(exchangeName)
      .then(r => setMarkets((r.data || []).map(toCompactSymbol)))
      .catch(() => setMarkets([]))
      .finally(() => setLoading(false))
  }

  // Cargar mercados cuando cambia la cuenta
  // Si no hay accountId (bots solo alertas) o paper, usamos BingX como fuente de referencia
  useEffect(() => {
    if (paperMode || alertsOnly || !accountId) {
      loadExchangeMarkets('bingx')
      return
    }

    setLoading(true)
    exchangeAccountsService.markets(accountId)
      .then(r => {
        const list = (r.data || []).map(toCompactSymbol)
        if (list.length === 0) {
          // Fallback al exchange correcto si markets() no devuelve nada
          loadExchangeMarkets(exchange || 'bingx')
        } else {
          setMarkets(list)
          setLoading(false)
        }
      })
      .catch(() => loadExchangeMarkets(exchange || 'bingx'))
  }, [accountId, paperMode, alertsOnly, exchange])

  // Sincronizar query si el valor externo cambia (modo edición)
  useEffect(() => { setQuery(value || '') }, [value])

  // Cerrar al click fuera
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const normalizedQuery = query.toUpperCase()
  const filtered = normalizedQuery.length < 1
    ? markets.slice(0, 50)
    : markets.filter(s => s.includes(normalizedQuery)).slice(0, 50)

  const handleSelect = (symbol) => {
    const compact = toCompactSymbol(symbol)
    setQuery(compact)
    onChange(compact)
    setOpen(false)
  }

  const handleInputChange = (e) => {
    const compact = toCompactSymbol(e.target.value)
    setQuery(compact)
    onChange(compact)
    setOpen(true)
  }

  const canSearch = paperMode || alertsOnly || accountId

  return (
    <div ref={ref} className="relative">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={handleInputChange}
          onFocus={() => setOpen(true)}
          className="input font-mono pr-8"
          placeholder={canSearch ? 'Busca o escribe el símbolo…' : 'Selecciona primero una cuenta'}
          disabled={!canSearch}
        />
        {loading && (
          <Loader2 size={14} className="animate-spin absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 dark:text-gray-500" />
        )}
      </div>

      {open && canSearch && filtered.length > 0 && (
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

      {!loading && canSearch && markets.length === 0 && (
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
  use_roi_percentage: false,
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
  webhook_enabled: true,
  indicator_enabled: false,
  telegram_chat_id: '',
  telegram_thread_id: '',
  alerts_only: false,
  ai_signal_mode: true,
  ai_optimal_config_enabled: true,
  auto_timeframe: true,
  ai_min_score: 60,
  ai_require_clear: true,
  ai_max_concurrent: 1,
  ai_allowed_tiers: ['STRONG'],
  ai_allowed_statuses: ['CLEAR'],
  ai_sizing_strong: 100,
  ai_sizing_moderate: 100,
  ai_sizing_weak: 100,
  ai_sizing_clear: 100,
  ai_sizing_caution: 100,
  ai_cb_strong: 3,
  ai_cb_moderate: 2,
  ai_cb_weak: 1,
  ai_pf_total: 50,
  ai_pf_symbol: 30,
  ai_pf_dir: 40,
  ai_pf_alt: 3,
  trigger_indicator: '',
  trigger_timeframe: '',
  trigger_min_grade: 'A+,A,A-',
  trigger_timing: 'candle_close',
  trigger_interval_minutes: 4,
  min_confirm_candles: 1,
  ind_config: {},
  // Conflict config v2
  cc_same_direction: 'reject',
  cc_opp_ia: 'close_and_open',
  cc_opp_webhook: 'close_and_open',
  cc_opp_indicator: 'close_and_open',
  cc_auto_evaluate: true,
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
    use_roi_percentage: bot.use_roi_percentage ?? false,
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
    ai_signal_mode:    bot.ai_signal_mode ?? false,
    ai_optimal_config_enabled: bot.ai_optimal_config_enabled ?? false,
    auto_timeframe:    bot.auto_timeframe ?? false,
    ai_min_score:      bot.ai_signal_config?.min_score      ?? 60,
    ai_require_clear:  bot.ai_signal_config?.require_clear  ?? true,
    ai_max_concurrent: bot.ai_signal_config?.max_concurrent ?? 1,
    ai_allowed_tiers:    bot.ai_signal_config?.allowed_tiers    ?? ['STRONG'],
    ai_allowed_statuses: bot.ai_signal_config?.allowed_statuses ?? ['CLEAR'],
    ai_sizing_strong:    Math.round((bot.ai_signal_config?.sizing_multipliers?.STRONG    ?? 1.0) * 100),
    ai_sizing_moderate:  Math.round((bot.ai_signal_config?.sizing_multipliers?.MODERATE  ?? 1.0) * 100),
    ai_sizing_weak:      Math.round((bot.ai_signal_config?.sizing_multipliers?.WEAK      ?? 1.0) * 100),
    ai_sizing_clear:     Math.round((bot.ai_signal_config?.sizing_multipliers?.CLEAR     ?? 1.0) * 100),
    ai_sizing_caution:   Math.round((bot.ai_signal_config?.sizing_multipliers?.CAUTION   ?? 1.0) * 100),
    ai_cb_strong:        bot.ai_signal_config?.circuit_breaker_thresholds?.STRONG?.consecutive_sl   ?? 3,
    ai_cb_moderate:      bot.ai_signal_config?.circuit_breaker_thresholds?.MODERATE?.consecutive_sl ?? 2,
    ai_cb_weak:          bot.ai_signal_config?.circuit_breaker_thresholds?.WEAK?.consecutive_sl     ?? 1,
    ai_pf_total:         bot.ai_signal_config?.portfolio_limits?.max_total_exposure_pct       ?? 50,
    ai_pf_symbol:        bot.ai_signal_config?.portfolio_limits?.max_symbol_exposure_pct      ?? 30,
    ai_pf_dir:           bot.ai_signal_config?.portfolio_limits?.max_directional_exposure_pct ?? 40,
    ai_pf_alt:           bot.ai_signal_config?.portfolio_limits?.alt_correlation_threshold    ?? 3,
    trigger_indicator:        bot.trigger_indicator === 'ict' ? 'ict' : '',
    trigger_timeframe:        bot.trigger_timeframe        ?? '',
    trigger_min_grade:        bot.trigger_min_grade        ?? 'A+,A,A-',
    trigger_timing:           bot.trigger_timing           ?? 'candle_close',
    trigger_interval_minutes: bot.trigger_interval_minutes ?? 4,
    min_confirm_candles:      bot.min_confirm_candles      ?? 1,
    webhook_enabled:          bot.webhook_enabled          ?? true,
    indicator_enabled:        bot.indicator_enabled        ?? false,
    telegram_chat_id:         bot.telegram_chat_id         ?? '',
    telegram_thread_id:       bot.telegram_thread_id       ?? '',
    alerts_only:              bot.alerts_only              ?? false,
    ind_config:               bot.ict_config               ?? {},
    // Conflict config v2 — per source
    cc_same_direction:        bot.conflict_config?.same_direction ?? 'reject',
    cc_opp_ia:                bot.conflict_config?.opposite_direction?.ia         ?? 'close_and_open',
    cc_opp_webhook:           bot.conflict_config?.opposite_direction?.webhook    ?? 'close_and_open',
    cc_opp_indicator:         bot.conflict_config?.opposite_direction?.indicator  ?? 'close_and_open',
    cc_auto_evaluate:         bot.conflict_config?.auto_evaluate_profit ?? true,
  }
}

function buildPayload(f) {
  const payload = {
    bot_name: f.bot_name,
    symbol: f.symbol.trim(),
    timeframe: f.timeframe,
    leverage: parseInt(f.leverage),
    use_roi_percentage: f.use_roi_percentage,
    ...(f.alerts_only
      ? {
          // Valores mínimos válidos para bots de solo alertas
          position_sizing_type: 'fixed',
          position_value: 1,
          initial_sl_percentage: 1,
          take_profits: [],
          trailing_config: { enabled: false, activation_profit: 0, callback_rate: 0 },
          breakeven_config: { enabled: false, activation_profit: 0, lock_profit: 0 },
          dynamic_sl_config: { enabled: false, step_percent: 0, max_steps: 0 },
        }
      : {
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
        }),
  }
  
  payload.signal_confirmation_minutes = parseInt(f.signal_confirmation_minutes) || 0

  // Fuentes de activación independientes
  payload.webhook_enabled   = f.webhook_enabled
  payload.indicator_enabled = f.indicator_enabled
  payload.telegram_chat_id  = f.telegram_chat_id || null
  payload.telegram_thread_id = f.telegram_thread_id ? parseInt(f.telegram_thread_id) : null
  payload.alerts_only       = f.alerts_only
  payload.ai_signal_mode    = f.ai_signal_mode
  payload.ai_optimal_config_enabled = f.ai_optimal_config_enabled
  payload.auto_timeframe     = f.auto_timeframe

  // Config indicador (siempre se envía, el backend la ignora si indicator_enabled=false)
  payload.trigger_indicator        = f.trigger_indicator || 'ict'
  payload.trigger_timeframe        = f.trigger_timeframe || null
  payload.trigger_min_grade        = f.trigger_min_grade || 'A+,A,A-'
  payload.trigger_timing           = f.trigger_timing || 'candle_close'
  payload.trigger_interval_minutes = parseInt(f.trigger_interval_minutes) || 4
  payload.min_confirm_candles      = parseInt(f.min_confirm_candles) || 1
  payload.ict_config               = Object.keys(f.ind_config || {}).length > 0 ? f.ind_config : {}

  // Config IA (siempre se envía)
  payload.ai_signal_config = {
    min_score:         parseInt(f.ai_min_score)      || 60,
    require_clear:     f.ai_require_clear,
    max_concurrent:    parseInt(f.ai_max_concurrent) || 1,
    allowed_tiers:     f.ai_allowed_tiers     || ['STRONG'],
    allowed_statuses:  f.ai_allowed_statuses  || ['CLEAR'],
    sizing_multipliers: {
      STRONG:   (parseInt(f.ai_sizing_strong)   || 100) / 100,
      MODERATE: (parseInt(f.ai_sizing_moderate) || 100) / 100,
      WEAK:     (parseInt(f.ai_sizing_weak)     || 100) / 100,
      CLEAR:    (parseInt(f.ai_sizing_clear)    || 100) / 100,
      CAUTION:  (parseInt(f.ai_sizing_caution)  || 100) / 100,
    },
    circuit_breaker_thresholds: {
      STRONG:   { consecutive_sl: parseInt(f.ai_cb_strong)   || 3 },
      MODERATE: { consecutive_sl: parseInt(f.ai_cb_moderate) || 2 },
      WEAK:     { consecutive_sl: parseInt(f.ai_cb_weak)     || 1 },
    },
    portfolio_limits: {
      max_total_exposure_pct:       parseInt(f.ai_pf_total) || 50,
      max_symbol_exposure_pct:      parseInt(f.ai_pf_symbol) || 30,
      max_directional_exposure_pct: parseInt(f.ai_pf_dir) || 40,
      alt_correlation_threshold:    parseInt(f.ai_pf_alt) || 3,
    },
  }

  // Conflict config v2
  payload.conflict_config = {
    same_direction: f.cc_same_direction || 'reject',
    opposite_direction: {
      ia:         f.cc_opp_ia        || 'close_and_open',
      webhook:    f.cc_opp_webhook   || 'close_and_open',
      indicator:  f.cc_opp_indicator || 'close_and_open',
    },
    auto_evaluate_profit: f.cc_auto_evaluate !== false,
  }

  // Agregar solo el tipo de cuenta correspondiente (si no es solo alertas)
  if (!f.alerts_only) {
    if (f.account_type === 'paper') {
      payload.paper_balance_id = f.paper_balance_id || null
    } else {
      payload.exchange_account_id = f.exchange_account_id || null
    }
  }
  
  return payload
}

/* Restringe campos avanzados para roles no-developer */
function applyRoleRestrictions(form, dev) {
  if (dev) return form
  return {
    ...form,
    alerts_only: false,
    ai_signal_mode: false,
    ai_optimal_config_enabled: false,
    auto_timeframe: false,
    indicator_enabled: false,
    webhook_enabled: true,
  }
}

/* ─── Tabs ────────────────────────────────────────────────── */
const ALL_TABS = ['Básico', 'Capital / SL', 'Take Profits', 'Trailing Stop', 'Breakeven', 'Stop dinámico', 'Activación']
const ALERT_TABS = ['Básico', 'Activación']

const TIMEFRAMES = ['15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w']

/* ─── Main page ───────────────────────────────────────────── */
export default function BotEditPage() {
  const { botId } = useParams()
  const navigate  = useNavigate()
  const isEdit    = !!botId
  const user      = useAuthStore(s => s.user)
  const isDev     = isDeveloper(user)

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
        .then(r => {
          setBotData(r.data)
          setForm(applyRoleRestrictions(flattenBot(r.data), isDev))
        })
        .catch(() => setError('No se pudo cargar el bot'))
        .finally(() => setLoading(false))
    } else {
      setForm(f => applyRoleRestrictions(f, isDev))
    }
  }, [botId, isEdit, isDev])

  const set = (field, value) => setForm(f => ({ ...f, [field]: value }))
  const setInd = (key, value) => setForm(f => ({ ...f, ind_config: { ...f.ind_config, [key]: value } }))

  const handleSubmit = async () => {
    // Validación básica antes de enviar
    if (!form.bot_name.trim())         return setError('El nombre del bot es obligatorio')
    if (!form.symbol.trim())           return setError('El símbolo es obligatorio')
    if (!form.alerts_only) {
      if (form.account_type === 'real' && !form.exchange_account_id) {
        return setError('Selecciona una cuenta de exchange')
      }
      if (form.account_type === 'paper' && !form.paper_balance_id) {
        return setError('Selecciona una cuenta de paper trading')
      }
      if (!form.position_value)          return setError('El capital por operación es obligatorio')
      if (!form.initial_sl_percentage)   return setError('El stop loss inicial es obligatorio')
    }

    setSaving(true)
    setError(null)
    try {
      const payload = buildPayload(form)
      if (isEdit) {
        await botsService.update(botId, payload)
      } else {
        const res = await botsService.create(payload)
        navigate(`/bots/${res.data.id}`)
        return
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

  const tabName = (form.alerts_only ? ALERT_TABS : ALL_TABS)[tab]

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
        {(form.alerts_only ? ALERT_TABS : ALL_TABS).map((t, i) => (
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
        {tabName === 'Básico' && (
          <>
            <Field label="Nombre del bot">
              <input
                type="text" value={form.bot_name}
                onChange={e => set('bot_name', e.target.value)}
                className="input" placeholder="Mi bot BTC" required
              />
            </Field>

            {/* Modo solo alertas — solo developer */}
            {isDev && (
              <>
                <Toggle
                  checked={form.alerts_only}
                  onChange={v => {
                    set('alerts_only', v)
                    if (v) {
                      set('ai_signal_mode', false)
                      set('ai_optimal_config_enabled', false)
                      set('auto_timeframe', false)
                      set('webhook_enabled', true)   // los bots solo alertas reciben señales por webhook
                      set('indicator_enabled', false)
                    }
                  }}
                  label="Solo alertas (sin ejecución de trades)"
                />
                {form.alerts_only && (
                  <p className="text-xs text-slate-500 dark:text-gray-400">
                    Este bot solo recibirá señales de TradingView y las enviará a Telegram. No abrirá posiciones ni requiere cuenta de exchange.
                  </p>
                )}
              </>
            )}

            {!form.alerts_only && (
              <>
                {/* Selector de tipo de cuenta */}
                <Field label="Modo de trading">
                  <div className={`flex gap-2 ${!isDev ? 'flex-col' : ''}`}>
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
                    {isDev && (
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
                    )}
                  </div>
                  {!isDev && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                      El modo paper está disponible solo para el perfil developer.
                    </p>
                  )}
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
              </>
            )}

            <Field label="Símbolo" hint="Futuros perpetuos — ejemplo: BTCUSDT">
              {form.alerts_only ? (
                <SymbolSearch
                  value={form.symbol}
                  onChange={v => set('symbol', v)}
                  alertsOnly={true}
                />
              ) : (
                <SymbolSearch
                  value={form.symbol}
                  onChange={v => set('symbol', v)}
                  accountId={form.exchange_account_id}
                  paperMode={form.account_type === 'paper'}
                  exchange={accounts.find(a => a.id === form.exchange_account_id)?.exchange}
                />
              )}
            </Field>

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

            <Toggle
              checked={form.use_roi_percentage}
              onChange={v => set('use_roi_percentage', v)}
              label="Usar %ROI (afectado por leverage)"
            />
            {form.use_roi_percentage && (
              <p className="text-xs text-slate-500 dark:text-gray-400">
                Cuando está activo, los % de SL, TP, Trailing, BE y Stop dinámico se interpretan como %ROI.
                Ej: con leverage 10x, un SL del 50% ROI = movimiento de precio del 5%.
              </p>
            )}

            {!form.alerts_only && (
              <div className="border border-slate-200 dark:border-gray-700 rounded-lg p-4 space-y-4 mt-4">
                <h4 className="text-sm font-semibold text-slate-700 dark:text-gray-300 flex items-center gap-2">
                  <AlertTriangle size={16} className="text-yellow-500" />
                  Gestión de Conflictos
                </h4>
                <p className="text-xs text-slate-500 dark:text-gray-400">
                  Reglas cuando este bot recibe una señal y ya existe una posición abierta en el mismo activo.
                </p>

                {/* Regla fija: mismo sentido */}
                <div className="flex items-center gap-2 p-2 rounded bg-slate-50 dark:bg-gray-800/50">
                  <span className="text-xs text-slate-500 dark:text-gray-400">Mismo sentido:</span>
                  <span className="text-xs font-semibold text-red-500">Siempre rechazar</span>
                  <span className="text-[10px] text-slate-400">(no se permiten duplicados)</span>
                </div>

                {/* Per-source config para contrario */}
                <div className="space-y-3">
                  <p className="text-xs font-medium text-slate-600 dark:text-gray-300">Sentido contrario — acción por fuente:</p>
                  {[
                    ...(isDev ? [{ key: 'cc_opp_ia', label: 'Scanner IA', color: 'violet' }] : []),
                    { key: 'cc_opp_webhook',   label: 'Webhook',           color: 'blue' },
                    ...(isDev ? [{ key: 'cc_opp_indicator', label: 'Indicador interno', color: 'emerald' }] : []),
                  ].map(({ key, label, color }) => (
                    <Field key={key} label={label}>
                      <select
                        value={form[key] || 'close_and_open'}
                        onChange={e => set(key, e.target.value)}
                        className="input text-sm"
                      >
                        <option value="close_and_open">Cerrar anterior y abrir nueva</option>
                        <option value="keep_both">Mantener ambas posiciones</option>
                        <option value="reject">Rechazar nueva señal</option>
                      </select>
                    </Field>
                  ))}
                </div>

                <Toggle
                  label="Auto-evaluar profit + tendencia"
                  checked={form.cc_auto_evaluate !== false}
                  onChange={v => set('cc_auto_evaluate', v)}
                />
                <p className="text-xs text-slate-500 dark:text-gray-400">
                  Si está activo, una señal contraria se rechaza automáticamente si la posición existente está en profit y la tendencia de 15min le favorece.
                </p>
              </div>
            )}

          </>
        )}

        {/* ── Tab 1: Capital / SL ── */}
        {tabName === 'Capital / SL' && (
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

            <Field label={`Stop loss inicial (${form.use_roi_percentage ? '%ROI' : '% precio'})`} hint={form.use_roi_percentage ? '% de retorno sobre el margen (afectado por leverage)' : 'Distancia desde el precio de entrada'}>
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
        {tabName === 'Take Profits' && (
          <TakeProfitsList
            value={form.take_profits}
            onChange={tps => set('take_profits', tps)}
          />
        )}

        {/* ── Tab 3: Trailing Stop ── */}
        {tabName === 'Trailing Stop' && (
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
        {tabName === 'Breakeven' && (
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

        {/* ── Tab 6: Activación ── */}
        {tabName === 'Activación' && (() => {
          const TF_SECS = { '1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1h':3600,'2h':7200,'4h':14400,'6h':21600,'12h':43200,'1d':86400 }
          const scanTf = form.trigger_timeframe || form.timeframe
          const candleSecs = TF_SECS[scanTf] || 3600
          const scans = form.trigger_interval_minutes || 4
          const intervalSecs = Math.max(60, candleSecs / scans)
          const intervalMin = (intervalSecs / 60).toFixed(intervalSecs < 300 ? 1 : 0)

          return (
            <>
              <div>
                <p className="text-sm font-semibold text-slate-700 dark:text-gray-200 mb-1">¿Cómo se activa este bot?</p>
                <p className="text-xs text-slate-500 dark:text-gray-400 mb-4">Activa una o más fuentes de señales que dispararán las órdenes.</p>
              </div>

              {/* ── Toggles de modo ── */}
              <div className="grid grid-cols-1 gap-3">

                {/* Webhook */}
                <div className="flex items-center justify-between p-4 rounded-xl border border-slate-200 dark:border-gray-700">
                  <div className="flex items-start gap-3">
                    <span className="text-xl mt-0.5">📡</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-slate-800 dark:text-white">Webhook externo</p>
                      <p className="text-xs text-slate-500 dark:text-gray-400 mt-0.5">TradingView u otro sistema envía alertas JSON al endpoint del bot. Tú controlas cuándo y cómo se dispara desde fuera.</p>
                    </div>
                  </div>
                  <Toggle
                    checked={form.webhook_enabled}
                    onChange={v => { if (isDev && !form.alerts_only) set('webhook_enabled', v) }}
                    disabled={!isDev || form.alerts_only}
                  />
                </div>

                {/* Indicador interno — solo developer */}
                {isDev && (
                  <div className="flex items-center justify-between p-4 rounded-xl border border-slate-200 dark:border-gray-700">
                    <div className="flex items-start gap-3">
                      <span className="text-xl mt-0.5">📊</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-slate-800 dark:text-white">Indicador interno</p>
                        <p className="text-xs text-slate-500 dark:text-gray-400 mt-0.5">El sistema escanea el par y la temporalidad configurados usando el indicador seleccionado. Cuando detecta una confluencia A / A+ dispara el bot automáticamente.</p>
                      </div>
                    </div>
                    <Toggle
                      checked={form.indicator_enabled}
                      onChange={v => { if (!form.alerts_only) { set('indicator_enabled', v); if (v && !form.trigger_indicator) set('trigger_indicator', 'ict') } }}
                      disabled={form.alerts_only}
                    />
                  </div>
                )}

                {/* Scanner IA — solo developer */}
                {isDev && (
                  <div className="flex items-center justify-between p-4 rounded-xl border border-slate-200 dark:border-gray-700">
                    <div className="flex items-start gap-3">
                      <span className="text-xl mt-0.5">🤖</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-slate-800 dark:text-white">Scanner IA</p>
                        <p className="text-xs text-slate-500 dark:text-gray-400 mt-0.5">El scanner ICT+SMC con modelo XGBoost evalúa confluencias y anti-fake en tiempo real. Por defecto dispara STRONG+CLEAR, pero puedes configurar MODERATE y CAUTION bajo tu responsabilidad.</p>
                      </div>
                    </div>
                    <Toggle
                      checked={form.ai_signal_mode}
                      onChange={v => {
                        if (!form.alerts_only) {
                          setForm(f => ({
                            ...f,
                            ai_signal_mode: v,
                            ai_optimal_config_enabled: v,
                            auto_timeframe: v,
                          }))
                        }
                      }}
                      disabled={form.alerts_only}
                    />
                  </div>
                )}

                {/* Estrategia Monte Carlo activa */}
                {isEdit && botData?.montecarlo_config?.strategy_id && (
                  <div className="flex items-center justify-between p-4 rounded-xl border border-amber-500/30 bg-amber-500/5">
                    <div className="flex items-start gap-3">
                      <span className="text-xl mt-0.5">📊</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-slate-800 dark:text-white">
                          Estrategia Monte Carlo
                          {botData.montecarlo_config?.enabled && botData.montecarlo_config?.mode === 'setup_base' && (
                            <span className="ml-2 text-[10px] bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300 px-1.5 py-0.5 rounded">Setup Base IA</span>
                          )}
                        </p>
                        <p className="text-xs text-slate-500 dark:text-gray-400 mt-0.5">
                          ID: {botData.montecarlo_config.strategy_id.slice(0, 8)}... · 
                          {botData.montecarlo_config.strategy_symbol} · 
                          {botData.montecarlo_config.strategy_timeframe}
                          {botData.montecarlo_config?.setup_cache?.context?.direction_bias && (
                            <span className="ml-1">
                              · Bias: <span className="font-medium">{botData.montecarlo_config.setup_cache.context.direction_bias}</span>
                              · Confianza: <span className="font-medium">{botData.montecarlo_config.setup_cache.context.confidence_tier}</span>
                            </span>
                          )}
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={() => navigate('/monte-carlo')}
                      className="text-xs bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded"
                    >
                      Ver MC
                    </button>
                  </div>
                )}
              </div>

              {/* ── Config expandida según modo ── */}

              {/* Webhook config */}
              {form.webhook_enabled && (
                <div className="mt-4 rounded-xl border border-blue-500/30 bg-blue-500/5 px-4 py-4 space-y-4">
                  <p className="text-xs font-semibold text-blue-400 uppercase tracking-wide">Opciones de webhook</p>
                  <Field
                    label="Delay de confirmación (minutos)"
                    hint="0 = ejecución inmediata. El bot espera N min y cancela si el precio se revierte."
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="number" min="0" max="60" step="1"
                        value={form.signal_confirmation_minutes}
                        onChange={e => set('signal_confirmation_minutes', e.target.value)}
                        className="input w-24"
                        placeholder="0"
                      />
                      <span className="text-sm text-slate-500 dark:text-gray-400">minutos</span>
                    </div>
                  </Field>

                  <Field label="Chat ID de Telegram" hint="Grupo o canal donde se enviarán las alertas (ej: -1003984916065)">
                    <input
                      type="text"
                      value={form.telegram_chat_id}
                      onChange={e => set('telegram_chat_id', e.target.value)}
                      className="input w-full font-mono"
                      placeholder="-1003984916065"
                    />
                  </Field>

                  <Field label="Topic ID de Telegram" hint="Opcional. ID del tema/foro dentro del grupo (ej: 13)">
                    <input
                      type="number"
                      value={form.telegram_thread_id}
                      onChange={e => set('telegram_thread_id', e.target.value)}
                      className="input w-32"
                      placeholder="13"
                    />
                  </Field>
                </div>
              )}
              {isEdit && botData?.webhook_secret && (form.webhook_enabled || form.alerts_only) && (
                <WebhookUrlDisplay botId={botId} secret={botData.webhook_secret} />
              )}

              {/* Indicador config */}
              {form.indicator_enabled && !form.alerts_only && (
                <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-4 space-y-4">
                  <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">Configuración del indicador</p>

                  <Field label="Indicador">
                    <select value={form.trigger_indicator} onChange={e => set('trigger_indicator', e.target.value)} className="input">
                      <option value="ict">ICT / SMC — Order Blocks + FVG + BOS/CHoCH</option>
                    </select>
                  </Field>

                  {/* ── Parámetros del indicador ───────────────────────── */}
                  {form.trigger_indicator === 'ict' && (
                    <div className="rounded-xl border border-slate-200 dark:border-gray-700 bg-slate-50 dark:bg-gray-800/50 px-4 py-3 space-y-3">
                      <p className="text-[11px] font-bold text-slate-500 dark:text-gray-400 uppercase tracking-wide">Parámetros ICT / SMC</p>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs text-slate-600 dark:text-gray-300 mb-1">Pivot confirmación (velas)</label>
                          <input type="number" min={2} max={10} value={form.ind_config.pivot_len ?? 5}
                            onChange={e => setInd('pivot_len', parseInt(e.target.value))}
                            className="input w-full text-sm" />
                          <p className="text-[10px] text-slate-400 mt-0.5">Velas a cada lado para confirmar pivot</p>
                        </div>
                        <div>
                          <label className="block text-xs text-slate-600 dark:text-gray-300 mb-1">Tamaño mín. pivot (× ATR)</label>
                          <input type="number" min={0.1} max={3} step={0.1} value={form.ind_config.atr_mult ?? 0.3}
                            onChange={e => setInd('atr_mult', parseFloat(e.target.value))}
                            className="input w-full text-sm" />
                          <p className="text-[10px] text-slate-400 mt-0.5">Pivots más pequeños = más señales</p>
                        </div>
                        <div>
                          <label className="block text-xs text-slate-600 dark:text-gray-300 mb-1">Período ATR</label>
                          <input type="number" min={5} max={30} value={form.ind_config.atr_len ?? 14}
                            onChange={e => setInd('atr_len', parseInt(e.target.value))}
                            className="input w-full text-sm" />
                        </div>
                        <div>
                          <label className="block text-xs text-slate-600 dark:text-gray-300 mb-1">Modo de entrada</label>
                          <select value={form.ind_config.entry_mode ?? 'ob_or_fvg'} onChange={e => setInd('entry_mode', e.target.value)} className="input w-full text-sm">
                            <option value="ob_or_fvg">OB o FVG</option>
                            <option value="ob_only">Solo Order Block</option>
                            <option value="fvg_only">Solo FVG</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs text-slate-600 dark:text-gray-300 mb-1">Velas a analizar</label>
                          <input type="number" min={100} max={500} step={50} value={form.ind_config.candles_limit ?? 200}
                            onChange={e => setInd('candles_limit', parseInt(e.target.value))}
                            className="input w-full text-sm" />
                        </div>
                      </div>
                    </div>
                  )}


                  <Field label="Temporalidad del scan" hint="El bot escaneará esta TF buscando confluencias. Puede diferir del TF de ejecución.">
                    <select value={form.trigger_timeframe} onChange={e => set('trigger_timeframe', e.target.value)} className="input">
                      <option value="">Igual que el bot ({form.timeframe})</option>
                      {['15m','30m','1h','2h','4h','6h','8h','12h','1d'].map(tf => (
                        <option key={tf} value={tf}>{tf}</option>
                      ))}
                    </select>
                  </Field>

                  <Field label="Tipos de señal que activan el bot">
                    <div className="space-y-2">
                      {[
                        { g: 'A+', color: 'emerald', dir: 'LONG',       desc: 'BOS alcista — ruptura de estructura al alza' },
                        { g: 'A',  color: 'blue',    dir: 'LONG/SHORT', desc: 'CHoCH — cambio de carácter (reversión de tendencia)' },
                        { g: 'A-', color: 'red',     dir: 'SHORT',      desc: 'BOS bajista — ruptura de estructura a la baja' },
                      ].map(({ g, color, dir, desc }) => {
                        const grades = form.trigger_min_grade ? form.trigger_min_grade.split(',') : []
                        const checked = grades.includes(g)
                        const toggle = () => {
                          const next = checked ? grades.filter(x => x !== g) : [...grades, g]
                          set('trigger_min_grade', next.join(',') || 'A+,A,A-')
                        }
                        const colors = {
                          emerald: checked ? 'border-emerald-500 bg-emerald-500/10' : 'border-slate-200 dark:border-gray-700',
                          blue:    checked ? 'border-blue-500 bg-blue-500/10'       : 'border-slate-200 dark:border-gray-700',
                          red:     checked ? 'border-red-500 bg-red-500/10'         : 'border-slate-200 dark:border-gray-700',
                        }
                        const badges = { emerald: 'bg-emerald-500/20 text-emerald-300', blue: 'bg-blue-500/20 text-blue-300', red: 'bg-red-500/20 text-red-300' }
                        return (
                          <button key={g} type="button" onClick={toggle}
                            className={`w-full flex items-center gap-3 p-3 rounded-xl border-2 text-left transition-all ${colors[color]}`}
                          >
                            <div className={`w-4 h-4 rounded border-2 shrink-0 flex items-center justify-center ${checked ? `border-${color}-500 bg-${color}-500` : 'border-slate-400'}`}>
                              {checked && <span className="text-white text-[10px] font-bold">✓</span>}
                            </div>
                            <span className={`text-sm font-bold px-2 py-0.5 rounded ${badges[color]}`}>{g}</span>
                            <div className="flex-1 min-w-0">
                              <p className="text-xs font-semibold text-slate-700 dark:text-gray-200">{dir}</p>
                              <p className="text-[10px] text-slate-500 dark:text-gray-400">{desc}</p>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                    <p className="text-xs text-slate-400 mt-2">
                      {(() => {
                        const grades = form.trigger_min_grade ? form.trigger_min_grade.split(',') : []
                        const hasAp = grades.includes('A+'), hasA = grades.includes('A'), hasAm = grades.includes('A-')
                        if (hasAp && hasA && hasAm) return 'Ejecutará LONG (BOS↑ y CHoCH↑) y SHORT (BOS↓ y CHoCH↓)'
                        if (hasAp && hasA)  return 'Solo LONG: BOS alcista y CHoCH alcista'
                        if (hasA  && hasAm) return 'Solo SHORT: CHoCH bajista y BOS bajista'
                        if (hasAp)          return 'Solo LONG por BOS alcista (continuación)'
                        if (hasAm)          return 'Solo SHORT por BOS bajista (continuación)'
                        if (hasA)           return 'Solo reversiones CHoCH (LONG o SHORT según dirección)'
                        return 'Selecciona al menos un tipo'
                      })()}
                    </p>
                  </Field>

                  <Field label="Timing de la alerta">
                    <div className="flex gap-2">
                      {[
                        ['candle_close', '⏱ Al cierre de vela',  'Señal confirmada — más conservador'],
                        ['intracandle',  '⚡ Durante la vela',    'Entrada más temprana — ideal para TFs altas'],
                      ].map(([val, label, desc]) => (
                        <button key={val} type="button" onClick={() => set('trigger_timing', val)}
                          className={`flex-1 py-2.5 px-3 rounded-xl border-2 text-left transition-all ${
                            form.trigger_timing === val
                              ? 'border-emerald-500 bg-emerald-500/10'
                              : 'border-slate-200 dark:border-gray-700 hover:border-slate-300'
                          }`}
                        >
                          <span className="block text-xs font-semibold text-slate-800 dark:text-white">{label}</span>
                          <span className="block text-[10px] text-slate-500 dark:text-gray-400 mt-0.5">{desc}</span>
                        </button>
                      ))}
                    </div>
                  </Field>

                  {form.trigger_timing === 'intracandle' && (
                    <Field label="Frecuencia de escaneo" hint={`Divide la vela ${scanTf} en partes iguales → cada ~${intervalMin} min`}>
                      <div className="flex items-center gap-3">
                        <select value={form.trigger_interval_minutes} onChange={e => set('trigger_interval_minutes', parseInt(e.target.value))} className="input w-32">
                          {[2, 3, 4, 6, 8, 12, 24].map(n => <option key={n} value={n}>{n}× por vela</option>)}
                        </select>
                        <span className="text-xs text-slate-400">≈ cada {intervalMin} min</span>
                      </div>
                    </Field>
                  )}

                  <Field label="Confirmación de señal" hint="La señal debe detectarse N veces seguidas antes de ejecutar. Reduce falsas entradas.">
                    <select value={form.min_confirm_candles} onChange={e => set('min_confirm_candles', parseInt(e.target.value))} className="input w-40">
                      <option value={1}>Inmediata (1 detección)</option>
                      <option value={2}>2 detecciones seguidas</option>
                      <option value={3}>3 detecciones seguidas</option>
                    </select>
                  </Field>

                  <div className="rounded-lg bg-emerald-900/30 border border-emerald-500/20 px-3 py-2.5 text-xs space-y-1">
                    <p className="font-semibold text-emerald-300">El bot se activará cuando:</p>
                    <ul className="list-disc list-inside space-y-0.5 text-emerald-400/80">
                      <li>ICT detecte confluencia en <strong>{form.trigger_timeframe || form.timeframe}</strong></li>
                      <li>Señal de tipo: <strong>{form.trigger_min_grade || 'A+,A,A-'}</strong></li>
                      <li>{form.trigger_timing === 'candle_close' ? 'Al cierre de la vela' : `Durante la vela — cada ~${intervalMin} min`}</li>
                      {form.min_confirm_candles > 1 && <li>Confirmado <strong>{form.min_confirm_candles}×</strong> seguidas</li>}
                    </ul>
                  </div>
                </div>
              )}

              {/* AI config */}
              {form.ai_signal_mode && (
                <div className="mt-4 rounded-xl border border-violet-500/30 bg-violet-500/5 px-4 py-4 space-y-4">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-violet-400 uppercase tracking-wide">Filtros del scanner IA</p>
                    <AutoConfigButton symbol={form.symbol} onApply={(cfg) => {
                      // 1. Build updated form object
                      const updated = {
                        ...form,
                        ai_optimal_config_enabled: true,
                        auto_timeframe: true,
                        ai_min_score: cfg.min_score,
                        ai_allowed_tiers: cfg.allowed_tiers,
                        ai_allowed_statuses: cfg.allowed_statuses,
                        ai_max_concurrent: cfg.max_concurrent,
                        ai_sizing_strong: Math.round((cfg.sizing_multipliers?.STRONG ?? 1) * 100),
                        ai_sizing_moderate: Math.round((cfg.sizing_multipliers?.MODERATE ?? 1) * 100),
                        ai_sizing_weak: Math.round((cfg.sizing_multipliers?.WEAK ?? 1) * 100),
                        ai_sizing_clear: Math.round((cfg.sizing_multipliers?.CLEAR ?? 1) * 100),
                        ai_sizing_caution: Math.round((cfg.sizing_multipliers?.CAUTION ?? 1) * 100),
                        ai_cb_strong: cfg.circuit_breaker_thresholds?.STRONG?.consecutive_sl ?? 3,
                        ai_cb_moderate: cfg.circuit_breaker_thresholds?.MODERATE?.consecutive_sl ?? 2,
                        ai_cb_weak: cfg.circuit_breaker_thresholds?.WEAK?.consecutive_sl ?? 1,
                        ai_pf_total: cfg.portfolio_limits?.max_total_exposure_pct ?? 50,
                        ai_pf_symbol: cfg.portfolio_limits?.max_symbol_exposure_pct ?? 30,
                        ai_pf_dir: cfg.portfolio_limits?.max_directional_exposure_pct ?? 40,
                        ai_pf_alt: cfg.portfolio_limits?.alt_correlation_threshold ?? 3,
                      }
                      // 2. Update local state for visual feedback
                      setForm(updated)
                      // 3. Auto-save in background (only for edit mode)
                      if (isEdit && botId) {
                        const payload = buildPayload(updated)
                        botsService.update(botId, payload)
                          .then(r => {
                            setBotData(r.data)
                            // Toast or subtle feedback could go here
                          })
                          .catch(e => {
                            const detail = e.response?.data?.detail
                            setError(detail || 'Error al guardar config automática')
                          })
                      }
                    }} />
                  </div>

                  {/* Auto-apply optimal config */}
                  <div className="flex items-center justify-between p-3 rounded-lg bg-violet-500/10 border border-violet-500/20">
                    <div>
                      <p className="text-sm font-medium text-slate-800 dark:text-white">Config óptima automática</p>
                      <p className="text-xs text-slate-500 dark:text-gray-400">Aplica automáticamente la mejor configuración por ticker basada en estadísticas históricas de señales AI.</p>
                    </div>
                    <Toggle checked={form.ai_optimal_config_enabled} onChange={v => set('ai_optimal_config_enabled', v)} />
                  </div>

                  {/* Auto-timeframe */}
                  <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <div>
                      <p className="text-sm font-medium text-slate-800 dark:text-white">Temporalidad autónoma</p>
                      <p className="text-xs text-slate-500 dark:text-gray-400">El bot ignora el timeframe fijo y solo activa señales en la temporalidad con mejor rendimiento histórico para este par.</p>
                    </div>
                    <Toggle checked={form.auto_timeframe} onChange={v => set('auto_timeframe', v)} />
                  </div>

                  <Field label="Score mínimo de confluencia" hint="0–100. El scanner puntúa cada señal; solo pasan las que superen este umbral.">
                    <div className="flex items-center gap-3">
                      <input type="number" min="0" max="100" step="5" value={form.ai_min_score}
                        onChange={e => set('ai_min_score', e.target.value)} className="input w-24" placeholder="60" />
                      <span className="text-sm text-slate-500 dark:text-gray-400">/ 100</span>
                    </div>
                  </Field>

                  <Field label="Máx. posiciones IA simultáneas" hint="No abre nueva posición si ya tiene este número abierto.">
                    <input type="number" min="1" max="5" step="1" value={form.ai_max_concurrent}
                      onChange={e => set('ai_max_concurrent', e.target.value)} className="input w-24" placeholder="1" />
                  </Field>

                  {/* Tiers selector */}
                  <Field label="Tiers de calidad aceptados" hint="STRONG = ≥70 pts · MODERATE = ≥45 pts · WEAK = <45 pts. Incluir tiers inferiores aumenta operaciones pero también riesgo.">
                    <div className="space-y-2">
                      {[
                        { tier: 'STRONG',   label: 'STRONG',   color: 'emerald', desc: '≥70 pts — calidad alta (recomendado)' },
                        { tier: 'MODERATE', label: 'MODERATE', color: 'yellow',  desc: '≥45 pts — calidad media' },
                        { tier: 'WEAK',     label: 'WEAK',     color: 'orange',  desc: '<45 pts — calidad baja, alto riesgo' },
                      ].map(({ tier, label, color, desc }) => {
                        const checked = (form.ai_allowed_tiers || []).includes(tier)
                        const toggle = () => {
                          const next = checked
                            ? (form.ai_allowed_tiers || []).filter(t => t !== tier)
                            : [...(form.ai_allowed_tiers || []), tier]
                          set('ai_allowed_tiers', next.length ? next : ['STRONG'])
                        }
                        const border = checked
                          ? color === 'emerald' ? 'border-emerald-500 bg-emerald-500/10'
                          : color === 'yellow'  ? 'border-yellow-500 bg-yellow-500/10'
                          : 'border-orange-500 bg-orange-500/10'
                          : 'border-slate-200 dark:border-gray-700'
                        const badge = color === 'emerald' ? 'bg-emerald-500/20 text-emerald-300'
                          : color === 'yellow' ? 'bg-yellow-500/20 text-yellow-300'
                          : 'bg-orange-500/20 text-orange-300'
                        return (
                          <button key={tier} type="button" onClick={toggle}
                            className={`w-full flex items-center gap-3 p-3 rounded-xl border-2 text-left transition-all ${border}`}
                          >
                            <div className={`w-4 h-4 rounded border-2 shrink-0 flex items-center justify-center ${checked ? 'border-current bg-current' : 'border-slate-400'}`}>
                              {checked && <span className="text-white text-[10px] font-bold">✓</span>}
                            </div>
                            <span className={`text-sm font-bold px-2 py-0.5 rounded ${badge}`}>{label}</span>
                            <div className="flex-1 min-w-0">
                              <p className="text-[10px] text-slate-500 dark:text-gray-400">{desc}</p>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </Field>

                  {/* Statuses selector */}
                  <Field label="Estados anti-fake aceptados" hint="CLEAR = sin red flags · CAUTION = 1 red flag (esperar confirmación) · BLOCK = 2+ red flags (evitar). Incluir CAUTION aumenta señales pero también falsos positivos.">
                    <div className="space-y-2">
                      {[
                        { status: 'CLEAR',   label: 'CLEAR',   color: 'emerald', desc: '0 red flags — señal limpia (recomendado)' },
                        { status: 'CAUTION', label: 'CAUTION', color: 'yellow',  desc: '1 red flag — precaución, mayor riesgo' },
                      ].map(({ status, label, color, desc }) => {
                        const checked = (form.ai_allowed_statuses || []).includes(status)
                        const toggle = () => {
                          const next = checked
                            ? (form.ai_allowed_statuses || []).filter(s => s !== status)
                            : [...(form.ai_allowed_statuses || []), status]
                          set('ai_allowed_statuses', next.length ? next : ['CLEAR'])
                        }
                        const border = checked
                          ? color === 'emerald' ? 'border-emerald-500 bg-emerald-500/10'
                          : 'border-yellow-500 bg-yellow-500/10'
                          : 'border-slate-200 dark:border-gray-700'
                        const badge = color === 'emerald' ? 'bg-emerald-500/20 text-emerald-300'
                          : 'bg-yellow-500/20 text-yellow-300'
                        return (
                          <button key={status} type="button" onClick={toggle}
                            className={`w-full flex items-center gap-3 p-3 rounded-xl border-2 text-left transition-all ${border}`}
                          >
                            <div className={`w-4 h-4 rounded border-2 shrink-0 flex items-center justify-center ${checked ? 'border-current bg-current' : 'border-slate-400'}`}>
                              {checked && <span className="text-white text-[10px] font-bold">✓</span>}
                            </div>
                            <span className={`text-sm font-bold px-2 py-0.5 rounded ${badge}`}>{label}</span>
                            <div className="flex-1 min-w-0">
                              <p className="text-[10px] text-slate-500 dark:text-gray-400">{desc}</p>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                    <p className="text-xs text-amber-600 dark:text-amber-400 mt-2">
                      ⚠️ BLOCK nunca se incluye por seguridad. Revisa el backtest antes de activar MODERATE o CAUTION.
                    </p>
                  </Field>

                  {/* Sizing multipliers */}
                  <Field label="Sizing dinámico por calidad" hint="% del capital configurado que se usará según tier y status. 100% = tamaño normal. 50% = mitad de riesgo. 0% = desactivado.">
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        { key: 'ai_sizing_strong',   label: 'STRONG',   color: 'emerald', def: 100 },
                        { key: 'ai_sizing_moderate', label: 'MODERATE', color: 'yellow',  def: 100 },
                        { key: 'ai_sizing_weak',     label: 'WEAK',     color: 'orange',  def: 100 },
                        { key: 'ai_sizing_clear',    label: 'CLEAR',    color: 'emerald', def: 100 },
                        { key: 'ai_sizing_caution',  label: 'CAUTION',  color: 'yellow',  def: 100 },
                      ].map(({ key, label, color, def }) => (
                        <div key={key} className="flex items-center gap-2">
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                            color === 'emerald' ? 'bg-emerald-500/20 text-emerald-300' :
                            color === 'yellow'  ? 'bg-yellow-500/20 text-yellow-300' :
                            'bg-orange-500/20 text-orange-300'
                          }`}>{label}</span>
                          <input type="number" min="0" max="200" step="5"
                            value={form[key] ?? def}
                            onChange={e => set(key, e.target.value)}
                            className="input w-16 text-xs py-1" />
                          <span className="text-xs text-slate-500">%</span>
                        </div>
                      ))}
                    </div>
                  </Field>

                  {/* Circuit breaker thresholds */}
                  <Field label="Circuit breaker por tier" hint="Cuántos SL consecutivos en ese tier bloquean nuevas entradas. Se auto-resetea después de 24h.">
                    <div className="space-y-2">
                      {[
                        { key: 'ai_cb_strong',   label: 'STRONG',   color: 'emerald', def: 3 },
                        { key: 'ai_cb_moderate', label: 'MODERATE', color: 'yellow',  def: 2 },
                        { key: 'ai_cb_weak',     label: 'WEAK',     color: 'orange',  def: 1 },
                      ].map(({ key, label, color, def }) => (
                        <div key={key} className="flex items-center gap-3">
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded w-20 text-center ${
                            color === 'emerald' ? 'bg-emerald-500/20 text-emerald-300' :
                            color === 'yellow'  ? 'bg-yellow-500/20 text-yellow-300' :
                            'bg-orange-500/20 text-orange-300'
                          }`}>{label}</span>
                          <input type="number" min="1" max="10" step="1"
                            value={form[key] ?? def}
                            onChange={e => set(key, e.target.value)}
                            className="input w-16 text-xs py-1" />
                          <span className="text-xs text-slate-500">SL seguidos → pausa</span>
                        </div>
                      ))}
                    </div>
                  </Field>

                  {/* Portfolio limits */}
                  <Field label="Límites de exposición (Portfolio)" hint="El bot reducirá o bloqueará entradas si se superan estos umbrales de riesgo agregado.">
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        { key: 'ai_pf_total', label: 'Exposición total max', unit: '% equity', def: 50 },
                        { key: 'ai_pf_symbol', label: 'Por símbolo max', unit: '% equity', def: 30 },
                        { key: 'ai_pf_dir', label: 'Direccional max', unit: '% equity', def: 40 },
                        { key: 'ai_pf_alt', label: 'Alts LONG antes alerta', unit: 'posiciones', def: 3 },
                      ].map(({ key, label, unit, def }) => (
                        <div key={key}>
                          <p className="text-[10px] text-slate-500 dark:text-slate-400 mb-1">{label}</p>
                          <div className="flex items-center gap-2">
                            <input type="number" min="1" max="200" step="5"
                              value={form[key] ?? def}
                              onChange={e => set(key, e.target.value)}
                              className="input w-16 text-xs py-1" />
                            <span className="text-[10px] text-slate-500">{unit}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Field>

                  <div className="rounded-lg bg-violet-900/30 border border-violet-500/20 px-3 py-2.5 text-xs space-y-1">
                    <p className="font-semibold text-violet-300">El bot se activará cuando:</p>
                    <ul className="list-disc list-inside space-y-0.5 text-violet-400/80">
                      <li>Score IA ≥ <strong>{form.ai_min_score}</strong></li>
                      <li>Tier: <strong>{(form.ai_allowed_tiers || []).join(', ') || 'STRONG'}</strong></li>
                      <li>Anti-fake: <strong>{(form.ai_allowed_statuses || []).join(', ') || 'CLEAR'}</strong></li>
                      <li>Posiciones IA abiertas &lt; <strong>{form.ai_max_concurrent}</strong></li>
                      <li>Sizing ajustado según tier/status configurado</li>
                      <li>Circuit breaker cerrado para ese tier</li>
                    </ul>
                  </div>
                </div>
              )}
            </>
          )
        })()}

        {/* ── Tab 5: Stop dinámico ── */}
        {tabName === 'Stop dinámico' && (
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
