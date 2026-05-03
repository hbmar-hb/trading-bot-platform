import { useEffect, useRef, useState } from 'react'
import EmojiPicker from 'emoji-picker-react'
import { Hash, Image, Plus, Send, Smile, Trash2, X } from 'lucide-react'
import { chatService } from '@/services/chatService'
import useAuthStore from '@/store/authStore'
import useUiStore from '@/store/uiStore'

/* ─── Crear sala modal ───────────────────────────────────── */
function CreateRoomModal({ onClose, onCreated }) {
  const [name, setName]       = useState('')
  const [desc, setDesc]       = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

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
            <button type="submit" disabled={loading} className="btn-primary">{loading ? 'Creando…' : 'Crear sala'}</button>
            <button type="button" onClick={onClose} className="btn-ghost">Cancelar</button>
          </div>
        </form>
      </div>
    </div>
  )
}

/* ─── GIF picker modal ───────────────────────────────────── */
function GifPicker({ onSelect, onClose }) {
  const [query, setQuery]   = useState('')
  const [gifs, setGifs]     = useState([])
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(false)
  const timerRef = useRef(null)

  const load = async (q) => {
    setLoading(true)
    try {
      const { data } = await chatService.searchGifs(q)
      setEnabled(data.enabled)
      setGifs(data.data || [])
    } catch {
      setGifs([])
    } finally { setLoading(false) }
  }

  useEffect(() => { load('') }, [])

  const handleSearch = (e) => {
    const q = e.target.value
    setQuery(q)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => load(q), 400)
  }

  if (!enabled) return (
    <div className="absolute bottom-full mb-2 right-0 w-80 bg-white dark:bg-gray-900 border border-slate-200 dark:border-gray-800 rounded-xl p-4 shadow-xl z-50 text-center">
      <p className="text-sm text-slate-500 dark:text-gray-400">GIFs no configurados.</p>
      <p className="text-xs text-slate-400 dark:text-gray-500 mt-1">Añade <code className="bg-slate-100 dark:bg-gray-800 px-1 rounded">GIPHY_API_KEY</code> al .env del servidor.</p>
      <button onClick={onClose} className="mt-3 text-xs text-blue-500 hover:underline">Cerrar</button>
    </div>
  )

  return (
    <div className="absolute bottom-full mb-2 right-0 w-80 bg-white dark:bg-gray-900 border border-slate-200 dark:border-gray-800 rounded-xl shadow-xl z-50 overflow-hidden">
      <div className="flex items-center gap-2 p-3 border-b border-slate-200 dark:border-gray-800">
        <input
          autoFocus value={query} onChange={handleSearch}
          placeholder="Buscar GIF…"
          className="flex-1 bg-slate-100 dark:bg-gray-800 rounded-lg px-3 py-1.5 text-sm outline-none text-slate-900 dark:text-gray-100"
        />
        <button onClick={onClose} className="text-slate-400 hover:text-slate-700 dark:hover:text-gray-300"><X size={16} /></button>
      </div>
      <div className="h-64 overflow-y-auto p-2">
        {loading && <p className="text-center text-sm text-slate-400 dark:text-gray-500 py-4">Buscando…</p>}
        {!loading && gifs.length === 0 && <p className="text-center text-sm text-slate-400 dark:text-gray-500 py-4">Sin resultados</p>}
        <div className="grid grid-cols-3 gap-1.5">
          {gifs.map(gif => (
            <button key={gif.id} onClick={() => { onSelect(gif.url); onClose() }}
              className="rounded-lg overflow-hidden hover:ring-2 hover:ring-blue-500 transition-all">
              <img src={gif.preview} alt={gif.title} className="w-full h-20 object-cover" loading="lazy" />
            </button>
          ))}
        </div>
      </div>
      <p className="text-center text-[10px] text-slate-300 dark:text-gray-600 py-1">Powered by Giphy</p>
    </div>
  )
}

/* ─── Burbuja de mensaje ─────────────────────────────────── */
function MessageBubble({ msg, isOwn }) {
  const time    = new Date(msg.created_at).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
  const initial = msg.username?.[0]?.toUpperCase() || '?'
  const isGif   = msg.content?.startsWith('[gif]')
  const gifUrl  = isGif ? msg.content.slice(5) : null

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
        {isGif
          ? <img src={gifUrl} alt="gif" className="mt-1 rounded-lg max-w-xs max-h-48 object-contain" />
          : <p className="text-sm text-slate-700 dark:text-gray-300 break-words whitespace-pre-wrap">{msg.content}</p>
        }
      </div>
    </div>
  )
}

