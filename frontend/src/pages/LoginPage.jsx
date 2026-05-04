import { useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { authService } from '@/services/auth'
import useAuthStore from '@/store/authStore'

export default function LoginPage() {
  const [step, setStep]         = useState('credentials')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode]         = useState('')
  const [tempToken, setTempToken] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [resendEmail, setResendEmail] = useState('')
  const [resendSent, setResendSent] = useState(false)
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
        navigate(data.must_change_password ? '/change-password' : '/dashboard')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al iniciar sesion')
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
      setError(err.response?.data?.detail || 'Codigo incorrecto')
      setCode('')
      codeRef.current?.focus()
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async (e) => {
    e.preventDefault()
    if (!resendEmail) return
    setLoading(true); setError(null)
    try {
      await authService.resendVerification({ email: resendEmail })
      setResendSent(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al reenviar')
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
            {step === 'credentials' ? 'Accede a tu cuenta' : 'Verificacion en dos pasos'}
          </p>
        </div>

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
                className="input w-full" placeholder="admin"
                autoFocus required
              />
            </div>
            <div>
              <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Contraseña</label>
              <input
                type="password" value={password}
                onChange={e => setPassword(e.target.value)}
                className="input w-full" placeholder="********"
                required
              />
            </div>
            <button type="submit" disabled={loading} className="btn-primary w-full mt-2">
              {loading ? 'Comprobando...' : 'Iniciar sesion'}
            </button>
            <div className="flex justify-between text-sm pt-1">
              <Link to="/forgot-password" className="text-blue-500 hover:text-blue-600">
                Olvide mi contraseña
              </Link>
            </div>
            {error && error.toLowerCase().includes('email no verificado') && !resendSent && (
              <div className="border-t border-slate-200 dark:border-gray-800 pt-3 space-y-2">
                <p className="text-xs text-slate-500 dark:text-gray-400">
                  Introduce tu email para reenviar el enlace de verificacion:
                </p>
                <div className="flex gap-2">
                  <input
                    type="email" value={resendEmail}
                    onChange={e => setResendEmail(e.target.value)}
                    className="input flex-1 text-sm"
                    placeholder="tu@email.com"
                  />
                  <button
                    onClick={handleResend}
                    disabled={loading || !resendEmail}
                    className="btn-secondary text-sm px-3"
                  >
                    Reenviar
                  </button>
                </div>
              </div>
            )}
            {resendSent && (
              <p className="text-xs text-green-500">Enlace de verificacion reenviado.</p>
            )}
          </form>
        )}

        {step === '2fa' && (
          <form onSubmit={handle2fa} className="bg-white dark:bg-gray-900 rounded-xl border border-slate-200 dark:border-gray-800 p-6 space-y-4">
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm">
                {error}
              </div>
            )}
            <p className="text-sm text-slate-500 dark:text-gray-400">
              Introduce el codigo de 6 digitos de tu app de autenticacion.
            </p>
            <div>
              <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Codigo 2FA</label>
              <input
                ref={codeRef}
                type="text" inputMode="numeric" pattern="\d{6}"
                maxLength={6} value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                className="input text-center font-mono text-2xl tracking-widest w-full"
                placeholder="000000"
                required
              />
            </div>
            <button type="submit" disabled={loading || code.length !== 6} className="btn-primary w-full">
              {loading ? 'Verificando...' : 'Verificar'}
            </button>
            <button
              type="button"
              onClick={() => { setStep('credentials'); setError(null); setCode('') }}
              className="w-full text-sm text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-300"
            >
              Volver
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
