import { useState, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authService } from '@/services/auth'
import { CheckCircle, XCircle, Loader2 } from 'lucide-react'

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  const [status, setStatus] = useState('loading') // loading | success | error
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!token) {
      setStatus('error')
      setMessage('Token invalido o faltante')
      return
    }

    authService.verifyEmail({ token })
      .then(() => {
        setStatus('success')
        setMessage('Email verificado correctamente. Ya puedes iniciar sesion.')
      })
      .catch((err) => {
        setStatus('error')
        setMessage(err.response?.data?.detail || 'Error al verificar el email')
      })
  }, [token])

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-gray-950">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Verificacion de email</h1>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-xl border border-slate-200 dark:border-gray-800 p-6 space-y-4 text-center">
          {status === 'loading' && (
            <>
              <Loader2 className="mx-auto text-blue-500 animate-spin" size={48} />
              <p className="text-slate-500 dark:text-gray-400">Verificando tu email...</p>
            </>
          )}

          {status === 'success' && (
            <>
              <CheckCircle className="mx-auto text-green-500" size={48} />
              <p className="text-slate-700 dark:text-gray-300">{message}</p>
              <Link to="/login" className="inline-block text-sm text-blue-500 hover:text-blue-600">
                Ir al login
              </Link>
            </>
          )}

          {status === 'error' && (
            <>
              <XCircle className="mx-auto text-red-500" size={48} />
              <p className="text-red-400">{message}</p>
              <Link to="/login" className="inline-block text-sm text-blue-500 hover:text-blue-600">
                Volver al login
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
