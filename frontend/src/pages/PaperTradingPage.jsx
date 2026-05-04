import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, Plus, RefreshCcw, Trash2, Wallet } from 'lucide-react'
import { paperTradingService } from '@/services/paperTrading'
import LoadingSpinner from '@/components/Common/LoadingSpinner'

function CreateForm({ onCreated }) {
  const [form, setForm] = useState({ label: '', initial_balance: 10000 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const payload = {
        label: form.label.trim(),
        initial_balance: parseFloat(form.initial_balance)
      }
      console.log('Enviando:', payload)
      const response = await paperTradingService.create(payload)
      console.log('Respuesta:', response)
      // La respuesta puede venir en response.data o directamente
      const data = response.data || response
      onCreated(data)
      setForm({ label: '', initial_balance: 10000 })
    } catch (err) {
      console.error('Error completo:', err)
      console.error('Response:', err.response)
      const errorMsg = err.response?.data?.detail 
        || err.response?.statusText 
        || err.message 
        || 'Error al crear cuenta'
      setError(`Error ${err.response?.status || ''}: ${errorMsg}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card space-y-4">
      <h3 className="font-semibold text-slate-900 dark:text-gray-100">Crear cuenta Paper Trading</h3>
      
      {error && <p className="text-sm text-red-400">{error}</p>}
      
      <div>
        <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1">Nombre de la cuenta</label>
        <input
          type="text"
          value={form.label}
          onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
          className="input"
          placeholder="Ej: Cuenta de prueba"
          required
        />
      </div>

      <div>
        <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1">Balance inicial (USDT)</label>
        <input
          type="number"
          min="100"
          step="100"
          value={form.initial_balance}
          onChange={e => setForm(f => ({ ...f, initial_balance: e.target.value }))}
          className="input"
          required
        />
        <p className="text-xs text-slate-500 dark:text-gray-400 mt-1">
          Balance ficticio para practicar sin riesgo
        </p>
      </div>

      <button 
        type="submit" 
        disabled={loading}
        className="btn-primary flex items-center gap-2 text-sm w-full justify-center"
      >
        {loading ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
        {loading ? 'Creando...' : 'Crear cuenta paper'}
      </button>
    </form>
  )
}

function AccountCard({ account, onUpdate, onDelete }) {
  const [resetting, setResetting] = useState(false)
  const [balance, setBalance] = useState(null)
  const [showBalance, setShowBalance] = useState(false)

  const handleReset = async () => {
    if (!confirm(`¿Resetear "${account.label}" al balance inicial de ${parseFloat(account.initial_balance).toFixed(0)} USDT?`)) return
    setResetting(true)
    try {
      const { data } = await paperTradingService.reset(account.id)
      onUpdate(data)
    } catch (e) {
      alert('Error al resetear cuenta')
    } finally {
      setResetting(false)
    }
  }

  const loadBalance = async () => {
    try {
      const { data } = await paperTradingService.getBalance(account.id)
      setBalance(data)
      setShowBalance(true)
    } catch (e) {
      console.error('Error cargando balance:', e)
    }
  }

  return (
    <div className="card border-l-4 border-l-purple-500">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Wallet size={20} className="text-purple-400" />
          <div>
            <h4 className="font-medium text-slate-900 dark:text-gray-100">{account.label}</h4>
            <p className="text-xs text-slate-500 dark:text-gray-400">
              Creada: {new Date(account.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={resetting}
            className="btn-secondary text-xs flex items-center gap-1.5"
            title="Resetear al balance inicial"
          >
            {resetting ? <Loader2 size={12} className="animate-spin" /> : <RefreshCcw size={12} />}
            Reset
          </button>
          <button
            onClick={() => onDelete(account.id)}
            className="p-1.5 text-slate-400 dark:text-gray-400 hover:text-red-400"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* Balance info */}
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
          <p className="text-xs text-slate-500 dark:text-gray-400">Balance inicial</p>
          <p className="text-lg font-mono font-medium text-slate-900 dark:text-gray-100">
            {parseFloat(account.initial_balance).toLocaleString()} USDT
          </p>
        </div>
        <div className="bg-slate-100 dark:bg-gray-800/50 rounded-lg p-3">
          <p className="text-xs text-slate-500 dark:text-gray-400">Balance disponible</p>
          <p className="text-lg font-mono font-medium text-purple-500 dark:text-purple-400">
            {parseFloat(account.available_balance).toLocaleString()} USDT
          </p>
        </div>
      </div>

      {showBalance && balance && (
        <div className="mt-3 p-3 bg-purple-500/10 rounded-lg">
          <div className="flex justify-between items-center">
            <span className="text-sm text-slate-500 dark:text-gray-400">Equity total</span>
            <span className="font-mono font-medium text-slate-900 dark:text-gray-100">
              {balance.total_equity.toLocaleString()} USDT
            </span>
          </div>
          {balance.unrealized_pnl !== 0 && (
            <div className="flex justify-between items-center mt-1">
              <span className="text-sm text-slate-500 dark:text-gray-400">PnL no realizado</span>
              <span className={`font-mono ${balance.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {balance.unrealized_pnl >= 0 ? '+' : ''}{balance.unrealized_pnl.toFixed(2)} USDT
              </span>
            </div>
          )}
        </div>
      )}

      {!showBalance && (
        <button
          onClick={loadBalance}
          className="mt-3 text-xs text-purple-600 dark:text-purple-400 hover:text-purple-500 dark:hover:text-purple-300"
        >
          Ver balance actual →
        </button>
      )}
    </div>
  )
}

