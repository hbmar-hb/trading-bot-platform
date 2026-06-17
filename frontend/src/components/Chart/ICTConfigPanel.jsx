import { useRef, useState, useEffect, useCallback } from 'react'
import { X, GripHorizontal } from 'lucide-react'

// ─── Color presets ────────────────────────────────────────────────────────────

const ICT_COLOR_PRESETS = {
  classic: {
    label: 'Clásico',
    fvg: { colorBull: '#2962FF', colorBear: '#FF6D00', colorIFVG: '#a855f7' },
    ob:  { colorBull: '#1B5E20', colorBear: '#FF5252' },
    structure: {
      colorBull: '#1B5E20', colorBear: '#FF5252',
      colorInternalBull: '#1B5E20', colorInternalBear: '#FF5252',
      colorStrongWeakBull: '#1B5E20', colorStrongWeakBear: '#FF5252',
    },
    fib: { oteColor: '#FFD600', lineColor: '#9E9E9E' },
    signal: { longColor: '#22c55e', shortColor: '#ef4444', entryColor: '#e2e8f0', slColor: '#f87171', tpColor: '#4ade80' },
  },
  dark: {
    label: 'Oscuro',
    fvg: { colorBull: '#38bdf8', colorBear: '#fb7185', colorIFVG: '#c084fc' },
    ob:  { colorBull: '#34d399', colorBear: '#fb7185' },
    structure: {
      colorBull: '#34d399', colorBear: '#fb7185',
      colorInternalBull: '#34d399', colorInternalBear: '#fb7185',
      colorStrongWeakBull: '#34d399', colorStrongWeakBear: '#fb7185',
    },
    fib: { oteColor: '#fde047', lineColor: '#94a3b8' },
    signal: { longColor: '#34d399', shortColor: '#fb7185', entryColor: '#e2e8f0', slColor: '#fca5a5', tpColor: '#86efac' },
  },
  contrast: {
    label: 'Alto contraste',
    fvg: { colorBull: '#00eaff', colorBear: '#ff0055', colorIFVG: '#bd00ff' },
    ob:  { colorBull: '#00ff88', colorBear: '#ff0055' },
    structure: {
      colorBull: '#00ff88', colorBear: '#ff0055',
      colorInternalBull: '#00ff88', colorInternalBear: '#ff0055',
      colorStrongWeakBull: '#00ff88', colorStrongWeakBear: '#ff0055',
    },
    fib: { oteColor: '#ffcc00', lineColor: '#ffffff' },
    signal: { longColor: '#00ff88', shortColor: '#ff0055', entryColor: '#ffffff', slColor: '#ff4444', tpColor: '#00ff66' },
  },
}

