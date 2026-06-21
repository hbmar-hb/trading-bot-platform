"""Optional local LLM client for live scanner tips.

Designed to talk to an OpenAI-compatible endpoint running on the user's local
machine (e.g. Ollama, vLLM, llama.cpp server). The backend calls the URL
configured in LOCAL_LLM_URL; if it is not set, the endpoint returns a friendly
placeholder instead of failing.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel

from config.settings import settings


class LocalLLMTip(BaseModel):
    tip: str
    rationale: str
    confidence: str  # high | medium | low


DEFAULT_TIMEOUT = 120.0


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
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
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