export default function PaperTradingPage() {
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)

  const loadAccounts = async () => {
    try {
      const { data } = await paperTradingService.list()
      setAccounts(data || [])
    } catch (e) {
      console.error('Error cargando cuentas paper:', e)
      setAccounts([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAccounts()
  }, [])

  const handleCreated = (account) => {
    setAccounts(prev => [account, ...prev])
  }

  const handleUpdate = (updated) => {
    setAccounts(prev => prev.map(a => a.id === updated.id ? updated : a))
  }

  const handleDelete = async (id) => {
    if (!confirm('¿Eliminar esta cuenta paper? Las posiciones abiertas se perderán.')) return
    try {
      await paperTradingService.delete(id)
      setAccounts(prev => prev.filter(a => a.id !== id))
    } catch (e) {
      alert('Error al eliminar cuenta')
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Paper Trading</h1>
          <p className="text-sm text-slate-500 dark:text-gray-400 mt-1">
            Practica con dinero ficticio sin riesgo real
          </p>
        </div>
        <Link to="/bots" className="btn-secondary text-sm">
          Ver mis bots
        </Link>
      </div>

      <CreateForm onCreated={handleCreated} />

      <div className="space-y-3">
        <h2 className="font-semibold text-slate-700 dark:text-gray-300">Tus cuentas paper</h2>
        
        {loading ? (
          <div className="flex justify-center py-12">
            <LoadingSpinner />
          </div>
        ) : !Array.isArray(accounts) || accounts.length === 0 ? (
          <div className="card text-center py-10">
            <p className="text-slate-500 dark:text-gray-400">No tienes cuentas paper</p>
            <p className="text-sm text-slate-600 dark:text-gray-500 mt-2">
              Crea una arriba para empezar a practicar
            </p>
          </div>
        ) : Array.isArray(accounts) ? (
          accounts.map(account => (
            <AccountCard
              key={account.id}
              account={account}
              onUpdate={handleUpdate}
              onDelete={handleDelete}
            />
          ))
        ) : (
          <div className="card text-center py-10">
            <p className="text-slate-500 dark:text-gray-400">Error al cargar cuentas</p>
          </div>
        )}
      </div>

      <div className="card bg-slate-100 dark:bg-gray-800/30">
        <h3 className="font-medium text-sm text-slate-700 dark:text-gray-300 mb-2">¿Qué es Paper Trading?</h3>
        <ul className="text-sm text-slate-600 dark:text-gray-400 space-y-1 list-disc list-inside">
          <li>Opera con dinero ficticio sin riesgo real</li>
          <li>Prueba estrategias antes de usar dinero real</li>
          <li>El precio de mercado es el mismo que en exchanges reales</li>
          <li>Las operaciones se ejecutan simulando slippage y fees</li>
        </ul>
      </div>
    </div>
  )
}
