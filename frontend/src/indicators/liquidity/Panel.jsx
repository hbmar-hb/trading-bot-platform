import { X } from 'lucide-react'

function Section({ title, children }) {
  return (
    <div className="mb-4">
      <h4 className="text-[10px] font-bold text-slate-500 dark:text-gray-400 uppercase tracking-wider mb-2">{title}</h4>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="w-3.5 h-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
      <span className="text-xs text-slate-700 dark:text-gray-200">{label}</span>
    </label>
  )
}

function NumberInput({ label, value, min, max, step, onChange }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-700 dark:text-gray-200">{label}</span>
      <input
        type="number" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-16 px-1.5 py-0.5 text-xs bg-slate-100 dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded text-right"
      />
    </div>
  )
}

function ColorInput({ label, value, onChange }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-700 dark:text-gray-200">{label}</span>
      <div className="relative w-6 h-6 rounded overflow-hidden border border-slate-300 dark:border-gray-600">
        <input type="color" value={value} onChange={e => onChange(e.target.value)} className="absolute -top-1 -left-1 w-8 h-8 p-0 border-0 cursor-pointer" />
      </div>
    </div>
  )
}

export default function LiquidityPanel({ config, onChange, onClose }) {
  const update = (path, value) => {
    const keys = path.split('.')
    onChange(prev => {
      const next = { ...prev }
      let target = next
      for (let i = 0; i < keys.length - 1; i++) {
        target[keys[i]] = { ...target[keys[i]] }
        target = target[keys[i]]
      }
      target[keys[keys.length - 1]] = value
      return next
    })
  }

  return (
    <div className="absolute top-10 left-2 z-20 w-80 max-h-[80vh] flex flex-col bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-slate-200 dark:border-gray-700 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-slate-100 dark:border-gray-700/60">
        <span className="text-xs font-bold text-slate-800 dark:text-white">Liquidity Sweeps</span>
        <button onClick={onClose} className="p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-gray-300 rounded hover:bg-slate-100 dark:hover:bg-gray-700">
          <X size={14} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <Section title="Detección">
          <NumberInput label="Lookback (velas)" value={config.lookback} min={10} max={500} onChange={v => update('lookback', v)} />
          <NumberInput label="Tolerancia (%)" value={config.tolerancePercent} min={0.01} max={1} step={0.01} onChange={v => update('tolerancePercent', v)} />
          <NumberInput label="Min. toques" value={config.minTouches} min={2} max={10} onChange={v => update('minTouches', v)} />
        </Section>
        <Section title="Visualización">
          <Toggle label="Mostrar niveles" checked={config.showLevels} onChange={v => update('showLevels', v)} />
          <Toggle label="Mostrar sweeps" checked={config.showSweeps} onChange={v => update('showSweeps', v)} />
        </Section>
        <Section title="Colores">
          <ColorInput label="EQH" value={config.colors.eqh} onChange={v => update('colors.eqh', v)} />
          <ColorInput label="EQL" value={config.colors.eql} onChange={v => update('colors.eql', v)} />
          <ColorInput label="Sweep" value={config.colors.sweep} onChange={v => update('colors.sweep', v)} />
        </Section>
      </div>
    </div>
  )
}
