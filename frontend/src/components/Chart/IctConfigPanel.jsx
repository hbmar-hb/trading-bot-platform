import { useState } from 'react'
import { X } from 'lucide-react'

const TABS = [
  { key: 'config', label: 'Configuración' },
  { key: 'style', label: 'Estilo' },
  { key: 'visibility', label: 'Visibilidad' },
]

function Section({ title, children }) {
  return (
    <div className="mb-4">
      <h4 className="text-[10px] font-bold text-slate-500 dark:text-gray-400 uppercase tracking-wider mb-2">{title}</h4>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

function Toggle({ label, checked, onChange, disabled }) {
  return (
    <label className={`flex items-center gap-2 cursor-pointer ${disabled ? 'opacity-50' : ''}`}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} disabled={disabled} className="w-3.5 h-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
      <span className="text-xs text-slate-700 dark:text-gray-200">{label}</span>
    </label>
  )
}

function NumberInput({ label, value, min, max, step, onChange, disabled }) {
  return (
    <div className={`flex items-center justify-between ${disabled ? 'opacity-50' : ''}`}>
      <span className="text-xs text-slate-700 dark:text-gray-200">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
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
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-mono text-slate-400 uppercase">{value}</span>
        <div className="relative w-6 h-6 rounded overflow-hidden border border-slate-300 dark:border-gray-600">
          <input
            type="color"
            value={value}
            onChange={e => onChange(e.target.value)}
            className="absolute -top-1 -left-1 w-8 h-8 p-0 border-0 cursor-pointer"
          />
        </div>
      </div>
    </div>
  )
}

export default function IctConfigPanel({ config, onChange, onClose }) {
  const [tab, setTab] = useState('config')

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
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-slate-100 dark:border-gray-700/60">
        <span className="text-xs font-bold text-slate-800 dark:text-white">ICT Concepts</span>
        <button onClick={onClose} className="p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-gray-300 rounded hover:bg-slate-100 dark:hover:bg-gray-700">
          <X size={14} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-100 dark:border-gray-700/60">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 px-2 py-2 text-[11px] font-semibold transition-colors ${
              tab === t.key
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-600 dark:border-blue-400'
                : 'text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3">
        {tab === 'config' && (
          <>
            <Section title="ICT Concepts Signals">
              <Toggle label="Signals" checked={config.signals} onChange={v => update('signals', v)} />
              <Toggle label="Show Swing Areas" checked={config.showSwingAreas} onChange={v => update('showSwingAreas', v)} />
              <Toggle label="Trading Overlay" checked={config.tradingOverlay} onChange={v => update('tradingOverlay', v)} />
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-700 dark:text-gray-200">Trading Dashboard</span>
                <select
                  value={config.tradingDashboard}
                  onChange={e => update('tradingDashboard', e.target.value)}
                  className="text-xs bg-slate-100 dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded px-1.5 py-0.5"
                >
                  <option value="top_right">Top Right</option>
                  <option value="top_left">Top Left</option>
                  <option value="off">Off</option>
                </select>
              </div>
            </Section>

            <Section title="Pro Filters">
              <Toggle label="Activar filtros pro" checked={config.proFilters.enabled} onChange={v => update('proFilters.enabled', v)} />
              <div className="pl-4 space-y-2 border-l-2 border-slate-100 dark:border-gray-700">
                <Toggle label="Filtro tendencia (EMA)" checked={config.proFilters.trendFilter} onChange={v => update('proFilters.trendFilter', v)} disabled={!config.proFilters.enabled} />
                <Toggle label="Requerir sweep previo" checked={config.proFilters.requireSweep} onChange={v => update('proFilters.requireSweep', v)} disabled={!config.proFilters.enabled} />
                <Toggle label="Filtro momentum" checked={config.proFilters.momentumFilter} onChange={v => update('proFilters.momentumFilter', v)} disabled={!config.proFilters.enabled} />
                <Toggle label="Cooldown anti-chop" checked={config.proFilters.cooldown} onChange={v => update('proFilters.cooldown', v)} disabled={!config.proFilters.enabled} />
                <NumberInput label="Cooldown barras" value={config.proFilters.cooldownBars} min={1} max={50} onChange={v => update('proFilters.cooldownBars', v)} disabled={!config.proFilters.enabled} />
                <NumberInput label="Pivot len" value={config.proFilters.pivotLen} min={3} max={20} onChange={v => update('proFilters.pivotLen', v)} />
                <NumberInput label="ATR mult" value={config.proFilters.atrMult} min={0} max={5} step={0.1} onChange={v => update('proFilters.atrMult', v)} />
                <NumberInput label="Trend EMA" value={config.proFilters.trendLen} min={10} max={200} onChange={v => update('proFilters.trendLen', v)} />
              </div>
            </Section>
          </>
        )}

        {tab === 'style' && (
          <>
            <Section title="ICT Signals">
              <ColorInput label="Long" value={config.colors.signalLong} onChange={v => update('colors.signalLong', v)} />
              <ColorInput label="Short" value={config.colors.signalShort} onChange={v => update('colors.signalShort', v)} />
              <ColorInput label="Contra-tendencia" value={config.colors.signalContra} onChange={v => update('colors.signalContra', v)} />
            </Section>
            <Section title="ICT Overlay">
              <ColorInput label="Alcista" value={config.colors.overlayBull} onChange={v => update('colors.overlayBull', v)} />
              <ColorInput label="Bajista" value={config.colors.overlayBear} onChange={v => update('colors.overlayBear', v)} />
            </Section>
          </>
        )}

        {tab === 'visibility' && (
          <>
            <Section title="Elementos">
              <Toggle label="BOS / CHoCH" checked={config.visibility.bosChoch} onChange={v => update('visibility.bosChoch', v)} />
              <Toggle label="Order Blocks" checked={config.visibility.orderBlocks} onChange={v => update('visibility.orderBlocks', v)} />
              <Toggle label="Fair Value Gaps" checked={config.visibility.fairValueGaps} onChange={v => update('visibility.fairValueGaps', v)} />
              <Toggle label="Pivots (H/L)" checked={config.visibility.pivots} onChange={v => update('visibility.pivots', v)} />
              <Toggle label="Entry Signals" checked={config.visibility.entries} onChange={v => update('visibility.entries', v)} />
              <Toggle label="Active Levels" checked={config.visibility.levels} onChange={v => update('visibility.levels', v)} />
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
