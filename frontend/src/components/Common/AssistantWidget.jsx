import { useState, useRef, useEffect } from 'react'
import { MessageCircle, X, Send, Bot } from 'lucide-react'
import api from '@/services/api'

const WELCOME = '¡Hola! Soy el asistente de la plataforma. Puedo ayudarte con dudas sobre bots, el scanner de IA, el chart, paper trading y más. ¿En qué puedo ayudarte?'

export default function AssistantWidget() {
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    if (open && history.length === 0) {
      setHistory([{ role: 'assistant', content: WELCOME }])
    }
    if (open) {
      setTimeout(() => textareaRef.current?.focus(), 100)
    }
  }, [open])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, loading])

  async function send() {
    const msg = input.trim()
    if (!msg || loading) return

    const next = [...history, { role: 'user', content: msg }]
    setHistory(next)
    setInput('')
    setLoading(true)

    try {
      const { data } = await api.post('/assistant/message', {
        message: msg,
        history: next.slice(-8),
      })
      setHistory(h => [...h, { role: 'assistant', content: data.reply }])
    } catch {
      setHistory(h => [...h, { role: 'assistant', content: 'Error al conectar con el asistente. Inténtalo de nuevo.' }])
    } finally {
      setLoading(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="fixed bottom-20 right-4 md:bottom-6 md:right-6 z-50 flex flex-col items-end gap-2">
      {open && (
        <div className="w-80 sm:w-96 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden" style={{ height: '440px' }}>

          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-indigo-600 text-white flex-shrink-0">
            <div className="flex items-center gap-2">
              <Bot size={18} />
              <span className="font-semibold text-sm">Asistente de la plataforma</span>
            </div>
            <button onClick={() => setOpen(false)} className="hover:opacity-75 transition-opacity">
              <X size={16} />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {history.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                  m.role === 'user'
                    ? 'bg-indigo-600 text-white rounded-br-sm'
                    : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-bl-sm'
                }`}>
                  {m.content}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 dark:bg-gray-800 px-4 py-3 rounded-2xl rounded-bl-sm">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </span>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-gray-200 dark:border-gray-700 flex gap-2 flex-shrink-0">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Escribe tu pregunta... (Enter para enviar)"
              rows={1}
              className="flex-1 resize-none text-sm px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            <button
              onClick={send}
              disabled={!input.trim() || loading}
              className="p-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Floating button */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-12 h-12 bg-indigo-600 hover:bg-indigo-700 text-white rounded-full shadow-xl flex items-center justify-center transition-all hover:scale-105 active:scale-95"
        title="Asistente de la plataforma"
      >
        {open ? <X size={20} /> : <MessageCircle size={20} />}
      </button>
    </div>
  )
}