export const DEFAULT_ICT_CONFIG = {
  fvg: {
    showFVG:          true,
    showIFVG:         true,
    showMidline:      true,
    showLabel:        true,
    maxFVG:           10,
    maxIFVG:          5,
    extensionBars:    5,
    minSizeATRMult:   0.5,
    filterEnabled:    true,
    colorBull:        '#2962FF',
    colorBear:        '#FF6D00',
    colorIFVG:        '#a855f7',
    alphaFill:        0.18,
  },
  ob: {
    showOB:           true,
    showMidline:      true,
    showLabel:        true,
    showGrade:        true,
    maxPerTf:         10,
    lookback:         30,
    extensionBars:    10,
    mitigation:       'wick',
    minVolumeGrade:   1.2,
    colorBull:        '#1B5E20',
    colorBear:        '#FF5252',
    alphaFill:        0.22,
  },
  structure: {
    showSwingStruct:       true,
    showInternalStruct:    true,
    showSwingLabels:       true,
    showStrongWeak:        true,
    swingLen:              10,
    internalLen:           5,
    minMoveATRMult:        0.5,
    colorBull:             '#1B5E20',
    colorBear:             '#FF5252',
    colorInternalBull:     '#1B5E20',
    colorInternalBear:     '#FF5252',
    colorStrongWeakBull:   '#1B5E20',
    colorStrongWeakBear:   '#FF5252',
  },
  fib: {
    showFib:    true,
    showOTE:    true,
    oteColor:   '#FFD600',
    lineColor:  '#9E9E9E',
  },
  multiTimeframe: {
    enableHTF:           true,
    htfResolution:       '',
    htfEMALen:           50,
    requireHTFAlignment: false,
  },
  signal: {
    showSignal:          true,
    showSL:              true,
    numTPs:              5,
    showTP1:             true,
    showTP2:             true,
    showTP3:             true,
    showTP4:             true,
    showTP5:             true,
    showHistory:         true,
    minScore:            4,
    minRR:               1.2,
    useStructuralSLTP:   true,
    requireSweep:        false,
    rejectAsia:          false,
    rejectEquilibrium:   false,
    requirePremiumDiscount: false,
    poiProximityPct:     0.5,
    recentStructureBars: 15,
    slTpRecencyBars:     20,
    useVolume:           true,
    volSpikeThreshold:   1.5,
    longColor:           '#22c55e',
    shortColor:          '#ef4444',
    entryColor:          '#e2e8f0',
    slColor:             '#f87171',
    tpColor:             '#4ade80',
  },
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function Toggle({ checked, onChange }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-4 w-7 flex-shrink-0 rounded-full transition-colors focus:outline-none ${
        checked ? 'bg-cyan-500' : 'bg-gray-600'
      }`}
    >
      <span
        className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform mt-0.5 ${
          checked ? 'translate-x-3.5' : 'translate-x-0.5'
        }`}
      />
    </button>
  )
}

function Row({ label, checked, onChange }) {
  return (
    <div className="flex items-center justify-between py-1 px-3">
      <span className="text-xs text-gray-300">{label}</span>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  )
}

function NumRow({ label, value, onChange, min = 1, max = 20 }) {
  return (
    <div className="flex items-center justify-between py-1 px-3">
      <span className="text-xs text-gray-400">{label}</span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(Math.max(min, value - 1))}
          className="w-5 h-5 flex items-center justify-center rounded text-gray-400 hover:text-white hover:bg-gray-600 text-sm leading-none"
        >−</button>
        <span className="text-xs text-gray-200 w-5 text-center tabular-nums">{value}</span>
        <button
          onClick={() => onChange(Math.min(max, value + 1))}
          className="w-5 h-5 flex items-center justify-center rounded text-gray-400 hover:text-white hover:bg-gray-600 text-sm leading-none"
        >+</button>
      </div>
    </div>
  )
}

function ColorRow({ label, value, onChange }) {
  return (
    <div className="flex items-center justify-between py-1 px-3">
      <span className="text-xs text-gray-400">{label}</span>
      <label className="cursor-pointer relative">
        <div
          className="w-6 h-5 rounded border border-gray-600 cursor-pointer"
          style={{ backgroundColor: value }}
        />
        <input
          type="color"
          value={value}
          onChange={e => onChange(e.target.value)}
          className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
        />
      </label>
    </div>
  )
}

function AlphaRow({ label, value, onChange, min = 5, max = 60 }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center justify-between py-1 px-3 gap-2">
      <span className="text-xs text-gray-400 flex-shrink-0">{label}</span>
      <div className="flex items-center gap-2 flex-1 justify-end">
        <input
          type="range"
          min={min} max={max} step={1}
          value={pct}
          onChange={e => onChange(parseInt(e.target.value) / 100)}
          className="h-1 w-20 accent-cyan-400"
        />
        <span className="text-xs text-gray-400 w-7 text-right tabular-nums">{pct}%</span>
      </div>
    </div>
  )
}

