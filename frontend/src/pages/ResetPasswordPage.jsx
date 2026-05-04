import { useState, useEffect } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { authService } from '@/services/auth'
import { Lock, ArrowLeft, CheckCircle } from 'lucide-react'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (!token) {
      setError('Token invalido o faltante')
    }
  }, [token])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (password !== confirm) {
      setError('Las contraseñas no coinciden')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await authService.resetPassword({ token, new_password: password })
      setSuccess(true)
      setTimeout(() => navigate('/login'), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al restablecer la contraseña')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-gray-950">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Nueva contraseña</h1>
          <p className="text-slate-500 dark:text-gray-400 mt-1 text-sm">
            Introduce tu nueva contraseña
          </p>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-xl border border-slate-200 dark:border-gray-800 p-6 space-y-4">
          {success ? (
            <div className="text-center space-y-4">
              <CheckCircle className="mx-auto text-green-500" size={48} />
              <p className="text-slate-700 dark:text-gray-300">
                Contraseña actualizada correctamente. Redirigiendo al login...
              </p>
              <Link to="/login" className="inline-flex items-center text-sm text-blue-500 hover:text-blue-600">
                <ArrowLeft size={16} className="mr-1" /> Ir al login ahora
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm">
                  {error}
                </div>
              )}
              <div>
                <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Nueva contraseña</label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="password" value={password}
                    onChange={e => setPassword(e.target.value)}
                    className="input pl-9 w-full"
                    placeholder="Minimo 8 caracteres"
                    autoFocus required
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Confirmar contraseña</label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="password" value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                    className="input pl-9 w-full"
                    placeholder="Repite la contraseña"
                    required
                  />
                </div>
              </div>
              <button type="submit" disabled={loading || !token} className="btn-primary w-full">
                {loading ? 'Guardando...' : 'Guardar contraseña'}
              </button>
              <div className="text-center">
                <Link to="/login" className="inline-flex items-center text-sm text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-300">
                  <ArrowLeft size={16} className="mr-1" /> Volver al login
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
