import { useEffect, useRef, useState } from 'react'
import { Bot, RefreshCw, Send, Sparkles, X } from 'lucide-react'
import { cn } from '@/utils/cn'
import api from '@/services/api'

const SUGGESTIONS = [
  '¿Por qué el deployment gate está en este estado?',
  '¿Cuáles son los problemas críticos ahora?',
  '¿Qué debo hacer para reactivar bots reales?',
  'Resume la salud del modelo.',
]

function getApiUrl() {
  return import.meta.env.VITE_API_URL || ''
}

async function* sseStream(url) {
  const token = localStorage.getItem('access_token')
  const response = await fetch(`${getApiUrl()}${url}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      Accept: 'text/event-stream',
    },
  })

  if (!response.ok) {
    const text = await response.text().catch(() => 'Error desconocido')
    throw new Error(`HTTP ${response.status}: ${text}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    let event = null
    let data = null
    for (const line of lines) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        data = line.slice(5).trim()
      } else if (line.trim() === '' && event != null) {
        try {
          yield { event, data: data ? JSON.parse(data) : {} }
        } catch {
          yield { event, data: { raw: data } }
        }
        event = null
        data = null
      }
    }
  }
}

export default function EngineAIHelper({ page = 'ai' }) {
  const [open, setOpen] = useState(false)
  const [summary, setSummary] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [phase, setPhase] = useState(null)
  const [streamedText, setStreamedText] = useState('')
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState([])
  const [answerText, setAnswerText] = useState('')
  const [loadingAnswer, setLoadingAnswer] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => {
    if (open) {
      loadSummary()
      setTimeout(() => textareaRef.current?.focus(), 100)
    }
    return () => {
      abortRef.current?.abort()
    }
  }, [open])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, streamedText, answerText])

  async function loadSummary() {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoadingSummary(true)
    setError('')
    setSummary(null)
    setMetrics(null)
    setStreamedText('')
    setPhase(null)

    try {
      for await (const { event, data } of sseStream('/ai/engine-summary/stream')) {
        if (controller.signal.aborted) break
        if (event === 'phase') {
          setPhase(data)
        } else if (event === 'metrics') {
          setMetrics(data.metrics)
        } else if (event === 'token') {
          setStreamedText(t => t + (data.content || ''))
        } else if (event === 'summary') {
          setSummary(data)
          setStreamedText('')
          setPhase(null)
          setLoadingSummary(false)
        } else if (event === 'error') {
          setError(data.message || 'Error generando el resumen.')
          setLoadingSummary(false)
        }
      }
    } catch (e) {
      setError(e.message || 'Error de conexión con el asistente.')
    } finally {
      setLoadingSummary(false)
    }
  }

  async function sendQuestion(q) {
    const text = (q ?? question).trim()
    if (!text || loadingAnswer) return

    setQuestion('')
    setHistory(h => [...h, { role: 'user', content: text }])
    setLoadingAnswer(true)
    setAnswerText('')
    setError('')

    try {
      for await (const { event, data } of sseStream(`/assistant/explain/stream?question=${encodeURIComponent(text)}`)) {
        if (event === 'phase') {
          setPhase(data)
        } else if (event === 'metrics') {
          setMetrics(data.metrics)
        } else if (event === 'token') {
          setAnswerText(t => t + (data.content || ''))
        } else if (event === 'answer') {
          setHistory(h => [...h, { role: 'assistant', content: data.answer, model: data.model_used }])
          setAnswerText('')
          setPhase(null)
          setLoadingAnswer(false)
        } else if (event === 'error') {
          setHistory(h => [...h, { role: 'assistant', content: data.message || 'Error al responder.' }])
          setLoadingAnswer(false)
        }
      }
    } catch (e) {
      setHistory(h => [...h, { role: 'assistant', content: e.message || 'Error de conexión.' }])
    } finally {
      setLoadingAnswer(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendQuestion()
    }
  }

  const gateState = metrics?.deployment_gate?.state || summary?.metrics?.deployment_gate?.state || 'unknown'
  const statusColor =
    gateState === 'HEALTHY'
      ? 'bg-emerald-600 hover:bg-emerald-700'
      : gateState === 'DEGRADED'
        ? 'bg-amber-600 hover:bg-amber-700'
        : gateState === 'PAUSED'
          ? 'bg-red-600 hover:bg-red-700'
          : 'bg-indigo-600 hover:bg-indigo-700'

  const currentSummary = summary || {}
  const currentMetrics = metrics || summary?.metrics || {}

  return (
    <div className="fixed bottom-20 left-4 md:bottom-6 md:left-6 z-50 flex flex-col items-start gap-2">
      {open && (
        <div className="w-80 sm:w-[28rem] bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden" style={{ height: '560px' }}>
          {/* Header */}
          <div className={cn('flex items-center justify-between px-4 py-3 text-white flex-shrink-0', statusColor)}>
            <div className="flex items-center gap-2">
              <Sparkles size={18} />
              <span className="font-semibold text-sm">Asistente del motor IA</span>
            </div>
            <div className="flex items-center gap-1">
              <button onClick={loadSummary} disabled={loadingSummary} className="p-1.5 hover:bg-white/20 rounded-lg transition-colors" title="Regenerar resumen">
                <RefreshCw size={14} className={cn(loadingSummary && 'animate-spin')} />
              </button>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-white/20 rounded-lg transition-colors">
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {error && (
              <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-3 text-xs text-red-700 dark:text-red-300">
                {error}
              </div>
            )}

            {/* Phase indicator */}
            {phase && (
              <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-gray-400">
                <RefreshCw size={12} className="animate-spin" />
                {phase.message}
              </div>
            )}

            {/* Summary card */}
            {!summary && !streamedText && loadingSummary && !phase && (
              <div className="flex items-center justify-center py-8 text-sm text-slate-500">
                <RefreshCw size={16} className="animate-spin mr-2" /> Iniciando asistente...
              </div>
            )}

            {streamedText && (
              <div className="rounded-xl border border-indigo-200 dark:border-indigo-900/40 bg-indigo-50 dark:bg-indigo-900/20 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Bot size={14} className="text-indigo-600 dark:text-indigo-400" />
                  <span className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wide">Generando resumen...</span>
                </div>
                <p className="text-sm text-indigo-900 dark:text-indigo-100 leading-relaxed whitespace-pre-wrap">
                  {streamedText}
                  <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-indigo-600 animate-pulse" />
                </p>
              </div>
            )}

            {currentSummary.summary && (
              <div className="space-y-3">
                <div className="rounded-xl border border-slate-200 dark:border-gray-700 bg-slate-50 dark:bg-gray-800/50 p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Bot size={14} className="text-indigo-600 dark:text-indigo-400" />
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 uppercase tracking-wide">Resumen ejecutivo</span>
                  </div>
                  <p className="text-sm text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
                    {currentSummary.summary}
                  </p>
                </div>

                {currentSummary.key_issues?.length > 0 && (
                  <div className="rounded-xl border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-900/20 p-3">
                    <span className="text-xs font-semibold text-red-700 dark:text-red-300 uppercase tracking-wide">Problemas clave</span>
                    <ul className="mt-2 space-y-1">
                      {currentSummary.key_issues.map((issue, i) => (
                        <li key={i} className="text-xs text-red-800 dark:text-red-200 flex gap-2">
                          <span>•</span>
                          <span>{issue}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {currentSummary.recommendation && (
                  <div className="rounded-xl border border-emerald-200 dark:border-emerald-900/40 bg-emerald-50 dark:bg-emerald-900/20 p-3">
                    <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300 uppercase tracking-wide">Recomendación</span>
                    <p className="mt-1 text-xs text-emerald-800 dark:text-emerald-200">{currentSummary.recommendation}</p>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg border border-slate-200 dark:border-gray-700 p-2">
                    <span className="text-slate-500 dark:text-gray-400">Gate</span>
                    <div className={cn('font-semibold', gateState === 'HEALTHY' ? 'text-emerald-600' : gateState === 'PAUSED' ? 'text-red-600' : 'text-amber-600')}>
                      {gateState}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-200 dark:border-gray-700 p-2">
                    <span className="text-slate-500 dark:text-gray-400">Modelo</span>
                    <div className="font-semibold text-slate-700 dark:text-slate-200">
                      {currentMetrics.model?.type || '—'} ({currentMetrics.model?.samples || 0} muestras)
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-200 dark:border-gray-700 p-2">
                    <span className="text-slate-500 dark:text-gray-400">AUC</span>
                    <div className="font-semibold text-slate-700 dark:text-slate-200">
                      {currentMetrics.model?.auc != null ? currentMetrics.model.auc.toFixed(4) : '—'}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-200 dark:border-gray-700 p-2">
                    <span className="text-slate-500 dark:text-gray-400">Señales 24h</span>
                    <div className="font-semibold text-slate-700 dark:text-slate-200">
                      {currentMetrics.signals_24h?.total ?? '—'}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Suggestions */}
            {!history.length && !loadingAnswer && !streamedText && (
              <div className="space-y-2">
                <span className="text-xs font-semibold text-slate-500 dark:text-gray-400">Preguntas sugeridas</span>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => sendQuestion(s)}
                      className="text-xs px-2.5 py-1.5 rounded-lg bg-slate-100 dark:bg-gray-800 text-slate-700 dark:text-gray-300 hover:bg-slate-200 dark:hover:bg-gray-700 transition-colors text-left"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Chat history */}
            {history.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={cn(
                    'max-w-[90%] px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap',
                    m.role === 'user'
                      ? 'bg-indigo-600 text-white rounded-br-sm'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-bl-sm'
                  )}
                >
                  {m.content}
                  {m.model && (
                    <div className="mt-1 text-[10px] opacity-60">modelo: {m.model}</div>
                  )}
                </div>
              </div>
            ))}

            {answerText && (
              <div className="flex justify-start">
                <div className="max-w-[90%] px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-bl-sm">
                  {answerText}
                  <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-gray-500 animate-pulse" />
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-gray-200 dark:border-gray-700 flex gap-2 flex-shrink-0">
            <textarea
              ref={textareaRef}
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Pregunta sobre métricas concretas..."
              rows={1}
              className="flex-1 resize-none text-sm px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            <button
              onClick={() => sendQuestion()}
              disabled={!question.trim() || loadingAnswer}
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
        className={cn(
          'w-12 h-12 text-white rounded-full shadow-xl flex items-center justify-center transition-all hover:scale-105 active:scale-95',
          statusColor
        )}
        title="Asistente del motor IA"
      >
        {open ? <X size={20} /> : <Bot size={20} />}
      </button>
    </div>
  )
}
