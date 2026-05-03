import { useEffect, useRef, useState } from 'react'
import { Hash, Plus, Send, Trash2, X } from 'lucide-react'
import { chatService } from '@/services/chatService'
import useAuthStore from '@/store/authStore'

function CreateRoomModal({ onClose, onCreated }) {
  const [name, setName]         = useState('')
  const [desc, setDesc]         = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      const { data } = await chatService.createRoom({ name: name.trim(), description: desc.trim() || null })
      onCreated(data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear la sala')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-white dark:bg-gray-900 border border-slate-200 dark:border-gray-800 rounded-xl w-full max-w-sm p-6 space-y-4 mx-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-900 dark:text-white">Nueva sala</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-900 dark:hover:text-white"><X size={18} /></button>
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1">Nombre</label>
            <input value={name} onChange={e => setName(e.target.value)}
              className="input w-full" placeholder="general" required autoFocus />
          </div>
          <div>
            <label className="block text-sm text-slate-500 dark:text-gray-400 mb-1">Descripción (opcional)</label>
            <input value={desc} onChange={e => setDesc(e.target.value)}
              className="input w-full" placeholder="Tema de la sala" />
          </div>
          <div className="flex gap-2 pt-1">
            <button type="submit" disabled={loading} className="btn-primary">
              {loading ? 'Creando…' : 'Crear sala'}
            </button>
            <button type="button" onClick={onClose} className="btn-ghost">Cancelar</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function MessageBubble({ msg, isOwn }) {
  const time = new Date(msg.created_at).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
  const initial = msg.username?.[0]?.toUpperCase() || '?'
  return (
    <div className="flex items-start gap-3 group px-4 py-1.5 hover:bg-slate-50 dark:hover:bg-gray-800/50 rounded-lg">
      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white font-bold text-sm shrink-0 mt-0.5 ${isOwn ? 'bg-blue-600' : 'bg-slate-500 dark:bg-gray-600'}`}>
        {initial}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className={`font-semibold text-sm ${isOwn ? 'text-blue-600 dark:text-blue-400' : 'text-slate-900 dark:text-gray-100'}`}>
            {msg.username}
          </span>
          <span className="text-xs text-slate-400 dark:text-gray-500">{time}</span>
        </div>
        <p className="text-sm text-slate-700 dark:text-gray-300 break-words">{msg.content}</p>
      </div>
    </div>
  )
}

export default function ChatPage() {
  const user     = useAuthStore(s => s.user)
  const token    = useAuthStore(s => s.token)
  const isAdmin  = user?.role === 'admin'

  const [rooms, setRooms]           = useState([])
  const [activeRoom, setActiveRoom] = useState(null)
  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState('')
  const [showModal, setShowModal]   = useState(false)
  const [loadingMsgs, setLoadingMsgs] = useState(false)

  const wsRef       = useRef(null)
  const bottomRef   = useRef(null)
  const inputRef    = useRef(null)

  // Cargar salas al montar
  useEffect(() => {
    chatService.getRooms()
      .then(r => {
        setRooms(r.data)
        if (r.data.length > 0) setActiveRoom(r.data[0])
      })
      .catch(() => {})
  }, [])

  // Conectar WebSocket
  useEffect(() => {
    if (!token) return
    const wsUrl = (window.location.protocol === 'https:' ? 'wss' : 'ws') +
      '://' + window.location.host + '/api/ws?token=' + token

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'chat_message') {
          setMessages(prev => {
            // Evitar duplicados
            if (prev.find(m => m.id === msg.message_id)) return prev
            return [...prev, {
              id: msg.message_id,
              room_id: msg.room_id,
              user_id: msg.user_id,
              username: msg.username,
              content: msg.content,
              created_at: msg.created_at,
            }]
          })
        }
      } catch {}
    }

    return () => ws.close()
  }, [token])

  // Cargar mensajes cuando cambia la sala
  useEffect(() => {
    if (!activeRoom) return
    setLoadingMsgs(true)
    setMessages([])
    chatService.getMessages(activeRoom.id)
      .then(r => setMessages(r.data))
      .catch(() => {})
      .finally(() => setLoadingMsgs(false))
    inputRef.current?.focus()
  }, [activeRoom])

  // Scroll al último mensaje
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = () => {
    const content = input.trim()
    if (!content || !activeRoom || wsRef.current?.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({ type: 'chat_message', room_id: activeRoom.id, content }))
    setInput('')
    inputRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const handleDeleteRoom = async (room) => {
    if (!confirm(`¿Eliminar la sala "${room.name}"? Se borrarán todos los mensajes.`)) return
    try {
      await chatService.deleteRoom(room.id)
      setRooms(r => r.filter(x => x.id !== room.id))
      if (activeRoom?.id === room.id) setActiveRoom(null)
    } catch {}
  }

  const visibleMessages = messages.filter(m => m.room_id === activeRoom?.id)

  return (
    <div className="flex h-[calc(100vh-7rem)] -mt-2 gap-0 rounded-xl overflow-hidden border border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900">

      {/* ── Sidebar salas ── */}
      <div className="w-56 shrink-0 border-r border-slate-200 dark:border-gray-800 flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-gray-800">
          <span className="text-sm font-semibold text-slate-900 dark:text-white">Salas</span>
          {isAdmin && (
            <button onClick={() => setShowModal(true)}
              className="text-slate-400 hover:text-blue-500 dark:hover:text-blue-400 transition-colors" title="Nueva sala">
              <Plus size={16} />
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {rooms.length === 0 && (
            <p className="text-xs text-slate-400 dark:text-gray-500 px-4 py-2">
              {isAdmin ? 'Crea la primera sala →' : 'No hay salas disponibles'}
            </p>
          )}
          {rooms.map(room => (
            <div key={room.id}
              className={`group flex items-center gap-2 px-3 py-2 mx-1 rounded-lg cursor-pointer transition-colors ${
                activeRoom?.id === room.id
                  ? 'bg-blue-600/15 text-blue-600 dark:text-blue-400'
                  : 'text-slate-600 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-gray-800'
              }`}
              onClick={() => setActiveRoom(room)}
            >
              <Hash size={15} className="shrink-0" />
              <span className="text-sm flex-1 truncate">{room.name}</span>
              {isAdmin && (
                <button onClick={e => { e.stopPropagation(); handleDeleteRoom(room) }}
                  className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-400 transition-all">
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Área de mensajes ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeRoom ? (
          <>
            {/* Header */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200 dark:border-gray-800 shrink-0">
              <Hash size={16} className="text-slate-400" />
              <span className="font-semibold text-slate-900 dark:text-white">{activeRoom.name}</span>
              {activeRoom.description && (
                <span className="text-sm text-slate-400 dark:text-gray-500 ml-2 truncate">{activeRoom.description}</span>
              )}
            </div>

            {/* Mensajes */}
            <div className="flex-1 overflow-y-auto py-3">
              {loadingMsgs && (
                <p className="text-center text-sm text-slate-400 dark:text-gray-500 py-4">Cargando mensajes…</p>
              )}
              {!loadingMsgs && visibleMessages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center px-6">
                  <Hash size={40} className="text-slate-300 dark:text-gray-600 mb-3" />
                  <p className="font-semibold text-slate-700 dark:text-gray-300">Bienvenido a #{activeRoom.name}</p>
                  <p className="text-sm text-slate-400 dark:text-gray-500 mt-1">Sé el primero en escribir algo.</p>
                </div>
              )}
              {visibleMessages.map(msg => (
                <MessageBubble key={msg.id} msg={msg} isOwn={msg.user_id === user?.id} />
              ))}
              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="px-4 py-3 border-t border-slate-200 dark:border-gray-800 shrink-0">
              <div className="flex items-center gap-2 bg-slate-100 dark:bg-gray-800 rounded-lg px-3 py-2">
                <input
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`Mensaje en #${activeRoom.name}`}
                  className="flex-1 bg-transparent text-sm text-slate-900 dark:text-gray-100 placeholder-slate-400 dark:placeholder-gray-500 outline-none"
                  maxLength={2000}
                />
                <button onClick={sendMessage} disabled={!input.trim()}
                  className="text-blue-500 hover:text-blue-600 disabled:text-slate-300 dark:disabled:text-gray-600 transition-colors">
                  <Send size={18} />
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-center px-6">
            <div>
              <Hash size={48} className="text-slate-300 dark:text-gray-600 mx-auto mb-3" />
              <p className="text-slate-500 dark:text-gray-400">Selecciona una sala para empezar</p>
            </div>
          </div>
        )}
      </div>

      {showModal && (
        <CreateRoomModal
          onClose={() => setShowModal(false)}
          onCreated={(room) => { setRooms(r => [...r, room]); setActiveRoom(room) }}
        />
      )}
    </div>
  )
}
