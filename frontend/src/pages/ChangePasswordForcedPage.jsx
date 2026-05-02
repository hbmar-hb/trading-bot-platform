import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authService } from '@/services/auth'
import useAuthStore from '@/store/authStore'

export default function ChangePasswordForcedPage() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword]         = useState('')
  const [confirm, setConfirm]                 = useState('')
  const [loading, setLoading]                 = useState(false)
  const [error, setError]                     = useState(null)
  const { setUser, logout }                   = useAuthStore()
  const navigate                              = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (newPassword !== confirm) {
      setError('Las contraseñas no coinciden')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await authService.changePassword({ current_password: currentPassword, new_password: newPassword })
      const me = await authService.me()
      setUser(me.data)
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cambiar la contraseña')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-gray-950">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Cambio de contraseña</h1>
          <p className="text-slate-500 dark:text-gray-400 mt-1 text-sm">
            Debes cambiar tu contraseña antes de continuar
          </p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-900 rounded-xl border border-slate-200 dark:border-gray-800 p-6 space-y-4">
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Contraseña actual</label>
            <input
              type="password" value={currentPassword}
              onChange={e => setCurrentPassword(e.target.value)}
              className="input w-full" required autoFocus
            />
          </div>

          <div>
            <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Nueva contraseña</label>
            <input
              type="password" value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              className="input w-full" required
              placeholder="Mín. 8 caracteres, 1 mayúscula, 1 número"
            />
          </div>

          <div>
            <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Confirmar nueva contraseña</label>
            <input
              type="password" value={confirm}
              onChange={e => setConfirm(e.target.value)}
              className="input w-full" required
            />
          </div>

          <button type="submit" disabled={loading} className="btn-primary w-full mt-2">
            {loading ? 'Guardando...' : 'Cambiar contraseña'}
          </button>

          <button
            type="button"
            onClick={logout}
            className="w-full text-sm text-slate-500 dark:text-gray-400 hover:text-slate-700 dark:hover:text-gray-300"
          >
            Cerrar sesión
          </button>
        </form>
      </div>
    </div>
  )
}
