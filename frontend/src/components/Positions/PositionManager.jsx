import { useState, useEffect } from 'react'
import { 
  Shield, Target, TrendingUp, Lock, Activity, 
  Plus, Minus, X, Check, AlertTriangle, DollarSign,
  Percent, ChevronDown, ChevronUp
} from 'lucide-react'
import { positionsService } from '@/services/positions'

// Panel de Stop Loss
function SLPanel({ position, onUpdate }) {
  const [editing, setEditing] = useState(false)
  const [mode, setMode] = useState('pct') // 'pct' | 'price'
  const [pctValue, setPctValue] = useState('')
  const [priceValue, setPriceValue] = useState('')
  const [loading, setLoading] = useState(false)

  const currentSL = parseFloat(position?.current_sl_price || 0)
  const entryPrice = parseFloat(position?.entry_price || 0)
  const side = position?.side || 'long'
  const isProfit = side === 'long' ? currentSL > entryPrice : currentSL < entryPrice

  // Calcula % actual del SL respecto a entrada
  const currentSlPct = entryPrice > 0
    ? Math.abs(((currentSL - entryPrice) / entryPrice) * 100).toFixed(2)
    : '0'

  // Precio calculado desde el % introducido
  const priceFromPct = pctValue
    ? (side === 'long'
        ? entryPrice * (1 - parseFloat(pctValue) / 100)
        : entryPrice * (1 + parseFloat(pctValue) / 100))
    : null

  const handleSave = async () => {
    const price = mode === 'pct' ? priceFromPct : parseFloat(priceValue)
    if (!price || isNaN(price)) return
    setLoading(true)
    try {
      await positionsService.updateSL(position.id, { sl_price: price })
      onUpdate?.()
      setEditing(false)
      setPctValue('')
      setPriceValue('')
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || 'Error actualizando SL'
      alert(msg)
    } finally {
      setLoading(false)
    }
  }

  const openEditing = (pct) => {
    setPctValue(pct !== undefined ? String(pct) : '')
    setPriceValue(currentSL.toString())
    setEditing(true)
  }

  return (
    <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Shield size={16} className="text-red-500 dark:text-red-400" />
          <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300">Stop Loss</h4>
        </div>
        {isProfit && (
          <span className="text-xs bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 px-2 py-0.5 rounded">
            En Profit
          </span>
        )}
      </div>

      {/* Precio actual */}
      <div className="flex items-center justify-between mb-2">
        <div>
          <span className="font-mono text-lg text-red-500 dark:text-red-400">
            ${formatPrice(currentSL)}
          </span>
          <span className="text-xs text-slate-500 dark:text-gray-500 ml-2">
            -{currentSlPct}%
          </span>
        </div>
        <button
          onClick={() => openEditing()}
          className="p-1.5 hover:bg-slate-200 dark:hover:bg-gray-700 rounded text-slate-600 dark:text-gray-400"
        >
          <Activity size={14} />
        </button>
      </div>

      {editing ? (
        <div className="space-y-2">
          {/* Toggle modo */}
          <div className="flex rounded overflow-hidden border border-slate-200 dark:border-gray-700 text-xs">
            <button
              onClick={() => setMode('pct')}
              className={`flex-1 py-1 ${mode === 'pct' ? 'bg-blue-600 text-white' : 'bg-slate-100 dark:bg-gray-800 text-slate-600 dark:text-gray-400'}`}
            >
              % pérdida
            </button>
            <button
              onClick={() => setMode('price')}
              className={`flex-1 py-1 ${mode === 'price' ? 'bg-blue-600 text-white' : 'bg-slate-100 dark:bg-gray-800 text-slate-600 dark:text-gray-400'}`}
            >
              Precio
            </button>
          </div>

          {mode === 'pct' ? (
            <div>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  value={pctValue}
                  onChange={(e) => setPctValue(e.target.value)}
                  placeholder="ej: 2"
                  className="flex-1 input text-sm"
                  autoFocus
                />
                <span className="text-slate-500 dark:text-gray-400 text-sm">%</span>
              </div>
              {priceFromPct && (
                <p className="text-xs text-slate-500 dark:text-gray-500 mt-1">
                  Precio: ${formatPrice(priceFromPct)}
                </p>
              )}
            </div>
          ) : (
            <input
              type="number"
              step="0.00000001"
              value={priceValue}
              onChange={(e) => setPriceValue(e.target.value)}
              placeholder={currentSL.toString()}
              className="w-full input text-sm"
              autoFocus
            />
          )}

          <div className="flex gap-2">
            <button
              onClick={handleSave}
              disabled={loading}
              className="flex-1 btn-primary text-xs py-1"
            >
              {loading ? '...' : 'Guardar'}
            </button>
            <button
              onClick={() => { setEditing(false); setPctValue(''); setPriceValue('') }}
              className="flex-1 btn-secondary text-xs py-1"
            >
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        /* Quick moves */
        <div className="flex gap-1">
          {[0.5, 1, 2, 3, 5].map((pct) => (
            <button
              key={pct}
              onClick={() => openEditing(pct)}
              className="flex-1 px-1 py-1 bg-slate-200 dark:bg-gray-700 hover:bg-slate-300 dark:hover:bg-gray-600 rounded text-xs text-slate-600 dark:text-gray-400"
            >
              -{pct}%
            </button>
          ))}
          <button
            onClick={() => { setPriceValue(entryPrice.toString()); setMode('price'); setEditing(true) }}
            className="flex-1 px-1 py-1 bg-slate-200 dark:bg-gray-700 hover:bg-slate-300 dark:hover:bg-gray-600 rounded text-xs text-slate-600 dark:text-gray-400"
          >
            BE
          </button>
        </div>
      )}
    </div>
  )
}

