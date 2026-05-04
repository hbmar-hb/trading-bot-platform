import { useState, useEffect } from 'react'
import { TrendingUp, Settings, Play, Pause, RotateCcw } from 'lucide-react'

// Componente de control de Trailing Stop
export default function TrailingStopControl({ 
  position, 
  currentPrice, 
  onActivate, 
  onDeactivate, 
  onUpdate,
  isActive: externalActive 
}) {
  const [isActive, setIsActive] = useState(externalActive || false)
  const [config, setConfig] = useState({
    distance: 2, // % de distancia del precio
    step: 0.5,   // % mínimo de movimiento para actualizar
    type: 'percentage' // 'percentage' | 'fixed'
  })
  const [currentSL, setCurrentSL] = useState(position?.current_sl_price || 0)
  const [highestPrice, setHighestPrice] = useState(0)
  const [lowestPrice, setLowestPrice] = useState(Infinity)
  
  useEffect(() => {
    if (!isActive || !currentPrice) return
    
    const price = parseFloat(currentPrice)
    const entry = parseFloat(position?.entry_price || 0)
    
    if (position?.side === 'long') {
      // Para long: seguir el precio más alto
      if (price > highestPrice) {
        setHighestPrice(price)
        const newSL = price * (1 - config.distance / 100)
        if (newSL > currentSL && newSL > entry * 0.99) { // No bajar del breakeven
          setCurrentSL(newSL)
          onUpdate?.(newSL)
        }
      }
    } else {
      // Para short: seguir el precio más bajo
      if (price < lowestPrice) {
        setLowestPrice(price)
        const newSL = price * (1 + config.distance / 100)
        if (newSL < currentSL || currentSL === 0) {
          setCurrentSL(newSL)
          onUpdate?.(newSL)
        }
      }
    }
  }, [currentPrice, isActive, config.distance])
  
  const handleActivate = () => {
    const price = parseFloat(currentPrice)
    const entry = parseFloat(position?.entry_price || 0)
    
    if (position?.side === 'long') {
      setHighestPrice(price)
      const initialSL = Math.max(
        price * (1 - config.distance / 100),
        entry * 1.005 // Mínimo 0.5% en profit
      )
      setCurrentSL(initialSL)
    } else {
      setLowestPrice(price)
      const initialSL = price * (1 + config.distance / 100)
      setCurrentSL(initialSL)
    }
    
    setIsActive(true)
    onActivate?.(config)
  }
  
  const handleDeactivate = () => {
    setIsActive(false)
    onDeactivate?.(currentSL)
  }
  
  const handleReset = () => {
    setHighestPrice(0)
    setLowestPrice(Infinity)
    setCurrentSL(position?.current_sl_price || 0)
  }
  
  // Calcular distancia actual
  const distance = currentPrice && currentSL 
    ? Math.abs(parseFloat(currentPrice) - currentSL) / parseFloat(currentPrice) * 100
    : 0
  
  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp size={18} className="text-blue-400" />
          <h3 className="font-medium text-gray-300">Trailing Stop</h3>
        </div>
        <div className="flex items-center gap-2">
          {isActive ? (
            <span className="px-2 py-0.5 rounded text-xs bg-green-500/20 text-green-400 animate-pulse">
              Activo
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded text-xs bg-gray-700 text-gray-400">
              Inactivo
            </span>
          )}
        </div>
      </div>
      
      {/* Configuración */}
      <div className="space-y-3">
        <div>
          <label className="text-xs text-gray-500 block mb-1">
            Distancia del precio (%)
          </label>
          <div className="flex items-center gap-3">
            <input 
              type="range"
              min="0.5"
              max="10"
              step="0.5"
              value={config.distance}
              onChange={(e) => setConfig({...config, distance: parseFloat(e.target.value)})}
              disabled={isActive}
              className="flex-1 h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
            />
            <span className="font-mono text-sm w-12 text-right">{config.distance}%</span>
          </div>
        </div>
        
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Tipo</label>
            <select 
              value={config.type}
              onChange={(e) => setConfig({...config, type: e.target.value})}
              disabled={isActive}
              className="input w-full text-sm"
            >
              <option value="percentage">Porcentaje</option>
              <option value="fixed">Fijo (USDT)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Step (%)</label>
            <input 
              type="number"
              step="0.1"
              min="0.1"
              max="2"
              value={config.step}
              onChange={(e) => setConfig({...config, step: parseFloat(e.target.value)})}
              disabled={isActive}
              className="input w-full text-sm"
            />
          </div>
        </div>
      </div>
      
      {/* Estado actual */}
      {isActive && (
        <div className="bg-gray-800/50 rounded-lg p-3 space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">SL Actual:</span>
            <span className="font-mono text-red-400">${currentSL.toFixed(8)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Distancia:</span>
            <span className="font-mono text-blue-400">{distance.toFixed(2)}%</span>
          </div>
          {position?.side === 'long' && highestPrice > 0 && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Máximo alcanzado:</span>
              <span className="font-mono text-green-400">${highestPrice.toFixed(8)}</span>
            </div>
          )}
          {position?.side === 'short' && lowestPrice < Infinity && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Mínimo alcanzado:</span>
              <span className="font-mono text-green-400">${lowestPrice.toFixed(8)}</span>
            </div>
          )}
        </div>
      )}
      
      {/* Controles */}
      <div className="flex gap-2">
        {!isActive ? (
          <button 
            onClick={handleActivate}
            className="btn-primary flex-1 flex items-center justify-center gap-2"
          >
            <Play size={16} />
            Activar
          </button>
        ) : (
          <>
            <button 
              onClick={handleDeactivate}
              className="btn-secondary flex-1 flex items-center justify-center gap-2"
            >
              <Pause size={16} />
              Pausar
            </button>
            <button 
              onClick={handleReset}
              className="p-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
              title="Resetear"
            >
              <RotateCcw size={16} />
            </button>
          </>
        )}
      </div>
      
      <p className="text-xs text-gray-500">
        El Trailing Stop ajusta automáticamente tu SL para proteger ganancias.
      </p>
    </div>
  )
}

// Visualización del trailing stop en el gráfico
export function TrailingStopLine({ chart, candleSeries, position, trailingConfig, currentPrice }) {
  const [lineSeries, setLineSeries] = useState(null)
  
  useEffect(() => {
    if (!chart || !trailingConfig?.active) return
    
    const sl = chart.addLineSeries({
      color: '#f59e0b', // Amber
      lineWidth: 2,
      lineStyle: 2,
      title: 'Trailing SL',
      lastValueVisible: true,
    })
    
    setLineSeries(sl)
    
    return () => {
      chart.removeSeries(sl)
    }
  }, [chart, trailingConfig?.active])
  
  useEffect(() => {
    if (!lineSeries || !currentPrice || !trailingConfig?.slPrice) return
    
    // Actualizar línea con el nuevo SL
    const time = Math.floor(Date.now() / 1000)
    lineSeries.update({ time, value: trailingConfig.slPrice })
  }, [lineSeries, trailingConfig?.slPrice, currentPrice])
  
  return null
}
