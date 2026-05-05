import { Settings, X } from 'lucide-react'

export default function ShowiIctBadge({ onOpenSettings, onClose }) {
  return (
    <div className="absolute top-2 left-2 z-10 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-gray-900/80 dark:bg-black/80 backdrop-blur-sm border border-gray-700/50 shadow-lg">
      <span className="text-[11px] font-bold text-white tracking-tight">
        SHOWI ICT <span className="text-gray-400 font-normal">[1.0]</span>
      </span>
      <button onClick={onOpenSettings} title="Configuración" className="p-0.5 text-gray-400 hover:text-white transition-colors rounded hover:bg-gray-700/50">
        <Settings size={12} />
      </button>
      <button onClick={onClose} title="Desactivar" className="p-0.5 text-gray-400 hover:text-red-400 transition-colors rounded hover:bg-gray-700/50">
        <X size={12} />
      </button>
    </div>
  )
}
