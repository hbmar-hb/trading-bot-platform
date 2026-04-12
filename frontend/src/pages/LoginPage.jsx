import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authService } from '@/services/auth'
import useAuthStore from '@/store/authStore'

export default function LoginPage() {
  const [step, setStep]         = useState('credentials') // 'credentials' | '2fa'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode]         = useState('')
  const [tempToken, setTempToken] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const { setTokens, setUser }  = useAuthStore()
  const navigate                = useNavigate()
  const codeRef                 = useRef(null)

  const handleCredentials = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const { data } = await authService.login({ username, password })
      if (data.requires_2fa) {
        setTempToken(data.temp_token)
        setStep('2fa')
        setTimeout(() => codeRef.current?.focus(), 100)
      } else {
        setTokens(data.access_token, data.refresh_token)
        const me = await authService.me()
        setUser(me.data)
        navigate('/dashboard')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al iniciar sesión')
    } finally {
      setLoading(false)
    }
  }

  const handle2fa = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const { data } = await authService.login2fa({ temp_token: tempToken, totp_code: code })
      setTokens(data.access_token, data.refresh_token)
      const me = await authService.me()
      setUser(me.data)
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Código incorrecto')
      setCode('')
      codeRef.current?.focus()
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-gray-950">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Trading Bot Platform</h1>
          <p className="text-slate-500 dark:text-gray-400 mt-1 text-sm">
            {step === 'credentials' ? 'Accede a tu cuenta' : 'Verificación en dos pasos'}
          </p>
        </div>

        {/* ── Paso 1: usuario + contraseña ── */}
        {step === 'credentials' && (
          <form onSubmit={handleCredentials} className="bg-white dark:bg-gray-900 rounded-xl border border-slate-200 dark:border-gray-800 p-6 space-y-4">
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm">
                {error}
              </div>
            )}
            <div>
              <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Usuario</label>
              <input
                type="text" value={username}
                onChange={e => setUsername(e.target.value)}
                className="input" placeholder="admin"
                autoFocus required
              />
            </div>
            <div>
              <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Contraseña</label>
              <input
                type="password" value={password}
                onChange={e => setPassword(e.target.value)}
                className="input" placeholder="••••••••"
                required
              />
            </div>
            <button type="submit" disabled={loading} className="btn-primary w-full mt-2">
              {loading ? 'Comprobando…' : 'Iniciar sesión'}
            </button>
          </form>
        )}

        {/* ── Paso 2: código TOTP ── */}
        {step === '2fa' && (
          <form onSubmit={handle2fa} className="bg-white dark:bg-gray-900 rounded-xl border border-slate-200 dark:border-gray-800 p-6 space-y-4">
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm">
                {error}
              </div>
            )}
            <p className="text-sm text-slate-500 dark:text-gray-400">
              Introduce el código de 6 dígitos de tu app de autenticación.
            </p>
            <div>
              <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Código 2FA</label>
              <input
                ref={codeRef}
                type="text" inputMode="numeric" pattern="\d{6}"
                maxLength={6} value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                className="input text-center font-mono text-2xl tracking-widest"
                placeholder="000000"
                required
              />
            </div>
            <button type="submit" disabled={loading || code.length !== 6} className="btn-primary w-full">
              {loading ? 'Verificando…' : 'Verificar'}
            </button>
            <button
              type="button"
              onClick={() => { setStep('credentials'); setError(null); setCode('') }}
              className="w-full text-sm text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-300"
            >
              ← Volver
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
