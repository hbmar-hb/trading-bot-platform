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
    _UNAVAILABLE_MESSAGE,
)
from app.services.faq_service import answer_faq
from app.models.bot_config import BotConfig
from app.models.position import Position


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


def _gather_shadow_metrics() -> dict:
    """Recopila métricas del shadow mode últimas 24h."""
    try:
        with SessionLocal() as db:
            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

            # Evaluaciones por perfil
            shadow_agg = db.execute(
                text("""
                    SELECT
                        profile,
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE passed) as passed,
                        COUNT(*) FILTER (WHERE passed AND outcome = 'SUCCESS') as success,
                        COUNT(*) FILTER (WHERE passed AND outcome = 'FAILURE') as failure,
                        ROUND(AVG(score)::numeric, 1) as avg_score
                    FROM ai_signal_shadow_evaluations
                    WHERE evaluated_at > :since
                    GROUP BY profile
                """),
                {"since": since_24h},
            ).mappings().all()

            profiles = {}
            for row in shadow_agg:
                profiles[row["profile"]] = {
                    "total": row["total"],
                    "passed": row["passed"],
                    "success": row["success"],
                    "failure": row["failure"],
                    "avg_score": float(row["avg_score"]) if row["avg_score"] else None,
                    "win_rate": round(row["success"] / max(row["passed"], 1) * 100, 1) if row["passed"] else 0,
                }

            # Top confluencias ganadoras
            confluences = db.execute(
                text("""
                    SELECT
                        features_snapshot->>'has_ob' as ob,
                        features_snapshot->>'has_killzone' as killzone,
                        features_snapshot->>'htf_aligned' as htf,
                        features_snapshot->>'structure_type' as structure,
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE outcome = 'SUCCESS') as success
                    FROM ai_signal_shadow_evaluations
                    WHERE evaluated_at > :since
                        AND profile = 'bot_match'
                        AND passed = true
                    GROUP BY 1, 2, 3, 4
                    ORDER BY success DESC, total DESC
                    LIMIT 5
                """),
                {"since": since_24h},
            ).mappings().all()

            return {
                "profiles": profiles,
                "total_evaluations": sum(p["total"] for p in profiles.values()),
                "top_confluences": [
                    {
                        "ob": row["ob"],
                        "killzone": row["killzone"],
                        "htf": row["htf"],
                        "structure": row["structure"],
                        "total": row["total"],
                        "success": row["success"],
                    }
                    for row in confluences
                ],
            }
    except Exception as exc:
        logger.warning(f"[engine_narrator] Shadow metrics failed: {exc}")
        return {"error": str(exc)}


def _gather_circuit_breaker_metrics() -> dict:
    """Recopila estado del circuit breaker por bot."""
    try:
        with SessionLocal() as db:
            bots = db.execute(
                select(BotConfig.bot_name, BotConfig.ai_signal_config)
                .where(BotConfig.ai_signal_mode == True)
                .where(BotConfig.status == "active")
            ).all()

            cb_status = {}
            for bot_name, cfg in bots:
                if not cfg:
                    continue
                cb_state = cfg.get("circuit_breaker_state", {})
                blocked_tiers = [
                    tier for tier, state in cb_state.items()
                    if isinstance(state, dict) and state.get("tripped_at")
                ]
                if blocked_tiers:
                    cb_status[bot_name] = {
                        "blocked_tiers": blocked_tiers,
                        "state": "blocked",
                    }
                else:
                    cb_status[bot_name] = {"state": "clear"}

            return {
                "bots_affected": len([b for b in cb_status.values() if b["state"] == "blocked"]),
                "total_active": len(cb_status),
                "by_bot": cb_status,
            }
    except Exception as exc:
        logger.warning(f"[engine_narrator] Circuit breaker metrics failed: {exc}")
        return {"error": str(exc)}


def _gather_position_metrics() -> dict:
    """Recopila métricas de posiciones."""
    try:
        with SessionLocal() as db:
            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

            # Posiciones abiertas
            open_pos = db.execute(
                select(func.count(Position.id), func.sum(Position.realized_pnl))
                .where(Position.status == "open")
                .where(Position.source == "ai_bot")
            ).one()

            # Posiciones cerradas 24h
            closed = db.execute(
                select(
                    func.count(Position.id),
                    func.sum(Position.realized_pnl),
                    func.avg(
                        func.extract('epoch', Position.closed_at) -
                        func.extract('epoch', Position.opened_at)
                    ) / 60
                )
                .where(Position.status == "closed")
                .where(Position.closed_at > since_24h)
                .where(Position.source == "ai_bot")
            ).one()

            return {
                "open": {
                    "count": open_pos[0] or 0,
                    "unrealized_pnl": float(open_pos[1] or 0),
                },
                "closed_24h": {
                    "count": closed[0] or 0,
                    "realized_pnl": float(closed[1] or 0),
                    "avg_duration_min": round(float(closed[2] or 0), 1),
                },
            }
    except Exception as exc:
        logger.warning(f"[engine_narrator] Position metrics failed: {exc}")
        return {"error": str(exc)}


