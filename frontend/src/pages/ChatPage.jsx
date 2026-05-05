import { useEffect, useRef, useState } from 'react'
import { MessageSquare, Plus, Trash2, X, Send, Image, Smile, Lock, Users } from 'lucide-react'
import { chatService } from '@/services/chat'
import { usersService } from '@/services/usersService'
import useAuthStore from '@/store/authStore'

const BG_SHAPES = {
  none: 'none',
  bubbles: 'radial-gradient(circle at 20% 30%, rgba(255,255,255,0.06) 0%, transparent 20%), radial-gradient(circle at 80% 70%, rgba(255,255,255,0.04) 0%, transparent 25%)',
  dots: 'radial-gradient(circle, rgba(255,255,255,0.08) 1px, transparent 1px)',
  waves: 'repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0px, rgba(255,255,255,0.03) 2px, transparent 2px, transparent 10px)',
}

const FONTS = [
  { label: 'Inter',      value: 'Inter, sans-serif' },
  { label: 'Roboto',     value: 'Roboto, sans-serif' },
  { label: 'Open Sans',  value: '"Open Sans", sans-serif' },
  { label: 'Lato',       value: 'Lato, sans-serif' },
  { label: 'Mono',       value: '"JetBrains Mono", monospace' },
]

const EMOJIS = ['😀','😂','🥰','😎','🤔','😭','😡','👍','👎','🎉','🔥','❤️','💯','🚀','👀','🤝','🙏','💪','✅','❌','⚠️','💰','📈','📉','🎯','🏆','🤖','💎','🌙','☀️','🌍','🎁','🎵','🍕','☕','🍺','🏠','🚗','✈️','⌚']

function roleColor(role) {
  if (role === 'admin') return '#60a5fa'
  if (role === 'moderator') return '#fbbf24'
  return '#94a3b8'
}

