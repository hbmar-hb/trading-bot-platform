"""Optional local LLM client for live scanner tips.

Designed to talk to an OpenAI-compatible endpoint running on the user's local
machine (e.g. Ollama, vLLM, llama.cpp server). The backend calls the URL
configured in LOCAL_LLM_URL; if it is not set, the endpoint returns a friendly
placeholder instead of failing.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
from loguru import logger
from pydantic import BaseModel

from config.settings import settings


class LocalLLMTip(BaseModel):
    tip: str
    rationale: str
    confidence: str  # high | medium | low


DEFAULT_TIMEOUT = 120.0

# For interactive endpoints we need a fast connection-fail fallback when the
# local Ollama endpoint is not reachable, while still giving enough time for
# the model to answer once connected.
_INTERACTIVE_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

_UNAVAILABLE_MESSAGE = (
    "El asistente de IA local no está disponible en este momento. "
    "Inténtalo más tarde o contacta al administrador."
)


def _remote_fallback_allowed() -> bool:
    """Return True when the backend may fall back to a remote (paid) LLM."""
    return bool(getattr(settings, "local_llm_allow_remote_fallback", False))


def _build_tip_prompt(event: dict) -> str:
    status = event.get("status")
    symbol = event.get("symbol")
    timeframe = event.get("timeframe")
    direction = event.get("direction")
    score = event.get("score")
    tier = event.get("quality_tier")
    anti_fake = event.get("anti_fake_status")
    prob = event.get("success_probability")
    regime = event.get("regime")
    rejection = event.get("rejection_reason")
    features = event.get("features_preview") or {}

    if status == "SIGNAL":
        base = (
            f"Eres un asesor de trading experto. El motor de IA acaba de generar una señal:\n"
            f"- Par: {symbol} {timeframe}\n"
            f"- Dirección: {direction}\n"
            f"- Score: {score}\n"
            f"- Tier: {tier}\n"
            f"- Anti-fake status: {anti_fake}\n"
            f"- Probabilidad estimada: {prob}\n"
            f"- Régimen: {regime}\n"
            f"- Features: {json.dumps(features, ensure_ascii=False)}\n\n"
            f"Da un consejo comercial corto (2-3 frases) sobre qué vigilar antes de ejecutar. "
            f"Responde ÚNICAMENTE con JSON válido con campos: tip, rationale, confidence."
        )
    else:
        base = (
            f"Eres un asesor de trading experto. El motor de IA acaba de rechazar una señal:\n"
            f"- Par: {symbol} {timeframe}\n"
            f"- Motivo: {rejection}\n"
            f"- Régimen: {regime}\n"
            f"- Features: {json.dumps(features, ensure_ascii=False)}\n\n"
            f"Explica en 2-3 frases por qué se rechazó y qué cambios deberían darse para que sea interesante. "
            f"Responde ÚNICAMENTE con JSON válido con campos: tip, rationale, confidence."
        )
    return base


def _strip_markdown(content: str) -> str:
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


class LocalLLMSummary(BaseModel):
    summary: str
    key_issues: list[str]
    recommendation: str


def _extract_nested_text(obj: Any, path: tuple[str, ...]) -> Any:
    """Walk a nested dict trying a case-insensitive path."""
    if not isinstance(obj, dict):
        return None
    for key in path:
        found = None
        for k, v in obj.items():
            if isinstance(k, str) and k.lower().replace(' ', '_') == key.lower().replace(' ', '_'):
                found = v
                break
        if found is None:
            return None
        obj = found
    return obj


def _parse_summary_flexible(raw: str) -> LocalLLMSummary:
    """Parse summary JSON allowing several LLM output shapes."""
    content = _strip_markdown(raw).strip()
    if not content:
        raise ValueError("Empty LLM response")

    # Try direct JSON parse
    data = None
    for prefix in ["", "{", "["]:
        try:
            data = json.loads(prefix + content)
            break
        except Exception:
            continue
    if data is None:
        # Try to find first JSON object
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(content[start : end + 1])
            except Exception:
                pass
    if data is None:
        raise ValueError("No JSON object found in response")

    # Direct fields
    summary = data.get("summary") or data.get("resumen")
    key_issues = data.get("key_issues") or data.get("problemas") or data.get("issues")
    recommendation = data.get("recommendation") or data.get("recomendacion") or data.get("recomendación")

    # Nested Spanish shapes like {"Resumen Ejecutivo": {"Estado general": "..."}, ...}
    if summary is None:
        nested = _extract_nested_text(data, ("resumen ejecutivo",))
        if isinstance(nested, dict):
            summary = "\n".join(f"{k}: {v}" for k, v in nested.items() if isinstance(v, (str, int, float)))
        elif isinstance(nested, str):
            summary = nested

    if key_issues is None:
        nested = _extract_nested_text(data, ("problemas clave",)) or _extract_nested_text(data, ("problemas",))
        if isinstance(nested, list):
            key_issues = [str(i) for i in nested]
        elif isinstance(nested, str):
            key_issues = [nested]

    if recommendation is None:
        nested = _extract_nested_text(data, ("recomendacion",)) or _extract_nested_text(data, ("recomendación",))
        if isinstance(nested, str):
            recommendation = nested
        elif isinstance(nested, dict):
            recommendation = "\n".join(f"{k}: {v}" for k, v in nested.items() if isinstance(v, (str, int, float)))

    if not summary:
        raise ValueError(f"Could not extract summary from: {raw[:200]}")

    return LocalLLMSummary(
        summary=str(summary),
        key_issues=[str(i) for i in key_issues] if isinstance(key_issues, list) else [str(key_issues)] if key_issues else [],
        recommendation=str(recommendation) if recommendation else "Ninguna recomendación específica.",
    )


async def generate_tip(event: dict, *, heavy: bool = False) -> LocalLLMTip:
    """Generate a trading tip from a scan event using the local LLM.

    heavy=True uses the slow/capable model (background tasks).
    heavy=False (default) uses the fast model (interactive/user-facing).
    """
    local_url = getattr(settings, "local_llm_url", None)
    if heavy:
        model = getattr(settings, "local_llm_model_heavy", "mixtral:8x7b")
    else:
        model = getattr(settings, "local_llm_model", "mistral:7b")

    if not local_url:
        return LocalLLMTip(
            tip="Conecta tu modelo local (Ollama, vLLM, etc.) en LOCAL_LLM_URL para obtener tips de IA en vivo.",
            rationale="LOCAL_LLM_URL no está configurado en el backend.",
            confidence="low",
        )

    prompt = _build_tip_prompt(event)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Eres un asesor de trading conciso. Responde solo con JSON válido."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 300,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=_INTERACTIVE_TIMEOUT) as client:
            resp = await client.post(f"{local_url}/chat/completions", json=payload, headers={"Host": "localhost"})
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = _strip_markdown(content)
            parsed = LocalLLMTip.model_validate_json(content)
            return parsed
    except Exception as exc:
        logger.warning(f"[local_llm] Tip generation failed: {exc}")
        return LocalLLMTip(
            tip="No se pudo contactar con el modelo local. Verifica que esté corriendo y accesible.",
            rationale=str(exc),
            confidence="low",
        )


async def generate_summary(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> LocalLLMSummary:
    """Generate a structured summary of engine/system state using the local LLM.

    Falls back to the remote LLM client if the local endpoint is not available.
    """
    local_url = getattr(settings, "local_llm_url", None)
    # Use the assistant model by default for interactive summaries (faster than heavy).
    selected_model = model or getattr(settings, "local_llm_model_assistant", "qwen2.5:7b")

    system_content = (
        "Eres un administrador senior de sistemas y trading. "
        "Resume el estado del motor de IA y la plataforma en español, "
        "identifica los problemas críticos y da una recomendación clara.\n\n"
        "Responde ÚNICAMENTE con JSON válido y plano (sin objetos anidados) "
        "con exactamente estos campos:\n"
        "- summary: string (párrafo ejecutivo)\n"
        "- key_issues: array de strings (máximo 5 problemas)\n"
        "- recommendation: string (acción recomendada)\n\n"
        "Ejemplo:\n"
        '{"summary": "El sistema está en modo paper...", "key_issues": ["Pocos trades post-corte"], "recommendation": "Continuar acumulando métricas paper."}'
    )

    if local_url:
        payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=_INTERACTIVE_TIMEOUT) as client:
                resp = await client.post(f"{local_url}/chat/completions", json=payload, headers={"Host": "localhost"})
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return _parse_summary_flexible(content)
        except Exception as exc:
            logger.warning(f"[local_llm] Summary generation failed locally: {exc}.")
            if not _remote_fallback_allowed():
                logger.info("[local_llm] Remote fallback disabled by configuration.")
                return LocalLLMSummary(
                    summary=_UNAVAILABLE_MESSAGE,
                    key_issues=["Modelo local no disponible"],
                    recommendation="Revisa LOCAL_LLM_URL / LOCAL_LLM_ENABLED o habilita LOCAL_LLM_ALLOW_REMOTE_FALLBACK.",
                )
            logger.info("[local_llm] Trying remote fallback.")

    # Fallback to remote LLM (text completion, then flexible parse)
    if _remote_fallback_allowed():
        try:
            from app.services.llm_client import generate_chat_async, LLMError
            response = await generate_chat_async(
                [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return _parse_summary_flexible(response.content)
        except LLMError as exc:
            logger.warning(f"[local_llm] Remote LLM fallback also failed: {exc}")
        except Exception as exc:
            logger.warning(f"[local_llm] Unexpected remote fallback error: {exc}")

    return LocalLLMSummary(
        summary="No se pudo generar el resumen. Verifica que Ollama esté corriendo o que el LLM remoto esté configurado.",
        key_issues=["Modelo local no disponible", "Fallback remoto no disponible"],
        recommendation="Revisa LOCAL_LLM_URL, LOCAL_LLM_ENABLED y OPENROUTER_API_KEY.",
    )


async def answer_question(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> tuple[str, str]:
    """Answer a user question based on provided metrics using the local LLM.

    Returns (answer_text, model_used). Falls back to remote LLM if local is unavailable.
    """
    local_url = getattr(settings, "local_llm_url", None)
    # Use the assistant model by default for interactive Q&A.
    selected_model = model or getattr(settings, "local_llm_model_assistant", "qwen2.5:7b")

    system_content = (
        "Eres un asesor experto del motor de IA de esta plataforma de trading. "
        "Responde en español de forma concisa y basada ÚNICAMENTE en los datos proporcionados. "
        "Si no sabes algo o no está en los datos, dilo claramente."
    )

    if local_url:
        payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=_INTERACTIVE_TIMEOUT) as client:
                resp = await client.post(f"{local_url}/chat/completions", json=payload, headers={"Host": "localhost"})
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content.strip(), selected_model
        except Exception as exc:
            logger.warning(f"[local_llm] Question answering failed locally: {exc}.")
            if not _remote_fallback_allowed():
                logger.info("[local_llm] Remote fallback disabled by configuration.")
                return _UNAVAILABLE_MESSAGE, "local_unavailable"
            logger.info("[local_llm] Trying remote fallback.")

    # Fallback to remote LLM
    if _remote_fallback_allowed():
        try:
            from app.services.llm_client import generate_chat_async, LLMError
            response = await generate_chat_async(
                [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.content.strip(), response.model_used
        except LLMError as exc:
            logger.warning(f"[local_llm] Remote LLM fallback also failed: {exc}")
        except Exception as exc:
            logger.warning(f"[local_llm] Unexpected remote fallback error: {exc}")

    return (
        "No se pudo contactar con ningún modelo de lenguaje. "
        "Verifica que Ollama esté corriendo o que el LLM remoto esté configurado.",
        "unavailable",
    )


async def _stream_local_ollama(local_url: str, payload: dict):
    """Yields tokens from a local Ollama streaming completion."""
    async with httpx.AsyncClient(timeout=_INTERACTIVE_TIMEOUT) as client:
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
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue


async def generate_summary_stream(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> AsyncIterator[dict]:
    """Stream a structured summary from the local LLM (fallback remote).

    Yields dicts:
      {"event": "token", "content": str}
      {"event": "done", "data": LocalLLMSummary}
      {"event": "error", "message": str}
    """
    local_url = getattr(settings, "local_llm_url", None)
    selected_model = model or getattr(settings, "local_llm_model_assistant", "qwen2.5:7b")

    system_content = (
        "Eres un administrador senior de sistemas y trading. "
        "Resume el estado del motor de IA y la plataforma en español, "
        "identifica los problemas críticos y da una recomendación clara.\n\n"
        "Responde ÚNICAMENTE con JSON válido y plano (sin objetos anidados) "
        "con exactamente estos campos:\n"
        "- summary: string (párrafo ejecutivo)\n"
        "- key_issues: array de strings (máximo 5 problemas)\n"
        "- recommendation: string (acción recomendada)\n\n"
        "Ejemplo:\n"
        '{"summary": "El sistema está en modo paper...", "key_issues": ["Pocos trades post-corte"], "recommendation": "Continuar acumulando métricas paper."}'
    )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt},
    ]

    accumulated = ""

    if local_url:
        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            async for token in _stream_local_ollama(local_url, payload):
                accumulated += token
                yield {"event": "token", "content": token}
            try:
                parsed = _parse_summary_flexible(accumulated)
                yield {"event": "done", "data": parsed.model_dump()}
            except Exception as exc:
                logger.warning(f"[local_llm] Failed to parse streamed summary: {exc}")
                yield {"event": "error", "message": f"No se pudo parsear el resumen: {exc}"}
            return
        except Exception as exc:
            logger.warning(f"[local_llm] Summary stream failed locally: {exc}.")
            if not _remote_fallback_allowed():
                logger.info("[local_llm] Remote fallback disabled by configuration.")
                yield {"event": "error", "message": _UNAVAILABLE_MESSAGE}
                return
            logger.info("[local_llm] Trying remote stream fallback.")

    # Fallback to remote LLM stream
    if _remote_fallback_allowed():
        try:
            from app.services.llm_client import generate_chat_stream, LLMError
            async for token in generate_chat_stream(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                accumulated += token
                yield {"event": "token", "content": token}
            try:
                parsed = _parse_summary_flexible(accumulated)
                yield {"event": "done", "data": parsed.model_dump()}
            except Exception as exc:
                logger.warning(f"[local_llm] Failed to parse remote streamed summary: {exc}")
                yield {"event": "error", "message": f"No se pudo parsear el resumen remoto: {exc}"}
            return
        except LLMError as exc:
            logger.warning(f"[local_llm] Remote LLM stream fallback also failed: {exc}")
        except Exception as exc:
            logger.warning(f"[local_llm] Unexpected remote stream fallback error: {exc}")

    yield {
        "event": "error",
        "message": "No se pudo generar el resumen. Verifica que Ollama esté corriendo o que el LLM remoto esté configurado.",
    }


async def answer_question_stream(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> AsyncIterator[dict]:
    """Stream an answer from the local LLM (fallback remote).

    Yields dicts:
      {"event": "token", "content": str}
      {"event": "done", "model_used": str}
      {"event": "error", "message": str}
    """
    local_url = getattr(settings, "local_llm_url", None)
    selected_model = model or getattr(settings, "local_llm_model_assistant", "qwen2.5:7b")

    system_content = (
        "Eres un asesor experto del motor de IA de esta plataforma de trading. "
        "Responde en español de forma concisa y basada ÚNICAMENTE en los datos proporcionados. "
        "Si no sabes algo o no está en los datos, dilo claramente."
    )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt},
    ]

    if local_url:
        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            async for token in _stream_local_ollama(local_url, payload):
                yield {"event": "token", "content": token}
            yield {"event": "done", "model_used": selected_model}
            return
        except Exception as exc:
            logger.warning(f"[local_llm] Question stream failed locally: {exc}.")
            if not _remote_fallback_allowed():
                logger.info("[local_llm] Remote fallback disabled by configuration.")
                yield {"event": "error", "message": _UNAVAILABLE_MESSAGE}
                return
            logger.info("[local_llm] Trying remote stream fallback.")

    # Fallback to remote LLM stream
    if _remote_fallback_allowed():
        try:
            from app.services.llm_client import generate_chat_stream, LLMError
            async for token in generate_chat_stream(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                yield {"event": "token", "content": token}
            yield {"event": "done", "model_used": getattr(settings, "llm_default_model", "remote")}
            return
        except LLMError as exc:
            logger.warning(f"[local_llm] Remote LLM stream fallback also failed: {exc}")
        except Exception as exc:
            logger.warning(f"[local_llm] Unexpected remote stream fallback error: {exc}")

    yield {
        "event": "error",
        "message": "No se pudo contactar con ningún modelo de lenguaje. "
                   "Verifica que Ollama esté corriendo o que el LLM remoto esté configurado.",
    }