async def gather_engine_metrics() -> dict:
    """Recopila métricas relevantes del motor IA y la plataforma en paralelo."""
    metrics: dict = {"collected_at": datetime.now(timezone.utc).isoformat()}

    health_task = asyncio.create_task(_gather_health())
    db_task = asyncio.create_task(asyncio.to_thread(_gather_db_metrics))
    model_task = asyncio.create_task(asyncio.to_thread(_gather_model_metrics))
    shadow_task = asyncio.create_task(asyncio.to_thread(_gather_shadow_metrics))
    cb_task = asyncio.create_task(asyncio.to_thread(_gather_circuit_breaker_metrics))
    pos_task = asyncio.create_task(asyncio.to_thread(_gather_position_metrics))

    health, db_data, model, shadow, cb, pos = await asyncio.gather(
        health_task, db_task, model_task, shadow_task, cb_task, pos_task
    )

    metrics["health"] = health
    metrics.update(db_data)
    metrics["model"] = model
    metrics["shadow_mode"] = shadow
    metrics["circuit_breaker"] = cb
    metrics["positions"] = pos

    return metrics


def _build_summary_prompt(metrics: dict) -> str:
    """Construye el prompt para el resumen narrativo."""
    health = metrics.get("health", {})
    gate = metrics.get("deployment_gate", {})
    model = metrics.get("model", {})
    bots = metrics.get("bots", {})
    sig24 = metrics.get("signals_24h", {})
    shadow = metrics.get("shadow_mode", {})
    cb = metrics.get("circuit_breaker", {})
    pos = metrics.get("positions", {})

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
        f"- Shadow mode (24h): {shadow.get('total_evaluations', 'N/A')} evaluaciones",
        f"  • bot_match: {shadow.get('profiles', {}).get('bot_match', {}).get('passed', 0)} pasaron, win rate {shadow.get('profiles', {}).get('bot_match', {}).get('win_rate', 0)}%",
        f"  • strict: {shadow.get('profiles', {}).get('strict', {}).get('passed', 0)} pasaron",
        f"  • moderate: {shadow.get('profiles', {}).get('moderate', {}).get('passed', 0)} pasaron",
        f"  • relaxed: {shadow.get('profiles', {}).get('relaxed', {}).get('passed', 0)} pasaron",
        f"  • Top confluencias: {shadow.get('top_confluences', [])}",
        "",
        f"- Circuit breaker: {cb.get('bots_affected', 0)}/{cb.get('total_active', 0)} bots afectados",
        f"  • Bots bloqueados: {[k for k,v in cb.get('by_bot', {}).items() if v.get('state') == 'blocked'] or 'Ninguno'}",
        "",
        f"- Posiciones: {pos.get('open', {}).get('count', 0)} abiertas, {pos.get('closed_24h', {}).get('count', 0)} cerradas 24h",
        f"  • PnL cerrado 24h: {pos.get('closed_24h', {}).get('realized_pnl', 0):.2f} USDT",
        f"  • Duración promedio: {pos.get('closed_24h', {}).get('avg_duration_min', 0):.1f} min",
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
        # If the local LLM is unavailable and remote fallback is disabled,
        # try a mechanical FAQ answer from the knowledge base.
        if model_used == "local_unavailable":
            faq_answer = answer_faq(question, allowed_sources=None, top_k=5)
            if faq_answer and "No encontré información" not in faq_answer:
                return {
                    "question": question,
                    "answer": faq_answer,
                    "model_used": "faq",
                    "metrics_snapshot": metrics,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            answer = "El asistente de IA local no está disponible en este momento. Inténtalo más tarde."
            model_used = "unavailable"
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
    local_unavailable = False
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
                if _UNAVAILABLE_MESSAGE in event.get("message", ""):
                    local_unavailable = True
                else:
                    yield _sse_event("error", {"message": event.get("message", "Error desconocido")})
    except Exception as exc:
        logger.warning(f"[engine_narrator] Question stream failed: {exc}")
        yield _sse_event("error", {"message": str(exc)})
        return

    if local_unavailable:
        faq_answer = answer_faq(question, allowed_sources=None, top_k=5)
        if faq_answer and "No encontré información" not in faq_answer:
            for word in faq_answer.split():
                yield _sse_event("token", {"content": word + " "})
            yield _sse_event("answer", {
                "question": question,
                "answer": faq_answer,
                "model_used": "faq",
                "metrics_snapshot": metrics,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            })
        else:
            yield _sse_event("error", {"message": _UNAVAILABLE_MESSAGE})


def _sse_event(event: str, data: dict) -> str:
    """Formatea un evento SSE."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
