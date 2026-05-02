import { useState } from 'react'
import { Link } from 'react-router-dom'
import { authService } from '@/services/auth'
import { Mail, ArrowLeft, CheckCircle } from 'lucide-react'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [sent, setSent] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await authService.forgotPassword({ email })
      setSent(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al enviar el email')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-gray-950">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Recuperar contraseña</h1>
          <p className="text-slate-500 dark:text-gray-400 mt-1 text-sm">
            Introduce tu email y te enviaremos un enlace
          </p>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-xl border border-slate-200 dark:border-gray-800 p-6 space-y-4">
          {sent ? (
            <div className="text-center space-y-4">
              <CheckCircle className="mx-auto text-green-500" size={48} />
              <p className="text-slate-700 dark:text-gray-300">
                Si existe una cuenta con ese email, recibiras un enlace para restablecer tu contraseña.
              </p>
              <Link to="/login" className="inline-flex items-center text-sm text-blue-500 hover:text-blue-600">
                <ArrowLeft size={16} className="mr-1" /> Volver al login
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
                <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Email</label>
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="email" value={email}
                    onChange={e => setEmail(e.target.value)}
                    className="input pl-9 w-full"
                    placeholder="tu@email.com"
                    autoFocus required
                  />
                </div>
              </div>
              <button type="submit" disabled={loading} className="btn-primary w-full">
                {loading ? 'Enviando...' : 'Enviar enlace'}
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
