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
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)}
        className="w-3.5 h-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
      <span className="text-xs text-slate-700 dark:text-gray-200">{label}</span>
    </label>
  )
}

function NumberInput({ label, value, min, max, step = 1, onChange }) {
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
        <input type="color" value={value} onChange={e => onChange(e.target.value)}
          className="absolute -top-1 -left-1 w-8 h-8 p-0 border-0 cursor-pointer" />
      </div>
    </div>
  )
}

export default function SBTPanel({ config, onChange, onClose }) {
  const upd = (path, value) => {
    const keys = path.split('.')
    onChange(prev => {
      const next = { ...prev }
      let t = next
      for (let i = 0; i < keys.length - 1; i++) {
        t[keys[i]] = { ...t[keys[i]] }
        t = t[keys[i]]
      }
      t[keys[keys.length - 1]] = value
      return next
    })
  }

  return (
    <div className="absolute top-10 left-2 z-20 w-72 max-h-[80vh] flex flex-col bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-slate-200 dark:border-gray-700 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-slate-100 dark:border-gray-700/60">
        <span className="text-xs font-bold text-slate-800 dark:text-white">Squeeze Breakout</span>
        <button onClick={onClose} className="p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-gray-300 rounded hover:bg-slate-100 dark:hover:bg-gray-700">
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        <Section title="Compresión (motor dual BB + ATR)">
          <NumberInput label="Longitud de detección" value={config.squeezeLength} min={10} max={100} onChange={v => upd('squeezeLength', v)} />
          <NumberInput label="Multiplicador BB" value={config.bbMult} min={1.0} max={4.0} step={0.1} onChange={v => upd('bbMult', v)} />
          <NumberInput label="Umbral squeeze (BB)" value={config.squeezeThresh} min={0.1} max={1.0} step={0.05} onChange={v => upd('squeezeThresh', v)} />
          <NumberInput label="Ratio compresión ATR" value={config.atrCompressRatio} min={0.3} max={1.0} step={0.05} onChange={v => upd('atrCompressRatio', v)} />
          <NumberInput label="Barras mín. squeeze" value={config.minSqueezeBars} min={2} max={50} onChange={v => upd('minSqueezeBars', v)} />
          <NumberInput label="Umbral impulso (× ATR)" value={config.impulseMult} min={0.2} max={3.0} step={0.1} onChange={v => upd('impulseMult', v)} />
          <Toggle label="Prevenir superposición" checked={config.preventOverlap} onChange={v => upd('preventOverlap', v)} />
        </Section>

        <Section title="Objetivos (R:R)">
          <NumberInput label="Buffer SL (× ATR)" value={config.slBuffer} min={0.0} max={3.0} step={0.1} onChange={v => upd('slBuffer', v)} />
          <NumberInput label="TP1 R:R" value={config.tp1RR} min={0.1} max={5.0} step={0.1} onChange={v => upd('tp1RR', v)} />
          <NumberInput label="TP2 R:R" value={config.tp2RR} min={0.5} max={10.0} step={0.1} onChange={v => upd('tp2RR', v)} />
          <NumberInput label="TP3 R:R" value={config.tp3RR} min={1.0} max={15.0} step={0.1} onChange={v => upd('tp3RR', v)} />
        </Section>

        <Section title="Filtros">
          <Toggle label="Filtro de volumen" checked={config.useVolFilter} onChange={v => upd('useVolFilter', v)} />
          {config.useVolFilter && (
            <NumberInput label="Multiplicador vol." value={config.volMult} min={1.0} max={5.0} step={0.1} onChange={v => upd('volMult', v)} />
          )}
        </Section>

        <Section title="Visual">
          <Toggle label="Mostrar cajas de rango" checked={config.showBoxes} onChange={v => upd('showBoxes', v)} />
          <Toggle label="Línea central (dashed)" checked={config.showCenter} onChange={v => upd('showCenter', v)} />
          <Toggle label="Señales de ruptura" checked={config.showSignals} onChange={v => upd('showSignals', v)} />
          <Toggle label="Etiquetas resultado (✓/✗)" checked={config.showCloseLbls} onChange={v => upd('showCloseLbls', v)} />
        </Section>

        <Section title="Colores">
          <ColorInput label="Alcista" value={config.colors.bull} onChange={v => upd('colors.bull', v)} />
          <ColorInput label="Bajista" value={config.colors.bear} onChange={v => upd('colors.bear', v)} />
          <ColorInput label="Squeeze (neutral)" value={config.colors.neutral} onChange={v => upd('colors.neutral', v)} />
        </Section>
      </div>
    </div>
  )
}
