"""
Servicio de health checks ejecutable desde dentro del backend container.
No requiere Docker CLI ni acceso al host.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from app.services.cache import sync_redis
from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from sqlalchemy import select, text

# ─────────────────────────────────────────
# Config
# ─────────────────────────────────────────
PENDING_SIGNALS_THRESHOLD = 500
SIGNALS_2H_MIN = 3
SCORE_AVG_MIN = 50.0
CELERY_RETRY_THRESHOLD = 20


class HealthResult:
    def __init__(self, name: str, healthy: bool, info: dict | None = None, issues: list | None = None):
        self.name = name
        self.healthy = healthy
        self.info = info or {}
        self.issues = issues or []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "info": self.info,
            "issues": self.issues,
        }


# ═══════════════════════════════════════════
# 1. Infra / Sistema
# ═══════════════════════════════════════════
def check_infra() -> HealthResult:
    issues = []
    info = {}

    # Memoria desde /proc/meminfo (disponible en Linux containers)
    try:
        meminfo = Path("/proc/meminfo").read_text()
        mem = {}
        for line in meminfo.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                mem[key.strip()] = int(val.strip().split()[0])  # kB

        total = mem.get("MemTotal", 1)
        free = mem.get("MemFree", 0)
        available = mem.get("MemAvailable", free)
        buffers = mem.get("Buffers", 0)
        cached = mem.get("Cached", 0)

        used = total - available
        info["ram_total_mb"] = round(total / 1024, 1)
        info["ram_used_mb"] = round(used / 1024, 1)
        info["ram_free_pct"] = round(available / total * 100, 1)
        info["ram_used_pct"] = round(used / total * 100, 1)

        if info["ram_free_pct"] < 10:
            issues.append(f"🔴 RAM libre: {info['ram_free_pct']}%")

        # Swap
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        if swap_total > 0:
            swap_used_pct = round((swap_total - swap_free) / swap_total * 100, 1)
            info["swap_used_pct"] = swap_used_pct
            if swap_used_pct > 80:
                issues.append(f"🔴 Swap usage: {swap_used_pct}%")
    except Exception as exc:
        issues.append(f"🟡 No se pudo leer /proc/meminfo: {exc}")

    # Disco
    try:
        disk = subprocess.run(
            "df -h / | awk 'NR==2 {print $5}' | tr -d '%'",
            shell=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if disk:
            info["disk_used_pct"] = int(disk)
            if int(disk) > 90:
                issues.append(f"🔴 Disco usage: {disk}%")
    except Exception:
        pass

    # Load average
    try:
        loadavg = Path("/proc/loadavg").read_text().split()
        info["load_1m"] = float(loadavg[0])
    except Exception:
        pass

    return HealthResult("infra", len(issues) == 0, info, issues)


# ═══════════════════════════════════════════
# 2. Logs de errores recientes
# ═══════════════════════════════════════════
def check_logs() -> HealthResult:
    issues = []
    info = {}

    # Buscar en archivos de log si existen
    log_paths = [
        "/var/log/trading-bot-worker.log",
        "/var/log/trading-bot-backend.log",
    ]

    error_patterns = [
        ("NameError", "NameError en código"),
        ("AttributeError.*pd_score", "AttributeError pd_score"),
        ("AttributeError.*kz", "AttributeError kz"),
        ("Traceback", "Traceback detectado"),
        ("FATAL.*database", "Error fatal de DB"),
        ("Connection refused", "Problemas de conexión"),
    ]

    total_errors = 0
    for log_path in log_paths:
        try:
            p = Path(log_path)
            if not p.exists():
                continue
            # Leer últimas 500 líneas
            lines = p.read_text().splitlines()[-500:]
            text_block = "\n".join(lines)
            for pattern, label in error_patterns:
                import re
                matches = re.findall(pattern, text_block, re.IGNORECASE)
                if matches:
                    count = len(matches)
                    total_errors += count
                    issues.append(f"🔴 {label} ({count}x en {log_path})")
        except Exception:
            pass

    info["log_files_checked"] = len(log_paths)
    info["total_errors_found"] = total_errors

    return HealthResult("logs", len(issues) == 0, info, issues)


# ═══════════════════════════════════════════
# 3. Base de Datos
# ═══════════════════════════════════════════
async def check_database() -> HealthResult:
    issues = []
    info = {}

    try:
        async with AsyncSessionLocal() as db:
            # Bots por status
            bots = await db.execute(text("SELECT status, COUNT(*) as c FROM bot_configs GROUP BY status"))
            bots_by_status = {r[0]: r[1] for r in bots.all()}
            info["bots"] = bots_by_status

            # Señales últimas 2h
            since_2h = datetime.now(timezone.utc) - timedelta(hours=2)
            sigs_2h = await db.execute(
                text("SELECT COUNT(*) as c FROM ai_signals WHERE created_at > :since"),
                {"since": since_2h},
            )
            sig_count_2h = sigs_2h.scalar()
            info["signals_2h"] = sig_count_2h

            # Señales últimas 24h
            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            agg = await db.execute(
                text("""
                    SELECT COUNT(*) as total,
                           COUNT(*) FILTER (WHERE quality_tier = 'STRONG') as strong,
                           COUNT(*) FILTER (WHERE quality_tier = 'MODERATE') as moderate,
                           COUNT(*) FILTER (WHERE quality_tier = 'WEAK') as weak,
                           ROUND(AVG(score)::numeric, 1) as avg_score
                    FROM ai_signals WHERE created_at > :since
                """),
                {"since": since_24h},
            )
            row = agg.mappings().one()
            info["signals_24h"] = dict(row)

            # Pending signals
            pending = await db.execute(
                text("SELECT COUNT(*) as c FROM ai_signals WHERE outcome = 'PENDING'")
            )
            pending_count = pending.scalar()
            info["pending_signals"] = pending_count

            # Posiciones abiertas
            positions = await db.execute(
                text("SELECT symbol, side, unrealized_pnl FROM positions WHERE status = 'open'")
            )
            info["open_positions"] = [
                {"symbol": r[0], "side": r[1], "unrealized_pnl": float(r[2]) if r[2] else 0}
                for r in positions.all()
            ]

            # Último scan automático (independientemente de si generó señal)
            last_scan = await db.execute(
                text("SELECT MAX(scanned_at) as last FROM ai_latest_scans")
            )
            last_scan_at = last_scan.scalar()
            info["last_scan_at"] = last_scan_at.isoformat() if last_scan_at else None

            # Bot logs de error recientes
            recent_logs = await db.execute(
                text("""
                    SELECT event_type, message, created_at
                    FROM bot_logs
                    WHERE created_at > :since AND event_type LIKE '%error%'
                    ORDER BY created_at DESC LIMIT 5
                """),
                {"since": since_2h},
            )
            info["recent_errors"] = [
                {"event_type": r[0], "message": (r[1] or "")[:100], "created_at": r[2].isoformat() if r[2] else None}
                for r in recent_logs.all()
            ]
    except Exception as exc:
        return HealthResult("database", False, {}, [f"🔴 DB query failed: {exc}"])

    scanner_stuck = False
    if last_scan_at:
        scan_age_min = (datetime.now(timezone.utc) - last_scan_at).total_seconds() / 60
        info["last_scan_age_min"] = round(scan_age_min, 1)
        if scan_age_min > 120:
            scanner_stuck = True
            issues.append(f"🔴 Último scan hace {scan_age_min:.0f} min — scanner posiblemente atascado")
        elif scan_age_min > 30:
            issues.append(f"🟡 Último scan hace {scan_age_min:.0f} min")

    if sig_count_2h == 0:
        if scanner_stuck:
            issues.append("🔴 0 señales en últimas 2h y scanner atascado")
        else:
            issues.append("🟡 0 señales en últimas 2h — scanner activo pero sin confluencias")
    elif sig_count_2h < SIGNALS_2H_MIN:
        issues.append(f"🟡 Solo {sig_count_2h} señales en 2h (min={SIGNALS_2H_MIN})")

    avg_score = row.get("avg_score")
    if avg_score is not None and float(avg_score) < SCORE_AVG_MIN:
        issues.append(f"🟡 Score promedio 24h = {avg_score} (min={SCORE_AVG_MIN})")

    if pending_count > PENDING_SIGNALS_THRESHOLD:
        issues.append(f"🔴 {pending_count} signals pending (>{PENDING_SIGNALS_THRESHOLD})")

    return HealthResult("database", len(issues) == 0, info, issues)


# ═══════════════════════════════════════════
# 4. Modelos ML
# ═══════════════════════════════════════════
def check_models() -> HealthResult:
    issues = []
    info = {}

    models_dir = Path("/app/ai/models")
    weights_path = models_dir / "adaptive_weights.json"

    try:
        if weights_path.exists():
            weights = json.loads(weights_path.read_text())
            # Buscar timestamp en varios campos posibles
            last_updated = weights.get("last_updated") or weights.get("calibrated_at") or weights.get("generated_at") or "N/A"
            info["weights_last_updated"] = last_updated
            info["global_keys"] = len(weights.get("global", {}))
            by_bot = weights.get("by_bot", {}) or {}
            info["by_bot_keys"] = len(by_bot)
            info["by_ticker_keys"] = len(weights.get("by_ticker", {}))
            if info["by_bot_keys"] == 0:
                issues.append("🟡 by_bot vacío — normal hasta ≥50 trades cerrados por bot (bootstrap activo)")
            # Verificar antigüedad de pesos
            if last_updated != "N/A":
                try:
                    lu = datetime.fromisoformat(last_updated)
                    if lu.tzinfo is None:
                        lu = lu.replace(tzinfo=timezone.utc)
                    hours_ago = (datetime.now(timezone.utc) - lu).total_seconds() / 3600
                    info["weights_age_h"] = round(hours_ago, 1)
                    if hours_ago > 48:
                        issues.append(f"🟡 Pesos adaptativos no actualizados hace {hours_ago:.1f}h (esperado <24h)")
                except Exception:
                    pass
        else:
            # No pesos adaptativos legacy; verificar si existen modelos ensemble o retrain
            ensemble_path = models_dir / "ensemble_v1.pkl"
            retrain_meta_path = models_dir / "retrain_meta.json"
            if ensemble_path.exists() or retrain_meta_path.exists():
                info["fallback_models"] = [
                    p.name for p in [ensemble_path, retrain_meta_path] if p.exists()
                ]
                # Modo simplificado: se usan modelos ensemble/retrain globales
            else:
                issues.append("🔴 adaptive_weights.json no encontrado y tampoco hay modelos ensemble/retrain")
    except Exception as exc:
        issues.append(f"🔴 Error leyendo adaptive_weights.json: {exc}")

    # Directorios de modelos per-bot
    bots_dir = models_dir / "bots"
    if bots_dir.exists():
        bot_dirs = [d for d in bots_dir.iterdir() if d.is_dir()]
        info["bot_model_dirs"] = len(bot_dirs)
        # Verificar si los modelos per-bot tienen archivos recientes
        stale_bots = 0
        for d in bot_dirs:
            af_file = d / "anti_fake.pkl"
            if af_file.exists():
                mtime = datetime.fromtimestamp(af_file.stat().st_mtime, tz=timezone.utc)
                age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
                if age_h > 72:
                    stale_bots += 1
        if stale_bots:
            issues.append(f"🟡 {stale_bots} modelos per-bot sin actualizar >72h")
    else:
        info["bot_model_dirs"] = 0
        # Modo simplificado: no se usan modelos per-bot

    # Último drift check (task monitor_feature_drift escribe drift_monitor:last_run)
    try:
        last_run_raw = sync_redis.get("drift_monitor:last_run")
        if last_run_raw:
            last_run = datetime.fromisoformat(last_run_raw)
            hours_ago = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
            info["last_drift_check_h"] = round(hours_ago, 1)
            if hours_ago > 8:
                issues.append(f"🟡 Último drift check hace {hours_ago:.1f}h (esperado <4h)")
        else:
            # Fallback legacy: feature_importance_drift se actualiza durante retrain
            import asyncpg
            dsn = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
            if dsn:
                async def _drift():
                    conn = await asyncpg.connect(dsn=dsn)
                    try:
                        row = await conn.fetchrow(
                            "SELECT MAX(created_at) as last FROM feature_importance_drift"
                        )
                        return row["last"] if row else None
                    finally:
                        await conn.close()

                last_drift = asyncio.get_event_loop().run_until_complete(_drift())
                if last_drift:
                    hours_ago = (datetime.now(timezone.utc) - last_drift).total_seconds() / 3600
                    info["last_drift_check_h"] = round(hours_ago, 1)
                    if hours_ago > 168:
                        issues.append(f"🟡 Último drift check hace {hours_ago:.1f}h (esperado <4h)")
                else:
                    issues.append("🟡 No hay registros de drift reciente")
    except Exception:
        pass

    return HealthResult("ml_models", len(issues) == 0, info, issues)


# ═══════════════════════════════════════════
# 5. Celery Health
# ═══════════════════════════════════════════
def check_celery() -> HealthResult:
    issues = []
    info = {}

    try:
        from app.services.celery_app import celery_app
        inspect = celery_app.control.inspect()
        active = inspect.active()
        registered = inspect.registered()
        stats = inspect.stats()

        info["workers_online"] = len(stats) if stats else 0
        info["tasks_registered_sample"] = list(registered.values())[0][:5] if registered else []

        if not stats:
            issues.append("🔴 No hay workers de Celery conectados")
    except Exception as exc:
        issues.append(f"🟡 No se pudo inspeccionar Celery: {exc}")

    return HealthResult("celery", len(issues) == 0, info, issues)


# ═══════════════════════════════════════════
# 6. Exchange / Equity
# ═══════════════════════════════════════════
async def check_exchange() -> HealthResult:
    issues = []
    info = {}

    try:
        from app.exchanges.factory import create_exchange
        from app.models.exchange_account import ExchangeAccount

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ExchangeAccount).where(ExchangeAccount.is_active == True))
            accounts = result.scalars().all()
            acc_data = []
            for acc in accounts:
                try:
                    ex = create_exchange(acc)
                    eq = await ex.get_equity()
                    await ex.close()
                    total = float(eq.total_equity) if hasattr(eq, "total_equity") else float(str(eq))
                    acc_data.append({"label": acc.label, "exchange": acc.exchange, "equity": total, "ok": True})
                except Exception as exc:
                    acc_data.append({"label": acc.label, "exchange": acc.exchange, "error": str(exc)[:200], "ok": False})

            info["accounts"] = acc_data
            for acc in acc_data:
                if not acc.get("ok"):
                    issues.append(f"🔴 Exchange {acc['label']}: {acc.get('error', 'unknown')}")
    except Exception as exc:
        issues.append(f"🟡 No se pudo chequear exchange: {exc}")

    return HealthResult("exchange", len(issues) == 0, info, issues)


# ═══════════════════════════════════════════
# 7. Shadow Mode (Fase D)
# ═══════════════════════════════════════════
def check_shadow_mode() -> HealthResult:
    """Check shadow-mode Redis keys for signal_id=None regressions."""
    from app.services.shadow_monitor_service import run_shadow_monitor_check

    try:
        report = run_shadow_monitor_check(save_history=True)
    except Exception as exc:
        return HealthResult("shadow_mode", False, {}, [f"🔴 Shadow monitor failed: {exc}"])

    issues = []
    info = {
        "candidate_total": report["candidate"]["total_in_window"],
        "candidate_resolved": report["candidate"]["resolved"],
        "candidate_none_recent": report["candidate"]["none_recent"],
        "candidate_recent": report["candidate"]["recent_predictions"],
        "live_total": report["live"]["total_in_window"],
        "live_none_recent": report["live"]["none_recent"],
        "candidate_eval": report["candidate_eval"],
    }

    if report["candidate"]["none_recent"] > 0:
        issues.append(
            f"🔴 {report['candidate']['none_recent']} candidate predictions with signal_id='None'"
        )
    if report["live"]["none_recent"] > 0:
        issues.append(
            f"🔴 {report['live']['none_recent']} live predictions with signal_id='None'"
        )
    if report["candidate"]["recent_predictions"] == 0:
        issues.append("🟡 No recent candidate predictions")
    if report["live"]["recent_predictions"] == 0:
        issues.append("🟡 No recent live predictions")

    return HealthResult("shadow_mode", len(issues) == 0, info, issues)


# ═══════════════════════════════════════════
# Full Report
# ═══════════════════════════════════════════
async def run_full_check() -> dict:
    """Ejecuta todos los checks y devuelve un reporte completo."""
    results = {
        "infra": check_infra(),
        "logs": check_logs(),
        "database": await check_database(),
        "ml_models": check_models(),
        "celery": check_celery(),
        "exchange": await check_exchange(),
    }

    all_issues = []
    for r in results.values():
        all_issues.extend(r.issues)

    criticals = [i for i in all_issues if i.startswith("🔴")]
    warnings = [i for i in all_issues if i.startswith("🟡")]

    status = "healthy"
    if criticals:
        status = "critical"
    elif warnings:
        status = "warning"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks": {k: v.to_dict() for k, v in results.items()},
        "summary": {
            "total_issues": len(all_issues),
            "criticals": len(criticals),
            "warnings": len(warnings),
            "issues_list": all_issues,
        },
    }


def generate_shareable_log(report: dict) -> str:
    """Genera un log de texto plano para compartir."""
    lines = []
    lines.append("=" * 60)
    lines.append("TRADING BOT PLATFORM — SYSTEM HEALTH REPORT")
    lines.append(f"Generado: {report['timestamp']}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"ESTADO GLOBAL: {report['status'].upper()}")
    lines.append(f"  Críticos: {report['summary']['criticals']}")
    lines.append(f"  Advertencias: {report['summary']['warnings']}")
    lines.append("")

    for name, check in report["checks"].items():
        status = "✅ OK" if check["healthy"] else "❌ ISSUES"
        lines.append(f"[{name.upper()}] {status}")
        if check["info"]:
            for k, v in check["info"].items():
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, default=str)[:120]
                lines.append(f"  • {k}: {v}")
        for issue in check["issues"]:
            lines.append(f"  {issue}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
