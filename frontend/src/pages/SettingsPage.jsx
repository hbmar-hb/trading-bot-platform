import { useState } from 'react'
import { Palette, ShieldCheck, ShieldOff, Send } from 'lucide-react'
import { authService } from '@/services/auth'
import useAuthStore from '@/store/authStore'

function Section({ title, children }) {
  return (
    <div className="card space-y-4">
      <h2 className="font-semibold text-sm text-slate-700 dark:text-gray-300 border-b border-slate-200 dark:border-gray-800 pb-3">{title}</h2>
      {children}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">{label}</label>
      {children}
    </div>
  )
}

function Alert({ type, message }) {
  const styles = type === 'error'
    ? 'bg-red-500/10 border-red-500/30 text-red-400'
    : 'bg-green-500/10 border-green-500/30 text-green-400'
  return (
    <div className={`border rounded-lg px-4 py-3 text-sm ${styles}`}>{message}</div>
  )
}

function Toggle({ label, checked, onChange, disabled }) {
  return (
    <label className={`flex items-center gap-3 cursor-pointer ${disabled ? 'opacity-50' : ''}`}>
      <div className="relative">
        <input
          type="checkbox"
          className="sr-only peer"
          checked={checked}
          onChange={onChange}
          disabled={disabled}
        />
        <div className="w-10 h-6 bg-slate-200 dark:bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
      </div>
      <span className="text-sm text-slate-700 dark:text-gray-300">{label}</span>
    </label>
  )
}

