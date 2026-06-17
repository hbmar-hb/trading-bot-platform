"""Signal Diagnosis Service — orchestrates LLM diagnosis for rejected signals.

Pure functions (no I/O except DB read for signal loading).
The actual LLM call is delegated to llm_client.generate_structured().
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from loguru import logger
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════
# Pydantic schemas for structured LLM output
# ═══════════════════════════════════════════════════════════

class DiagnosisFactor(BaseModel):
    category: str  # "technical" | "risk" | "macro" | "sentiment"
    severity: str  # "critical" | "warning" | "info"
    description: str
    metric: str | None = None


class SignalDiagnosis(BaseModel):
    verdict: str  # "BLOCK" | "CAUTION" | "CLEAR"
    confidence: int  # 0-100
    summary: str
    factors: list[DiagnosisFactor]
    recommendation: str


# ═══════════════════════════════════════════════════════════
# Prompt loader
# ═══════════════════════════════════════════════════════════

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "ai" / "prompts"


def _load_prompt_template(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════
# Prompt builders
# ═══════════════════════════════════════════════════════════

def _render_anti_fake_prompt(signal, features: dict) -> str:
    template = _load_prompt_template("anti_fake_diagnosis")
    red_flags = signal.red_flags or []
    green_flags = signal.green_flags or []
    return template.replace("{{ticker}}", signal.ticker or "UNKNOWN") \
        .replace("{{direction}}", signal.direction or "unknown") \
        .replace("{{timeframe}}", signal.timeframe or "unknown") \
        .replace("{{score}}", str(signal.score or 0)) \
        .replace("{{quality_tier}}", signal.quality_tier or "UNKNOWN") \
        .replace("{{anti_fake_status}}", signal.anti_fake_status or "UNKNOWN") \
        .replace("{{success_probability}}", str(round((signal.success_probability or 0) * 100, 1))) \
        .replace("{{red_flags}}", json.dumps(red_flags, ensure_ascii=False)) \
        .replace("{{green_flags}}", json.dumps(green_flags, ensure_ascii=False)) \
        .replace("{{components}}", json.dumps(signal.components or {}, ensure_ascii=False)) \
        .replace("{{warnings}}", json.dumps(signal.warnings or [], ensure_ascii=False)) \
        .replace("{{features_json}}", json.dumps(features, indent=2, ensure_ascii=False))


def _render_gate_prompt(signal, gate_name: str, reason: str, gate_details: dict | None) -> str:
    template = _load_prompt_template("gate_rejection_diagnosis")
    return template.replace("{{ticker}}", signal.ticker or "UNKNOWN") \
        .replace("{{direction}}", signal.direction or "unknown") \
        .replace("{{timeframe}}", signal.timeframe or "unknown") \
        .replace("{{score}}", str(signal.score or 0)) \
        .replace("{{quality_tier}}", signal.quality_tier or "UNKNOWN") \
        .replace("{{anti_fake_status}}", signal.anti_fake_status or "UNKNOWN") \
        .replace("{{gate_name}}", gate_name) \
        .replace("{{rejection_reason}}", reason) \
        .replace("{{gate_details_json}}", json.dumps(gate_details or {}, indent=2, ensure_ascii=False)) \
        .replace("{{features_json}}", json.dumps(signal.features or {}, indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════

def build_prompt(signal, trigger_source: str, gate_details: dict | None = None) -> str:
    """Build the LLM prompt for a given signal and trigger source.

    Args:
        signal: AISignal instance (duck-typed).
        trigger_source: e.g. "anti_fake", "gate_kelly", "gate_portfolio".
        gate_details: Optional dict with gate-specific context.

    Returns:
        Rendered prompt string.
    """
    if trigger_source.startswith("anti_fake"):
        return _render_anti_fake_prompt(signal, signal.features or {})

    # Generic gate prompt for all other rejection sources
    gate_name = trigger_source.replace("gate_", "").upper()
    reason = gate_details.get("reason", "rejected by gate") if gate_details else "rejected by gate"
    return _render_gate_prompt(signal, gate_name, reason, gate_details)


def diagnose_signal_sync(
    signal,
    trigger_source: str,
    gate_details: dict | None = None,
) -> tuple[SignalDiagnosis, dict]:
    """Synchronous LLM diagnosis for a signal.

    Returns:
        Tuple of (SignalDiagnosis, metadata dict with model_used, latency_ms, cost_usd).

    Raises:
        LLMError: If LLM is disabled or call fails.
    """
    from app.services.llm_client import generate_structured

    prompt = build_prompt(signal, trigger_source, gate_details)
    diagnosis, response = generate_structured(prompt, SignalDiagnosis)

    metadata = {
        "model_used": response.model_used,
        "latency_ms": response.latency_ms,
        "cost_usd": response.cost_usd,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
    }
    return diagnosis, metadata


def save_diagnosis(
    db,
    signal_id: uuid.UUID,
    trigger_source: str,
    diagnosis: SignalDiagnosis,
    raw_response: str,
    metadata: dict,
) -> "LLMSignalDiagnosis":
    """Persist diagnosis to database."""
    from app.models.llm_signal_diagnosis import LLMSignalDiagnosis

    row = LLMSignalDiagnosis(
        ai_signal_id=signal_id,
        trigger_source=trigger_source,
        prompt_version="v1",
        model_used=metadata.get("model_used", "unknown"),
        raw_response=raw_response,
        diagnosis_json=diagnosis.model_dump(),
        latency_ms=metadata.get("latency_ms"),
        cost_usd=metadata.get("cost_usd"),
    )
    db.add(row)
    db.commit()
    logger.info(
        f"[LLM_DIAGNOSIS] Saved {trigger_source} diagnosis for signal {signal_id} "
        f"model={row.model_used} latency={row.latency_ms}ms"
    )
    return row
