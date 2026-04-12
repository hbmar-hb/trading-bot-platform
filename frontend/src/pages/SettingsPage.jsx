import { useState } from 'react'
import { ShieldCheck, ShieldOff } from 'lucide-react'
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
          </div>
        </div>
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
