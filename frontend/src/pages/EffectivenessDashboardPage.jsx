import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, TrendingUp, TrendingDown, Activity, Calendar, Download, Filter } from 'lucide-react'
import { optimizerService } from '@/services/optimizer'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

// ─── Componentes de Gráficos Simples ─────────────────────────

function LineChart({ data, height = 200 }) {
  if (!data || data.length < 2) {
    return <div className="text-center text-slate-400 py-8">Datos insuficientes</div>
  }
  
  const maxVal = Math.max(...data.map(d => d.value), 10)
  const minVal = Math.min(...data.map(d => d.value), -10)
  const range = maxVal - minVal || 1
  
  const points = data.map((d, i) => ({
    x: (i / (data.length - 1)) * 100,
    y: 100 - ((d.value - minVal) / range) * 100,
    value: d.value,
    date: d.date
  }))
  
  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ height }} className="w-full">
      {/* Línea base (0) */}
      <line 
        x1="0" y1={100 - ((0 - minVal) / range) * 100} 
        x2="100" y2={100 - ((0 - minVal) / range) * 100}
        stroke="#94a3b8" strokeWidth="0.5" strokeDasharray="2,2"
      />
      
      {/* Línea de datos */}
      <path d={linePath} fill="none" stroke="#3b82f6" strokeWidth="1.5" />
      
      {/* Puntos */}
      {points.map((p, i) => (
        <circle
          key={i}
          cx={p.x} cy={p.y} r="2"
          fill={p.value >= 0 ? '#22c55e' : '#ef4444'}
          className="hover:r-3 transition-all"
        />
      ))}
    </svg>
  )
}

