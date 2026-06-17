import { useState } from 'react'
import { Settings, X, ChevronDown, ChevronRight } from 'lucide-react'

// ─── Primitivos UI ────────────────────────────────────────────────────────────

function Section({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-slate-700/50 last:border-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider hover:text-slate-200 transition-colors"
      >
        {title}
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
      </button>
      {open && <div className="px-3 pb-3 space-y-2.5">{children}</div>}
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-2 min-h-[24px]">
      <span className="text-xs text-slate-400 leading-tight">{label}</span>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function Num({ value, min, max, step = 1, onChange }) {
  return (
    <input
      type="number" value={value} min={min} max={max} step={step}
      onChange={e => onChange(Number(e.target.value))}
      className="w-20 px-2 py-0.5 text-xs bg-slate-800 border border-slate-600 rounded text-slate-100 text-right focus:outline-none focus:border-yellow-500/70"
    />
  )
}

function Toggle({ checked, onChange }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`relative w-8 h-4 rounded-full transition-colors ${checked ? 'bg-yellow-500' : 'bg-slate-600'}`}
    >
      <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${checked ? 'translate-x-4' : 'translate-x-0.5'}`} />
    </button>
  )
}

function Color({ value, onChange }) {
  return (
    <input
      type="color" value={value}
      onChange={e => onChange(e.target.value)}
      className="w-7 h-6 rounded cursor-pointer border border-slate-600 bg-slate-800"
      style={{ padding: '1px' }}
    />
  )
}

// ─── Panel principal ──────────────────────────────────────────────────────────

export default function QuantumGoldPanel({ config: cfg, onChange, onClose }) {
  /** Actualiza una key de primer o segundo nivel (ej: 'bbLen' o 'colors.long') */
  const set = (path, value) =>
    onChange(prev => {
      const [a, b] = path.split('.')
      if (!b) return { ...prev, [a]: value }
      return { ...prev, [a]: { ...prev[a], [b]: value } }
    })

  return (
    <div className="absolute top-2 left-2 w-68 bg-slate-900/96 backdrop-blur border border-yellow-600/30 rounded-xl shadow-2xl z-50 flex flex-col max-h-[88vh] text-slate-200">

      {/* ── Header ── */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-1.5">
          <Settings size={12} className="text-yellow-500" />
          <span className="text-sm font-bold text-yellow-400 tracking-wide">⚡ Quantum Gold</span>
          <span className="text-xs text-slate-500">v1.0</span>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
          <X size={14} />
        </button>
      </div>

      {/* ── Contenido scrollable ── */}
      <div className="flex-1 overflow-y-auto">

        {/* EMA Ribbon */}
        <Section title="EMA Ribbon">
          <Row label="Mostrar EMAs">
            <Toggle checked={cfg.showEmas} onChange={v => set('showEmas', v)} />
          </Row>
          <Row label="Rápida">
            <Num value={cfg.emaFast} min={1} max={50} onChange={v => set('emaFast', v)} />
          </Row>
          <Row label="Media">
            <Num value={cfg.emaMid} min={1} max={100} onChange={v => set('emaMid', v)} />
          </Row>
          <Row label="Lenta">
            <Num value={cfg.emaSlow} min={10} max={200} onChange={v => set('emaSlow', v)} />
          </Row>
          <Row label="Tendencia">
            <Num value={cfg.emaTrend} min={50} max={500} onChange={v => set('emaTrend', v)} />
          </Row>
        </Section>

        {/* Supertrend */}
        <Section title="Supertrend">
          <Row label="ATR Longitud">
            <Num value={cfg.stAtrLen} min={1} max={50} onChange={v => set('stAtrLen', v)} />
          </Row>
          <Row label="Factor">
            <Num value={cfg.stFactor} min={0.5} max={10} step={0.1} onChange={v => set('stFactor', v)} />
          </Row>
        </Section>

        {/* Bollinger Bands */}
        <Section title="Bollinger Bands">
          <Row label="Longitud">
            <Num value={cfg.bbLen} min={5} max={100} onChange={v => set('bbLen', v)} />
          </Row>
          <Row label="Desviación">
            <Num value={cfg.bbStd} min={0.5} max={5} step={0.1} onChange={v => set('bbStd', v)} />
          </Row>
          <Row label="Squeeze umbral (%)">
            <Num value={cfg.bbSqzThreshold} min={0.1} max={5} step={0.05} onChange={v => set('bbSqzThreshold', v)} />
          </Row>
          <p className="text-xs text-slate-500 pt-0.5">
            Gold 5m–1H: 0.9% · sube a 1.2% si ves pocos squeezes
          </p>
        </Section>

        {/* RSI */}
        <Section title="RSI" defaultOpen={false}>
          <Row label="Longitud">
            <Num value={cfg.rsiLen} min={2} max={50} onChange={v => set('rsiLen', v)} />
          </Row>
          <p className="text-xs text-slate-500 font-semibold pt-0.5">Zona alcista</p>
          <Row label="  Mín">
            <Num value={cfg.rsiBullLo} min={30} max={65} onChange={v => set('rsiBullLo', v)} />
          </Row>
          <Row label="  Máx">
            <Num value={cfg.rsiBullHi} min={50} max={90} onChange={v => set('rsiBullHi', v)} />
          </Row>
          <p className="text-xs text-slate-500 font-semibold pt-0.5">Zona bajista</p>
          <Row label="  Mín">
            <Num value={cfg.rsiBearLo} min={10} max={45} onChange={v => set('rsiBearLo', v)} />
          </Row>
          <Row label="  Máx">
            <Num value={cfg.rsiBearHi} min={30} max={55} onChange={v => set('rsiBearHi', v)} />
          </Row>
        </Section>

        {/* Volumen */}
        <Section title="Volumen" defaultOpen={false}>
          <Row label="SMA Longitud">
            <Num value={cfg.volLen} min={5} max={100} onChange={v => set('volLen', v)} />
          </Row>
          <Row label="Multiplicador">
            <Num value={cfg.volMult} min={0.5} max={5} step={0.05} onChange={v => set('volMult', v)} />
          </Row>
          <p className="text-xs text-slate-500 pt-0.5">
            Gold 5m–1H: 1.4× · baja a 1.2× en activos poco líquidos
          </p>
        </Section>

        {/* Niveles SL / TP */}
        <Section title="Niveles SL / TP">
          <Row label="Mostrar niveles">
            <Toggle checked={cfg.showLevels} onChange={v => set('showLevels', v)} />
          </Row>
          <Row label="ATR Longitud">
            <Num value={cfg.atrLen} min={1} max={50} onChange={v => set('atrLen', v)} />
          </Row>
          <Row label="TP Mult (×ATR)">
            <Num value={cfg.tpMult} min={0.5} max={10} step={0.1} onChange={v => set('tpMult', v)} />
          </Row>
          <Row label="SL Mult (×ATR)">
            <Num value={cfg.slMult} min={0.1} max={5} step={0.1} onChange={v => set('slMult', v)} />
          </Row>
          <p className="text-xs text-slate-500 pt-0.5">
            R:R actual: 1:{(cfg.tpMult / cfg.slMult).toFixed(1)} · recomendado ≥ 1:2
          </p>
        </Section>

        {/* Filtros */}
        <Section title="Filtros">
          <Row label="Filtro tendencia EMA50>EMA200">
            <Toggle checked={cfg.useTrendFilter} onChange={v => set('useTrendFilter', v)} />
          </Row>
          <Row label="ATR mínimo ($)">
            <Num value={cfg.minAtrFilter} min={0} max={50} step={0.5} onChange={v => set('minAtrFilter', v)} />
          </Row>
          <p className="text-xs text-slate-500 pt-0.5">
            Gold 5m: $3 · 1H: $5–7 · 0 = desactivado
          </p>
          <Row label="Filtro sesión">
            <Toggle checked={cfg.useSess} onChange={v => set('useSess', v)} />
          </Row>
          <p className="text-xs text-slate-500">
            Londres 08–17h · NY 13:30–21h UTC
          </p>
        </Section>

        {/* Colores */}
        <Section title="Colores" defaultOpen={false}>
          <Row label="LONG">   <Color value={cfg.colors.long}    onChange={v => set('colors.long',    v)} /></Row>
          <Row label="SHORT">  <Color value={cfg.colors.short}   onChange={v => set('colors.short',   v)} /></Row>
          <Row label="Squeeze"><Color value={cfg.colors.squeeze} onChange={v => set('colors.squeeze', v)} /></Row>
          <Row label="SL">     <Color value={cfg.colors.sl}      onChange={v => set('colors.sl',      v)} /></Row>
          <Row label="TP">     <Color value={cfg.colors.tp}      onChange={v => set('colors.tp',      v)} /></Row>
        </Section>

      </div>
    </div>
  )
}
