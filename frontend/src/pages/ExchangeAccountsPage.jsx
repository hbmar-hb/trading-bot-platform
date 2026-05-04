import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle, Edit2, Eye, EyeOff, Loader2, Plus, Shield, ShieldAlert, ShieldCheck, Trash2, XCircle } from 'lucide-react'
import { exchangeAccountsService } from '@/services/exchangeAccounts'

function AccountForm({ onCreated }) {
  const [form, setForm]     = useState({ exchange: 'bingx', label: '', api_key: '', secret: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const { data } = await exchangeAccountsService.create(form)
      onCreated(data)
      setForm({ exchange: 'bingx', label: '', api_key: '', secret: '' })
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear cuenta')
    } finally { setLoading(false) }
  }

  return (
    <form onSubmit={handleSubmit} className="card space-y-4">
      <h3 className="font-semibold text-slate-900 dark:text-gray-100">Añadir cuenta de exchange</h3>
      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Exchange</label>
          <select
            value={form.exchange}
            onChange={e => setForm(f => ({...f, exchange: e.target.value}))}
            className="input"
          >
            <option value="bingx">BingX</option>
            <option value="bitunix">Bitunix</option>
          </select>
        </div>
        <div>
          <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Label</label>
          <input
            type="text"
            value={form.label}
            onChange={e => setForm(f => ({...f, label: e.target.value}))}
            className="input"
            placeholder="Mi cuenta principal"
            required
          />
        </div>
      </div>

      <div>
        <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">API Key</label>
        <input
          type="text"
          value={form.api_key}
          onChange={e => setForm(f => ({...f, api_key: e.target.value}))}
          className="input font-mono text-sm"
          placeholder="Pega tu API Key aquí"
          required
        />
      </div>

      <div>
        <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1.5">Secret</label>
        <input
          type="password"
          value={form.secret}
          onChange={e => setForm(f => ({...f, secret: e.target.value}))}
          className="input font-mono text-sm"
          placeholder="Pega tu Secret aquí"
          required
        />
      </div>

      <button type="submit" disabled={loading} className="btn-primary flex items-center gap-2">
        {loading ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
        {loading ? 'Guardando...' : 'Añadir cuenta'}
      </button>
    </form>
  )
}

function EditCredentialsForm({ account, onSaved, onCancel }) {
  const [form, setForm] = useState({ api_key: '', secret: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const updateData = {}
      if (form.api_key.trim()) updateData.api_key = form.api_key.trim()
      if (form.secret.trim()) updateData.secret = form.secret.trim()
      
      if (Object.keys(updateData).length === 0) {
        setError('Debes proporcionar al menos una credencial nueva')
        setLoading(false)
        return
      }
      
      await exchangeAccountsService.update(account.id, updateData)
      onSaved()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al actualizar credenciales')
    } finally { setLoading(false) }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 pt-4 border-t border-slate-200 dark:border-gray-800 space-y-3">
      <h4 className="text-sm font-medium text-slate-700 dark:text-gray-300">Actualizar credenciales</h4>
      {error && <p className="text-sm text-red-400">{error}</p>}
      
      <div>
        <label className="block text-xs text-slate-500 dark:text-gray-500 mb-1">Nueva API Key (dejar vacío para no cambiar)</label>
        <input
          type="text"
          value={form.api_key}
          onChange={e => setForm(f => ({...f, api_key: e.target.value}))}
          className="input font-mono text-sm"
          placeholder="Pega tu nueva API Key aquí"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 dark:text-gray-500 mb-1">Nuevo Secret (dejar vacío para no cambiar)</label>
        <input
          type="password"
          value={form.secret}
          onChange={e => setForm(f => ({...f, secret: e.target.value}))}
          className="input font-mono text-sm"
          placeholder="Pega tu nuevo Secret aquí"
        />
      </div>

      <div className="flex gap-2">
        <button type="submit" disabled={loading} className="btn-primary text-xs flex items-center gap-1.5">
          {loading ? <Loader2 size={12} className="animate-spin" /> : null}
          {loading ? 'Guardando...' : 'Guardar credenciales'}
        </button>
        <button type="button" onClick={onCancel} className="btn-secondary text-xs">
          Cancelar
        </button>
      </div>
    </form>
  )
}

// Componente para mostrar el estado de las credenciales
function CredentialsStatus({ account }) {
  const { last_health_status, last_health_check_at, last_health_error } = account
  
  // Si nunca se ha verificado
  if (!last_health_status) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-gray-500">
        <Shield size={14} />
        <span>Credenciales sin verificar</span>
      </div>
    )
  }
  
  const statusConfig = {
    healthy: {
      icon: ShieldCheck,
      color: 'text-green-400',
      bg: 'bg-green-500/10',
      label: 'Credenciales válidas'
    },
    error_credentials: {
      icon: ShieldAlert,
      color: 'text-red-400',
      bg: 'bg-red-500/10',
      label: 'Credenciales inválidas'
    },
    error_network: {
      icon: AlertCircle,
      color: 'text-yellow-400',
      bg: 'bg-yellow-500/10',
      label: 'Error de conexión'
    },
    error_unknown: {
      icon: AlertCircle,
      color: 'text-orange-400',
      bg: 'bg-orange-500/10',
      label: 'Error en verificación'
    }
  }
  
  const config = statusConfig[last_health_status] || statusConfig.error_unknown
  const Icon = config.icon
  const checkedTime = last_health_check_at 
    ? new Date(last_health_check_at).toLocaleString('es-ES', { 
        hour: '2-digit', 
        minute: '2-digit',
        day: '2-digit',
        month: '2-digit'
      })
    : null
  
  return (
    <div className={`flex flex-col gap-1`}>
      <div className={`flex items-center gap-1.5 text-xs ${config.color}`}>
        <Icon size={14} />
        <span className="font-medium">{config.label}</span>
        {checkedTime && <span className="text-slate-500 dark:text-gray-500 ml-1">(verificado {checkedTime})</span>}
      </div>
      {last_health_error && last_health_status !== 'healthy' && (
        <p className="text-xs text-red-400/80 ml-5 truncate" title={last_health_error}>
          {last_health_error}
        </p>
      )}
    </div>
  )
}

