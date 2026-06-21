"""Engine Narrator — asistente narrativo del motor IA.

Recopila métricas del dashboard, health checks, deployment gate y modelo,
y las resume en lenguaje natural usando un LLM local (fallback remoto).

Este servicio es informativo: no dispara acciones automáticas.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncIterator

from loguru import logger
from sqlalchemy import func, select, text

from app.services.database import SessionLocal
from app.services.system_health_service import run_full_check
from app.services.deployment_gate import get_latest_gate_status
from app.services.local_llm_client import (
    generate_summary,
    answer_question,
    generate_summary_stream,
    answer_question_stream,
)
from app.models.bot_config import BotConfig


def _format_number(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except Exception:
        return str(value)


def _format_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return str(value)


async def _gather_health() -> dict:
    """Health check con timeout para no bloquear el narrador."""
    try:
        return await asyncio.wait_for(run_full_check(), timeout=20.0)
    except asyncio.TimeoutError:
        logger.warning("[engine_narrator] Health check excedió 20s; omitiendo exchange.")
        return {
            "status": "timeout",
            "checks": {},
            "summary": {
                "total_issues": 0,
                "criticals": 0,
                "warnings": 0,
                "issues_list": ["🟡 Health check lento (>20s) — probablemente exchange API lenta."],
            },
        }
    except Exception as exc:
        logger.warning(f"[engine_narrator] Health check failed: {exc}")
        return {"status": "unknown", "error": str(exc)}


def _gather_db_metrics() -> dict:
    """Recopila deployment gate, bots y señales desde DB síncrona."""
    result: dict = {}
    try:
        with SessionLocal() as db:
            result["deployment_gate"] = get_latest_gate_status(db)

            bots_by_status = {
                row[0]: row[1]
                for row in db.execute(
                    select(BotConfig.status, func.count(BotConfig.id)).group_by(BotConfig.status)
                ).all()
            }
            result["bots"] = {
                "by_status": bots_by_status,
                "total": sum(bots_by_status.values()),
            }

            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            signal_agg = db.execute(
                text("""
                    SELECT COUNT(*) as total,
                           COUNT(*) FILTER (WHERE outcome = 'PENDING') as pending,
                           COUNT(*) FILTER (WHERE outcome IN ('SUCCESS', 'FAILURE_MAX_ADVERSE', 'FAILURE_BEHAVIORAL', 'CENSORED')) as resolved,
                           COUNT(*) FILTER (WHERE quality_tier = 'STRONG') as strong,
                           COUNT(*) FILTER (WHERE quality_tier = 'MODERATE') as moderate,
                           COUNT(*) FILTER (WHERE quality_tier = 'WEAK') as weak,
                           ROUND(AVG(score)::numeric, 1) as avg_score
                    FROM ai_signals WHERE created_at > :since
                """),
                {"since": since_24h},
            ).mappings().one()
            result["signals_24h"] = dict(signal_agg)

            since_2h = datetime.now(timezone.utc) - timedelta(hours=2)
            sig_2h = db.execute(
                text("SELECT COUNT(*) FROM ai_signals WHERE created_at > :since"),
                {"since": since_2h},
            ).scalar()
            result["signals_2h"] = sig_2h or 0
    except Exception as exc:
        logger.warning(f"[engine_narrator] DB metrics failed: {exc}")
        result["deployment_gate"] = {"state": "unknown", "error": str(exc)}
        result["bots"] = {"error": str(exc)}
        result["signals_24h"] = {"error": str(exc)}
        result["signals_2h"] = 0
    return result


def _gather_model_metrics() -> dict:
    """Recopila métricas del modelo ensemble o anti-fake."""
    try:
        from ai import ensemble_registry
        from ai.registry import model_info as af_info, model_ready as af_ready

        if ensemble_registry.model_ready():
            info = ensemble_registry.model_info()
            m = info.get("metrics", {})
            return {
                "type": "ensemble",
                "ready": True,
                "auc": m.get("ensemble_auc"),
                "accuracy": m.get("ensemble_accuracy"),
                "samples": m.get("train_samples"),
                "base_models": info.get("base_models", []),
                "trained_on": info.get("trained_on"),
            }
        else:
            info = af_info()
            m = info.get("metrics", {})
            return {
                "type": "anti_fake",
                "ready": af_ready(),
                "auc": m.get("auc") or m.get("oof_auc"),
                "accuracy": m.get("accuracy") or m.get("oof_accuracy"),
                "samples": info.get("samples_at_training", 0),
            }
    except Exception as exc:
        logger.warning(f"[engine_narrator] Model metrics failed: {exc}")
        return {"ready": False, "error": str(exc)}


async def gather_engine_metrics() -> dict:
    """Recopila métricas relevantes del motor IA y la plataforma en paralelo."""
    metrics: dict = {"collected_at": datetime.now(timezone.utc).isoformat()}

    health_task = asyncio.create_task(_gather_health())
    db_task = asyncio.create_task(asyncio.to_thread(_gather_db_metrics))
    model_task = asyncio.create_task(asyncio.to_thread(_gather_model_metrics))

    health, db_data, model = await asyncio.gather(health_task, db_task, model_task)

    metrics["health"] = health
    metrics.update(db_data)
    metrics["model"] = model

    return metrics


def _build_summary_prompt(metrics: dict) -> str:
    """Construye el prompt para el resumen narrativo."""
    health = metrics.get("health", {})
    gate = metrics.get("deployment_gate", {})
    model = metrics.get("model", {})
    bots = metrics.get("bots", {})
    sig24 = metrics.get("signals_24h", {})

    health_status = health.get("status", "unknown")
    issues = health.get("summary", {}).get("issues_list", [])
    gate_state = gate.get("state", "unknown")
    gate_reasons = gate.get("reasons", [])
    gate_metrics = gate.get("metrics", {})

    lines = [
        "Estado de la plataforma de trading con motor IA:",
        "",
        f"- Estado general del health check: {health_status}",
        f"- Problemas detectados ({len(issues)}):",
    ]
    for issue in issues[:15]:
        lines.append(f"  • {issue}")
    if len(issues) > 15:
        lines.append(f"  • ... y {len(issues) - 15} más")

    lines.extend([
        "",
        f"- Deployment gate: {gate_state}",
        f"  • Sharpe 20d: {_format_number(gate_metrics.get('sharpe_20'))}",
        f"  • Profit Factor: {_format_number(gate_metrics.get('profit_factor'))}",
        f"  • Max Drawdown: {_format_number(gate_metrics.get('max_drawdown_pct'))}%",
        f"  • Drift PSI: {_format_number(gate_metrics.get('drift_psi_max'))}",
        f"  • Confidence decay divergence: {_format_number(gate_metrics.get('confidence_decay_divergence'))}%",
        f"  • Walk-forward pass: {gate_metrics.get('wf_passed')}",
        f"  • Razones: {', '.join(gate_reasons) if gate_reasons else 'Ninguna'}",
        "",
        f"- Modelo activo: {model.get('type', 'unknown')} | listo: {model.get('ready')}",
        f"  • AUC: {_format_number(model.get('auc'))}",
        f"  • Accuracy: {_format_pct(model.get('accuracy'))}",
        f"  • Muestras de entrenamiento: {model.get('samples', 'N/A')}",
        f"  • Modelos base: {', '.join(model.get('base_models', []))}",
        f"  • Entrenado el: {model.get('trained_on') or 'N/A'}",
        "",
        f"- Bots: {bots.get('total', 'N/A')} en total | por estado: {bots.get('by_status', {})}",
        f"- Señales últimas 24h: {sig24.get('total', 'N/A')} (STRONG={sig24.get('strong', 0)}, MODERATE={sig24.get('moderate', 0)}, WEAK={sig24.get('weak', 0)}, pending={sig24.get('pending', 0)})",
        f"- Señales últimas 2h: {metrics.get('signals_2h', 'N/A')}",
        f"- Score promedio 24h: {sig24.get('avg_score') or 'N/A'}",
        "",
        "Contexto adicional:",
        "- El corte de datos limpio es 2026-06-10. Solo se usan señales/trades desde esa fecha.",
        "- Los bots reales de IA están pausados hasta que el paper trading muestre edge consistente.",
        "- El sistema prioriza datos limpios sobre métricas históricas altas.",
        "",
        "Genera un resumen ejecutivo en español.",
    ])

    return "\n".join(lines)


def _build_question_prompt(metrics: dict, question: str) -> str:
    """Construye el prompt para responder una pregunta del usuario."""
    prompt = _build_summary_prompt(metrics)
    return (
        f"{prompt}\n\n"
        f"Pregunta del usuario: {question}\n\n"
        "Responde de forma concisa basándote ÚNICAMENTE en los datos proporcionados. "
        "Si no está en los datos, dilo claramente."
    )


async def generate_engine_summary() -> dict:
    """Genera un resumen narrativo del estado del motor IA."""
    metrics = await gather_engine_metrics()
    prompt = _build_summary_prompt(metrics)

    try:
        summary = await generate_summary(prompt)
        return {
            "metrics": metrics,
            "summary": summary.summary,
            "key_issues": summary.key_issues,
            "recommendation": summary.recommendation,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning(f"[engine_narrator] Summary generation failed: {exc}")
        return {
            "metrics": metrics,
            "summary": "No se pudo generar el resumen en este momento.",
            "key_issues": [str(exc)],
            "recommendation": "Reintenta en unos segundos o revisa la conectividad con Ollama.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


async def answer_engine_question(question: str) -> dict:
    """Responde una pregunta del usuario sobre el estado del motor IA."""
    metrics = await gather_engine_metrics()
    prompt = _build_question_prompt(metrics, question)

    try:
        answer, model_used = await answer_question(prompt)
        return {
            "question": question,
            "answer": answer,
            "model_used": model_used,
            "metrics_snapshot": metrics,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning(f"[engine_narrator] Question answering failed: {exc}")
        return {
            "question": question,
            "answer": "No se pudo generar una respuesta en este momento.",
            "model_used": "unavailable",
            "metrics_snapshot": metrics,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


async def generate_engine_summary_stream() -> AsyncIterator[str]:
    """Genera un resumen narrativo en streaming (SSE).

    Eventos enviados:
      - phase:metrics  -> "Recopilando métricas..."
      - metrics        -> JSON con métricas recopiladas
      - phase:llm      -> "Generando resumen..."
      - token          -> chunk de texto del LLM
      - summary        -> JSON final con summary/key_issues/recommendation
      - error          -> mensaje de error
    """
    yield _sse_event("phase", {"phase": "metrics", "message": "Recopilando métricas..."})

    metrics = await gather_engine_metrics()
    yield _sse_event("metrics", {"metrics": metrics})

    yield _sse_event("phase", {"phase": "llm", "message": "Generando resumen con IA..."})

    prompt = _build_summary_prompt(metrics)
    try:
        async for event in generate_summary_stream(prompt):
            if event["event"] == "token":
                yield _sse_event("token", {"content": event["content"]})
            elif event["event"] == "done":
                data = event["data"]
                yield _sse_event("summary", {
                    "summary": data.get("summary", ""),
                    "key_issues": data.get("key_issues", []),
                    "recommendation": data.get("recommendation", ""),
                    "metrics": metrics,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                })
            elif event["event"] == "error":
                yield _sse_event("error", {"message": event.get("message", "Error desconocido")})
    except Exception as exc:
        logger.warning(f"[engine_narrator] Summary stream failed: {exc}")
        yield _sse_event("error", {"message": str(exc)})


async def answer_engine_question_stream(question: str) -> AsyncIterator[str]:
    """Responde una pregunta del usuario en streaming (SSE).

    Eventos enviados:
      - phase:metrics  -> "Recopilando métricas..."
      - metrics        -> JSON con métricas
      - phase:llm      -> "Generando respuesta..."
      - token          -> chunk de texto
      - answer         -> JSON final con answer y model_used
      - error          -> mensaje de error
    """
    yield _sse_event("phase", {"phase": "metrics", "message": "Recopilando métricas..."})

    metrics = await gather_engine_metrics()
    yield _sse_event("metrics", {"metrics": metrics})

    yield _sse_event("phase", {"phase": "llm", "message": "Generando respuesta con IA..."})

    prompt = _build_question_prompt(metrics, question)
    accumulated = ""
    try:
        async for event in answer_question_stream(prompt):
            if event["event"] == "token":
                accumulated += event["content"]
                yield _sse_event("token", {"content": event["content"]})
            elif event["event"] == "done":
                yield _sse_event("answer", {
                    "question": question,
                    "answer": accumulated.strip(),
                    "model_used": event.get("model_used", "unknown"),
                    "metrics_snapshot": metrics,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                })
            elif event["event"] == "error":
                yield _sse_event("error", {"message": event.get("message", "Error desconocido")})
    except Exception as exc:
        logger.warning(f"[engine_narrator] Question stream failed: {exc}")
        yield _sse_event("error", {"message": str(exc)})


def _sse_event(event: str, data: dict) -> str:
    """Formatea un evento SSE."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