// Formatea precio evitando notación científica
function formatPrice(price) {
  const p = parseFloat(price)
  if (!p || isNaN(p)) return '0'
  if (p >= 1000) return p.toFixed(2)
  if (p >= 1) return p.toFixed(4)
  if (p >= 0.01) return p.toFixed(6)
  return p.toFixed(8)
}

// Calcula % de beneficio de un TP respecto al precio de entrada
function tpToPercent(tpPrice, entryPrice, side) {
  const tp = parseFloat(tpPrice)
  const entry = parseFloat(entryPrice)
  if (!tp || !entry) return 0
  const pct = side === 'long'
    ? ((tp / entry) - 1) * 100
    : ((entry / tp) - 1) * 100
  return parseFloat(pct.toFixed(2))
}

// Calcula precio absoluto a partir de % de beneficio
function percentToTPPrice(percent, entryPrice, side) {
  const pct = parseFloat(percent) / 100
  const entry = parseFloat(entryPrice)
  if (!entry || isNaN(pct)) return 0
  return side === 'long'
    ? entry * (1 + pct)
    : entry * (1 - pct)
}

// Panel de Take Profits
function TPPanel({ position, onUpdate }) {
  const tps = position?.current_tp_prices || []
  const entryPrice = parseFloat(position?.entry_price || 0)
  const side = position?.side || 'long'
  const [adding, setAdding] = useState(false)
  const [profitPct, setProfitPct] = useState('')
  const [closePercent, setClosePercent] = useState(25)

  const calculatedPrice = profitPct ? percentToTPPrice(profitPct, entryPrice, side) : null

  const handleAdd = async () => {
    if (!profitPct || isNaN(parseFloat(profitPct))) return
    const tpPrice = percentToTPPrice(profitPct, entryPrice, side)
    if (!tpPrice) return
    const updatedTPs = [...tps.map(tp => parseFloat(tp.price || tp)), tpPrice]
    try {
      await positionsService.updateTP(position.id, updatedTPs)
      onUpdate?.()
      setAdding(false)
      setProfitPct('')
    } catch (e) {
      alert('Error añadiendo TP')
    }
  }

  const handleRemove = async (index) => {
    const updatedTPs = tps.filter((_, i) => i !== index).map(tp => parseFloat(tp.price || tp))
    try {
      await positionsService.updateTP(position.id, updatedTPs)
      onUpdate?.()
    } catch (e) {
      alert('Error eliminando TP')
    }
  }

  return (
    <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Target size={16} className="text-green-500 dark:text-green-400" />
          <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300">Take Profits ({tps.length})</h4>
        </div>
        <button
          onClick={() => setAdding(!adding)}
          className="p-1.5 hover:bg-slate-200 dark:hover:bg-gray-700 rounded text-green-600 dark:text-green-400"
        >
          <Plus size={14} />
        </button>
      </div>

      {/* Lista de TPs */}
      <div className="space-y-2 mb-2">
        {tps.map((tp, i) => {
          const tpPrice = parseFloat(tp.price || tp)
          const pct = tpToPercent(tpPrice, entryPrice, side)
          return (
            <div key={i} className="flex items-center justify-between bg-slate-200/60 dark:bg-gray-700/30 rounded p-2">
              <div>
                <span className="text-xs text-slate-500 dark:text-gray-500">TP{i + 1}</span>
                <p className="font-mono text-green-600 dark:text-green-400">+{pct}%</p>
                <p className="text-xs text-slate-500 dark:text-gray-500">${formatPrice(tpPrice)}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs bg-slate-300 dark:bg-gray-700 px-2 py-1 rounded text-slate-700 dark:text-gray-300">
                  {tp.close_percent || 25}%
                </span>
                <button
                  onClick={() => handleRemove(i)}
                  className="p-1 hover:bg-red-500/20 rounded text-red-500 dark:text-red-400"
                >
                  <X size={12} />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Añadir nuevo TP */}
      {adding && (
        <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-gray-700">
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-500 mb-1 block">% de beneficio</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="0.1"
                min="0.1"
                value={profitPct}
                onChange={(e) => setProfitPct(e.target.value)}
                placeholder="ej: 2"
                className="flex-1 input text-sm"
              />
              <span className="text-slate-500 dark:text-gray-400 text-sm">%</span>
            </div>
            {calculatedPrice && (
              <p className="text-xs text-slate-500 dark:text-gray-500 mt-1">
                Precio: ${formatPrice(calculatedPrice)}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 flex-1">
              <input
                type="number"
                min="1"
                max="100"
                step="1"
                value={closePercent}
                onChange={(e) => setClosePercent(Math.min(100, Math.max(1, parseInt(e.target.value) || 1)))}
                className="flex-1 input text-sm"
                placeholder="25"
              />
              <span className="text-slate-500 dark:text-gray-400 text-sm">% pos.</span>
            </div>
            <button
              onClick={handleAdd}
              className="btn-primary text-xs px-3"
            >
              <Check size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// Panel de Trailing Stop
function TrailingPanel({ position, onUpdate }) {
  const [config, setConfig] = useState({
    active: false,
    distance: 2,
    step: 0.5,
    type: 'percentage'
  })

  const handleToggle = async () => {
    const newActive = !config.active
    setConfig({ ...config, active: newActive })
    // Aquí iría la llamada al backend
  }

  return (
    <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-amber-500 dark:text-amber-400" />
          <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300">Trailing Stop</h4>
        </div>
        <button
          onClick={handleToggle}
          className={`px-2 py-1 rounded text-xs ${config.active ? 'bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400' : 'bg-slate-200 dark:bg-gray-700 text-slate-600 dark:text-gray-400'}`}
        >
          {config.active ? 'Activo' : 'Inactivo'}
        </button>
      </div>

      {config.active && (
        <div className="space-y-3 pt-2">
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-500">Distancia: {config.distance}%</label>
            <input
              type="range"
              min="0.5"
              max="10"
              step="0.5"
              value={config.distance}
              onChange={(e) => setConfig({ ...config, distance: parseFloat(e.target.value) })}
              className="w-full h-1 bg-gray-700 rounded-lg appearance-none"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-500">Tipo</label>
            <select
              value={config.type}
              onChange={(e) => setConfig({ ...config, type: e.target.value })}
              className="w-full input text-sm mt-1"
            >
              <option value="percentage">Porcentaje</option>
              <option value="fixed">Fijo (USDT)</option>
            </select>
          </div>
          <p className="text-xs text-slate-500 dark:text-gray-500">
            El SL se moverá automáticamente manteniendo {config.distance}% de distancia del precio favorable.
          </p>
        </div>
      )}
    </div>
  )
}

// Panel de BreakEven
function BreakEvenPanel({ position, onUpdate }) {
  const [config, setConfig] = useState({
    active: false,
    triggerPercent: 1,
    lockProfit: 0.3
  })

  return (
    <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Lock size={16} className="text-blue-500 dark:text-blue-400" />
          <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300">BreakEven</h4>
        </div>
        <button
          onClick={() => setConfig({ ...config, active: !config.active })}
          className={`px-2 py-1 rounded text-xs ${config.active ? 'bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400' : 'bg-slate-200 dark:bg-gray-700 text-slate-600 dark:text-gray-400'}`}
        >
          {config.active ? 'Activo' : 'Inactivo'}
        </button>
      </div>

      {config.active && (
        <div className="space-y-3 pt-2">
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-500">Activar al: {config.triggerPercent}% de profit</label>
            <input
              type="range"
              min="0.5"
              max="5"
              step="0.1"
              value={config.triggerPercent}
              onChange={(e) => setConfig({ ...config, triggerPercent: parseFloat(e.target.value) })}
              className="w-full h-1 bg-gray-700 rounded-lg appearance-none"
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 dark:text-gray-500">Bloquear profit: {config.lockProfit}%</label>
            <input
              type="range"
              min="0.1"
              max="2"
              step="0.1"
              value={config.lockProfit}
              onChange={(e) => setConfig({ ...config, lockProfit: parseFloat(e.target.value) })}
              className="w-full h-1 bg-gray-700 rounded-lg appearance-none"
            />
          </div>
          <p className="text-xs text-slate-500 dark:text-gray-500">
            Cuando el profit alcance {config.triggerPercent}%, el SL se moverá a entrada + {config.lockProfit}%.
          </p>
        </div>
      )}
    </div>
  )
}

// Panel de Stop Dinámico
function DynamicSLPanel({ position, onUpdate }) {
  const [steps, setSteps] = useState([
    { tpPercent: 1, slPercent: 0.5 },
    { tpPercent: 2, slPercent: 1 },
    { tpPercent: 3, slPercent: 2 }
  ])
  const [active, setActive] = useState(false)

  const addStep = () => {
    setSteps([...steps, { tpPercent: steps.length + 1, slPercent: steps.length * 0.5 }])
  }

  const removeStep = (index) => {
    setSteps(steps.filter((_, i) => i !== index))
  }

  return (
    <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-purple-500 dark:text-purple-400" />
          <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300">Stop Dinámico</h4>
        </div>
        <button
          onClick={() => setActive(!active)}
          className={`px-2 py-1 rounded text-xs ${active ? 'bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400' : 'bg-slate-200 dark:bg-gray-700 text-slate-600 dark:text-gray-400'}`}
        >
          {active ? 'Activo' : 'Inactivo'}
        </button>
      </div>

      {active && (
        <div className="space-y-2">
          {steps.map((step, i) => (
            <div key={i} className="flex items-center gap-2 bg-slate-200/60 dark:bg-gray-700/30 rounded p-2">
              <span className="text-xs text-slate-500 dark:text-gray-500 w-8">{i + 1}</span>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-600 dark:text-gray-400">TP:</span>
                  <input
                    type="number"
                    value={step.tpPercent}
                    onChange={(e) => {
                      const newSteps = [...steps]
                      newSteps[i].tpPercent = parseFloat(e.target.value)
                      setSteps(newSteps)
                    }}
                    className="w-14 input text-xs py-1"
                  />
                  <span className="text-xs text-slate-600 dark:text-gray-400">%</span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-slate-600 dark:text-gray-400">SL:</span>
                  <input
                    type="number"
                    value={step.slPercent}
                    onChange={(e) => {
                      const newSteps = [...steps]
                      newSteps[i].slPercent = parseFloat(e.target.value)
                      setSteps(newSteps)
                    }}
                    className="w-14 input text-xs py-1"
                  />
                  <span className="text-xs text-slate-600 dark:text-gray-400">%</span>
                </div>
              </div>
              <button
                onClick={() => removeStep(i)}
                className="p-1 hover:bg-red-500/20 rounded text-red-500 dark:text-red-400"
              >
                <Minus size={14} />
              </button>
            </div>
          ))}
          <button
            onClick={addStep}
            className="w-full py-1.5 bg-slate-200 dark:bg-gray-700 hover:bg-slate-300 dark:hover:bg-gray-600 rounded text-xs flex items-center justify-center gap-1 text-slate-700 dark:text-gray-300"
          >
            <Plus size={14} /> Añadir paso
          </button>
        </div>
      )}
    </div>
  )
}

// Panel de Cierre Parcial
function PartialClosePanel({ position, onUpdate }) {
  const [percent, setPercent] = useState(25)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const currentPnL = parseFloat(position?.unrealized_pnl || 0)
  const quantity = parseFloat(position?.quantity || 0)
  const closeQty = quantity * (percent / 100)
  const estimatedPnL = currentPnL * (percent / 100)
  
  const isValid = true  // el backend y el exchange gestionan el mínimo

  const handleClose = async () => {
    if (!confirm(`¿Cerrar ${percent}% de la posición (${closeQty.toFixed(6)})?`)) return
    
    setLoading(true)
    setError(null)
    try {
      await positionsService.partialClose(position.id, { percent })
      onUpdate?.()
      alert('Cierre parcial ejecutado correctamente')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      if (msg.includes('menor que el mínimo')) {
        setError(`⚠️ ${msg}`)
      } else {
        setError('Error en cierre parcial. Inténtalo de nuevo.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-2">
        <DollarSign size={16} className="text-cyan-500 dark:text-cyan-400" />
        <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300">Cierre Parcial</h4>
      </div>

      <div className="space-y-3">
        <div>
          <label className="text-xs text-slate-500 dark:text-gray-500">% a cerrar: {percent}%</label>
          <input
            type="range"
            min="10"
            max="100"
            step="5"
            value={percent}
            onChange={(e) => { setPercent(parseInt(e.target.value)); setError(null) }}
            className="w-full h-1 bg-gray-700 rounded-lg appearance-none"
          />
          <div className="flex justify-between text-xs text-slate-500 dark:text-gray-500 mt-1">
            <span>10%</span>
            <span>50%</span>
            <span>100%</span>
          </div>
        </div>

        <div className="bg-slate-200/60 dark:bg-gray-700/30 rounded p-2 space-y-1">
          <div className="flex justify-between text-sm">
            <span className="text-slate-500 dark:text-gray-500">Cantidad:</span>
            <span className="font-mono text-slate-800 dark:text-gray-200">{closeQty.toFixed(6)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500 dark:text-gray-500">PnL estimado:</span>
            <span className={`font-mono ${estimatedPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {estimatedPnL >= 0 ? '+' : ''}{estimatedPnL.toFixed(2)} USDT
            </span>
          </div>
        </div>
        
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded p-2 text-xs text-red-400">
            {error}
          </div>
        )}
        
        <button
          onClick={handleClose}
          disabled={loading}
          className={`w-full text-sm py-2 rounded ${
            loading || !isValid 
              ? 'bg-gray-700 text-gray-500 cursor-not-allowed' 
              : 'btn-primary'
          }`}
        >
          {loading ? 'Ejecutando...' : `Tomar ${percent}% de beneficios`}
        </button>
      </div>
    </div>
  )
}

// Botón de Cierre Total
function CloseAllButton({ position, onUpdate }) {
  const [confirming, setConfirming] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleClose = async () => {
    setLoading(true)
    setError(null)
    try {
      await positionsService.close(position.id)
      onUpdate?.()
      alert('Posición cerrada correctamente')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  if (confirming) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 space-y-2">
        <p className="text-sm text-red-400 flex items-center gap-2">
          <AlertTriangle size={16} />
          ¿Cerrar toda la posición?
        </p>
        <p className="text-xs text-gray-400">
          Cantidad: {parseFloat(position?.quantity || 0).toFixed(4)} {position?.symbol}
        </p>
        
        {error && (
          <div className="bg-red-500/20 rounded p-2 text-xs text-red-300">
            Error: {error}
          </div>
        )}
        
        <div className="flex gap-2">
          <button 
            onClick={handleClose}
            disabled={loading}
            className="flex-1 bg-red-600 hover:bg-red-700 text-white py-2 rounded text-sm"
          >
            {loading ? 'Cerrando...' : 'Sí, cerrar todo'}
          </button>
          <button 
            onClick={() => { setConfirming(false); setError(null) }}
            className="flex-1 btn-secondary text-sm py-2"
          >
            Cancelar
          </button>
        </div>
      </div>
    )
  }

  return (
    <button 
      onClick={() => setConfirming(true)}
      className="w-full bg-red-600 hover:bg-red-700 text-white py-3 rounded-lg text-sm font-medium flex items-center justify-center gap-2"
    >
      <X size={18} />
      Cerrar Posición Total
    </button>
  )
}

// Panel principal que agrupa todo
export default function PositionManager({ position, onPositionUpdate }) {
  const [expanded, setExpanded] = useState({
    sl: true,
    tp: true,
    trailing: false,
    breakeven: false,
    dynamic: false,
    partial: true
  })

  const toggle = (key) => setExpanded({ ...expanded, [key]: !expanded[key] })

  return (
    <div className="space-y-3 w-full">
      {/* SL */}
      <div>
        <button 
          onClick={() => toggle('sl')}
          className="w-full flex items-center justify-between p-2 bg-slate-100 dark:bg-gray-800/50 rounded-lg text-left text-slate-700 dark:text-gray-300"
        >
          <span className="text-sm font-medium">Stop Loss</span>
          {expanded.sl ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {expanded.sl && (
          <div className="mt-2">
            <SLPanel position={position} onUpdate={onPositionUpdate} />
          </div>
        )}
      </div>

      {/* TPs */}
      <div>
        <button 
          onClick={() => toggle('tp')}
          className="w-full flex items-center justify-between p-2 bg-slate-100 dark:bg-gray-800/50 rounded-lg text-left text-slate-700 dark:text-gray-300"
        >
          <span className="text-sm font-medium">Take Profits</span>
          {expanded.tp ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {expanded.tp && (
          <div className="mt-2">
            <TPPanel position={position} onUpdate={onPositionUpdate} />
          </div>
        )}
      </div>

      {/* Trailing */}
      <div>
        <button 
          onClick={() => toggle('trailing')}
          className="w-full flex items-center justify-between p-2 bg-slate-100 dark:bg-gray-800/50 rounded-lg text-left text-slate-700 dark:text-gray-300"
        >
          <span className="text-sm font-medium">Trailing Stop</span>
          {expanded.trailing ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {expanded.trailing && (
          <div className="mt-2">
            <TrailingPanel position={position} onUpdate={onPositionUpdate} />
          </div>
        )}
      </div>

      {/* BreakEven */}
      <div>
        <button 
          onClick={() => toggle('breakeven')}
          className="w-full flex items-center justify-between p-2 bg-slate-100 dark:bg-gray-800/50 rounded-lg text-left text-slate-700 dark:text-gray-300"
        >
          <span className="text-sm font-medium">BreakEven</span>
          {expanded.breakeven ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {expanded.breakeven && (
          <div className="mt-2">
            <BreakEvenPanel position={position} onUpdate={onPositionUpdate} />
          </div>
        )}
      </div>

      {/* Dynamic SL */}
      <div>
        <button 
          onClick={() => toggle('dynamic')}
          className="w-full flex items-center justify-between p-2 bg-slate-100 dark:bg-gray-800/50 rounded-lg text-left text-slate-700 dark:text-gray-300"
        >
          <span className="text-sm font-medium">Stop Dinámico</span>
          {expanded.dynamic ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {expanded.dynamic && (
          <div className="mt-2">
            <DynamicSLPanel position={position} onUpdate={onPositionUpdate} />
          </div>
        )}
      </div>

      {/* Partial Close */}
      <div>
        <button 
          onClick={() => toggle('partial')}
          className="w-full flex items-center justify-between p-2 bg-slate-100 dark:bg-gray-800/50 rounded-lg text-left text-slate-700 dark:text-gray-300"
        >
          <span className="text-sm font-medium">Cierre Parcial</span>
          {expanded.partial ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {expanded.partial && (
          <div className="mt-2">
            <PartialClosePanel position={position} onUpdate={onPositionUpdate} />
          </div>
        )}
      </div>

      {/* Close All */}
      <div className="pt-2 border-t border-slate-200 dark:border-gray-700">
        <CloseAllButton position={position} onUpdate={onPositionUpdate} />
      </div>
    </div>
  )
}
