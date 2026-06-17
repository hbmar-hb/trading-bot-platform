#!/usr/bin/env python3
"""
Monitor completo de salud del sistema Trading Bot Platform.

Revisa cada X minutos:
  1. Contenedores Docker (estado, reinicios, memoria)
  2. Logs recientes de backend/worker (NameError, Traceback, errores críticos)
  3. Métricas de DB: bots, señales, posiciones, signals pending
  4. Estado de modelos ML: último retrain, samples, drift
  5. Celery: colas, workers, retries
  6. Exchange: equity, conectividad

Uso manual:
    python3 backend/scripts/monitor_system.py

Para cron cada 5 minutos:
    */5 * * * * cd /home/deploy/apps/trading-bot-platform && python3 backend/scripts/monitor_system.py >> /var/log/trading-bot-monitor.log 2>&1

Exit code:
    0 = healthy
    1 = warning
    2 = critical
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─────────────────────────────────────────
# Paths
# ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

LOG_FILE = Path("/var/log/trading-bot-monitor.log")
STATE_FILE = Path("/tmp/trading-bot-monitor-state.json")
ENV_FILE = PROJECT_ROOT / ".env"

# ─────────────────────────────────────────
# Config
# ─────────────────────────────────────────
MEM_THRESHOLD = 85.0
VPS_MEM_THRESHOLD = 10.0
SWAP_THRESHOLD = 80.0
PENDING_SIGNALS_THRESHOLD = 500
SIGNALS_2H_MIN = 3
SCORE_AVG_MIN = 50.0
CELERY_RETRY_THRESHOLD = 20  # en 2h
COOLDOWN_MINUTES = 30

# ─────────────────────────────────────────
# Colores terminal
# ─────────────────────────────────────────
R = "\033[91m"
Y = "\033[93m"
G = "\033[92m"
B = "\033[94m"
RST = "\033[0m"


def _load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    return env


ENV = _load_env()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _shell(cmd: str, timeout: int = 10) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as exc:
        return f"[ERROR: {exc}]"


def _docker_logs(service: str, since: str = "5m") -> str:
    return _shell(f"docker logs trading-bot-platform-{service}-1 --since {since} 2>&1", timeout=15)


def _send_alert(title: str, body: str, level: str = "essential") -> None:
    """Envía alerta vía Telegram/Discord si están configurados."""
    try:
        from app.services.notifier import send_telegram_sync
        msg = f"🚨 <b>{title}</b>\n\n{body}"
        send_telegram_sync(msg, level=level)
    except Exception:
        pass


# ═══════════════════════════════════════════
# 1. Docker / Infra
# ═══════════════════════════════════════════
def check_docker() -> dict:
    services = ["backend", "celery_worker", "celery_beat", "postgres", "redis", "pgbouncer", "frontend"]
    issues = []
    info = {}

    for svc in services:
        status = _shell(f"docker ps --filter name=trading-bot-platform-{svc}-1 --format '{{{{.Status}}}}'")
        if not status or "Up" not in status:
            issues.append(f"🔴 {svc}: {status or 'NOT RUNNING'}")
        else:
            info[svc] = status

    # Memoria VPS
    mem = _shell("free | awk '/Mem:/ {printf \"%.1f\", $3/$2 * 100.0}'")
    swap = _shell("free | awk '/Swap:/ {if($2>0) printf \"%.1f\", $3/$2 * 100.0; else print 0}'")
    mem_free = _shell("free | awk '/Mem:/ {printf \"%.1f\", $7/$2 * 100.0}'")

    if mem and float(mem) > MEM_THRESHOLD:
        issues.append(f"🔴 VPS RAM usage: {mem}%")
    if mem_free and float(mem_free) < VPS_MEM_THRESHOLD:
        issues.append(f"🔴 VPS RAM free: {mem_free}%")
    if swap and float(swap) > SWAP_THRESHOLD:
        issues.append(f"🔴 VPS Swap usage: {swap}%")

    # Disk
    disk = _shell("df -h / | awk 'NR==2 {print $5}' | tr -d '%'")
    if disk and int(disk) > 90:
        issues.append(f"🔴 Disk usage: {disk}%")

    return {"healthy": len(issues) == 0, "issues": issues, "info": info, "mem": mem, "swap": swap, "disk": disk}


# ═══════════════════════════════════════════
# 2. Logs recientes (errores críticos)
# ═══════════════════════════════════════════
def check_logs() -> dict:
    issues = []
    patterns = [
        ("NameError", "🔴 NameError en código — posible bug de refactor"),
        ("AttributeError.*pd_score", "🔴 AttributeError pd_score — confluence engine roto"),
        ("AttributeError.*kz", "🔴 AttributeError kz — confluence engine roto"),
        ("Traceback", "🟡 Traceback detectado en worker"),
        ("Received unregistered task", "🟡 Task de Celery no registrado"),
        ("bingx requires to release all resources", "🟡 Sesiones BingX sin cerrar"),
        ("Connection refused|Connection reset|timeout", "🟡 Problemas de red/DB"),
        ("FATAL.*database", "🔴 Error fatal de base de datos"),
    ]

    worker_logs = _docker_logs("celery_worker", "10m")
    backend_logs = _docker_logs("backend", "10m")
    combined = worker_logs + "\n" + backend_logs

    for pattern, label in patterns:
        import re
        matches = re.findall(pattern, combined, re.IGNORECASE)
        if matches:
            count = len(matches)
            issues.append(f"{label} ({count}x en 10m)")

    return {"healthy": len(issues) == 0, "issues": issues}


# ═══════════════════════════════════════════
# 3. Métricas de Base de Datos
# ═══════════════════════════════════════════
def check_database() -> dict:
    try:
        import asyncpg
        import asyncio

        dsn = ENV.get("DATABASE_URL", "").replace("+asyncpg", "")
        # Si corremos fuera del container, reemplazar pgbouncer:6432 por localhost:5433
        if dsn and "pgbouncer" in dsn:
            dsn = dsn.replace("pgbouncer:6432", "localhost:5433")
        if not dsn:
            return {"healthy": False, "issues": ["🔴 DATABASE_URL no configurada"], "data": {}}

        async def _query():
            conn = await asyncpg.connect(dsn=dsn)
            try:
                # Bots
                bots = await conn.fetch(
                    "SELECT status, COUNT(*) as c FROM bot_configs GROUP BY status"
                )
                bots_by_status = {r["status"]: r["c"] for r in bots}

                # Señales últimas 2h
                since_2h = datetime.now(timezone.utc) - timedelta(hours=2)
                sigs_2h = await conn.fetch(
                    "SELECT COUNT(*) as c FROM ai_signals WHERE created_at > $1", since_2h
                )
                sig_count_2h = sigs_2h[0]["c"]

                # Señales últimas 24h
                since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
                agg = await conn.fetchrow(
                    """
                    SELECT COUNT(*) as total,
                           COUNT(*) FILTER (WHERE quality_tier = 'STRONG') as strong,
                           COUNT(*) FILTER (WHERE quality_tier = 'MODERATE') as moderate,
                           COUNT(*) FILTER (WHERE quality_tier = 'WEAK') as weak,
                           ROUND(AVG(score)::numeric, 1) as avg_score
                    FROM ai_signals WHERE created_at > $1
                    """,
                    since_24h,
                )

                # Pending signals (outcome = 'PENDING')
                pending = await conn.fetch(
                    "SELECT COUNT(*) as c FROM ai_signals WHERE outcome = 'PENDING'"
                )
                pending_count = pending[0]["c"]

                # Posiciones abiertas
                positions = await conn.fetch(
                    "SELECT symbol, side, unrealized_pnl FROM positions WHERE status = 'open'"
                )

                # Últimos bot_logs de error
                recent_logs = await conn.fetch(
                    """
                    SELECT event_type, message, created_at
                    FROM bot_logs
                    WHERE created_at > $1 AND event_type LIKE '%error%'
                    ORDER BY created_at DESC LIMIT 5
                    """,
                    since_2h,
                )

                # Signal logs recientes
                outcomes = await conn.fetch(
                    "SELECT COUNT(*) as c FROM signal_logs WHERE received_at > $1",
                    since_2h,
                )

                return {
                    "bots": bots_by_status,
                    "signals_2h": sig_count_2h,
                    "signals_24h": dict(agg) if agg else {},
                    "pending": pending_count,
                    "positions": [dict(p) for p in positions],
                    "recent_errors": [dict(r) for r in recent_logs],
                    "outcomes_2h": outcomes[0]["c"] if outcomes else 0,
                }
            finally:
                await conn.close()

        data = asyncio.run(_query())
    except Exception as exc:
        return {"healthy": False, "issues": [f"🔴 DB query failed: {exc}"], "data": {}}

    issues = []
    if data.get("signals_2h", 0) == 0:
        issues.append("🔴 0 señales en últimas 2h — scanner posiblemente atascado")
    elif data.get("signals_2h", 0) < SIGNALS_2H_MIN:
        issues.append(f"🟡 Solo {data['signals_2h']} señales en 2h (min={SIGNALS_2H_MIN})")

    avg_score = data.get("signals_24h", {}).get("avg_score")
    if avg_score is not None and float(avg_score) < SCORE_AVG_MIN:
        issues.append(f"🟡 Score promedio 24h = {avg_score} (min={SCORE_AVG_MIN})")

    if data.get("pending", 0) > PENDING_SIGNALS_THRESHOLD:
        issues.append(f"🔴 {data['pending']} signals pending (>{PENDING_SIGNALS_THRESHOLD})")

    return {"healthy": len(issues) == 0, "issues": issues, "data": data}


# ═══════════════════════════════════════════
# 4. Estado de Modelos ML
# ═══════════════════════════════════════════
def check_models() -> dict:
    issues = []
    info = {}

    # Verificar archivo de pesos adaptativos
    weights_path = PROJECT_ROOT / "backend" / "app" / "ai" / "models" / "adaptive_weights.json"
    # En producción el volumen monta en /app/ai/models dentro del container
    try:
        import json
        # Intentar leer desde dentro del container
        raw = _shell(
            "docker exec trading-bot-platform-backend-1 cat /app/ai/models/adaptive_weights.json",
            timeout=5,
        )
        if raw.startswith("{"):
            weights = json.loads(raw)
            info["weights_last_updated"] = weights.get("last_updated", "N/A")
            info["global_keys"] = len(weights.get("global", {}))
            info["by_bot_keys"] = len(weights.get("by_bot", {}))
            info["by_ticker_keys"] = len(weights.get("by_ticker", {}))
            if info["by_bot_keys"] == 0:
                issues.append("🟡 adaptive_weights.json: by_bot vacío (bots sin samples suficientes)")
        else:
            issues.append("🔴 adaptive_weights.json no legible desde container")
    except Exception as exc:
        issues.append(f"🟡 No se pudo leer adaptive_weights.json: {exc}")

    # Verificar archivos de modelo per-bot
    try:
        bot_models = _shell(
            "docker exec trading-bot-platform-backend-1 ls -1 /app/ai/models/bots/ 2>/dev/null || echo 'NONE'",
            timeout=5,
        )
        if bot_models == "NONE":
            issues.append("🟡 No hay directorio /app/ai/models/bots/ (modelos per-bot no creados)")
        else:
            bot_count = len([l for l in bot_models.splitlines() if l.strip()])
            info["bot_model_dirs"] = bot_count
    except Exception:
        pass

    # Verificar último drift check
    try:
        import asyncpg
        import asyncio

        dsn = ENV.get("DATABASE_URL", "").replace("+asyncpg", "")
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

            last_drift = asyncio.run(_drift())
            if last_drift:
                hours_ago = (datetime.now(timezone.utc) - last_drift).total_seconds() / 3600
                info["last_drift_check_h"] = round(hours_ago, 1)
                if hours_ago > 8:
                    issues.append(f"🟡 Último drift check hace {hours_ago:.1f}h (esperado <4h)")
            else:
                issues.append("🟡 No hay registros de feature_importance_drift")
    except Exception:
        pass

    return {"healthy": len(issues) == 0, "issues": issues, "info": info}


# ═══════════════════════════════════════════
# 5. Celery Health
# ═══════════════════════════════════════════
def check_celery() -> dict:
    issues = []
    info = {}

    # Workers activos
    registered = _shell(
        "docker exec trading-bot-platform-backend-1 python -m celery -A app.services.celery_app inspect registered 2>&1 | head -5",
        timeout=15,
    )
    if "Error" in registered or not registered:
        issues.append("🔴 Celery inspect failed — worker no responde")
    else:
        info["registered_tasks_sample"] = registered[:100]

    # Revisar retries recientes en logs (excluir el task retry_pending_sl_orders que es normal)
    worker_logs = _docker_logs("celery_worker", "2h")
    import re
    retry_matches = re.findall(r"retry\b", worker_logs, re.IGNORECASE)
    # Filtrar líneas que son solo el nombre del task retry_pending_sl_orders
    sl_retry_lines = [l for l in worker_logs.splitlines() if "retry_pending_sl_orders" in l]
    retry_count = max(0, len(retry_matches) - len(sl_retry_lines) * 2)
    info["retries_2h"] = retry_count
    if retry_count > CELERY_RETRY_THRESHOLD:
        issues.append(f"🔴 {retry_count} retries Celery en 2h (>{CELERY_RETRY_THRESHOLD})")
    elif retry_count > 5:
        issues.append(f"🟡 {retry_count} retries Celery en 2h")

    return {"healthy": len(issues) == 0, "issues": issues, "info": info}


# ═══════════════════════════════════════════
# 6. Exchange / Equity
# ═══════════════════════════════════════════
def check_exchange() -> dict:
    issues = []
    info = {}

    # Escribir script temporal en host y copiar al container
    script_path = PROJECT_ROOT / ".tmp_check_equity.py"
    script_path.write_text(
        "import asyncio, json, os\n"
        'os.environ[\"LOGURU_LEVEL\"] = \"WARNING\"\n'
        "from app.exchanges.factory import create_exchange\n"
        "from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal\n"
        "from sqlalchemy import select\n"
        "from app.models.exchange_account import ExchangeAccount\n"
        "async def _c():\n"
        "    async with AsyncSessionLocal() as db:\n"
        "        r = await db.execute(select(ExchangeAccount).where(ExchangeAccount.is_active == True))\n"
        "        acs = r.scalars().all()\n"
        "        out = []\n"
        "        for a in acs:\n"
        "            try:\n"
        "                ex = create_exchange(a)\n"
        "                eq = await ex.get_equity()\n"
        "                await ex.close()\n"
        "                total = float(eq.total_equity) if hasattr(eq, 'total_equity') else float(str(eq))\n"
        '                out.append({"label": a.label, "eq": total, "ok": True})\n'
        "            except Exception as e:\n"
        '                out.append({"label": a.label, "err": str(e)[:100], "ok": False})\n'
        "        return out\n"
        "print(json.dumps(asyncio.run(_c())))\n"
    )
    _shell(
        f"docker cp {script_path} trading-bot-platform-backend-1:/tmp/tb_equity.py",
        timeout=10,
    )
    equity_output = _shell(
        "docker exec trading-bot-platform-backend-1 sh -c 'cd /app && PYTHONPATH=/app python /tmp/tb_equity.py'",
        timeout=30,
    )
    try:
        script_path.unlink(missing_ok=True)
        for line in equity_output.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                data = json.loads(line)
                info["accounts"] = data
                for acc in data:
                    if not acc.get("ok"):
                        issues.append(f"🔴 Exchange {acc['label']}: {acc.get('err', 'unknown')}")
                break
        else:
            issues.append("🟡 No se encontró JSON de equity en la salida")
    except Exception as exc:
        issues.append(f"🟡 No se pudo parsear equity del exchange: {exc}")

    return {"healthy": len(issues) == 0, "issues": issues, "info": info}


# ═══════════════════════════════════════════
# Reporte Final
# ═══════════════════════════════════════════
def main() -> int:
    print(f"\n{'='*70}")
    print(f"  MONITOR DE SALUD — Trading Bot Platform  |  {_ts()}")
    print(f"{'='*70}")

    checks = {
        "🐳 Docker / Infra": check_docker(),
        "📜 Logs": check_logs(),
        "🗄️  Base de Datos": check_database(),
        "🧠 Modelos ML": check_models(),
        "⚙️  Celery": check_celery(),
        "💰 Exchange": check_exchange(),
    }

    all_issues = []
    for name, result in checks.items():
        status = f"{G}✅ HEALTHY{RST}" if result["healthy"] else f"{R}❌ ISSUES{RST}"
        print(f"\n{name:<20s} {status}")
        if result.get("info"):
            for k, v in result["info"].items():
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, default=str)[:120]
                print(f"   {B}•{RST} {k}: {v}")
        for issue in result.get("issues", []):
            color = R if issue.startswith("🔴") else Y
            print(f"   {color}{issue}{RST}")
            all_issues.append(f"[{name}] {issue}")

    # Veredicto global
    criticals = [i for i in all_issues if "🔴" in i]
    warnings = [i for i in all_issues if "🟡" in i]

    print(f"\n{'='*70}")
    if criticals:
        print(f"  {R}🔴 CRÍTICO: {len(criticals)} problemas críticos detectados{RST}")
        exit_code = 2
    elif warnings:
        print(f"  {Y}🟡 WARNING: {len(warnings)} advertencias{RST}")
        exit_code = 1
    else:
        print(f"  {G}✅ SISTEMA SANO — Todos los checks pasaron{RST}")
        exit_code = 0
    print(f"{'='*70}\n")

    # Enviar alerta si hay problemas y no estamos en cooldown
    if criticals or warnings:
        should_alert = True
        now_ts = datetime.now(timezone.utc).timestamp()
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                last_alert = state.get("last_alert", 0)
                if now_ts - last_alert < COOLDOWN_MINUTES * 60:
                    should_alert = False
            except Exception:
                pass

        if should_alert:
            title = "ALERTA DE SALUD" + (" CRÍTICA" if criticals else "")
            body = "\n".join(all_issues[:10])
            if len(all_issues) > 10:
                body += f"\n... y {len(all_issues)-10} más"
            _send_alert(title, body)
            STATE_FILE.write_text(json.dumps({"last_alert": now_ts}))

    # Log a archivo
    try:
        with LOG_FILE.open("a") as f:
            f.write(f"{_ts()} | exit={exit_code} | issues={len(all_issues)}\n")
    except Exception:
        pass

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