function RangeRow({ label, value, onChange, min = 0.0, max = 1.0, step = 0.05, suffix = '' }) {
  return (
    <div className="flex items-center justify-between py-1 px-3 gap-2">
      <span className="text-xs text-gray-400 flex-shrink-0">{label}</span>
      <div className="flex items-center gap-2 flex-1 justify-end">
        <input
          type="range"
          min={min} max={max} step={step}
          value={value}
          onChange={e => onChange(parseFloat(e.target.value))}
          className="h-1 w-20 accent-cyan-400"
        />
        <span className="text-xs text-gray-400 w-10 text-right tabular-nums">{value.toFixed(2)}{suffix}</span>
      </div>
    </div>
  )
}

function SelectRow({ label, value, options, onChange }) {
  return (
    <div className="flex items-center justify-between py-1 px-3">
      <span className="text-xs text-gray-400">{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="text-xs bg-gray-800 text-gray-200 border border-gray-700 rounded px-1.5 py-0.5 cursor-pointer focus:outline-none"
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

function SectionHeader({ label, color }) {
  return (
    <div className="flex items-center gap-2 px-3 pt-3 pb-0.5">
      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
      <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">{label}</span>
    </div>
  )
}

function Divider() {
  return <div className="border-t border-gray-700/60 my-1.5" />
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export default function ICTConfigPanel({ config, onChange, onClose }) {
  const panelRef   = useRef(null)
  const isDragging = useRef(false)
  const dragOrigin = useRef({ mx: 0, my: 0, px: 0, py: 0 })
  const [pos, setPos] = useState({ x: 8, y: 60 })

  const onHeaderMouseDown = useCallback((e) => {
    if (!panelRef.current) return
    isDragging.current = true
    dragOrigin.current = { mx: e.clientX, my: e.clientY, px: pos.x, py: pos.y }
    e.preventDefault()
  }, [pos])

  useEffect(() => {
    const onMove = (e) => {
      if (!isDragging.current) return
      const dx = e.clientX - dragOrigin.current.mx
      const dy = e.clientY - dragOrigin.current.my
      setPos({
        x: Math.max(0, dragOrigin.current.px + dx),
        y: Math.max(0, dragOrigin.current.py + dy),
      })
    }
    const onUp = () => { isDragging.current = false }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',   onUp)
    }
  }, [])

  const set = (section, key, value) =>
    onChange({ ...config, [section]: { ...config[section], [key]: value } })

  const applyPreset = (presetKey) => {
    const p = ICT_COLOR_PRESETS[presetKey]
    if (!p) return
    onChange({
      ...config,
      fvg: { ...config.fvg, ...p.fvg },
      ob:  { ...config.ob,  ...p.ob  },
      structure: { ...config.structure, ...p.structure },
      fib: { ...config.fib, ...p.fib },
      signal: { ...config.signal, ...p.signal },
    })
  }

  return (
    <div
      ref={panelRef}
      className="absolute z-50 w-64 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden select-none"
      style={{ left: pos.x, top: pos.y }}
    >
      <div
        className="flex items-center justify-between px-3 py-2 border-b border-gray-700 bg-gray-800/90 cursor-grab active:cursor-grabbing"
        onMouseDown={onHeaderMouseDown}
      >
        <div className="flex items-center gap-1.5">
          <GripHorizontal size={11} className="text-gray-500" />
          <span className="text-xs font-semibold text-cyan-400 tracking-wide">ICT / SMC</span>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-200 transition-colors">
          <X size={13} />
        </button>
      </div>

      <div className="overflow-y-auto max-h-[75vh]">

        {/* ── Preset & quick config ───────────────────────────────────────── */}
        <SectionHeader label="Apariencia" color="#9CA3AF" />
        <SelectRow
          label="Preset color"
          value="custom"
          options={[
            { value: 'custom', label: 'Personalizado' },
            ...Object.entries(ICT_COLOR_PRESETS).map(([k, v]) => ({ value: k, label: v.label })),
          ]}
          onChange={v => v === 'custom' ? null : applyPreset(v)}
        />
        <Divider />

        {/* ── Fair Value Gaps ──────────────────────────────────────────────── */}
        <SectionHeader label="Fair Value Gaps" color="#00BCD4" />
        <Row label="FVG (BISI / SIBI)" checked={config.fvg.showFVG} onChange={v => set('fvg','showFVG',v)} />
        <Row label="IFVG (invertido)"  checked={config.fvg.showIFVG} onChange={v => set('fvg','showIFVG',v)} />
        <Row label="Línea central"     checked={config.fvg.showMidline} onChange={v => set('fvg','showMidline',v)} />
        <Row label="Etiquetas"         checked={config.fvg.showLabel} onChange={v => set('fvg','showLabel',v)} />
        <NumRow label="Máx FVG"  value={config.fvg.maxFVG}  onChange={v => set('fvg','maxFVG',v)} max={50} />
        <NumRow label="Máx IFVG" value={config.fvg.maxIFVG} onChange={v => set('fvg','maxIFVG',v)} max={20} />
        <NumRow label="Extensión" value={config.fvg.extensionBars ?? 5} onChange={v => set('fvg','extensionBars',v)} min={0} max={100} />
        <RangeRow label="Filtro ATR" value={config.fvg.minSizeATRMult ?? 0.5} onChange={v => set('fvg','minSizeATRMult',v)} min={0} max={2} step={0.1} />
        <Divider />
        <ColorRow label="Color alcista" value={config.fvg.colorBull} onChange={v => set('fvg','colorBull',v)} />
        <ColorRow label="Color bajista" value={config.fvg.colorBear} onChange={v => set('fvg','colorBear',v)} />
        <ColorRow label="Color IFVG"    value={config.fvg.colorIFVG} onChange={v => set('fvg','colorIFVG',v)} />
        <AlphaRow label="Opacidad"      value={config.fvg.alphaFill} onChange={v => set('fvg','alphaFill',v)} />

        <Divider />

        {/* ── Order Blocks ─────────────────────────────────────────────────── */}
        <SectionHeader label="Order Blocks" color="#43A047" />
        <Row label="Mostrar OBs"   checked={config.ob.showOB}       onChange={v => set('ob','showOB',v)} />
        <Row label="Línea central" checked={config.ob.showMidline}    onChange={v => set('ob','showMidline',v)} />
        <Row label="Etiquetas"     checked={config.ob.showLabel}      onChange={v => set('ob','showLabel',v)} />
        <Row label="Mostrar grado" checked={config.ob.showGrade}      onChange={v => set('ob','showGrade',v)} />
        <SelectRow
          label="Mitigación"
          value={config.ob.mitigation || 'wick'}
          options={[{value:'wick',label:'Mecha'},{value:'close',label:'Cierre'}]}
          onChange={v => set('ob','mitigation',v)}
        />
        <NumRow label="Máx por TF" value={config.ob.maxPerTf ?? 10} onChange={v => set('ob','maxPerTf',v)} max={50} />
        <NumRow label="Lookback" value={config.ob.lookback ?? 30} onChange={v => set('ob','lookback',v)} min={5} max={200} />
        <NumRow label="Extensión" value={config.ob.extensionBars ?? 10} onChange={v => set('ob','extensionBars',v)} min={0} max={100} />
        <Divider />
        <ColorRow label="Color OB alcista" value={config.ob.colorBull} onChange={v => set('ob','colorBull',v)} />
        <ColorRow label="Color OB bajista" value={config.ob.colorBear} onChange={v => set('ob','colorBear',v)} />
        <AlphaRow label="Opacidad"         value={config.ob.alphaFill} onChange={v => set('ob','alphaFill',v)} />

        <Divider />

        {/* ── Estructura ───────────────────────────────────────────────────── */}
        <SectionHeader label="Estructura" color="#76FF03" />
        <Row label="Estructura swing"    checked={config.structure.showSwingStruct}    onChange={v => set('structure','showSwingStruct',v)} />
        <Row label="Estructura interna"  checked={config.structure.showInternalStruct} onChange={v => set('structure','showInternalStruct',v)} />
        <Row label="HH / HL / LH / LL"   checked={config.structure.showSwingLabels}    onChange={v => set('structure','showSwingLabels',v)} />
        <Row label="Strong / Weak"       checked={config.structure.showStrongWeak}     onChange={v => set('structure','showStrongWeak',v)} />
        <NumRow label="Swing len"    value={config.structure.swingLen ?? 10} onChange={v => set('structure','swingLen',v)} min={3} max={50} />
        <NumRow label="Internal len" value={config.structure.internalLen ?? 5} onChange={v => set('structure','internalLen',v)} min={2} max={20} />
        <RangeRow label="Min. mov. ATR" value={config.structure.minMoveATRMult ?? 0.5} onChange={v => set('structure','minMoveATRMult',v)} min={0} max={2} step={0.1} />
        <Divider />
        <ColorRow label="Color alcista"  value={config.structure.colorBull} onChange={v => set('structure','colorBull',v)} />
        <ColorRow label="Color bajista"  value={config.structure.colorBear} onChange={v => set('structure','colorBear',v)} />

        <Divider />

        {/* ── Fibonacci ────────────────────────────────────────────────────── */}
        <SectionHeader label="Fibonacci" color="#FFD600" />
        <Row label="Mostrar Fib"   checked={config.fib.showFib}  onChange={v => set('fib','showFib',v)} />
        <Row label="Mostrar OTE"   checked={config.fib.showOTE}  onChange={v => set('fib','showOTE',v)} />
        <ColorRow label="Color OTE"  value={config.fib.oteColor}  onChange={v => set('fib','oteColor',v)} />
        <ColorRow label="Color líneas" value={config.fib.lineColor} onChange={v => set('fib','lineColor',v)} />

        <Divider />

        {/* ── Multi-Timeframe ──────────────────────────────────────────────── */}
        <SectionHeader label="Multi-Timeframe" color="#9C27B0" />
        <Row label="Activar HTF" checked={config.multiTimeframe?.enableHTF ?? true} onChange={v => set('multiTimeframe','enableHTF',v)} />
        <SelectRow
          label="Timeframe HTF"
          value={config.multiTimeframe?.htfResolution || 'auto'}
          options={[
            { value: 'auto', label: 'Auto' },
            { value: '5m', label: '5m' },
            { value: '15m', label: '15m' },
            { value: '1h', label: '1h' },
            { value: '4h', label: '4h' },
            { value: '1d', label: '1d' },
            { value: '1w', label: '1w' },
          ]}
          onChange={v => set('multiTimeframe','htfResolution', v === 'auto' ? '' : v)}
        />
        <NumRow label="HTF EMA" value={config.multiTimeframe?.htfEMALen ?? 50} onChange={v => set('multiTimeframe','htfEMALen',v)} min={10} max={200} />
        <Row label="Requerir alineación HTF" checked={config.multiTimeframe?.requireHTFAlignment ?? false} onChange={v => set('multiTimeframe','requireHTFAlignment',v)} />

        <Divider />

        {/* ── Señales ICT ──────────────────────────────────────────────────── */}
        <SectionHeader label="Señales" color="#22c55e" />
        <Row label="Mostrar señales" checked={config.signal?.showSignal ?? true} onChange={v => set('signal','showSignal',v)} />

        {(config.signal?.showSignal ?? true) && <>
          <Divider />
          <Row label="Stop Loss" checked={config.signal?.showSL ?? true} onChange={v => set('signal','showSL',v)} />
          <NumRow label="Nº de TPs" value={config.signal?.numTPs ?? 5} onChange={v => set('signal','numTPs',v)} min={1} max={5} />
          {(config.signal?.numTPs ?? 5) >= 1 && <Row label="TP1" checked={config.signal?.showTP1 ?? true} onChange={v => set('signal','showTP1',v)} />}
          {(config.signal?.numTPs ?? 5) >= 2 && <Row label="TP2" checked={config.signal?.showTP2 ?? true} onChange={v => set('signal','showTP2',v)} />}
          {(config.signal?.numTPs ?? 5) >= 3 && <Row label="TP3" checked={config.signal?.showTP3 ?? true} onChange={v => set('signal','showTP3',v)} />}
          {(config.signal?.numTPs ?? 5) >= 4 && <Row label="TP4" checked={config.signal?.showTP4 ?? true} onChange={v => set('signal','showTP4',v)} />}
          {(config.signal?.numTPs ?? 5) >= 5 && <Row label="TP5" checked={config.signal?.showTP5 ?? true} onChange={v => set('signal','showTP5',v)} />}
          <Divider />
          <NumRow label="Score mínimo" value={config.signal?.minScore ?? 4} onChange={v => set('signal','minScore',v)} min={1} max={12} />
          <RangeRow label="R mínimo" value={config.signal?.minRR ?? 1.2} min={0.5} max={5.0} step={0.1} onChange={v => set('signal','minRR',v)} />
          <RangeRow label="Proximidad POI %" value={config.signal?.poiProximityPct ?? 0.5} min={0} max={5} step={0.1} suffix="%" onChange={v => set('signal','poiProximityPct',v)} />
          <NumRow label="Barras estructura reciente" value={config.signal?.recentStructureBars ?? 15} onChange={v => set('signal','recentStructureBars',v)} min={1} max={100} />
          <NumRow label="Barras SL/TP recientes" value={config.signal?.slTpRecencyBars ?? 20} onChange={v => set('signal','slTpRecencyBars',v)} min={1} max={200} />
          <Divider />
          <Row label="SL/TP estructurales" checked={config.signal?.useStructuralSLTP ?? true} onChange={v => set('signal','useStructuralSLTP',v)} />
          <Divider />
          <SectionHeader label="Gates de calidad" color="#F59E0B" />
          <Row label="Requerir sweep" checked={config.signal?.requireSweep ?? false} onChange={v => set('signal','requireSweep',v)} />
          <Row label="Rechazar Asia" checked={config.signal?.rejectAsia ?? false} onChange={v => set('signal','rejectAsia',v)} />
          <Row label="Rechazar equilibrium" checked={config.signal?.rejectEquilibrium ?? false} onChange={v => set('signal','rejectEquilibrium',v)} />
          <Row label="PD array obligatorio" checked={config.signal?.requirePremiumDiscount ?? false} onChange={v => set('signal','requirePremiumDiscount',v)} />
          <Row label="Usar volumen" checked={config.signal?.useVolume ?? true} onChange={v => set('signal','useVolume',v)} />
          <RangeRow label="Umbral volumen" value={config.signal?.volSpikeThreshold ?? 1.5} min={1} max={5} step={0.1} onChange={v => set('signal','volSpikeThreshold',v)} />
          <Divider />
          <ColorRow label="Color LONG"  value={config.signal?.longColor ?? '#22c55e'}  onChange={v => set('signal','longColor',v)} />
          <ColorRow label="Color SHORT" value={config.signal?.shortColor ?? '#ef4444'} onChange={v => set('signal','shortColor',v)} />
          <ColorRow label="Color Entry" value={config.signal?.entryColor ?? '#e2e8f0'} onChange={v => set('signal','entryColor',v)} />
          <ColorRow label="Color SL"    value={config.signal?.slColor ?? '#f87171'}    onChange={v => set('signal','slColor',v)} />
          <ColorRow label="Color TP"    value={config.signal?.tpColor ?? '#4ade80'}    onChange={v => set('signal','tpColor',v)} />
          <Divider />
          <Row label="Historial señales" checked={config.signal?.showHistory ?? true} onChange={v => set('signal','showHistory',v)} />
        </>}

        <div className="h-2" />
      </div>
    </div>
  )
}