function BarChart({ data }) {
  if (!data || data.length === 0) return <div className="text-center text-slate-400 py-8">Sin datos</div>
  
  const maxVal = Math.max(...data.map(d => Math.abs(d.value)), 1)
  
  return (
    <div className="space-y-2">
      {data.map((item, i) => {
        const width = Math.min(100, (Math.abs(item.value) / maxVal) * 100)
        const isPositive = item.value >= 0
        
        return (
          <div key={i} className="flex items-center gap-2 text-sm">
            <span className="w-28 text-xs text-slate-500 truncate">{item.name}</span>
            <div className="flex-1 flex items-center">
              <div
                className={`h-5 rounded transition-all ${isPositive ? 'bg-green-500' : 'bg-red-400'}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className={`w-16 text-right font-mono text-xs ${isPositive ? 'text-green-500' : 'text-red-400'}`}>
              {isPositive ? '+' : ''}{item.value}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ─── Componente Principal ────────────────────────────────────

export default function EffectivenessDashboardPage() {
  const { botId } = useParams()
  const navigate = useNavigate()
  
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [dateRange, setDateRange] = useState('30') // días

  useEffect(() => {
    loadData()
  }, [botId, dateRange])

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await optimizerService.getEffectivenessDashboard(botId)
      setData(res.data)
    } catch (e) {
      setError('No se pudo cargar el dashboard')
    } finally {
      setLoading(false)
    }
  }

  const exportCSV = () => {
    if (!data?.timeline) return
    
    const csv = [
      ['Fecha', 'Parámetro', 'Cambio', 'Efectividad'].join(','),
      ...data.timeline.map(t => [
        new Date(t.timestamp).toLocaleDateString(),
        Object.keys(t.changes || {}).join('; '),
        JSON.stringify(t.changes || {}),
        t.effectiveness || 'N/A'
      ].join(','))
    ].join('\n')
    
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `effectiveness-${botId}.csv`
    a.click()
  }

  if (loading) return <div className="flex justify-center py-20"><LoadingSpinner /></div>
  if (error) return <p className="text-red-400 p-4">{error}</p>
  if (!data?.summary) return (
    <div className="max-w-4xl mx-auto p-6">
      <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-slate-500 mb-4">
        <ArrowLeft size={16} /> Volver
      </button>
      <p className="text-slate-500 text-center py-12">No hay datos de auto-optimización disponibles</p>
    </div>
  )

  const { summary, weighted_stats, changes_by_parameter, timeline } = data
  
  // Preparar datos para gráficos
  const timelineData = (timeline || [])
    .filter(t => t.effectiveness !== null)
    .slice(-parseInt(dateRange))
    .map(t => ({
      date: new Date(t.timestamp).toLocaleDateString('es', { day: 'numeric', month: 'short' }),
      value: t.effectiveness || 0
    }))
  
  const paramData = Object.entries(changes_by_parameter || {})
    .map(([name, info]) => ({
      name: name.replace(/_/g, ' ').replace(/percentage/g, '%'),
      value: info.avg_effectiveness || 0,
      count: info.count
    }))
    .sort((a, b) => b.value - a.value)

  // Top y bottom cambios
  const sortedChanges = (timeline || [])
    .filter(t => t.effectiveness !== null && t.changes)
    .sort((a, b) => (b.effectiveness || 0) - (a.effectiveness || 0))
  
  const topChanges = sortedChanges.slice(0, 5)
  const bottomChanges = sortedChanges.slice(-5).reverse()

  return (
    <div className="max-w-5xl mx-auto p-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="btn-ghost p-2">
            <ArrowLeft size={20} />
          </button>
          <div>
            <h1 className="text-xl font-bold">📊 Dashboard de Efectividad</h1>
            <p className="text-sm text-slate-500">Análisis de cambios automáticos del bot</p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <select 
            value={dateRange} 
            onChange={(e) => setDateRange(e.target.value)}
            className="text-sm px-3 py-1.5 rounded border border-slate-200"
          >
            <option value="7">Últimos 7 días</option>
            <option value="30">Últimos 30 días</option>
            <option value="90">Últimos 90 días</option>
            <option value="999">Todo</option>
          </select>
          
          <button onClick={exportCSV} className="flex items-center gap-1 text-sm px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded">
            <Download size={14} /> CSV
          </button>
        </div>
      </div>

      {/* Cabecera - Estado General */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
          <p className="text-xs text-slate-500 mb-1">Tasa de éxito</p>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-blue-500">
              {summary.total_auto_changes > 0 
                ? Math.round((timeline?.filter(t => (t.effectiveness || 0) > 0).length / summary.total_auto_changes) * 100)
                : 0}%
            </span>
            <span className="text-xs text-slate-400">{summary.total_auto_changes} cambios</span>
          </div>
        </div>
        
        <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
          <p className="text-xs text-slate-500 mb-1">Efectividad ponderada</p>
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-bold ${
              weighted_stats.weighted_avg > 0 ? 'text-green-500' : 
              weighted_stats.weighted_avg < 0 ? 'text-red-400' : 'text-slate-400'
            }`}>
              {weighted_stats.weighted_avg > 0 ? '+' : ''}{weighted_stats.weighted_avg}
            </span>
            <span className="text-xs text-slate-400">pts</span>
          </div>
        </div>
        
        <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
          <p className="text-xs text-slate-500 mb-1">Tendencia</p>
          <div className="flex items-center gap-2">
            {weighted_stats.trend === 'improving' && <TrendingUp className="text-green-500" size={24} />}
            {weighted_stats.trend === 'declining' && <TrendingDown className="text-red-400" size={24} />}
            {weighted_stats.trend === 'neutral' && <Activity className="text-slate-400" size={24} />}
            <span className={`font-medium ${
              weighted_stats.trend === 'improving' ? 'text-green-500' :
              weighted_stats.trend === 'declining' ? 'text-red-400' : 'text-slate-400'
            }`}>
              {weighted_stats.trend === 'improving' ? 'Mejorando' :
               weighted_stats.trend === 'declining' ? 'Empeorando' : 'Estable'}
            </span>
          </div>
        </div>
        
        <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
          <p className="text-xs text-slate-500 mb-1">Último cambio</p>
          {timeline?.filter(t => t.changes)?.slice(-1)[0] ? (
            <div>
              <span className="text-sm font-medium">
                {Object.keys(timeline.filter(t => t.changes).slice(-1)[0].changes || {}).join(', ')}
              </span>
              <p className="text-xs text-slate-400">
                {new Date(timeline.filter(t => t.changes).slice(-1)[0].timestamp).toLocaleDateString()}
              </p>
            </div>
          ) : (
            <span className="text-sm text-slate-400">Sin cambios</span>
          )}
        </div>
      </div>

      {/* Gráfico de Evolución Temporal */}
      <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
        <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
          <Calendar size={16} /> Evolución Temporal
        </h2>
        <div className="h-48">
          <LineChart data={timelineData} height={180} />
        </div>
        <div className="flex justify-between text-xs text-slate-400 mt-2">
          <span>{timelineData[0]?.date}</span>
          <span>Hoy</span>
        </div>
      </div>

      {/* Gráfico de Barras + Tablas */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Análisis por Parámetro */}
        <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
          <h2 className="text-sm font-semibold mb-4">Efectividad por Parámetro</h2>
          <BarChart data={paramData} />
        </div>

        {/* Mejores Cambios */}
        <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
          <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
            <TrendingUp size={16} className="text-green-500" /> Mejores Cambios
          </h2>
          <div className="space-y-2">
            {topChanges.map((change, i) => (
              <div key={i} className="text-sm p-2 bg-green-50 dark:bg-green-900/20 rounded">
                <div className="flex justify-between">
                  <span className="font-medium">{Object.keys(change.changes || {}).join(', ')}</span>
                  <span className="text-green-600 font-mono">+{change.effectiveness} pts</span>
                </div>
                <p className="text-xs text-slate-500">
                  {new Date(change.timestamp).toLocaleDateString()} • Confianza: {change.confidence}
                </p>
              </div>
            ))}
            {topChanges.length === 0 && (
              <p className="text-sm text-slate-400 text-center py-4">Sin datos suficientes</p>
            )}
          </div>
        </div>
      </div>

      {/* Peores Cambios */}
      <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-slate-200">
        <h2 className="text-sm font-semibold mb-4 flex items-center gap-2">
          <TrendingDown size={16} className="text-red-400" /> Cambios a Evitar
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {bottomChanges.map((change, i) => (
            <div key={i} className="text-sm p-3 bg-red-50 dark:bg-red-900/20 rounded">
              <div className="flex justify-between">
                <span className="font-medium">{Object.keys(change.changes || {}).join(', ')}</span>
                <span className="text-red-500 font-mono">{change.effectiveness} pts</span>
              </div>
              <p className="text-xs text-slate-500 mt-1">
                {new Date(change.timestamp).toLocaleDateString()} • Confianza: {change.confidence}
              </p>
            </div>
          ))}
          {bottomChanges.length === 0 && (
            <p className="text-sm text-slate-400 col-span-full text-center py-4">Sin datos suficientes</p>
          )}
        </div>
      </div>

      {/* Recomendación basada en datos */}
      {summary.most_effective_param && (
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-xl p-4 border border-blue-200">
          <h3 className="text-sm font-medium text-blue-800 dark:text-blue-300 mb-2">
            💡 Recomendación basada en histórico
          </h3>
          <p className="text-sm text-blue-700 dark:text-blue-400">
            El parámetro <strong>{summary.most_effective_param.replace(/_/g, ' ')}</strong> ha sido 
            el más efectivo en las auto-optimizaciones. Considera priorizar ajustes en este parámetro.
          </p>
        </div>
      )}
    </div>
  )
}
