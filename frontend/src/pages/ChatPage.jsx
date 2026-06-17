import { useEffect, useRef, useState } from 'react'
import { MessageSquare, Plus, Trash2, X, Send, Image, Smile, Lock, Users } from 'lucide-react'
import { chatService } from '@/services/chat'
import { usersService } from '@/services/usersService'
import useAuthStore from '@/store/authStore'

const BG_SHAPES = {
  none: 'none',
  bubbles: 'radial-gradient(circle at 20% 30%, var(--shape-color) 0%, transparent 20%), radial-gradient(circle at 80% 70%, var(--shape-color) 0%, transparent 25%)',
  dots: 'radial-gradient(circle, var(--shape-color) 1px, transparent 1px)',
  waves: 'repeating-linear-gradient(45deg, var(--shape-color) 0px, var(--shape-color) 2px, transparent 2px, transparent 10px)',
}

const FONTS = [
  { label: 'Inter',      value: 'Inter, sans-serif' },
  { label: 'Roboto',     value: 'Roboto, sans-serif' },
  { label: 'Open Sans',  value: '"Open Sans", sans-serif' },
  { label: 'Lato',       value: 'Lato, sans-serif' },
  { label: 'Mono',       value: '"JetBrains Mono", monospace' },
]

const EMOJI_CATEGORIES = [
  { label: '😊 Caras', emojis: ['😀','😂','🤣','😅','😊','🥹','😍','🥰','😎','🤩','😏','😒','🤔','😬','🙃','😤','😭','😱','🤯','😴','🥸','🤮','😈','👻','💀','🙈','🙉','🙊'] },
  { label: '👋 Gestos', emojis: ['👍','👎','👏','🙌','🤝','🙏','💪','✌️','🤙','👌','🤜','🤛','🫶','🫂','👋','🤚','🖐️','✋','🤞','🤟'] },
  { label: '❤️ Corazones', emojis: ['❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','💕','💞','💓','💗','💖','💘','💝','❣️','💔','🔥','✨'] },
  { label: '📈 Trading', emojis: ['📈','📉','💰','💸','🤑','💎','💵','💴','💶','💷','🏦','📊','📋','🎯','⚡','🔔','📌','🔑','⏰','🚀'] },
  { label: '🎉 Celebración', emojis: ['🎉','🎊','🏆','🥇','🥈','🥉','🎖️','🏅','🎯','💯','⭐','🌟','✅','🎁','🎈','🎂','🥂','🍾','👑','🤖'] },
  { label: '🌍 Naturaleza', emojis: ['🌍','🌙','☀️','⭐','🌟','⚡','🌊','🌈','🌺','🌸','🍀','🌴','🏔️','🌋','🌅','☁️','❄️','🔥','💧','🌱'] },
  { label: '🍕 Comida', emojis: ['🍕','☕','🍺','🥤','🎂','🍦','🍎','🍣','🍔','🌮','🥐','🍜','🧃','🫖','🍷','🥃','🧁','🍩','🍫','🥑'] },
  { label: '⚠️ Símbolos', emojis: ['✅','❌','⚠️','❓','❗','💡','🔔','💬','📌','🔑','🔒','🔓','🔍','📣','🚫','⛔','🆕','🆙','🔄','➡️'] },
]

const EMOJIS = EMOJI_CATEGORIES.flatMap(c => c.emojis)

function roleColor(role) {
  if (role === 'admin') return '#2563eb'
  if (role === 'moderator') return '#d97706'
  return '#64748b'
}

/**
 * Calcula luminosidad de un color hex.
 */
function getLuminance(hexColor) {
  const hex = hexColor.replace('#', '')
  const r = parseInt(hex.substr(0, 2), 16) / 255
  const g = parseInt(hex.substr(2, 2), 16) / 255
  const b = parseInt(hex.substr(4, 2), 16) / 255
  // Corrección gamma
  const rs = r <= 0.03928 ? r / 12.92 : Math.pow((r + 0.055) / 1.055, 2.4)
  const gs = g <= 0.03928 ? g / 12.92 : Math.pow((g + 0.055) / 1.055, 2.4)
  const bs = b <= 0.03928 ? b / 12.92 : Math.pow((b + 0.055) / 1.055, 2.4)
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs
}

