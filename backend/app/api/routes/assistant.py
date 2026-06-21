"""AI assistant endpoint — answers user questions using local or remote LLM."""
from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from app.api.dependencies import get_current_authorized_user
from app.services import llm_client, local_llm_client
from app.services.knowledge_service import search_knowledge
from app.services.engine_narrator import answer_engine_question, answer_engine_question_stream
from config.settings import settings

router = APIRouter(prefix="/assistant", tags=["assistant"])

_SYSTEM_PROMPT_TEMPLATE = (
    "Eres el asistente de Quantum Trading, una plataforma de trading automatizado de criptomonedas. "
    "Responde siempre en español, con tono amable, profesional y conciso. "
    "INSTRUCCIONES ESTRICTAS:\n"
    "- Basa tu respuesta EXCLUSIVAMENTE en el contexto proporcionado.\n"
    "- Si el contexto no contiene la respuesta, di: 'No tengo información específica sobre eso en la base de conocimiento.'\n"
    "- No inventes pasos, cifras, ejemplos ni datos que no aparezcan en el contexto.\n"
    "- Para saludos o charla informal, responde de forma natural y breve.\n\n"
    "Contexto relevante:\n{context}\n\n"
    "Responde de forma útil y honesta."
)

_UNAVAILABLE = (
    "El asistente de IA no está disponible en este momento. "
    "El administrador debe configurar Ollama (local) o una clave de OpenRouter/Moonshot (remoto)."
)

_ERROR_LOCAL = (
    "No se pudo conectar con el modelo de IA local. "
    "Asegúrate de que Ollama está ejecutándose en el equipo con el modelo cargado."
)

_ERROR_REMOTE = (
    "No se pudo conectar con el modelo de IA remoto. "
    "Verifica la clave de OpenRouter/Moonshot y la conectividad."
)

_ASSISTANT_TEMPERATURE = 0.2
_ASSISTANT_MAX_TOKENS = 350