/* ─── Página principal ───────────────────────────────────── */
export default function ChatPage() {
  const user    = useAuthStore(s => s.user)
  const token   = useAuthStore(s => s.token)
  const isDark  = useUiStore(s => s.isDark)
  const isAdmin = user?.role === 'admin'

  const [rooms, setRooms]             = useState([])
  const [activeRoom, setActiveRoom]   = useState(null)
  const [messages, setMessages]       = useState([])
  const [input, setInput]             = useState('')
  const [showModal, setShowModal]     = useState(false)
  const [showEmoji, setShowEmoji]     = useState(false)
  const [showGif, setShowGif]         = useState(false)
  const [loadingMsgs, setLoadingMsgs] = useState(false)

  const wsRef     = useRef(null)
  const bottomRef = useRef(null)
  const inputRef  = useRef(null)

  useEffect(() => {
    chatService.getRooms()
      .then(r => { setRooms(r.data); if (r.data.length > 0) setActiveRoom(r.data[0]) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!token) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/api/ws?token=${token}`)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'chat_message') {
          setMessages(prev => {
            if (prev.find(m => m.id === msg.message_id)) return prev
            return [...prev, { id: msg.message_id, room_id: msg.room_id, user_id: msg.user_id, username: msg.username, content: msg.content, created_at: msg.created_at }]
          })
        }
      } catch {}
    }
    return () => ws.close()
  }, [token])

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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Cerrar popups al hacer click fuera
  useEffect(() => {
    const handler = () => { setShowEmoji(false); setShowGif(false) }
    if (showEmoji || showGif) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showEmoji, showGif])

  const sendText = (content) => {
    if (!content.trim() || !activeRoom || wsRef.current?.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({ type: 'chat_message', room_id: activeRoom.id, content }))
  }

  const sendMessage = () => {
    sendText(input)
    setInput('')
    inputRef.current?.focus()
  }

  const sendGif = (url) => sendText(`[gif]${url}`)

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const handleDeleteRoom = async (room) => {
    if (!confirm(`¿Eliminar "${room.name}"? Se borrarán todos los mensajes.`)) return
    try {
      await chatService.deleteRoom(room.id)
      setRooms(r => r.filter(x => x.id !== room.id))
      if (activeRoom?.id === room.id) setActiveRoom(null)
    } catch {}
  }

  const visibleMessages = messages.filter(m => m.room_id === activeRoom?.id)

  return (
    <div className="flex h-[calc(100vh-7rem)] -mt-2 rounded-xl overflow-hidden border border-slate-200 dark:border-gray-800 bg-white dark:bg-gray-900">

      {/* Sidebar */}
      <div className="w-52 shrink-0 border-r border-slate-200 dark:border-gray-800 flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-gray-800">
          <span className="text-sm font-semibold text-slate-900 dark:text-white">Salas</span>
          {isAdmin && (
            <button onClick={() => setShowModal(true)} title="Nueva sala"
              className="text-slate-400 hover:text-blue-500 transition-colors">
              <Plus size={16} />
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {rooms.length === 0 && (
            <p className="text-xs text-slate-400 dark:text-gray-500 px-4 py-2">
              {isAdmin ? 'Crea la primera sala →' : 'Sin salas'}
            </p>
          )}
          {rooms.map(room => (
            <div key={room.id} onClick={() => setActiveRoom(room)}
              className={`group flex items-center gap-2 px-3 py-2 mx-1 rounded-lg cursor-pointer transition-colors ${
                activeRoom?.id === room.id
                  ? 'bg-blue-600/15 text-blue-600 dark:text-blue-400'
                  : 'text-slate-600 dark:text-gray-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-gray-800'
              }`}>
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

      {/* Mensajes */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeRoom ? (
          <>
            <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200 dark:border-gray-800 shrink-0">
              <Hash size={16} className="text-slate-400" />
              <span className="font-semibold text-slate-900 dark:text-white">{activeRoom.name}</span>
              {activeRoom.description && (
                <span className="text-sm text-slate-400 dark:text-gray-500 ml-2 truncate">{activeRoom.description}</span>
              )}
            </div>

            <div className="flex-1 overflow-y-auto py-3">
              {loadingMsgs && <p className="text-center text-sm text-slate-400 py-4">Cargando…</p>}
              {!loadingMsgs && visibleMessages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center px-6">
                  <Hash size={40} className="text-slate-300 dark:text-gray-600 mb-3" />
                  <p className="font-semibold text-slate-700 dark:text-gray-300">Bienvenido a #{activeRoom.name}</p>
                  <p className="text-sm text-slate-400 dark:text-gray-500 mt-1">Sé el primero en escribir.</p>
                </div>
              )}
              {visibleMessages.map(msg => (
                <MessageBubble key={msg.id} msg={msg} isOwn={msg.user_id === user?.id} />
              ))}
              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="px-4 py-3 border-t border-slate-200 dark:border-gray-800 shrink-0">
              <div className="flex items-center gap-2 bg-slate-100 dark:bg-gray-800 rounded-xl px-3 py-2">
                {/* Emoji */}
                <div className="relative" onMouseDown={e => e.stopPropagation()}>
                  <button onClick={() => { setShowEmoji(v => !v); setShowGif(false) }}
                    className="text-slate-400 hover:text-yellow-500 transition-colors">
                    <Smile size={18} />
                  </button>
                  {showEmoji && (
                    <div className="absolute bottom-full mb-2 left-0 z-50">
                      <EmojiPicker
                        theme={isDark ? 'dark' : 'light'}
                        skinTonesDisabled
                        searchDisabled={false}
                        height={380}
                        width={320}
                        onEmojiClick={(e) => {
                          setInput(prev => prev + e.emoji)
                          inputRef.current?.focus()
                        }}
                      />
                    </div>
                  )}
                </div>

                {/* GIF */}
                <div className="relative" onMouseDown={e => e.stopPropagation()}>
                  <button onClick={() => { setShowGif(v => !v); setShowEmoji(false) }}
                    className="text-slate-400 hover:text-purple-500 transition-colors text-xs font-bold tracking-tight">
                    GIF
                  </button>
                  {showGif && (
                    <GifPicker onSelect={sendGif} onClose={() => setShowGif(false)} />
                  )}
                </div>

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
        <CreateRoomModal onClose={() => setShowModal(false)}
          onCreated={(room) => { setRooms(r => [...r, room]); setActiveRoom(room) }} />
      )}
    </div>
  )
}
