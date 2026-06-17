"""Internal (zero-cost) signal diagnosis generator.

Replaces the external LLM diagnosis with a rule-based explanation built from
signal fields that the engine already computes: anti_fake_status, score,
success_probability, red_flags, green_flags, components, and features.

The output shape matches SignalDiagnosis so it can be stored in the same
LLMSignalDiagnosis table and consumed by the same UI / bot activator code.
"""
from __future__ import annotations

from app.services.signal_diagnosis import DiagnosisFactor, SignalDiagnosis


def _verdict_from_signal(signal) -> str:
    status = getattr(signal, "anti_fake_status", None) or "CLEAR"
    return status.upper()


def _confidence_from_signal(signal) -> int:
    prob = getattr(signal, "success_probability", None)
    if prob is not None:
        return int(round(prob * 100))
    score = getattr(signal, "score", None) or 0
    return min(100, max(0, int(score)))


def _factor_from_flag(flag: str, good: bool = False) -> DiagnosisFactor:
    category = "technical"
    if any(k in flag.lower() for k in ("risk", "drawdown", "exposure", "size")):
        category = "risk"
    elif any(k in flag.lower() for k in ("macro", "funding", "session")):
        category = "macro"
    if good:
        return DiagnosisFactor(
            category=category,
            severity="info",
            description=flag,
            metric=None,
        )
    severity = "critical" if any(k in flag.lower() for k in ("block", "fatal", "extreme")) else "warning"
    return DiagnosisFactor(
        category=category,
        severity=severity,
        description=flag,
        metric=None,
    )


def _recommendation(verdict: str, confidence: int, has_red: bool, has_green: bool) -> str:
    if verdict == "BLOCK":
        return (
            "Señal de alta probabilidad de fracaso. Evitar entrada o, si se opera, "
            "usar tamaño mínimo y stop loss ajustado."
        )
    if verdict == "CAUTION":
        return (
            "Señal con factores de riesgo presentes. Reducir tamaño, esperar "
            "confirmación de precio o mejorar punto de entrada."
        )
    if has_green and confidence >= 60:
        return "Señal favorable. Operar con gestión de riesgo habitual."
    if has_green:
        return "Señal aceptable pero no óptima. Confirmar con volumen y estructura antes de entrar."
    return "Señal sin factores destacados. Mantener tamaño conservador."


def _summary(verdict: str, ticker: str, direction: str, timeframe: str, score: float, confidence: int) -> str:
    base = f"{ticker} {timeframe} {direction.upper()} — score {score:.1f}, confianza ML {confidence}%"
    if verdict == "BLOCK":
        return f"{base}. La señal es rechazada por múltiples factores de riesgo."
    if verdict == "CAUTION":
        return f"{base}. La señal es válida pero presenta advertencias que reducen su calidad."
    return f"{base}. La señal cumple los criterios mínimos de confluencia."


def diagnose_signal_internal(
    signal,
    trigger_source: str = "anti_fake",
    gate_details: dict | None = None,
) -> tuple[SignalDiagnosis, dict]:
    """Generate a SignalDiagnosis object from internal signal fields.

    Returns:
        (SignalDiagnosis, metadata dict)
    """
    ticker = getattr(signal, "ticker", "UNKNOWN") or "UNKNOWN"
    direction = getattr(signal, "direction", "unknown") or "unknown"
    timeframe = getattr(signal, "timeframe", "unknown") or "unknown"
    score = float(getattr(signal, "score", 0) or 0)

    verdict = _verdict_from_signal(signal)
    confidence = _confidence_from_signal(signal)

    factors: list[DiagnosisFactor] = []
    for flag in getattr(signal, "red_flags", None) or []:
        factors.append(_factor_from_flag(flag, good=False))
    for flag in getattr(signal, "green_flags", None) or []:
        factors.append(_factor_from_flag(flag, good=True))

    # Gate-specific factor for rejected signals
    if trigger_source.startswith("gate_") and gate_details:
        reason = gate_details.get("reason") or trigger_source.replace("gate_", "")
        factors.append(
            DiagnosisFactor(
                category="risk",
                severity="critical" if verdict == "BLOCK" else "warning",
                description=f"Rechazada por gate: {reason}",
                metric=None,
            )
        )

    if not factors:
        factors.append(
            DiagnosisFactor(
                category="technical",
                severity="info",
                description="No se detectaron factores críticos ni advertencias destacadas.",
                metric=None,
            )
        )

    diagnosis = SignalDiagnosis(
        verdict=verdict,
        confidence=confidence,
        summary=_summary(verdict, ticker, direction, timeframe, score, confidence),
        factors=factors,
        recommendation=_recommendation(verdict, confidence, len(getattr(signal, "red_flags", None) or []) > 0, len(getattr(signal, "green_flags", None) or []) > 0),
    )

    metadata = {
        "model_used": "internal",
        "latency_ms": 0,
        "cost_usd": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    return diagnosis, metadata
