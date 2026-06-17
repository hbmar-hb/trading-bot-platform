import { Zap, Settings, X } from 'lucide-react'

/**
 * Badge flotante del indicador Quantum Gold.
 * Muestra el estado actual del mercado en tiempo real.
 * Se posiciona debajo del badge ICT (top-12) para evitar solapamiento.
 */
export default function QuantumGoldBadge({ result, onOpenSettings, onClose }) {
  const cur = result?.cur

  const trendColor = !cur ? 'text-slate-400'
    : cur.stBull ? 'text-emerald-400' : 'text-red-400'

  const trendLabel = !cur ? '–'
    : cur.stBull ? '▲ BULL' : '▼ BEAR'

  const sessLabel = !cur ? null
    : cur.session.lon && cur.session.ny ? 'LON+NY'
    : cur.session.lon ? 'LON'
    : cur.session.ny  ? 'NY'
    : null

  const sigLabel = !cur?.lastSig ? null
    : cur.lastSig.isLong ? '▲ LONG' : '▼ SHORT'

  const sigColor = !cur?.lastSig ? ''
    : cur.lastSig.isLong ? 'text-emerald-300' : 'text-red-300'

  return (
    <div className="absolute top-12 left-2 flex items-center gap-1 bg-slate-900/92 backdrop-blur border border-yellow-700/40 rounded-lg px-2 py-1 z-40 shadow-lg select-none">

      {/* Icono + nombre */}
      <Zap size={11} className="text-yellow-400 shrink-0" />
      <span className="text-xs font-bold text-yellow-300 tracking-wide">QUANTUM</span>

      {/* Separador */}
      <span className="text-slate-600">·</span>

      {/* Tendencia Supertrend */}
      <span className={`text-xs font-semibold ${trendColor}`}>{trendLabel}</span>

      {/* RSI */}
      {cur && (
        <>
          <span className="text-slate-600">·</span>
          <span className={`text-xs ${cur.rsi > 70 ? 'text-red-400' : cur.rsi < 30 ? 'text-emerald-400' : 'text-slate-300'}`}>
            RSI {Math.round(cur.rsi)}
          </span>
        </>
      )}

      {/* Squeeze activo */}
      {cur?.squeeze && (
        <>
          <span className="text-slate-600">·</span>
          <span className="text-xs text-yellow-400 font-semibold animate-pulse">SQZ</span>
        </>
      )}

      {/* Sesión */}
      {sessLabel && (
        <>
          <span className="text-slate-600">·</span>
          <span className="text-xs text-blue-400">{sessLabel}</span>
        </>
      )}

      {/* Última señal */}
      {sigLabel && (
        <>
          <span className="text-slate-600">·</span>
          <span className={`text-xs font-bold ${sigColor}`}>{sigLabel}</span>
        </>
      )}

      {/* Controles */}
      <button
        onClick={onOpenSettings}
        className="ml-1 text-slate-500 hover:text-yellow-400 transition-colors"
        title="Configuración"
      >
        <Settings size={11} />
      </button>
      <button
        onClick={onClose}
        className="text-slate-500 hover:text-red-400 transition-colors"
        title="Cerrar indicador"
      >
        <X size={11} />
      </button>
    </div>
  )
}