/* ─── Sección Personalización del Chat ────────────────────── */
function ChatPersonalizationSection({ user, onUpdated }) {
  const [bgColor, setBgColor]     = useState(user?.chat_bg_color || '#1f2937')
  const [bgShape, setBgShape]     = useState(user?.chat_bg_shape || 'none')
  const [fontFamily, setFontFamily] = useState(user?.chat_font_family || 'Inter')
  const [fontSize, setFontSize]   = useState(user?.chat_font_size || 14)
  const [fontColor, setFontColor] = useState(user?.chat_font_color || '#e2e8f0')
  const [saving, setSaving]       = useState(false)
  const [status, setStatus]       = useState(null)

  const COLORS = [
    '#ffffff', '#f8fafc', '#f1f5f9', '#e2e8f0', '#cbd5e1',
    '#94a3b8', '#64748b', '#475569', '#334155', '#1e293b',
    '#fef2f2', '#fff7ed', '#fefce8', '#f0fdf4', '#eff6ff',
    '#faf5ff', '#fdf2f8', '#fff1f2', '#ecfeff', '#f0f9ff',
  ]

  const SHAPES = [
    { value: 'none', label: 'Sólido' },
    { value: 'bubbles', label: 'Burbujas' },
    { value: 'dots', label: 'Puntos' },
    { value: 'waves', label: 'Ondas' },
  ]

  const FONTS = [
    { label: 'Inter', value: 'Inter' },
    { label: 'Roboto', value: 'Roboto' },
    { label: 'Open Sans', value: 'Open Sans' },
    { label: 'Lato', value: 'Lato' },
    { label: 'Mono', value: 'JetBrains Mono' },
  ]

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true); setStatus(null)
    try {
      const { data } = await authService.updateMe({
        chat_bg_color: bgColor,
        chat_bg_shape: bgShape,
        chat_font_family: fontFamily,
        chat_font_size: fontSize,
        chat_font_color: fontColor,
      })
      setStatus({ type: 'success', message: 'Personalización guardada' })
      onUpdated(data)
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data?.detail || 'Error al guardar' })
    } finally { setSaving(false) }
  }

  return (
    <form onSubmit={handleSave} className="space-y-4">
      {status && <Alert type={status.type} message={status.message} />}

      <Field label="Color de fondo">
        <div className="flex flex-wrap gap-2">
          {COLORS.map(c => (
            <button
              key={c}
              type="button"
              onClick={() => setBgColor(c)}
              className={`w-8 h-8 rounded-full border-2 transition-transform hover:scale-110 ${
                bgColor === c ? 'border-white scale-110' : 'border-transparent'
              }`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </Field>

      <Field label="Forma de fondo">
        <div className="flex gap-2">
          {SHAPES.map(s => (
            <button
              key={s.value}
              type="button"
              onClick={() => setBgShape(s.value)}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                bgShape === s.value
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white/5 text-slate-300 border-white/10 hover:bg-white/10'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </Field>

      <div className="grid grid-cols-3 gap-4">
        <Field label="Tipo de letra">
          <select
            value={fontFamily}
            onChange={e => setFontFamily(e.target.value)}
            className="input"
          >
            {FONTS.map(f => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Tamaño de letra">
          <input
            type="number"
            min={10}
            max={24}
            value={fontSize}
            onChange={e => setFontSize(parseInt(e.target.value))}
            className="input"
          />
        </Field>
        <Field label="Color de letra">
          <div className="flex flex-wrap gap-1.5">
            {['#ffffff','#e2e8f0','#94a3b8','#475569','#0f172a','#1e3a8a','#14532d','#7f1d1d','#fbbf24','#f472b6'].map(c => (
              <button
                key={c}
                type="button"
                onClick={() => setFontColor(c)}
                className={`w-6 h-6 rounded-full border-2 transition-transform hover:scale-110 ${
                  fontColor === c ? 'border-blue-500 scale-110' : 'border-transparent'
                }`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>
        </Field>
      </div>

      <button type="submit" disabled={saving} className="btn-primary text-sm flex items-center gap-2">
        <Palette size={14} />
        {saving ? 'Guardando…' : 'Guardar personalización'}
      </button>
    </form>
  )
}

/* ─── Sección 2FA ─────────────────────────────────────────── */
function TwoFactorSection({ user, onUpdated }) {
  const [step, setStep]       = useState('idle')   // idle | scan | confirm | disable
  const [qrImage, setQrImage] = useState('')
  const [secret, setSecret]   = useState('')
  const [code, setCode]       = useState('')
  const [loading, setLoading] = useState(false)
  const [status, setStatus]   = useState(null)

  const startSetup = async () => {
    setLoading(true); setStatus(null)
    try {
      const { data } = await authService.setup2fa()
      setQrImage(data.qr_image)
      setSecret(data.secret)
      setStep('scan')
    } catch {
      setStatus({ type: 'error', message: 'Error al generar el QR' })
    } finally {
      setLoading(false) }
  }

  const confirmSetup = async (e) => {
    e.preventDefault()
    setLoading(true); setStatus(null)
    try {
      await authService.verify2fa({ totp_code: code })
      setStatus({ type: 'success', message: '2FA activado correctamente' })
      setStep('idle')
      setCode('')
      onUpdated()
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data?.detail || 'Código incorrecto' })
      setCode('')
    } finally {
      setLoading(false) }
  }

  const disable2fa = async (e) => {
    e.preventDefault()
    setLoading(true); setStatus(null)
    try {
      await authService.disable2fa({ totp_code: code })
      setStatus({ type: 'success', message: '2FA desactivado' })
      setStep('idle')
      setCode('')
      onUpdated()
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data?.detail || 'Código incorrecto' })
      setCode('')
    } finally {
      setLoading(false) }
  }

  const enabled = user?.totp_enabled

  return (
    <div className="space-y-4">
      {/* Estado actual */}
      <div className="flex items-center gap-3">
        {enabled
          ? <ShieldCheck size={20} className="text-green-400 shrink-0" />
          : <ShieldOff size={20} className="text-slate-400 dark:text-gray-500 shrink-0" />
        }
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-gray-100">{enabled ? '2FA activado' : '2FA desactivado'}</p>
          <p className="text-xs text-slate-500 dark:text-gray-400">
            {enabled
              ? 'Tu cuenta está protegida con Google Authenticator'
              : 'Activa el 2FA para añadir una capa extra de seguridad'
            }
          </p>
        </div>
      </div>

      {status && <Alert type={status.type} message={status.message} />}

      {/* Flujo activación */}
      {!enabled && step === 'idle' && (
        <button onClick={startSetup} disabled={loading} className="btn-primary text-sm">
          {loading ? 'Generando QR…' : 'Activar 2FA'}
        </button>
      )}

      {!enabled && step === 'scan' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-500 dark:text-gray-400">
            Escanea este QR con <strong className="text-slate-900 dark:text-white">Google Authenticator</strong> u otra app TOTP:
          </p>
          <div className="flex justify-center">
            <img src={`data:image/png;base64,${qrImage}`} alt="QR 2FA" className="rounded-lg w-48 h-48" />
          </div>
          <p className="text-xs text-slate-500 dark:text-gray-400 text-center">
            ¿No puedes escanear? Clave manual:&nbsp;
            <code className="font-mono text-slate-700 dark:text-gray-300 break-all">{secret}</code>
          </p>
          <form onSubmit={confirmSetup} className="space-y-3">
            <Field label="Código de verificación">
              <input
                type="text" inputMode="numeric" pattern="\d{6}" maxLength={6}
                value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                className="input text-center font-mono text-xl tracking-widest"
                placeholder="000000" autoFocus required
              />
            </Field>
            <div className="flex gap-2">
              <button type="submit" disabled={loading || code.length !== 6} className="btn-primary text-sm">
                {loading ? 'Verificando…' : 'Confirmar y activar'}
              </button>
              <button type="button" onClick={() => { setStep('idle'); setCode('') }} className="btn-ghost text-sm">
                Cancelar
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Flujo desactivación */}
      {enabled && step === 'idle' && (
        <button onClick={() => setStep('disable')} className="btn-ghost text-sm text-red-400 hover:text-red-300">
          Desactivar 2FA
        </button>
      )}

      {enabled && step === 'disable' && (
        <form onSubmit={disable2fa} className="space-y-3">
          <p className="text-sm text-slate-500 dark:text-gray-400">Introduce tu código actual para confirmar la desactivación:</p>
          <Field label="Código 2FA">
            <input
              type="text" inputMode="numeric" pattern="\d{6}" maxLength={6}
              value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
              className="input text-center font-mono text-xl tracking-widest"
              placeholder="000000" autoFocus required
            />
          </Field>
          <div className="flex gap-2">
            <button type="submit" disabled={loading || code.length !== 6} className="btn-primary bg-red-600 hover:bg-red-700 text-sm">
              {loading ? 'Desactivando…' : 'Confirmar desactivación'}
            </button>
            <button type="button" onClick={() => { setStep('idle'); setCode('') }} className="btn-ghost text-sm">
              Cancelar
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

/* ─── Sección Notificaciones Telegram ─────────────────────── */
function TelegramNotificationsSection({ user, onUpdated }) {
  const [chatId, setChatId]     = useState(user?.telegram_chat_id || '')
  const [notifyOpen, setNotifyOpen]       = useState(user?.notify_on_open ?? true)
  const [notifyPartial, setNotifyPartial] = useState(user?.notify_on_partial ?? true)
  const [notifyClose, setNotifyClose]     = useState(user?.notify_on_close ?? true)
  const [saving, setSaving]     = useState(false)
  const [status, setStatus]     = useState(null)

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true); setStatus(null)
    try {
      const { data } = await authService.updateMe({
        telegram_chat_id: chatId.trim() || null,
        notify_on_open: notifyOpen,
        notify_on_partial: notifyPartial,
        notify_on_close: notifyClose,
      })
      setStatus({ type: 'success', message: 'Preferencias guardadas correctamente' })
      onUpdated(data)
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data?.detail || 'Error al guardar' })
    } finally {
      setSaving(false)
    }
  }

  const hasChatId = !!chatId.trim()

  return (
    <form onSubmit={handleSave} className="space-y-4">
      {status && <Alert type={status.type} message={status.message} />}

      <Field label="ID de chat de Telegram">
        <div className="flex gap-2">
          <input
            type="text"
            value={chatId}
            onChange={e => setChatId(e.target.value)}
            placeholder="Ej: 123456789 o @tu_usuario"
            className="input flex-1"
          />
        </div>
        <p className="text-xs text-slate-400 dark:text-gray-500 mt-1">
          Introduce tu ID de chat de Telegram. Puedes obtenerlo hablando con{' '}
          <a href="https://t.me/userinfobot" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">@userinfobot</a>.
        </p>
      </Field>

      <div className="space-y-3 pt-1">
        <Toggle
          label="Notificar al abrir posición"
          checked={notifyOpen}
          onChange={e => setNotifyOpen(e.target.checked)}
          disabled={!hasChatId}
        />
        <Toggle
          label="Notificar en take profit parcial"
          checked={notifyPartial}
          onChange={e => setNotifyPartial(e.target.checked)}
          disabled={!hasChatId}
        />
        <Toggle
          label="Notificar al cerrar posición"
          checked={notifyClose}
          onChange={e => setNotifyClose(e.target.checked)}
          disabled={!hasChatId}
        />
      </div>

      <div className="flex gap-2">
        <button type="submit" disabled={saving} className="btn-primary text-sm flex items-center gap-2">
          <Send size={14} />
          {saving ? 'Guardando…' : 'Guardar preferencias'}
        </button>
        <button
          type="button"
          disabled={!hasChatId || saving}
          onClick={async () => {
            setSaving(true); setStatus(null)
            try {
              await authService.testTelegram()
              setStatus({ type: 'success', message: 'Mensaje de prueba enviado a Telegram' })
            } catch (err) {
              setStatus({ type: 'error', message: err.response?.data?.detail || 'Error al enviar prueba' })
            } finally { setSaving(false) }
          }}
          className="btn-ghost text-sm flex items-center gap-2 disabled:opacity-50"
        >
          🧪 Probar
        </button>
      </div>
    </form>
  )
}

/* ─── Page ────────────────────────────────────────────────── */
export default function SettingsPage() {
  const { user, setUser } = useAuthStore()

  const [pwForm, setPwForm]     = useState({ current: '', next: '', confirm: '' })
  const [pwSaving, setPwSaving] = useState(false)
  const [pwStatus, setPwStatus] = useState(null)

  const setPw = (k, v) => setPwForm(f => ({ ...f, [k]: v }))

  const changePassword = async (e) => {
    e.preventDefault()
    if (pwForm.next !== pwForm.confirm) {
      setPwStatus({ type: 'error', message: 'Las contraseñas nuevas no coinciden' })
      return
    }
    setPwSaving(true); setPwStatus(null)
    try {
      await authService.changePassword({ current_password: pwForm.current, new_password: pwForm.next })
      setPwStatus({ type: 'success', message: 'Contraseña actualizada correctamente' })
      setPwForm({ current: '', next: '', confirm: '' })
    } catch (err) {
      setPwStatus({ type: 'error', message: err.response?.data?.detail || 'Error al cambiar la contraseña' })
    } finally {
      setPwSaving(false)
    }
  }

  const refreshUser = async () => {
    const { data } = await authService.me()
    setUser(data)
  }

  const updateUserFromData = (data) => {
    setUser({ ...user, ...data })
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return '—'
    const d = new Date(dateStr)
    return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'long', year: 'numeric' })
  }

  return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-xl font-bold text-slate-900 dark:text-white">Ajustes</h1>

      <Section title="Cuenta">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-blue-600 flex items-center justify-center text-lg font-bold text-white">
            {user?.username?.[0]?.toUpperCase() ?? '?'}
          </div>
          <div>
            <p className="font-medium text-slate-900 dark:text-gray-100">{user?.username}</p>
            <p className="text-sm text-slate-500 dark:text-gray-400">{user?.email}</p>
            <p className="text-xs text-slate-400 dark:text-gray-500 mt-0.5">
              Alta: {formatDate(user?.created_at)}
            </p>
          </div>
        </div>
      </Section>

      <Section title="Notificaciones Telegram">
        <TelegramNotificationsSection user={user} onUpdated={updateUserFromData} />
      </Section>

      <Section title="Personalización del Chat">
        <ChatPersonalizationSection user={user} onUpdated={updateUserFromData} />
      </Section>

      <Section title="Verificación en dos pasos (2FA)">
        <TwoFactorSection user={user} onUpdated={refreshUser} />
      </Section>

      <Section title="Cambiar contraseña">
        <form onSubmit={changePassword} className="space-y-4">
          {pwStatus && <Alert type={pwStatus.type} message={pwStatus.message} />}
          <Field label="Contraseña actual">
            <input type="password" value={pwForm.current} onChange={e => setPw('current', e.target.value)} className="input" required />
          </Field>
          <Field label="Nueva contraseña">
            <input type="password" value={pwForm.next} onChange={e => setPw('next', e.target.value)} className="input" required minLength={8} />
          </Field>
          <Field label="Confirmar nueva contraseña">
            <input type="password" value={pwForm.confirm} onChange={e => setPw('confirm', e.target.value)} className="input" required />
          </Field>
          <button type="submit" disabled={pwSaving} className="btn-primary">
            {pwSaving ? 'Guardando…' : 'Cambiar contraseña'}
          </button>
        </form>
      </Section>

      <Section title="Sistema">
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-gray-400">Versión</span>
            <span className="font-mono text-slate-700 dark:text-gray-300">1.0.0</span>
          </div>
        </div>
      </Section>
    </div>
  )
}
