"""AI assistant endpoint — answers user questions using local or remote LLM.

Persists every interaction so the dataset can be used for analytics and future
fine-tuning. Developer users bypass the phase-1 knowledge restriction.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_authorized_user
from app.models.assistant_interaction import AssistantInteraction
from app.models.user import User
from app.services import llm_client, local_llm_client
from app.services.database import get_db, managed_async_session
from app.services.engine_narrator import (
    answer_engine_question,
    answer_engine_question_stream,
)
from app.services.knowledge_service import search_knowledge
from config.settings import settings

router = APIRouter(prefix="/assistant", tags=["assistant"])

# Knowledge sources enabled for regular users (phase 1).
_PHASE1_ALLOWED_SOURCES = ["phase1_user_guide.md"]

_USER_SYSTEM_PROMPT_TEMPLATE = (
    "Eres el asistente de Quantum Trading, una plataforma de trading automatizado de criptomonedas. "
    "Responde siempre en español, con tono amable, profesional y conciso. "
    "INSTRUCCIONES ESTRICTAS:\n"
    "- Basa tu respuesta EXCLUSIVAMENTE en el contexto proporcionado.\n"
    "- En esta fase el usuario SOLO tiene acceso a estas páginas: Dashboard, Bots, Posiciones, Analytics, "
    "Exchanges, Historial, Manual, Paper, Optimizer DB, Docs y Ajustes.\n"
    "- Si la pregunta es sobre páginas no habilitadas (IA Engine, Scanner Live, Chart, Monte Carlo, Chat, "
    "Administración del Sistema, gestión de usuarios, etc.), responde EXACTAMENTE: "
    "'En esta fase no tengo acceso a información sobre esa funcionalidad. Consulta la documentación disponible en Docs o contacta al administrador.'\n"
    "- Si el contexto no contiene la respuesta, di: 'No tengo información específica sobre eso en la base de conocimiento.'\n"
    "- No inventes pasos, cifras, ejemplos ni datos que no aparezcan en el contexto.\n"
    "- No asumas que funcionalidades no habilitadas están disponibles para el usuario.\n"
    "- Para saludos o charla informal, responde de forma natural y breve.\n\n"
    "Contexto relevante:\n{context}\n\n"
    "Responde de forma útil y honesta."
)

_DEVELOPER_SYSTEM_PROMPT_TEMPLATE = (
    "Eres el asistente técnico de Quantum Trading. El usuario que habla contigo es DESARROLLADOR/SUPER-ADMIN "
    "y tiene acceso completo a toda la plataforma, incluyendo IA Engine, gestión de usuarios, administración del sistema, "
    "Scanner Live, Chart, Monte Carlo, Chat y cualquier funcionalidad interna. "
    "Responde siempre en español, con tono profesional, técnico y conciso.\n"
    "INSTRUCCIONES:\n"
    "- Basa tu respuesta en el contexto proporcionado y en tu conocimiento técnico de la plataforma.\n"
    "- Sé exhaustivo: explica la lógica, los archivos relevantes, los flujos de datos y las decisiones de diseño cuando sea útil.\n"
    "- Si el contexto no contiene la respuesta, indica claramente qué falta y sugiere dónde buscar en el código o la documentación.\n"
    "- No inventes pasos, cifras ni datos que no aparezcan en el contexto; para aspectos técnicos puedes razonar sobre la arquitectura conocida.\n"
    "- Para saludos o charla informal, responde de forma natural y breve.\n\n"
    "Contexto relevante:\n{context}\n\n"
    "Responde de forma útil, técnica y honesta."
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
    interaction_id: uuid.UUID | None = None


class FeedbackRequest(BaseModel):
    interaction_id: uuid.UUID
    feedback: int = Field(..., ge=-1, le=1)  # 1 = helpful, -1 = not helpful, 0 = reset
    comment: str | None = None


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


def _is_developer(user: User) -> bool:
    """Return True for super-developers configured in settings."""
    return user.username in settings.developer_username_set


async def get_current_developer_user(
    user: User = Depends(get_current_authorized_user),
) -> User:
    """Like get_current_authorized_user but restricted to configured developers."""
    if not _is_developer(user):
        raise HTTPException(
            status_code=403,
            detail="Esta funcionalidad del asistente solo está disponible para desarrolladores.",
        )
    return user


def _build_system_prompt(question: str, user: User) -> str:
    if _is_developer(user):
        allowed_sources = None
        template = _DEVELOPER_SYSTEM_PROMPT_TEMPLATE
    else:
        allowed_sources = _PHASE1_ALLOWED_SOURCES
        template = _USER_SYSTEM_PROMPT_TEMPLATE

    chunks = search_knowledge(question, top_k=5, allowed_sources=allowed_sources)
    if chunks:
        context = "\n\n".join(
            f"- {chunk.title} ({chunk.source}):\n{chunk.text[:400]}"
            for chunk in chunks
        )
    else:
        context = "No se encontró contexto específico en la base de conocimiento."
    return template.format(context=context)


def _use_local_llm() -> bool:
    """Use local Ollama when explicitly enabled and configured."""
    return bool(
        settings.local_llm_enabled
        and settings.assistant_use_local_llm
        and settings.local_llm_url
    )


def _build_messages(question: str, history: list[Message], user: User) -> list[dict]:
    messages = [{"role": "system", "content": _build_system_prompt(question, user)}]
    for m in history[-3:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": question})
    return messages


def _source_scope_for_user(user: User) -> str:
    return "developer" if _is_developer(user) else "phase1"


async def _persist_interaction(
    interaction_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    answer: str,
    source_scope: str,
    model_used: str | None,
    was_streamed: bool,
    latency_ms: int | None,
    extra_data: dict | None,
) -> None:
    """Persist an assistant turn in the background (fire-and-forget)."""
    async def _save() -> None:
        try:
            async with managed_async_session(_create_interaction) as _result:
                pass
        except Exception as exc:
            logger.warning(f"[assistant] failed to persist interaction: {exc}")

    async def _create_interaction(session: AsyncSession) -> AssistantInteraction:
        interaction = AssistantInteraction(
            id=interaction_id,
            user_id=user_id,
            question=question,
            answer=answer,
            source_scope=source_scope,
            model_used=model_used,
            was_streamed=was_streamed,
            latency_ms=latency_ms,
            extra_data=extra_data or {},
        )
        session.add(interaction)
        await session.flush()
        return interaction

    # Run without blocking the response to the user.
    asyncio.create_task(_save())


@router.post("/message", response_model=AssistantResponse)
async def assistant_message(
    req: AssistantRequest,
    user: User = Depends(get_current_authorized_user),
) -> AssistantResponse:
    if _is_greeting(req.message):
        return AssistantResponse(reply=_greeting_reply())

    messages = _build_messages(req.message, req.history, user)
    source_scope = _source_scope_for_user(user)
    started_at = time.perf_counter()

    interaction_id = uuid.uuid4()

    if _use_local_llm():
        response = await _assistant_message_local(messages)
        model_used = settings.local_llm_model_assistant
    else:
        response = await _assistant_message_remote(messages)
        model_used = settings.llm_default_model

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    _persist_interaction(
        interaction_id=interaction_id,
        user_id=user.id,
        question=req.message,
        answer=response.reply,
        source_scope=source_scope,
        model_used=model_used,
        was_streamed=False,
        latency_ms=latency_ms,
        extra_data={"messages": messages},
    )
    return AssistantResponse(reply=response.reply, interaction_id=interaction_id)


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
    user: User = Depends(get_current_authorized_user),
):
    """Stream assistant replies via Server-Sent Events."""
    if _is_greeting(req.message):
        async def _greeting_stream():
            for word in _greeting_reply().split():
                yield f"event: message\ndata: {json.dumps({'content': word + ' '})}\n\n"
            yield "event: done\ndata: \n\n"
        return StreamingResponse(_greeting_stream(), media_type="text/event-stream")

    messages = _build_messages(req.message, req.history, user)
    source_scope = _source_scope_for_user(user)
    started_at = time.perf_counter()
    interaction_id = uuid.uuid4()

    if _use_local_llm():
        return _assistant_stream_local(
            messages,
            user_id=user.id,
            question=req.message,
            source_scope=source_scope,
            model_used=settings.local_llm_model_assistant,
            started_at=started_at,
            interaction_id=interaction_id,
        )
    return _assistant_stream_remote(
        messages,
        user_id=user.id,
        question=req.message,
        source_scope=source_scope,
        model_used=settings.llm_default_model,
        started_at=started_at,
        interaction_id=interaction_id,
    )


def _assistant_stream_local(
    messages: list[dict],
    user_id: uuid.UUID,
    question: str,
    source_scope: str,
    model_used: str,
    started_at: float,
    interaction_id: uuid.UUID,
) -> StreamingResponse:
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
        accumulated = ""
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
                                accumulated += content
                                yield f"event: message\ndata: {json.dumps({'content': content})}\n\n"
                        except Exception:
                            continue
        except Exception as exc:
            logger.warning(f"[assistant/stream] local LLM call failed: {exc}")
            yield f"event: error\ndata: {json.dumps({'error': _ERROR_LOCAL})}\n\n"
        finally:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            _persist_interaction(
                interaction_id=interaction_id,
                user_id=user_id,
                question=question,
                answer=accumulated,
                source_scope=source_scope,
                model_used=model_used,
                was_streamed=True,
                latency_ms=latency_ms,
                extra_data={"messages": messages},
            )
            yield f"event: interaction\ndata: {json.dumps({'interaction_id': str(interaction_id)})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


def _assistant_stream_remote(
    messages: list[dict],
    user_id: uuid.UUID,
    question: str,
    source_scope: str,
    model_used: str,
    started_at: float,
    interaction_id: uuid.UUID,
) -> StreamingResponse:
    async def _generate():
        accumulated = ""
        try:
            async for token in llm_client.generate_chat_stream(
                messages=messages,
                max_tokens=_ASSISTANT_MAX_TOKENS,
                temperature=_ASSISTANT_TEMPERATURE,
            ):
                accumulated += token
                yield f"event: message\ndata: {json.dumps({'content': token})}\n\n"
            yield "event: done\ndata: \n\n"
        except Exception as exc:
            logger.warning(f"[assistant/stream] remote LLM call failed: {exc}")
            yield f"event: error\ndata: {json.dumps({'error': _ERROR_REMOTE})}\n\n"
        finally:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            _persist_interaction(
                interaction_id=interaction_id,
                user_id=user_id,
                question=question,
                answer=accumulated,
                source_scope=source_scope,
                model_used=model_used,
                was_streamed=True,
                latency_ms=latency_ms,
                extra_data={"messages": messages},
            )
            yield f"event: interaction\ndata: {json.dumps({'interaction_id': str(interaction_id)})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post("/reload-knowledge")
async def reload_knowledge_endpoint(
    _dev: User = Depends(get_current_developer_user),
) -> dict:
    """Reload markdown knowledge files without restarting the backend."""
    from app.services.knowledge_service import reload_knowledge
    return reload_knowledge()


class ExplainRequest(BaseModel):
    question: str


@router.post("/explain")
async def explain_engine_metrics(
    req: ExplainRequest,
    _dev: User = Depends(get_current_developer_user),
) -> dict:
    """Answer a developer question about current engine/system metrics.

    Uses live data from the AI dashboard, deployment gate and health checks.
    """
    return await answer_engine_question(req.question)


@router.get("/explain/stream")
async def explain_engine_metrics_stream(
    question: str = Query(..., min_length=1),
    _dev: User = Depends(get_current_developer_user),
):
    """Stream an answer about current engine/system metrics via SSE (developer only).

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


