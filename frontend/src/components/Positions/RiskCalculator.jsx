import { useState, useEffect } from 'react'
import { Calculator, Target, Shield, TrendingUp, AlertTriangle, Check } from 'lucide-react'

// Calculadora de Riesgo/Recompensa integrada
export default function RiskCalculator({ 
  position, 
  currentPrice, 
  proposedSL, 
  proposedTPs,
  accountBalance = 10000 // Balance por defecto para cálculos
}) {
  const [calculations, setCalculations] = useState(null)
  const [riskPercent, setRiskPercent] = useState(2) // Riesgo por defecto: 2%
  
  useEffect(() => {
    if (!position || !currentPrice) return
    
    const entry = parseFloat(position.entry_price)
    const price = parseFloat(currentPrice)
    const qty = parseFloat(position.quantity)
    const sl = proposedSL ? parseFloat(proposedSL) : parseFloat(position.current_sl_price || 0)
    const tps = proposedTPs?.length > 0 
      ? proposedTPs.map(tp => parseFloat(tp.price || tp))
      : position.current_tp_prices?.map(tp => parseFloat(tp.price)) || []
    
    // Calcular riesgo
    const riskAmount = Math.abs(entry - sl) * qty
    const riskPercentOfAccount = (riskAmount / accountBalance) * 100
    
    // Calcular recompensa potencial
    let rewardAmount = 0
    if (tps.length > 0) {
      // Ponderar por niveles de TP
      tps.forEach((tp, i) => {
        const weight = 1 / tps.length
        const tpProfit = Math.abs(tp - entry) * qty * weight
        rewardAmount += tpProfit
      })
    }
    
    // Ratio Riesgo/Recompensa
    const riskRewardRatio = riskAmount > 0 ? rewardAmount / riskAmount : 0
    
    // Breakeven price (considerando fees estimados)
    const estimatedFee = entry * qty * 0.0005 // 0.05% fee estimado
    const breakevenPrice = position.side === 'long'
      ? entry + (estimatedFee / qty)
      : entry - (estimatedFee / qty)
    
    // Distancia al SL (%)
    const distanceToSL = sl > 0 ? Math.abs(price - sl) / price * 100 : 0
    
    // Recomendación
    let recommendation = 'neutral'
    let recommendationText = 'Configuración aceptable'
    
    if (riskRewardRatio < 1) {
      recommendation = 'danger'
      recommendationText = 'Ratio R/R desfavorable (< 1:1)'
    } else if (riskRewardRatio < 2) {
      recommendation = 'warning'
      recommendationText = 'Ratio R/R bajo (1:1 - 2:1)'
    } else if (riskRewardRatio >= 2 && riskRewardRatio < 3) {
      recommendation = 'good'
      recommendationText = 'Buen ratio R/R (2:1 - 3:1)'
    } else if (riskRewardRatio >= 3) {
      recommendation = 'excellent'
      recommendationText = 'Excelente ratio R/R (> 3:1)'
    }
    
    if (riskPercentOfAccount > 3) {
      recommendation = 'danger'
      recommendationText = 'Riesgo muy alto (> 3% cuenta)'
    }
    
    setCalculations({
      riskAmount,
      riskPercentOfAccount,
      rewardAmount,
      riskRewardRatio,
      breakevenPrice,
      distanceToSL,
      estimatedFee,
      recommendation,
      recommendationText,
      tpDistances: tps.map(tp => ({
        price: tp,
        percent: Math.abs(tp - price) / price * 100,
        profit: Math.abs(tp - entry) * qty
      }))
    })
  }, [position, currentPrice, proposedSL, proposedTPs, accountBalance])
  
  if (!calculations) return null
  
  const getRecommendationColor = (rec) => {
    switch (rec) {
      case 'excellent': return 'bg-green-500/20 border-green-500/50 text-green-400'
      case 'good': return 'bg-green-500/10 border-green-500/30 text-green-400'
      case 'warning': return 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
      case 'danger': return 'bg-red-500/20 border-red-500/50 text-red-400'
      default: return 'bg-gray-700/50 border-gray-600 text-gray-400'
    }
  }
  
  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calculator size={18} className="text-purple-400" />
          <h3 className="font-medium text-gray-300">Análisis de Riesgo</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Balance:</span>
          <input 
            type="number"
            value={accountBalance}
            onChange={(e) => setAccountBalance(parseFloat(e.target.value) || 0)}
            className="w-24 input text-sm"
            placeholder="Balance"
          />
        </div>
      </div>
      
      {/* Recomendación */}
      <div className={`p-3 rounded-lg border ${getRecommendationColor(calculations.recommendation)}`}>
        <div className="flex items-center gap-2">
          {calculations.recommendation === 'danger' ? (
            <AlertTriangle size={16} />
          ) : (
            <Check size={16} />
          )}
          <span className="font-medium text-sm">{calculations.recommendationText}</span>
        </div>
      </div>
      
      {/* Métricas principales */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-800/50 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <Shield size={14} className="text-red-400" />
            <span className="text-xs text-gray-500">Riesgo</span>
          </div>
          <p className="font-mono text-lg text-red-400">
            -${calculations.riskAmount.toFixed(2)}
          </p>
          <p className="text-xs text-gray-500">
            {calculations.riskPercentOfAccount.toFixed(2)}% de cuenta
          </p>
        </div>
        
        <div className="bg-gray-800/50 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <Target size={14} className="text-green-400" />
            <span className="text-xs text-gray-500">Recompensa</span>
          </div>
          <p className="font-mono text-lg text-green-400">
            +${calculations.rewardAmount.toFixed(2)}
          </p>
          <p className="text-xs text-gray-500">
            Ratio: 1:{calculations.riskRewardRatio.toFixed(1)}
          </p>
        </div>
      </div>
      
      {/* Detalles */}
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-500">Breakeven:</span>
          <span className="font-mono">${calculations.breakevenPrice.toFixed(8)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Distancia al SL:</span>
          <span className="font-mono text-red-400">{calculations.distanceToSL.toFixed(2)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Fees estimados:</span>
          <span className="font-mono text-gray-400">${calculations.estimatedFee.toFixed(4)}</span>
        </div>
      </div>
      
      {/* Take Profits */}
      {calculations.tpDistances.length > 0 && (
        <div className="pt-3 border-t border-gray-700">
          <h4 className="text-xs text-gray-500 mb-2 flex items-center gap-2">
            <TrendingUp size={12} />
            Take Profits
          </h4>
          <div className="space-y-1">
            {calculations.tpDistances.map((tp, i) => (
              <div key={i} className="flex justify-between items-center text-sm">
                <span className="text-gray-400">TP{i+1} @ ${tp.price.toFixed(4)}</span>
                <div className="text-right">
                  <span className="font-mono text-green-400">+${tp.profit.toFixed(2)}</span>
                  <span className="text-xs text-gray-500 ml-2">({tp.percent.toFixed(1)}%)</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      
      {/* Slider de riesgo */}
      <div className="pt-3 border-t border-gray-700">
        <label className="text-xs text-gray-500 block mb-2">
          Riesgo máximo recomendado: {riskPercent}%
        </label>
        <input 
          type="range"
          min="0.5"
          max="5"
          step="0.5"
          value={riskPercent}
          onChange={(e) => setRiskPercent(parseFloat(e.target.value))}
          className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
        />
        <p className="text-xs text-gray-500 mt-1">
          {calculations.riskPercentOfAccount <= riskPercent 
            ? '✓ Riesgo dentro de límites aceptables'
            : `⚠ Excede el ${riskPercent}% recomendado`
          }
        </p>
      </div>
    </div>
  )
}

// Mini versión para mostrar en la lista de posiciones
export function RiskBadge({ riskRewardRatio }) {
  if (!riskRewardRatio || riskRewardRatio === 0) return null
  
  let color = 'bg-gray-700 text-gray-400'
  let text = `${riskRewardRatio.toFixed(1)}:1`
  
  if (riskRewardRatio >= 3) {
    color = 'bg-green-500/20 text-green-400'
  } else if (riskRewardRatio >= 2) {
    color = 'bg-green-500/10 text-green-400'
  } else if (riskRewardRatio >= 1) {
    color = 'bg-yellow-500/10 text-yellow-400'
  } else {
    color = 'bg-red-500/10 text-red-400'
  }
  
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      R/R {text}
    </span>
  )
}