class Message(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class AssistantRequest(BaseModel):
    message: str
    history: list[Message] = []


class AssistantResponse(BaseModel):
    reply: str


_GREETINGS = {
    "hola", "buenos días", "buenas tardes", "buenas noches", "hey", "saludos",
    "qué tal", "como estás", "cómo estás", "buen día", "hola!", "hey!",
}


def _is_greeting(message: str) -> bool:
    cleaned = message.lower().strip().rstrip("!?.")
    return cleaned in _GREETINGS or any(cleaned.startswith(g) for g in _GREETINGS)


def _greeting_reply() -> str:
    return (
        "¡Hola! Soy el asistente de Quantum Trading. "
        "Puedo ayudarte con dudas sobre bots, el scanner de IA, señales ICT/SMC, "
        "paper trading, el dashboard o cualquier aspecto de la plataforma. "
        "¿En qué puedo ayudarte?"
    )


def _build_system_prompt(question: str) -> str:
    chunks = search_knowledge(question, top_k=5)
    if chunks:
        context = "\n\n".join(
            f"- {chunk.title} ({chunk.source}):\n{chunk.text[:400]}"
            for chunk in chunks
        )
    else:
        context = "No se encontró contexto específico en la base de conocimiento."
    return _SYSTEM_PROMPT_TEMPLATE.format(context=context)


def _use_local_llm() -> bool:
    """Use local Ollama when explicitly enabled and configured."""
    return bool(
        settings.local_llm_enabled
        and settings.assistant_use_local_llm
        and settings.local_llm_url
    )


def _build_messages(question: str, history: list[Message]) -> list[dict]:
    messages = [{"role": "system", "content": _build_system_prompt(question)}]
    for m in history[-3:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": question})
    return messages


@router.post("/message", response_model=AssistantResponse)
async def assistant_message(
    req: AssistantRequest,
    _user=Depends(get_current_authorized_user),
) -> AssistantResponse:
    if _is_greeting(req.message):
        return AssistantResponse(reply=_greeting_reply())

    messages = _build_messages(req.message, req.history)

    if _use_local_llm():
        return await _assistant_message_local(messages)
    return await _assistant_message_remote(messages)


async def _assistant_message_local(messages: list[dict]) -> AssistantResponse:
    local_url = settings.local_llm_url
    model = settings.local_llm_model_assistant
    payload = {
        "model": model,
        "messages": messages,
        "temperature": _ASSISTANT_TEMPERATURE,
        "max_tokens": _ASSISTANT_MAX_TOKENS,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=local_llm_client.DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{local_url}/chat/completions",
                json=payload,
                headers={"Host": "localhost"},
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return AssistantResponse(reply=reply.strip())
    except Exception as exc:
        logger.warning(f"[assistant] local LLM call failed: {exc}")
        return AssistantResponse(reply=_ERROR_LOCAL)


async def _assistant_message_remote(messages: list[dict]) -> AssistantResponse:
    try:
        response = await llm_client.generate_chat_async(
            messages=messages,
            max_tokens=_ASSISTANT_MAX_TOKENS,
            temperature=_ASSISTANT_TEMPERATURE,
        )
        return AssistantResponse(reply=response.content.strip())
    except Exception as exc:
        logger.warning(f"[assistant] remote LLM call failed: {exc}")
        return AssistantResponse(reply=_ERROR_REMOTE)


@router.post("/message/stream")
async def assistant_message_stream(
    req: AssistantRequest,
    _user=Depends(get_current_authorized_user),
):
    """Stream assistant replies via Server-Sent Events."""
    if _is_greeting(req.message):
        async def _greeting_stream():
            for word in _greeting_reply().split():
                yield f"event: message\ndata: {json.dumps({'content': word + ' '})}\n\n"
            yield "event: done\ndata: \n\n"
        return StreamingResponse(_greeting_stream(), media_type="text/event-stream")

    messages = _build_messages(req.message, req.history)

    if _use_local_llm():
        return _assistant_stream_local(messages)
    return _assistant_stream_remote(messages)


def _assistant_stream_local(messages: list[dict]) -> StreamingResponse:
    local_url = settings.local_llm_url
    model = settings.local_llm_model_assistant
    payload = {
        "model": model,
        "messages": messages,
        "temperature": _ASSISTANT_TEMPERATURE,
        "max_tokens": _ASSISTANT_MAX_TOKENS,
        "stream": True,
    }

    async def _generate():
        try:
            async with httpx.AsyncClient(timeout=local_llm_client.DEFAULT_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{local_url}/chat/completions",
                    json=payload,
                    headers={"Host": "localhost"},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            yield "event: done\ndata: \n\n"
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield f"event: message\ndata: {json.dumps({'content': content})}\n\n"
                        except Exception:
                            continue
        except Exception as exc:
            logger.warning(f"[assistant/stream] local LLM call failed: {exc}")
            yield f"event: error\ndata: {json.dumps({'error': _ERROR_LOCAL})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


def _assistant_stream_remote(messages: list[dict]) -> StreamingResponse:
    async def _generate():
        try:
            async for token in llm_client.generate_chat_stream(
                messages=messages,
                max_tokens=_ASSISTANT_MAX_TOKENS,
                temperature=_ASSISTANT_TEMPERATURE,
            ):
                yield f"event: message\ndata: {json.dumps({'content': token})}\n\n"
            yield "event: done\ndata: \n\n"
        except Exception as exc:
            logger.warning(f"[assistant/stream] remote LLM call failed: {exc}")
            yield f"event: error\ndata: {json.dumps({'error': _ERROR_REMOTE})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post("/reload-knowledge")
async def reload_knowledge_endpoint(_user=Depends(get_current_authorized_user)) -> dict:
    """Reload markdown knowledge files without restarting the backend."""
    from app.services.knowledge_service import reload_knowledge
    return reload_knowledge()


class ExplainRequest(BaseModel):
    question: str


@router.post("/explain")
async def explain_engine_metrics(
    req: ExplainRequest,
    _user=Depends(get_current_authorized_user),
) -> dict:
    """Answer a user question about current engine/system metrics.

    Uses live data from the AI dashboard, deployment gate and health checks.
    """
    return await answer_engine_question(req.question)


@router.get("/explain/stream")
async def explain_engine_metrics_stream(
    question: str = Query(..., min_length=1),
    _user=Depends(get_current_authorized_user),
):
    """Stream an answer about current engine/system metrics via SSE.

    Events:
      - phase:metrics
      - metrics
      - phase:llm
      - token
      - answer
      - error
    """
    return StreamingResponse(
        answer_engine_question_stream(question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