export default function ChatPage() {
  const { user } = useAuthStore()
  const [rooms, setRooms]             = useState([])
  const [activeRoom, setActiveRoom]   = useState(null)
  const [messages, setMessages]       = useState([])
  const [input, setInput]             = useState('')
  const [loading, setLoading]         = useState(false)
  const [showNewRoom, setShowNewRoom] = useState(false)
  const [newRoomName, setNewRoomName] = useState('')
  const [newRoomDesc, setNewRoomDesc] = useState('')
  const [newRoomPrivate, setNewRoomPrivate] = useState(false)
  const [allUsers, setAllUsers]       = useState([])
  const [selectedMembers, setSelectedMembers] = useState([])
  const [showGifs, setShowGifs]       = useState(false)
  const [gifQuery, setGifQuery]       = useState('')
  const [gifs, setGifs]               = useState([])
  const [gifLoading, setGifLoading]   = useState(false)
  const [showEmojis, setShowEmojis]   = useState(false)
  const [showMembers, setShowMembers] = useState(false)
  const messagesEndRef = useRef(null)
  const pollRef        = useRef(null)

  const isAdmin = user?.role === 'admin'
  const isMod   = user?.role === 'moderator'
  const canManageChannels = isAdmin || isMod

  const prefs = {
    bgColor:    user?.chat_bg_color    || '#1f2937',
    bgShape:    user?.chat_bg_shape    || 'none',
    fontFamily: user?.chat_font_family || 'Inter',
    fontSize:   user?.chat_font_size   || 14,
    fontColor:  user?.chat_font_color  || '#e2e8f0',
  }

  useEffect(() => {
    loadRooms()
    if (isAdmin) {
      usersService.list().then(r => setAllUsers(r.data || [])).catch(() => {})
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  useEffect(() => {
    if (activeRoom) {
      loadMessages()
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(loadMessages, 2000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [activeRoom])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadRooms = async () => {
    try {
      const { data } = await chatService.listRooms()
      const list = Array.isArray(data) ? data : []
      setRooms(list)
      if (list.length > 0 && !activeRoom) setActiveRoom(list[0])
    } catch {}
  }

  const loadMessages = async () => {
    if (!activeRoom) return
    try {
      const { data } = await chatService.listMessages(activeRoom.id)
      setMessages(Array.isArray(data) ? data : [])
    } catch {}
  }

  const send = async (content) => {
    if (!content.trim() || !activeRoom) return
    setLoading(true)
    try {
      await chatService.sendMessage({ room_id: activeRoom.id, content: content.trim() })
      setInput('')
      loadMessages()
    } catch {
      alert('Error al enviar mensaje')
    } finally { setLoading(false) }
  }

  const createRoom = async (e) => {
    e.preventDefault()
    if (!newRoomName.trim()) return
    try {
      const payload = {
        name: newRoomName.trim(),
        description: newRoomDesc.trim() || undefined,
        is_private: newRoomPrivate,
        member_ids: newRoomPrivate ? selectedMembers : [],
      }
      const { data } = await chatService.createRoom(payload)
      setRooms(r => [data, ...r])
      setActiveRoom(data)
      setShowNewRoom(false)
      setNewRoomName(''); setNewRoomDesc(''); setNewRoomPrivate(false); setSelectedMembers([])
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al crear sala')
    }
  }

  const deleteRoom = async (id) => {
    if (!confirm('¿Eliminar esta sala y todos sus mensajes?')) return
    try {
      await chatService.deleteRoom(id)
      setRooms(r => r.filter(x => x.id !== id))
      if (activeRoom?.id === id) setActiveRoom(null)
    } catch (err) {
      alert(err.response?.data?.detail || 'No puedes eliminar esta sala')
    }
  }

  const toggleMember = (uid) =>
    setSelectedMembers(prev => prev.includes(uid) ? prev.filter(x => x !== uid) : [...prev, uid])

  const searchGifs = async () => {
    if (!gifQuery.trim()) return
    setGifLoading(true)
    try {
      const { data } = await chatService.searchGifs(gifQuery.trim())
      setGifs(Array.isArray(data?.gifs) ? data.gifs : [])
    } catch { setGifs([]) }
    finally { setGifLoading(false) }
  }

  const sendGif = (url) => {
    send(`![GIF](${url})`)
    setShowGifs(false); setGifs([]); setGifQuery('')
  }

  const bgStyle = {
    backgroundColor: prefs.bgColor,
    backgroundImage: BG_SHAPES[prefs.bgShape] || 'none',
    backgroundSize: prefs.bgShape === 'dots' ? '20px 20px' : prefs.bgShape === 'waves' ? '100px 20px' : 'auto',
    fontFamily: FONTS.find(f => f.label === prefs.fontFamily)?.value || prefs.fontFamily,
    fontSize: `${prefs.fontSize}px`,
    color: prefs.fontColor,
  }

  const insertEmoji = (emoji) => { setInput(prev => prev + emoji); setShowEmojis(false) }
  const isMe = (msg) => msg.user_id === user?.id

  return (
    <div className="flex h-[calc(100vh-4rem)] -mx-6 -my-6" style={bgStyle}>
      {/* Sidebar salas */}
      <div className="w-64 border-r border-white/10 flex flex-col" style={{ backgroundColor: prefs.bgColor, opacity: 0.95 }}>
        <div className="p-4 border-b border-white/10 flex items-center justify-between">
          <h2 className="font-semibold text-white flex items-center gap-2">
            <MessageSquare size={18} /> Chat
          </h2>
          {canManageChannels && (
            <button onClick={() => setShowNewRoom(true)} className="p-1.5 rounded hover:bg-white/10 text-white" title="Nuevo canal">
              <Plus size={16} />
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {rooms.map(room => (
            <div
              key={room.id}
              onClick={() => setActiveRoom(room)}
              className={`p-3 rounded-lg cursor-pointer flex items-center justify-between group ${
                activeRoom?.id === room.id ? 'bg-white/20' : 'hover:bg-white/10'
              }`}
            >
              <div className="min-w-0 flex items-center gap-1.5">
                {room.is_private && <Lock size={11} className="text-amber-400 shrink-0" />}
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{room.name}</p>
                  <p className="text-xs opacity-50 truncate">{room.description || 'Sin descripción'}</p>
                </div>
              </div>
              {canManageChannels && (
                <button
                  onClick={(e) => { e.stopPropagation(); deleteRoom(room.id) }}
                  className="opacity-0 group-hover:opacity-100 p-1 text-white/50 hover:text-red-400 transition-opacity shrink-0"
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
          {rooms.length === 0 && (
            <p className="text-sm opacity-40 text-center py-8">
              {canManageChannels ? 'No hay canales. Crea uno.' : 'No hay canales disponibles.'}
            </p>
          )}
        </div>
      </div>

      {/* Área de mensajes */}
      <div className="flex-1 flex flex-col">
        {activeRoom ? (
          <>
            <div className="p-4 border-b border-white/10 flex items-center justify-between" style={{ backgroundColor: prefs.bgColor, opacity: 0.9 }}>
              <div className="flex items-center gap-2">
                {activeRoom.is_private && <Lock size={14} className="text-amber-400" />}
                <div>
                  <h3 className="font-semibold">{activeRoom.name}</h3>
                  <p className="text-xs opacity-50">{activeRoom.description || `${messages.length} mensajes`}</p>
                </div>
              </div>
              {isAdmin && activeRoom.is_private && (
                <button onClick={() => setShowMembers(!showMembers)} title="Gestionar miembros" className="p-1.5 rounded hover:bg-white/10">
                  <Users size={16} />
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.map(msg => (
                <div key={msg.id} className={`flex ${isMe(msg) ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[70%] rounded-xl px-4 py-2 ${
                    isMe(msg) ? 'bg-blue-600 rounded-br-none' : 'bg-white/10 rounded-bl-none'
                  }`}>
                    {!isMe(msg) && (
                      <p className="text-xs font-bold mb-0.5" style={{ color: roleColor(msg.role) }}>
                        {msg.username}
                      </p>
                    )}
                    {msg.content.startsWith('![GIF]') ? (
                      <img src={msg.content.match(/\((.*)\)/)?.[1]} alt="GIF" className="rounded-lg max-h-40" />
                    ) : (
                      <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    )}
                    <p className={`text-[10px] mt-1 ${isMe(msg) ? 'text-blue-200' : 'opacity-40'}`}>
                      {new Date(msg.created_at).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-white/10" style={{ backgroundColor: prefs.bgColor, opacity: 0.95 }}>
              <div className="flex gap-2">
                <button onClick={() => setShowGifs(!showGifs)} className="p-2 rounded-lg bg-white/10 text-white hover:bg-white/20"><Image size={18} /></button>
                <button onClick={() => { setShowEmojis(!showEmojis); setShowGifs(false) }} className="p-2 rounded-lg bg-white/10 text-white hover:bg-white/20"><Smile size={18} /></button>
                <input
                  type="text"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && send(input)}
                  placeholder="Escribe un mensaje..."
                  className="flex-1 px-4 py-2 rounded-lg bg-white/10 placeholder-white/40 border border-white/10 focus:outline-none focus:border-blue-500"
                />
                <button onClick={() => send(input)} disabled={loading || !input.trim()} className="p-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                  <Send size={18} />
                </button>
              </div>

              {showEmojis && (
                <div className="mt-3 p-3 rounded-lg bg-black/40 border border-white/10">
                  <div className="flex flex-wrap gap-2">
                    {EMOJIS.map(emoji => (
                      <button key={emoji} type="button" onClick={() => insertEmoji(emoji)} className="text-xl hover:scale-125 transition-transform p-1">{emoji}</button>
                    ))}
                  </div>
                </div>
              )}

              {showGifs && (
                <div className="mt-3 p-3 rounded-lg bg-black/40 border border-white/10">
                  <div className="flex gap-2 mb-2">
                    <input type="text" value={gifQuery} onChange={e => setGifQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && searchGifs()}
                      placeholder="Buscar GIFs..." className="flex-1 px-3 py-1.5 rounded bg-white/10 placeholder-white/40 text-sm border border-white/10" />
                    <button onClick={searchGifs} className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm hover:bg-blue-700">{gifLoading ? '...' : 'Buscar'}</button>
                    <button onClick={() => setShowGifs(false)} className="p-1.5 text-white/50 hover:text-white"><X size={16} /></button>
                  </div>
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {gifs.map(g => (
                      <img key={g.id} src={g.preview} alt={g.title} onClick={() => sendGif(g.url)} className="h-24 rounded cursor-pointer hover:ring-2 ring-blue-500 shrink-0" />
                    ))}
                    {gifs.length === 0 && !gifLoading && <p className="text-xs opacity-40">Busca algo para ver GIFs</p>}
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <MessageSquare size={48} className="text-white/20 mx-auto mb-4" />
              <p className="opacity-50">Selecciona un canal o {canManageChannels ? 'crea uno nuevo' : 'espera a que haya canales disponibles'}</p>
            </div>
          </div>
        )}
      </div>

      {/* Modal nueva sala */}
      {showNewRoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-white/10 rounded-xl w-full max-w-sm p-6 space-y-4 mx-4">
            <h3 className="font-semibold text-white">Nuevo canal de chat</h3>
            <form onSubmit={createRoom} className="space-y-3">
              <div>
                <label className="block text-sm text-white/50 mb-1">Nombre</label>
                <input type="text" value={newRoomName} onChange={e => setNewRoomName(e.target.value)}
                  className="w-full px-3 py-2 rounded bg-white/10 text-white border border-white/10 focus:outline-none focus:border-blue-500"
                  required autoFocus />
              </div>
              <div>
                <label className="block text-sm text-white/50 mb-1">Descripción (opcional)</label>
                <input type="text" value={newRoomDesc} onChange={e => setNewRoomDesc(e.target.value)}
                  className="w-full px-3 py-2 rounded bg-white/10 text-white border border-white/10 focus:outline-none focus:border-blue-500" />
              </div>

              {isAdmin && (
                <label className="flex items-center gap-2.5 cursor-pointer py-1">
                  <div
                    onClick={() => { setNewRoomPrivate(p => !p); setSelectedMembers([]) }}
                    className={`w-10 h-5 rounded-full transition-colors relative ${newRoomPrivate ? 'bg-amber-500' : 'bg-white/20'}`}
                  >
                    <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${newRoomPrivate ? 'translate-x-5' : 'translate-x-0.5'}`} />
                  </div>
                  <span className="text-sm text-white flex items-center gap-1.5">
                    <Lock size={12} className={newRoomPrivate ? 'text-amber-400' : 'text-white/40'} />
                    Canal privado
                  </span>
                </label>
              )}

              {isAdmin && newRoomPrivate && allUsers.length > 0 && (
                <div>
                  <label className="block text-sm text-white/50 mb-1.5">Añadir miembros</label>
                  <div className="max-h-36 overflow-y-auto space-y-1 pr-1">
                    {allUsers.filter(u => u.id !== user?.id).map(u => (
                      <label key={u.id} className="flex items-center gap-2 p-1.5 rounded hover:bg-white/5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selectedMembers.includes(u.id)}
                          onChange={() => toggleMember(u.id)}
                          className="w-3.5 h-3.5"
                        />
                        <span className="text-sm text-white">{u.username}</span>
                        <span className="text-xs text-white/40 ml-auto">{u.role}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-2 pt-1">
                <button type="submit" className="btn-primary text-sm">Crear canal</button>
                <button type="button" onClick={() => { setShowNewRoom(false); setNewRoomPrivate(false); setSelectedMembers([]) }} className="btn-ghost text-sm">Cancelar</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
