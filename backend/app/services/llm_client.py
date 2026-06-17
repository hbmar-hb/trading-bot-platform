"""Generic LLM client for structured JSON generation.

Uses httpx + Pydantic v2 for type-safe LLM calls.
Supports OpenRouter with automatic fallback to secondary model.
"""
from __future__ import annotations

import json
import time
from typing import TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

T = TypeVar("T", bound=BaseModel)

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_TOKENS = 500


class LLMResponse(BaseModel):
    """Standardized LLM response metadata."""
    content: str
    model_used: str
    latency_ms: int
    cost_usd: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMError(Exception):
    """Raised when LLM call fails after all retries."""
    pass


def _build_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.api_base_url,
        "X-Title": "Trading Bot Platform",
    }


def _build_payload(prompt: str, model: str, max_tokens: int) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a trading analysis assistant. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }


def _parse_usage(response_json: dict) -> tuple[float | None, int | None, int | None]:
    """Extract cost and token usage from OpenRouter response."""
    usage = response_json.get("usage", {})
    cost = response_json.get("usage", {}).get("cost")
    # OpenRouter sometimes puts cost at top level
    if cost is None:
        cost = response_json.get("cost")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    return cost, prompt_tokens, completion_tokens


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_llm_sync(prompt: str, model: str, max_tokens: int) -> LLMResponse:
    """Synchronous LLM call with retries."""
    headers = _build_headers()
    payload = _build_payload(prompt, model, max_tokens)
    url = f"{settings.openrouter_base_url}/chat/completions"

    start = time.perf_counter()
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(f"LLM HTTP error {exc.response.status_code}: {exc.response.text[:200]}")
        raise
    except httpx.RequestError as exc:
        logger.warning(f"LLM request error: {exc}")
        raise

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    data = resp.json()
    choice = data.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    model_used = data.get("model", model)

    cost, prompt_tokens, completion_tokens = _parse_usage(data)

    return LLMResponse(
        content=content,
        model_used=model_used,
        latency_ms=elapsed_ms,
        cost_usd=cost,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def generate_structured(
    prompt: str,
    response_model: type[T],
    model: str | None = None,
    max_tokens: int | None = None,
) -> tuple[T, LLMResponse]:
    """Generate structured output from LLM.

    Args:
        prompt: The user prompt.
        response_model: Pydantic model class to validate the JSON response.
        model: Optional override model. Defaults to settings.llm_default_model.
        max_tokens: Optional override max_tokens.

    Returns:
        Tuple of (parsed_model, response_metadata).

    Raises:
        LLMError: If the LLM call fails or the response cannot be parsed.
    """
    if not settings.llm_enabled or not settings.openrouter_api_key:
        raise LLMError("LLM is disabled or OPENROUTER_API_KEY is not set")

    primary_model = model or settings.llm_default_model
    fallback_model = settings.llm_fallback_model
    max_tok = max_tokens or settings.llm_max_tokens or DEFAULT_MAX_TOKENS

    models_to_try = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models_to_try.append(fallback_model)

    last_error: Exception | None = None
    for attempt_model in models_to_try:
        try:
            logger.debug(f"LLM call to {attempt_model} (max_tokens={max_tok})")
            response = _call_llm_sync(prompt, attempt_model, max_tok)

            # Parse JSON
            content = response.content.strip()
            # Sometimes models wrap JSON in markdown code blocks
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            parsed = response_model.model_validate_json(content)
            logger.info(
                f"LLM success: model={response.model_used} "
                f"latency={response.latency_ms}ms cost={response.cost_usd}"
            )
            return parsed, response

        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(f"LLM response parse error with {attempt_model}: {exc}")
            last_error = exc
            continue
        except Exception as exc:
            logger.warning(f"LLM call failed with {attempt_model}: {exc}")
            last_error = exc
            continue

    raise LLMError(f"LLM failed after trying {models_to_try}: {last_error}")
