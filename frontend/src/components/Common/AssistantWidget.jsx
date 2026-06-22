import { useState, useRef, useEffect, useCallback } from 'react'
import { MessageCircle, X, Send, Bot, Square, ThumbsUp, ThumbsDown } from 'lucide-react'
import api, { BASE_URL } from '@/services/api'
import useAuthStore from '@/store/authStore'
import { isDeveloper } from '@/constants/roles'

const WELCOME = '¡Hola! Soy el asistente de la plataforma. Puedo ayudarte con dudas sobre bots, el scanner de IA, el chart, paper trading y más. ¿En qué puedo ayudarte?'

function getAccessToken() {
  return localStorage.getItem('access_token')
}

export default function AssistantWidget() {
  const user = useAuthStore(s => s.user)
  if (!isDeveloper(user)) return null

  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [feedbackMap, setFeedbackMap] = useState({})
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const abortRef = useRef(null)

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

  const stopStreaming = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [])

  async function sendFeedback(interactionId, value) {
    if (!interactionId) return
    try {
      await api.post('/assistant/feedback', {
        interaction_id: interactionId,
        feedback: value,
      })
      setFeedbackMap(prev => ({ ...prev, [interactionId]: value }))
    } catch {
      // Silently ignore feedback errors so the UI keeps working.
    }
  }

  async function send() {
    const msg = input.trim()
    if (!msg || loading) return

    const nextHistory = [...history, { role: 'user', content: msg }]
    setHistory(nextHistory)
    setInput('')
    setLoading(true)

    // Placeholder for the assistant reply that will be filled token by token.
    setHistory(h => [...h, { role: 'assistant', content: '' }])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = getAccessToken()
      const response = await fetch(`${BASE_URL}/assistant/message/stream`, {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(token && { Authorization: `Bearer ${token}` }),
        },
        body: JSON.stringify({
          message: msg,
          history: nextHistory.slice(-8),
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''
      let accumulated = ''
      let lastInteractionId = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
            continue
          }

          if (!line.startsWith('data: ')) continue
          const data = line.slice(6)

          if (currentEvent === 'message') {
            try {
              const parsed = JSON.parse(data)
              const chunk = parsed.content || ''
              accumulated += chunk
              setHistory(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  role: 'assistant',
                  content: accumulated,
                  interactionId: lastInteractionId,
                }
                return updated
              })
            } catch {
              // Ignore malformed SSE payloads.
            }
          } else if (currentEvent === 'error') {
            let errorMessage = 'Error al generar la respuesta. Inténtalo de nuevo.'
            try {
              const parsed = JSON.parse(data)
              errorMessage = parsed.error || errorMessage
            } catch {
              // Use default message.
            }
            setHistory(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = {
                role: 'assistant',
                content: errorMessage,
                interactionId: lastInteractionId,
              }
              return updated
            })
          } else if (currentEvent === 'interaction') {
            try {
              const parsed = JSON.parse(data)
              lastInteractionId = parsed.interaction_id || null
              setHistory(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  interactionId: lastInteractionId,
                }
                return updated
              })
            } catch {
              // Ignore malformed interaction payloads.
            }
          } else if (currentEvent === 'done') {
            // Streaming finished; nothing else to append.
          }
        }
      }

      // If nothing was produced, replace empty assistant message with a friendly fallback.
      setHistory(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === 'assistant' && last.content.trim() === '') {
          updated[updated.length - 1] = {
            role: 'assistant',
            content: 'No se pudo generar una respuesta en este momento.',
            interactionId: lastInteractionId,
          }
        }
        return updated
      })
    } catch (err) {
      if (err.name === 'AbortError') {
        setHistory(prev => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last?.role === 'assistant' && last.content.trim() === '') {
            updated[updated.length - 1] = {
              role: 'assistant',
              content: 'Respuesta cancelada.',
            }
          }
          return updated
        })
      } else {
        setHistory(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            role: 'assistant',
            content: 'Error al conectar con el asistente. Inténtalo de nuevo.',
          }
          return updated
        })
      }
    } finally {
      setLoading(false)
      abortRef.current = null
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
                  {m.role === 'assistant' && m.interactionId && (
                    <div className="flex items-center justify-end gap-1 mt-1.5 pt-1 border-t border-gray-200 dark:border-gray-700">
                      <button
                        onClick={() => sendFeedback(m.interactionId, 1)}
                        className={`p-1 rounded transition-colors ${
                          feedbackMap[m.interactionId] === 1
                            ? 'text-emerald-600 bg-emerald-100 dark:bg-emerald-900/30'
                            : 'text-gray-400 hover:text-emerald-600 hover:bg-gray-200 dark:hover:bg-gray-700'
                        }`}
                        title="Respuesta útil"
                      >
                        <ThumbsUp size={12} />
                      </button>
                      <button
                        onClick={() => sendFeedback(m.interactionId, -1)}
                        className={`p-1 rounded transition-colors ${
                          feedbackMap[m.interactionId] === -1
                            ? 'text-red-600 bg-red-100 dark:bg-red-900/30'
                            : 'text-gray-400 hover:text-red-600 hover:bg-gray-200 dark:hover:bg-gray-700'
                        }`}
                        title="Respuesta no útil"
                      >
                        <ThumbsDown size={12} />
                      </button>
                    </div>
                  )}
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
              onClick={loading ? stopStreaming : send}
              disabled={!loading && !input.trim()}
              className="p-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            >
              {loading ? <Square size={16} fill="currentColor" /> : <Send size={16} />}
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
