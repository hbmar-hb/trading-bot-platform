import { useEffect, useState } from 'react'
import { Edit2, Mail, Plus, Trash2, X, Check, Shield, ShieldCheck, User } from 'lucide-react'
import { usersService } from '@/services/usersService'
import useAuthStore from '@/store/authStore'

const ROLES = [
  { value: 'rol1',      label: 'ROL 1',      icon: User,        cls: 'bg-slate-500/20 text-slate-400' },
  { value: 'moderator', label: 'Moderador',  icon: Shield,      cls: 'bg-amber-500/20 text-amber-400' },
  { value: 'admin',     label: 'Admin',      icon: ShieldCheck, cls: 'bg-blue-500/20 text-blue-400' },
]

function roleMeta(role) {
  return ROLES.find(r => r.value === role) || ROLES[0]
}

function RoleBadge({ role }) {
  const m = roleMeta(role)
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${m.cls}`}>{m.label}</span>
  )
}

function Alert({ type, message }) {
  const s = type === 'error'
    ? 'bg-red-500/10 border-red-500/30 text-red-400'
    : 'bg-green-500/10 border-green-500/30 text-green-400'
  return <div className={`border rounded-lg px-4 py-3 text-sm ${s}`}>{message}</div>
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-white dark:bg-gray-900 border border-slate-200 dark:border-gray-800 rounded-xl w-full max-w-md p-6 space-y-4 mx-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-900 dark:text-white">{title}</h3>
          <button onClick={onClose} className="text-slate-500 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

/* ─── Modal crear usuario ─────────────────────────────────── */
function CreateUserModal({ onClose, onCreated }) {
  const [form, setForm]     = useState({ username: '', email: '', role: 'rol1', telegram_chat_id: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState(null)
  const [success, setSuccess] = useState(false)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const { data } = await usersService.create(form)
      onCreated(data)
      setSuccess(true)
      setTimeout(onClose, 1800)
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(Array.isArray(detail) ? detail.map(d => d.msg).join(' · ') : detail || 'Error al crear usuario')
    } finally { setLoading(false) }
  }

  return (
    <Modal title="Nuevo usuario" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <Alert type="error" message={error} />}
        {success && <Alert type="success" message="Usuario creado. Se ha enviado el email para establecer contraseña." />}
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Usuario</label>
          <input type="text" value={form.username} onChange={e => set('username', e.target.value)}
            className="input" placeholder="usuario" required />
        </div>
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Email</label>
          <input type="email" value={form.email} onChange={e => set('email', e.target.value)}
            className="input" placeholder="usuario@email.com" required />
        </div>
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Rol</label>
          <select value={form.role} onChange={e => set('role', e.target.value)} className="input">
            {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Telegram Chat ID</label>
          <input type="text" value={form.telegram_chat_id} onChange={e => set('telegram_chat_id', e.target.value)}
            className="input" placeholder="Ej: 123456789" />
        </div>
        <p className="text-xs text-slate-400 dark:text-gray-500 bg-slate-50 dark:bg-gray-800/50 rounded-lg px-3 py-2">
          El usuario recibirá un email para establecer su propia contraseña. Ningún administrador puede definirla.
        </p>
        <div className="flex gap-2 pt-1">
          <button type="submit" disabled={loading || success} className="btn-primary">
            {loading ? 'Creando…' : 'Crear y enviar email'}
          </button>
          <button type="button" onClick={onClose} className="btn-ghost">Cancelar</button>
        </div>
      </form>
    </Modal>
  )
}

/* ─── Modal editar usuario ────────────────────────────────── */
function EditUserModal({ user, onClose, onUpdated }) {
  const [form, setForm] = useState({
    username: user.username,
    email: user.email,
    role: user.role || 'rol1',
    telegram_chat_id: user.telegram_chat_id || '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const { data } = await usersService.update(user.id, form)
      onUpdated(data)
      onClose()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(Array.isArray(detail) ? detail.map(d => d.msg).join(' · ') : detail || 'Error al actualizar')
    } finally { setLoading(false) }
  }

  return (
    <Modal title={`Editar: ${user.username}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <Alert type="error" message={error} />}
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Usuario</label>
          <input type="text" value={form.username} onChange={e => set('username', e.target.value)}
            className="input" required />
        </div>
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Email</label>
          <input type="email" value={form.email} onChange={e => set('email', e.target.value)}
            className="input" required />
        </div>
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Rol</label>
          <select value={form.role} onChange={e => set('role', e.target.value)} className="input">
            {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Telegram Chat ID</label>
          <input type="text" value={form.telegram_chat_id} onChange={e => set('telegram_chat_id', e.target.value)}
            className="input" placeholder="Ej: 123456789" />
        </div>
        <div className="flex gap-2 pt-1">
          <button type="submit" disabled={loading} className="btn-primary">
            {loading ? 'Guardando…' : 'Guardar cambios'}
          </button>
          <button type="button" onClick={onClose} className="btn-ghost">Cancelar</button>
        </div>
      </form>
    </Modal>
  )
}

