import { Settings, X } from 'lucide-react'

const STRENGTH_LABEL = ['Normal', 'Normal', 'Medio', 'Fuerte']
const STRENGTH_COLOR = ['text-slate-400', 'text-slate-400', 'text-yellow-400', 'text-emerald-400']

export default function SBTBadge({ result, onOpenSettings, onClose }) {
  const dash = result?.dashboard ?? {}

  const resultColor = dash.lastResult === 'win'  ? 'text-emerald-400'
    : dash.lastResult === 'loss'                 ? 'text-red-400'
    : dash.lastResult === 'active'               ? 'text-yellow-400'
    : 'text-slate-400'

  const resultLabel = dash.lastResult === 'win'    ? 'Ganancia TP3'
    : dash.lastResult === 'loss'                   ? 'Pérdida SL'
    : dash.lastResult === 'active'                 ? 'Activa'
    : '—'

  const dirLabel = dash.lastDir === 1 ? 'Long' : dash.lastDir === -1 ? 'Short' : '—'
  const dirColor = dash.lastDir === 1 ? 'text-emerald-400' : dash.lastDir === -1 ? 'text-red-400' : 'text-slate-400'

  const strIdx = Math.min(Math.max(dash.strength ?? 0, 0), 3)

  return (
    <div className="absolute top-2 left-2 z-10 flex flex-col gap-1 rounded-lg bg-gray-900/85 dark:bg-black/85 backdrop-blur-sm border border-gray-700/50 shadow-lg overflow-hidden min-w-[160px]">
      {/* Header row */}
      <div className="flex items-center gap-1.5 px-2.5 pt-2 pb-1">
        <span className="text-[11px] font-bold text-white tracking-tight">
          Squeeze Breakout <span className="text-gray-400 font-normal">[1.0]</span>
        </span>
        <button onClick={onOpenSettings} title="Configuración" className="ml-auto p-0.5 text-gray-400 hover:text-white transition-colors rounded hover:bg-gray-700/50">
          <Settings size={12} />
        </button>
        <button onClick={onClose} title="Desactivar" className="p-0.5 text-gray-400 hover:text-red-400 transition-colors rounded hover:bg-gray-700/50">
          <X size={12} />
        </button>
      </div>

      {/* Info rows */}
      <div className="flex flex-col gap-0.5 px-2.5 pb-2">
        <Row label="Squeeze">
          {dash.sqActive
            ? <span className="text-yellow-400 font-medium">{`ACTIVO (${dash.sqBars})`}</span>
            : <span className="text-slate-500">Ninguno</span>
          }
        </Row>
        <Row label="Señal">
          <span className={dirColor}>{dirLabel}</span>
        </Row>
        <Row label="Fuerza">
          <span className={STRENGTH_COLOR[strIdx]}>{STRENGTH_LABEL[strIdx]}</span>
        </Row>
        <Row label="Trade">
          <span className={resultColor}>{resultLabel}</span>
        </Row>
      </div>
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-[10px] text-gray-500">{label}</span>
      <span className="text-[10px]">{children}</span>
    </div>
  )
}