@router.post("/feedback")
async def assistant_feedback(
    req: FeedbackRequest,
    user: User = Depends(get_current_authorized_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record user feedback for a previous assistant interaction."""
    from sqlalchemy import select

    result = await db.execute(
        select(AssistantInteraction).where(
            AssistantInteraction.id == req.interaction_id,
            AssistantInteraction.user_id == user.id,
        )
    )
    interaction = result.scalar_one_or_none()
    if not interaction:
        raise HTTPException(status_code=404, detail="Interacción no encontrada")

    interaction.feedback = req.feedback if req.feedback != 0 else None
    interaction.feedback_comment = req.comment
    await db.commit()

    return {"status": "recorded", "interaction_id": str(interaction.id)}


@router.get("/fine-tuning-dataset")
async def fine_tuning_dataset(
    min_feedback: int | None = Query(None, ge=-1, le=1),
    limit: int = Query(1000, ge=1, le=10000),
    _dev: User = Depends(get_current_developer_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export assistant interactions as JSONL for fine-tuning (developer only).

    Args:
        min_feedback: filter by feedback (1 = only positive, -1 = only negative).
        limit: maximum number of rows to export.
    """
    from sqlalchemy import select

    stmt = select(AssistantInteraction).order_by(AssistantInteraction.created_at.desc())
    if min_feedback is not None:
        stmt = stmt.where(AssistantInteraction.feedback == min_feedback)
    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    interactions = result.scalars().all()

    async def _jsonl_stream():
        for interaction in interactions:
            messages = interaction.extra_data.get("messages") if interaction.extra_data else None
            if not messages:
                # Fallback: reconstruct a minimal conversation.
                system_scope = (
                    _DEVELOPER_SYSTEM_PROMPT_TEMPLATE
                    if interaction.source_scope == "developer"
                    else _USER_SYSTEM_PROMPT_TEMPLATE
                )
                messages = [
                    {"role": "system", "content": system_scope.format(context="")},
                    {"role": "user", "content": interaction.question},
                    {"role": "assistant", "content": interaction.answer},
                ]
            record = {"messages": messages}
            yield json.dumps(record, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _jsonl_stream(),
        media_type="application/jsonl+json",
        headers={"Content-Disposition": "attachment; filename=assistant_fine_tuning.jsonl"},
    )