/* ─── Page ────────────────────────────────────────────────── */
export default function UsersPage() {
  const currentUser = useAuthStore(s => s.user)
  const [users, setUsers]         = useState([])
  const [loading, setLoading]     = useState(true)
  const [modal, setModal]         = useState(null)
  const [togglingId, setTogglingId] = useState(null)
  const [sendingReset, setSendingReset] = useState(null)
  const [onlineIds, setOnlineIds] = useState(new Set())

  useEffect(() => {
    Promise.all([
      usersService.list(),
      usersService.onlineStatus().catch(() => ({ data: { online_user_ids: [] } })),
    ])
      .then(([usersRes, onlineRes]) => {
        setUsers(usersRes.data)
        setOnlineIds(new Set(onlineRes.data.online_user_ids || []))
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleCreated = (user) => setUsers(u => [...u, user])
  const handleUpdated = (updated) => setUsers(u => u.map(x => x.id === updated.id ? updated : x))
  const handleDelete  = async (user) => {
    if (!confirm(`¿Eliminar usuario "${user.username}"? Esta acción no se puede deshacer.`)) return
    try {
      await usersService.delete(user.id)
      setUsers(u => u.filter(x => x.id !== user.id))
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al eliminar')
    }
  }

  const toggleActive = async (user) => {
    setTogglingId(user.id)
    try {
      const { data } = await usersService.update(user.id, { is_active: !user.is_active })
      handleUpdated(data)
    } catch (err) {
      alert(err.response?.data?.detail || 'Error')
    } finally { setTogglingId(null) }
  }

  const handleSendReset = async (user) => {
    if (!confirm(`Enviar email de restablecimiento de contraseña a "${user.username}" (${user.email})?`)) return
    setSendingReset(user.id)
    try {
      await usersService.sendResetEmail(user.id)
      alert(`Email de restablecimiento enviado a ${user.email}`)
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al enviar el email')
    } finally { setSendingReset(null) }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Usuarios</h1>
          {!loading && (
            <span className="text-xs px-2 py-1 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
              {onlineIds.size} en línea
            </span>
          )}
        </div>
        <button onClick={() => setModal({ type: 'create' })} className="btn-primary flex items-center gap-2 text-sm">
          <Plus size={16} /> Nuevo usuario
        </button>
      </div>

      {loading ? (
        <p className="text-slate-500 dark:text-gray-400 text-sm">Cargando…</p>
      ) : (
        <div className="space-y-2">
          {users.map(user => (
            <div key={user.id} className="card flex items-center gap-4">
              <div className="relative shrink-0">
                <div className={`w-9 h-9 rounded-full flex items-center justify-center font-bold text-white ${
                  user.role === 'admin' ? 'bg-blue-600' : user.role === 'moderator' ? 'bg-amber-500' : 'bg-emerald-600'
                }`}>
                  {user.username[0].toUpperCase()}
                </div>
                <span
                  className={`absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full border-2 border-white dark:border-gray-900 ${
                    onlineIds.has(user.id) ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-600'
                  }`}
                  title={onlineIds.has(user.id) ? 'Conectado' : 'Desconectado'}
                />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-slate-900 dark:text-gray-100">{user.username}</span>
                  <RoleBadge role={user.role} />
                  {user.id === currentUser?.id && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-500 dark:text-blue-400">tú</span>
                  )}
                  {user.totp_enabled && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-green-500/20 text-green-500 dark:text-green-400">2FA</span>
                  )}
                  {user.telegram_chat_id && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-500 dark:text-blue-400">TG</span>
                  )}
                  {!user.is_active && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-500 dark:text-red-400">inactivo</span>
                  )}
                </div>
                <p className="text-sm text-slate-500 dark:text-gray-400 truncate">{user.email}</p>
              </div>

              <div className="flex items-center gap-1 shrink-0">
                {user.id !== currentUser?.id && (
                  <button
                    onClick={() => toggleActive(user)}
                    disabled={togglingId === user.id}
                    title={user.is_active ? 'Desactivar' : 'Activar'}
                    className={`p-1.5 rounded transition-colors ${
                      user.is_active
                        ? 'text-green-500 dark:text-green-400 hover:text-yellow-400'
                        : 'text-slate-500 dark:text-gray-600 hover:text-green-400'
                    }`}
                  >
                    <Check size={15} />
                  </button>
                )}

                <button
                  onClick={() => setModal({ type: 'edit', user })}
                  title="Editar"
                  className="p-1.5 text-slate-500 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white rounded"
                >
                  <Edit2 size={15} />
                </button>

                <button
                  onClick={() => handleSendReset(user)}
                  disabled={sendingReset === user.id}
                  title="Enviar email de restablecimiento de contraseña"
                  className="p-1.5 text-slate-500 dark:text-gray-400 hover:text-amber-400 rounded"
                >
                  <Mail size={15} />
                </button>

                {user.id !== currentUser?.id && (
                  <button
                    onClick={() => handleDelete(user)}
                    title="Eliminar"
                    className="p-1.5 text-slate-500 dark:text-gray-400 hover:text-red-400 rounded"
                  >
                    <Trash2 size={15} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {modal?.type === 'create' && (
        <CreateUserModal onClose={() => setModal(null)} onCreated={handleCreated} />
      )}
      {modal?.type === 'edit' && (
        <EditUserModal user={modal.user} onClose={() => setModal(null)} onUpdated={handleUpdated} />
      )}
    </div>
  )
}