function AccountCard({ account, onDelete, onUpdated }) {
  const [testing, setTesting] = useState(false)
  const [result,  setResult]  = useState(null)
  const [editing, setEditing] = useState(false)
  const [localAccount, setLocalAccount] = useState(account)
  
  // Sincronizar con prop externa
  useEffect(() => {
    setLocalAccount(account)
  }, [account])

  const handleTest = async () => {
    setTesting(true); setResult(null)
    try {
      // Usar el nuevo endpoint de verificación que actualiza en DB
      const { data } = await exchangeAccountsService.verifyCredentials(account.id)
      setResult(data)
      // Actualizar cuenta local con nuevos datos
      if (data) {
        setLocalAccount(prev => ({
          ...prev,
          last_health_check_at: data.last_check,
          last_health_status: data.status,
          last_health_error: data.error
        }))
        // Notificar al padre para refrescar la lista
        if (onUpdated) onUpdated()
      }
    } catch (err) { 
      setResult({ 
        status: 'error', 
        error: err.response?.data?.detail || 'Error al verificar credenciales' 
      }) 
    }
    finally { setTesting(false) }
  }

  const handleDelete = async () => {
    if (!confirm(`¿Eliminar cuenta "${localAccount.label}"?`)) return
    try { await exchangeAccountsService.delete(localAccount.id); onDelete(localAccount.id) }
    catch (e) { alert(e.response?.data?.detail || 'Error al eliminar') }
  }

  const handleSaved = () => {
    setEditing(false)
    setResult({ status: 'healthy', message: 'Credenciales actualizadas. Haz clic en "Test conexión" para verificar.' })
  }

  // Determinar si hay problemas con las credenciales
  const hasCredentialIssues = localAccount.last_health_status && localAccount.last_health_status !== 'healthy'

  return (
    <div className={`card ${hasCredentialIssues ? 'border-red-500/30' : ''}`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-900 dark:text-gray-100">{localAccount.label}</span>
            <span className="text-xs px-2 py-0.5 rounded bg-slate-200 dark:bg-gray-800 text-slate-600 dark:text-gray-400 uppercase">
              {localAccount.exchange}
            </span>
            {!localAccount.is_active && (
              <span className="text-xs text-red-400">inactiva</span>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-gray-400 mt-0.5">
            Creada: {new Date(localAccount.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleTest}
            disabled={testing}
            className={`text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors ${
              hasCredentialIssues 
                ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30' 
                : 'bg-slate-200 dark:bg-gray-800 text-slate-700 dark:text-gray-200 hover:bg-slate-300 dark:hover:bg-gray-700'
            }`}
          >
            {testing ? <Loader2 size={12} className="animate-spin" /> : null}
            {testing ? 'Verificando...' : 'Verificar credenciales'}
          </button>
          <button 
            onClick={() => setEditing(!editing)} 
            className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-blue-400"
            title="Editar credenciales"
          >
            <Edit2 size={16} />
          </button>
          <button onClick={handleDelete} className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-red-400">
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* Estado de credenciales */}
      <div className="mt-3">
        <CredentialsStatus account={localAccount} />
      </div>

      {result && (
        <div className={`mt-3 flex items-center gap-2 text-sm rounded-lg px-3 py-2 ${
          result.status === 'healthy'
            ? 'bg-green-500/10 text-green-400'
            : 'bg-red-500/10 text-red-400'
        }`}>
          {result.status === 'healthy'
            ? <><CheckCircle size={14} /> {result.message || 'Credenciales verificadas correctamente'}</>
            : <><XCircle size={14} /> {result.error}</>
          }
        </div>
      )}

      {editing && (
        <EditCredentialsForm 
          account={localAccount} 
          onSaved={handleSaved} 
          onCancel={() => setEditing(false)} 
        />
      )}
    </div>
  )
}

export default function ExchangeAccountsPage() {
  const [accounts, setAccounts] = useState([])

  const loadAccounts = () => {
    exchangeAccountsService.list().then(r => setAccounts(r.data)).catch(() => {})
  }

  useEffect(() => {
    loadAccounts()
  }, [])

  const handleCreated = (account) => setAccounts(a => [account, ...a])
  const handleDelete  = (id)      => setAccounts(a => a.filter(x => x.id !== id))
  const handleUpdated = () => loadAccounts() // Refrescar lista completa

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold text-slate-900 dark:text-white">Cuentas de Exchange</h1>
      <p className="text-sm text-slate-500 dark:text-gray-400">
        Las API keys se encriptan antes de guardarse. Nunca se muestran en texto plano.
      </p>
      <AccountForm onCreated={handleCreated} />
      {accounts.map(a => (
        <AccountCard key={a.id} account={a} onDelete={handleDelete} onUpdated={handleUpdated} />
      ))}
    </div>
  )
}