function isLightColor(hexColor) {
  return getLuminance(hexColor) > 0.5
}

/**
 * Genera paleta adaptativa completa basada en el fondo.
 * GARANTIZA visibilidad en fondos claros.
 */
function getAdaptiveColors(bgColor, userFontColor, userOpacity = null) {
  const light = isLightColor(bgColor)
  
  // Opacidad base: en claros usamos valores más altos para que se note
  const baseOpacity = userOpacity !== null ? userOpacity : (light ? 0.15 : 0.08)
  const surfaceOpacity = light ? 0.6 : 0.25
  const hoverOpacity = light ? 0.85 : 0.12
  
  // Texto: si el usuario eligió uno, lo respetamos. Si no, auto.
  let text = userFontColor
  if (!text || text === '#e2e8f0') {
    text = light ? '#0f172a' : '#f8fafc'
  }
  
  // Si el texto elegido por el usuario no contrasta con el fondo, forzamos auto
  const textLum = getLuminance(text)
  const bgLum = getLuminance(bgColor)
  if (Math.abs(textLum - bgLum) < 0.3) {
    text = light ? '#0f172a' : '#f8fafc'
  }

  return {
    text,
    textMuted: light ? '#475569' : '#94a3b8',
    textInverse: light ? '#f8fafc' : '#0f172a',
    border: light 
      ? `rgba(15, 23, 42, ${Math.max(baseOpacity, 0.2)})`  // Bordes oscuros y VISIBLES
      : `rgba(248, 250, 252, ${baseOpacity})`,
    borderStrong: light 
      ? `rgba(15, 23, 42, 0.35)` 
      : `rgba(248, 250, 252, 0.25)`,
    surface: light 
      ? `rgba(255, 255, 255, ${surfaceOpacity})`  // Superficie blanca semitransparente
      : `rgba(0, 0, 0, ${surfaceOpacity})`,
    surfaceHover: light 
      ? `rgba(255, 255, 255, ${hoverOpacity})`
      : `rgba(255, 255, 255, ${hoverOpacity})`,
    surfaceActive: light
      ? 'rgba(255, 255, 255, 0.95)'
      : 'rgba(255, 255, 255, 0.15)',
    inputBg: light
      ? 'rgba(15, 23, 42, 0.06)'
      : 'rgba(248, 250, 252, 0.08)',
    inputBorder: light
      ? 'rgba(15, 23, 42, 0.25)'
      : 'rgba(248, 250, 252, 0.15)',
    placeholder: light
      ? 'rgba(15, 23, 42, 0.45)'
      : 'rgba(248, 250, 252, 0.45)',
    shapeColor: light
      ? `rgba(15, 23, 42, ${Math.max(baseOpacity, 0.1)})`
      : `rgba(248, 250, 252, ${baseOpacity})`,
    shadow: light
      ? '0 1px 3px rgba(15, 23, 42, 0.1), 0 1px 2px rgba(15, 23, 42, 0.06)'
      : '0 1px 3px rgba(0, 0, 0, 0.3), 0 1px 2px rgba(0, 0, 0, 0.2)',
    isLight: light,
  }
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
  const [mentions, setMentions]       = useState([])
  const mentionPollRef                = useRef(null)
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
    opacity:    user?.chat_opacity     || null, // Nuevo: control de opacidad fino
  }

  // Calcular colores adaptativos
  const adaptive = getAdaptiveColors(prefs.bgColor, prefs.fontColor, prefs.opacity)
  
  // Construir background-image con shapeColor correcto
  const shapeColor = adaptive.shapeColor
  const bgShapeStyle = BG_SHAPES[prefs.bgShape]
    ?.replace(/var\(--shape-color\)/g, shapeColor)
    ?.replace(/rgba\([^)]+\)/g, (match) => {
      // Reemplazar cualquier rgba hardcodeado por el adaptativo
      return shapeColor
    }) || 'none'

  useEffect(() => {
    loadRooms()
    loadMentions()
    if (isAdmin) {
      usersService.list().then(r => setAllUsers(r.data || [])).catch(() => {})
    }
    mentionPollRef.current = setInterval(loadMentions, 10000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (mentionPollRef.current) clearInterval(mentionPollRef.current)
    }
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

  const loadMentions = async () => {
    try {
      const { data } = await chatService.listMentions()
      setMentions(Array.isArray(data) ? data : [])
    } catch {}
  }

  const markRoomMentionsRead = async (roomId) => {
    try {
      await chatService.markRoomMentionsRead(roomId)
      setMentions(prev => prev.filter(m => m.room_id !== roomId))
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

  // Estilos base del contenedor principal
  const bgStyle = {
    backgroundColor: prefs.bgColor,
    backgroundImage: bgShapeStyle,
    backgroundSize: prefs.bgShape === 'dots' ? '20px 20px' : prefs.bgShape === 'waves' ? '100px 20px' : 'auto',
    fontFamily: FONTS.find(f => f.label === prefs.fontFamily)?.value || prefs.fontFamily,
    fontSize: `${prefs.fontSize}px`,
    color: adaptive.text,
  }

  const insertEmoji = (emoji) => { setInput(prev => prev + emoji); setShowEmojis(false) }
  const isMe = (msg) => msg.user_id === user?.id

  return (
    <div className="flex h-[calc(100vh-4rem)] -mx-6 -my-6" style={bgStyle}>
      {/* ─── SIDEBAR SALAS ─── */}
      <div 
        className="w-64 flex flex-col shrink-0"
        style={{ 
          backgroundColor: adaptive.surface,
          borderRight: `1px solid ${adaptive.borderStrong}`,
          boxShadow: adaptive.isLight ? adaptive.shadow : 'none',
        }}
      >
        {/* Header sidebar */}
        <div 
          className="p-4 flex items-center justify-between shrink-0"
          style={{ 
            borderBottom: `1px solid ${adaptive.borderStrong}`,
            backgroundColor: adaptive.isLight ? 'rgba(255,255,255,0.4)' : 'transparent',
          }}
        >
          <h2 className="font-semibold flex items-center gap-2" style={{ color: adaptive.text }}>
            <MessageSquare size={18} /> Chat
          </h2>
          {canManageChannels && (
            <button 
              onClick={() => setShowNewRoom(true)} 
              className="p-1.5 rounded-md transition-all"
              style={{ color: adaptive.textMuted }}
              onMouseEnter={e => {
                e.currentTarget.style.backgroundColor = adaptive.surfaceHover
                e.currentTarget.style.color = adaptive.text
              }}
              onMouseLeave={e => {
                e.currentTarget.style.backgroundColor = 'transparent'
                e.currentTarget.style.color = adaptive.textMuted
              }}
              title="Nuevo canal"
            >
              <Plus size={16} />
            </button>
          )}
        </div>

        {/* Lista de salas */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {rooms.map(room => (
            <div
              key={room.id}
              onClick={() => {
                setActiveRoom(room)
                markRoomMentionsRead(room.id)
              }}
              className="p-3 rounded-lg cursor-pointer flex items-center justify-between group transition-all"
              style={{
                backgroundColor: activeRoom?.id === room.id ? adaptive.surfaceActive : 'transparent',
                border: activeRoom?.id === room.id ? `1px solid ${adaptive.borderStrong}` : '1px solid transparent',
              }}
              onMouseEnter={e => {
                if (activeRoom?.id !== room.id) {
                  e.currentTarget.style.backgroundColor = adaptive.surfaceHover
                  e.currentTarget.style.border = `1px solid ${adaptive.border}`
                }
              }}
              onMouseLeave={e => {
                if (activeRoom?.id !== room.id) {
                  e.currentTarget.style.backgroundColor = 'transparent'
                  e.currentTarget.style.border = '1px solid transparent'
                }
              }}
            >
              <div className="min-w-0 flex items-center gap-2">
                {room.is_private && <Lock size={12} className="shrink-0" style={{ color: '#d97706' }} />}
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <p className="text-sm font-medium truncate" style={{ color: adaptive.text }}>{room.name}</p>
                    {mentions.some(m => m.room_id === room.id) && (
                      <span className="shrink-0 w-4 h-4 bg-blue-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                        @
                      </span>
                    )}
                  </div>
                  <p className="text-xs truncate" style={{ color: adaptive.textMuted }}>{room.description || 'Sin descripción'}</p>
                </div>
              </div>
              {canManageChannels && (
                <button
                  onClick={(e) => { e.stopPropagation(); deleteRoom(room.id) }}
                  className="opacity-0 group-hover:opacity-100 p-1 transition-all shrink-0 rounded"
                  style={{ color: adaptive.textMuted }}
                  onMouseEnter={e => {
                    e.currentTarget.style.color = '#dc2626'
                    e.currentTarget.style.backgroundColor = adaptive.isLight ? 'rgba(220, 38, 38, 0.1)' : 'rgba(220, 38, 38, 0.2)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.color = adaptive.textMuted
                    e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
          {rooms.length === 0 && (
            <p className="text-sm text-center py-8" style={{ color: adaptive.textMuted }}>
              {canManageChannels ? 'No hay canales. Crea uno.' : 'No hay canales disponibles.'}
            </p>
          )}
        </div>
      </div>

      {/* ─── ÁREA PRINCIPAL ─── */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeRoom ? (
          <>
            {/* Header del canal */}
            <div 
              className="p-4 flex items-center justify-between shrink-0"
              style={{ 
                backgroundColor: adaptive.isLight ? 'rgba(255,255,255,0.5)' : adaptive.surface,
                borderBottom: `1px solid ${adaptive.borderStrong}`,
                backdropFilter: 'blur(8px)',
              }}
            >
              <div className="flex items-center gap-2">
                {activeRoom.is_private && <Lock size={14} style={{ color: '#d97706' }} />}
                <div>
                  <h3 className="font-semibold" style={{ color: adaptive.text }}>{activeRoom.name}</h3>
                  <p className="text-xs" style={{ color: adaptive.textMuted }}>{activeRoom.description || `${messages.length} mensajes`}</p>
                </div>
              </div>
              {isAdmin && activeRoom.is_private && (
                <button 
                  onClick={() => setShowMembers(!showMembers)} 
                  title="Gestionar miembros" 
                  className="p-1.5 rounded-md transition-all"
                  style={{ color: adaptive.textMuted }}
                  onMouseEnter={e => {
                    e.currentTarget.style.backgroundColor = adaptive.surfaceHover
                    e.currentTarget.style.color = adaptive.text
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.backgroundColor = 'transparent'
                    e.currentTarget.style.color = adaptive.textMuted
                  }}
                >
                  <Users size={16} />
                </button>
              )}
            </div>

            {/* Mensajes */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map(msg => (
                <div key={msg.id} className={`flex ${isMe(msg) ? 'justify-end' : 'justify-start'}`}>
                  <div 
                    className={`max-w-[75%] rounded-2xl px-4 py-2.5 ${
                      isMe(msg) ? 'rounded-br-md' : 'rounded-bl-md'
                    }`}
                    style={{
                      backgroundColor: isMe(msg) ? '#2563eb' : adaptive.surface,
                      color: isMe(msg) ? '#ffffff' : adaptive.text,
                      border: isMe(msg) ? 'none' : `1px solid ${adaptive.border}`,
                      boxShadow: adaptive.isLight && !isMe(msg) ? adaptive.shadow : 'none',
                    }}
                  >
                    {!isMe(msg) && (
                      <p className="text-xs font-bold mb-1" style={{ color: roleColor(msg.role) }}>
                        {msg.username}
                      </p>
                    )}
                    {msg.content.startsWith('![GIF]') ? (
                      <img src={msg.content.match(/\((.*)\)/)?.[1]} alt="GIF" className="rounded-lg max-h-40 mt-1" />
                    ) : (
                      <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    )}
                    <p 
                      className="text-[10px] mt-1.5 font-medium" 
                      style={{ color: isMe(msg) ? 'rgba(255,255,255,0.75)' : adaptive.textMuted }}
                    >
                      {new Date(msg.created_at).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div 
              className="p-3 shrink-0"
              style={{ 
                backgroundColor: adaptive.isLight ? 'rgba(255,255,255,0.7)' : adaptive.surface,
                borderTop: `1px solid ${adaptive.borderStrong}`,
                backdropFilter: 'blur(8px)',
              }}
            >
              <div className="flex gap-2 items-center">
                <button 
                  onClick={() => setShowGifs(!showGifs)} 
                  className="p-2.5 rounded-xl transition-all shrink-0"
                  style={{ 
                    backgroundColor: adaptive.inputBg, 
                    color: adaptive.textMuted,
                    border: `1px solid ${adaptive.inputBorder}`,
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.backgroundColor = adaptive.surfaceHover
                    e.currentTarget.style.color = adaptive.text
                    e.currentTarget.style.borderColor = adaptive.borderStrong
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.backgroundColor = adaptive.inputBg
                    e.currentTarget.style.color = adaptive.textMuted
                    e.currentTarget.style.borderColor = adaptive.inputBorder
                  }}
                >
                  <Image size={18} />
                </button>
                <button 
                  onClick={() => { setShowEmojis(!showEmojis); setShowGifs(false) }} 
                  className="p-2.5 rounded-xl transition-all shrink-0"
                  style={{ 
                    backgroundColor: adaptive.inputBg, 
                    color: adaptive.textMuted,
                    border: `1px solid ${adaptive.inputBorder}`,
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.backgroundColor = adaptive.surfaceHover
                    e.currentTarget.style.color = adaptive.text
                    e.currentTarget.style.borderColor = adaptive.borderStrong
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.backgroundColor = adaptive.inputBg
                    e.currentTarget.style.color = adaptive.textMuted
                    e.currentTarget.style.borderColor = adaptive.inputBorder
                  }}
                >
                  <Smile size={18} />
                </button>
                <input
                  type="text"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && send(input)}
                  placeholder="Escribe un mensaje..."
                  className="flex-1 px-4 py-2.5 rounded-xl focus:outline-none transition-all"
                  style={{
                    backgroundColor: adaptive.isLight ? '#ffffff' : adaptive.inputBg,
                    color: adaptive.text,
                    border: `1px solid ${adaptive.inputBorder}`,
                    boxShadow: adaptive.isLight ? 'inset 0 1px 2px rgba(15, 23, 42, 0.05)' : 'none',
                  }}
                />
                <button 
                  onClick={() => send(input)} 
                  disabled={loading || !input.trim()} 
                  className="p-2.5 rounded-xl transition-all shrink-0 disabled:opacity-40"
                  style={{ 
                    backgroundColor: '#2563eb', 
                    color: '#ffffff',
                    boxShadow: '0 2px 4px rgba(37, 99, 235, 0.3)',
                  }}
                  onMouseEnter={e => {
                    if (!loading && input.trim()) {
                      e.currentTarget.style.backgroundColor = '#1d4ed8'
                      e.currentTarget.style.transform = 'scale(1.05)'
                    }
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.backgroundColor = '#2563eb'
                    e.currentTarget.style.transform = 'scale(1)'
                  }}
                >
                  <Send size={18} />
                </button>
              </div>

              {/* Panel Emojis */}
              {showEmojis && (
                <div
                  className="mt-3 p-3 rounded-xl border shadow-lg max-h-64 overflow-y-auto"
                  style={{
                    backgroundColor: adaptive.isLight ? '#ffffff' : adaptive.surface,
                    borderColor: adaptive.borderStrong,
                    boxShadow: adaptive.isLight ? '0 4px 20px rgba(15, 23, 42, 0.15)' : '0 4px 20px rgba(0, 0, 0, 0.4)',
                  }}
                >
                  {EMOJI_CATEGORIES.map(cat => (
                    <div key={cat.label} className="mb-3 last:mb-0">
                      <p className="text-[10px] font-semibold mb-1.5 uppercase tracking-wider" style={{ color: adaptive.textMuted }}>
                        {cat.label}
                      </p>
                      <div className="flex flex-wrap gap-0.5">
                        {cat.emojis.map(emoji => (
                          <button
                            key={emoji}
                            type="button"
                            onClick={() => insertEmoji(emoji)}
                            className="text-xl hover:scale-125 transition-transform p-1 rounded-lg"
                            onMouseEnter={e => { e.currentTarget.style.backgroundColor = adaptive.surfaceHover }}
                            onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent' }}
                          >
                            {emoji}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Panel GIFs */}
              {showGifs && (
                <div 
                  className="mt-3 p-3 rounded-xl border shadow-lg"
                  style={{ 
                    backgroundColor: adaptive.isLight ? '#ffffff' : adaptive.surface,
                    borderColor: adaptive.borderStrong,
                    boxShadow: adaptive.isLight ? '0 4px 20px rgba(15, 23, 42, 0.15)' : '0 4px 20px rgba(0, 0, 0, 0.4)',
                  }}
                >
                  <div className="flex gap-2 mb-2">
                    <input 
                      type="text" 
                      value={gifQuery} 
                      onChange={e => setGifQuery(e.target.value)} 
                      onKeyDown={e => e.key === 'Enter' && searchGifs()}
                      placeholder="Buscar GIFs..." 
                      className="flex-1 px-3 py-2 rounded-lg text-sm focus:outline-none transition-all"
                      style={{
                        backgroundColor: adaptive.inputBg,
                        color: adaptive.text,
                        border: `1px solid ${adaptive.inputBorder}`,
                      }}
                    />
                    <button 
                      onClick={searchGifs} 
                      className="px-4 py-2 rounded-lg text-white text-sm font-medium transition-all"
                      style={{ backgroundColor: '#2563eb' }}
                    >
                      {gifLoading ? '...' : 'Buscar'}
                    </button>
                    <button 
                      onClick={() => setShowGifs(false)} 
                      className="p-2 rounded-lg transition-all shrink-0"
                      style={{ color: adaptive.textMuted }}
                      onMouseEnter={e => {
                        e.currentTarget.style.backgroundColor = adaptive.surfaceHover
                        e.currentTarget.style.color = adaptive.text
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.backgroundColor = 'transparent'
                        e.currentTarget.style.color = adaptive.textMuted
                      }}
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {gifs.map(g => (
                      <img 
                        key={g.id} 
                        src={g.preview} 
                        alt={g.title} 
                        onClick={() => sendGif(g.url)} 
                        className="h-24 rounded-lg cursor-pointer hover:ring-2 shrink-0 transition-all hover:scale-105" 
                        style={{ 
                          border: `1px solid ${adaptive.border}`,
                          '--tw-ring-color': '#2563eb',
                        }}
                      />
                    ))}
                    {gifs.length === 0 && !gifLoading && (
                      <p className="text-xs py-2" style={{ color: adaptive.textMuted }}>
                        Busca algo para ver GIFs
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          /* Estado vacío */
          <div className="flex-1 flex items-center justify-center">
            <div 
              className="text-center p-8 rounded-2xl"
              style={{
                backgroundColor: adaptive.surface,
                border: `1px solid ${adaptive.border}`,
                boxShadow: adaptive.shadow,
              }}
            >
              <MessageSquare size={48} className="mx-auto mb-4" style={{ color: adaptive.textMuted }} />
              <p className="font-medium mb-1" style={{ color: adaptive.textMuted }}>
                Selecciona un canal
              </p>
              <p className="text-sm" style={{ color: adaptive.textMuted }}>
                {canManageChannels ? 'Crea uno nuevo para empezar' : 'Espera a que haya canales disponibles'}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* ─── MODAL NUEVA SALA ─── */}
      {showNewRoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div 
            className="rounded-2xl w-full max-w-sm p-6 space-y-4 mx-4 shadow-2xl"
            style={{ 
              backgroundColor: adaptive.isLight ? '#ffffff' : prefs.bgColor,
              border: `1px solid ${adaptive.borderStrong}`,
              color: adaptive.text,
            }}
          >
            <h3 className="font-semibold text-lg">Nuevo canal de chat</h3>
            <form onSubmit={createRoom} className="space-y-4">
              <div>
                <label className="block text-sm mb-1.5 font-medium" style={{ color: adaptive.textMuted }}>Nombre</label>
                <input 
                  type="text" 
                  value={newRoomName} 
                  onChange={e => setNewRoomName(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg focus:outline-none transition-all"
                  style={{
                    backgroundColor: adaptive.inputBg,
                    color: adaptive.text,
                    border: `1px solid ${adaptive.inputBorder}`,
                  }}
                  required 
                  autoFocus 
                />
              </div>
              <div>
                <label className="block text-sm mb-1.5 font-medium" style={{ color: adaptive.textMuted }}>Descripción (opcional)</label>
                <input 
                  type="text" 
                  value={newRoomDesc} 
                  onChange={e => setNewRoomDesc(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg focus:outline-none transition-all"
                  style={{
                    backgroundColor: adaptive.inputBg,
                    color: adaptive.text,
                    border: `1px solid ${adaptive.inputBorder}`,
                  }}
                />
              </div>

              {isAdmin && (
                <label 
                  className="flex items-center gap-3 cursor-pointer py-2 px-3 rounded-lg transition-all"
                  style={{
                    backgroundColor: adaptive.inputBg,
                    border: `1px solid ${adaptive.inputBorder}`,
                  }}
                >
                  <div
                    onClick={() => { setNewRoomPrivate(p => !p); setSelectedMembers([]) }}
                    className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer shrink-0 ${newRoomPrivate ? 'bg-amber-500' : 'bg-gray-400/40'}`}
                  >
                    <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${newRoomPrivate ? 'translate-x-5' : 'translate-x-0.5'}`} />
                  </div>
                  <span className="text-sm flex items-center gap-1.5 font-medium" style={{ color: adaptive.text }}>
                    <Lock size={12} className={newRoomPrivate ? 'text-amber-500' : ''} style={!newRoomPrivate ? { color: adaptive.textMuted } : {}} />
                    Canal privado
                  </span>
                </label>
              )}

              {isAdmin && newRoomPrivate && allUsers.length > 0 && (
                <div>
                  <label className="block text-sm mb-2 font-medium" style={{ color: adaptive.textMuted }}>Añadir miembros</label>
                  <div 
                    className="max-h-36 overflow-y-auto space-y-1 pr-1 rounded-lg border p-2"
                    style={{ 
                      borderColor: adaptive.border,
                      backgroundColor: adaptive.inputBg,
                    }}
                  >
                    {allUsers.filter(u => u.id !== user?.id).map(u => (
                      <label 
                        key={u.id} 
                        className="flex items-center gap-2 p-2 rounded-md cursor-pointer transition-all"
                        style={{ color: adaptive.text }}
                        onMouseEnter={e => e.currentTarget.style.backgroundColor = adaptive.surfaceHover}
                        onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
                      >
                        <input
                          type="checkbox"
                          checked={selectedMembers.includes(u.id)}
                          onChange={() => toggleMember(u.id)}
                          className="w-4 h-4 rounded"
                        />
                        <span className="text-sm font-medium">{u.username}</span>
                        <span className="text-xs ml-auto px-2 py-0.5 rounded-full" style={{ 
                          color: adaptive.textMuted,
                          backgroundColor: adaptive.surfaceHover,
                        }}>{u.role}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button 
                  type="submit" 
                  className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all"
                  style={{ 
                    backgroundColor: '#2563eb',
                    boxShadow: '0 2px 8px rgba(37, 99, 235, 0.3)',
                  }}
                >
                  Crear canal
                </button>
                <button 
                  type="button" 
                  onClick={() => { setShowNewRoom(false); setNewRoomPrivate(false); setSelectedMembers([]) }} 
                  className="px-4 py-2.5 rounded-xl text-sm font-medium transition-all"
                  style={{ 
                    color: adaptive.text, 
                    backgroundColor: adaptive.inputBg,
                    border: `1px solid ${adaptive.inputBorder}`,
                  }}
                >
                  Cancelar
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}