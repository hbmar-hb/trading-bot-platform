#!/usr/bin/env python3
"""
Monitor de salud del sistema Trading Bot Platform.

Revisa cada X minutos:
  1. Memoria de contenedores Docker (>85% = alerta)
  2. Contenedores reiniciándose
  3. OOM kills recientes
  4. RAM libre del VPS (<10% = alerta)
  5. Swap usage (>80% = alerta)

Uso:
  python3 scripts/monitor.py

Para correr cada 5 minutos con cron:
  */5 * * * * cd /home/deploy/apps/trading-bot-platform && python3 scripts/monitor.py >> /var/log/trading-bot-monitor.log 2>&1
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────
MEM_THRESHOLD = 85.0      # % de memoria del contenedor
VPS_MEM_THRESHOLD = 10.0  # % de RAM libre mínimo
SWAP_THRESHOLD = 80.0     # % de swap usado
COOLDOWN_MINUTES = 30     # no repetir la misma alerta por 30 min

LOG_FILE = Path("/var/log/trading-bot-monitor.log")
STATE_FILE = Path("/tmp/trading-bot-monitor-state.json")

# Leer credenciales del .env del proyecto
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env() -> dict:
    """Carga variables del .env si existen."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    return env


ENV = _load_env()
# Monitor del sistema: usa el bot de trading/IA si está configurado; si no, el legacy.
TELEGRAM_TOKEN = ENV.get("TELEGRAM_TRADING_BOT_TOKEN") or ENV.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = ENV.get("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK = ENV.get("DISCORD_WEBHOOK_URL", "")


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except PermissionError:
        pass  # si no hay permiso en /var/log, solo print


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _should_alert(alert_id: str) -> bool:
    """Cooldown: no repetir la misma alerta por N minutos."""
    state = _load_state()
    last = state.get("alerts", {}).get(alert_id)
    if last is None:
        return True
    elapsed = (datetime.now(timezone.utc).timestamp() - last) / 60
    return elapsed > COOLDOWN_MINUTES


def _mark_alert(alert_id: str) -> None:
    state = _load_state()
    state.setdefault("alerts", {})[alert_id] = datetime.now(timezone.utc).timestamp()
    _save_state(state)


# ─────────────────────────────────────────
# Notificaciones
# ─────────────────────────────────────────
def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": TELEGRAM_CHAT, "text": message, "parse_mode": "Markdown"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        log(f"[TELEGRAM ERROR] {exc}")


def send_discord(message: str) -> None:
    if not DISCORD_WEBHOOK:
        return
    try:
        import urllib.request
        data = json.dumps({"content": message}).encode()
        req = urllib.request.Request(DISCORD_WEBHOOK, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        log(f"[DISCORD ERROR] {exc}")


def notify(message: str, alert_id: str) -> None:
    log(message)
    if _should_alert(alert_id):
        send_telegram(f"🚨 *Trading Bot Alert*\n{message}")
        send_discord(f"🚨 Trading Bot Alert: {message}")
        _mark_alert(alert_id)


# ─────────────────────────────────────────
# Checks
# ─────────────────────────────────────────
def check_container_memory() -> list[str]:
    """Revisa memoria de contenedores Docker."""
    alerts = []
    out = _run([
        "docker", "stats", "--no-stream",
        "--format", "{{.Name}}|{{.MemUsage}}|{{.MemPerc}}"
    ])
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, usage, perc_str = line.split("|", 2)
        perc_str = perc_str.replace("%", "").strip()
        try:
            perc = float(perc_str)
        except ValueError:
            continue
        if perc >= MEM_THRESHOLD:
            alert = f"Contenedor `{name}` usando {perc:.1f}% de memoria ({usage})"
            alerts.append(alert)
            notify(alert, f"mem:{name}")
    return alerts


def check_container_restarts() -> list[str]:
    """Detecta contenedores que se están reiniciando."""
    alerts = []
    out = _run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"])
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        if "restart" in status.lower() or "restarting" in status.lower():
            alert = f"Contenedor `{name}` está reiniciándose: {status}"
            alerts.append(alert)
            notify(alert, f"restart:{name}")
    return alerts


def check_oom_kills() -> list[str]:
    """Busca OOM kills NUEVOS en las últimas 24 horas (no alerta por históricos)."""
    alerts = []
    out = _run(["journalctl", "--system", "--since", "24 hours ago", "-q"])

    oom_lines = [ln for ln in out.splitlines() if "out of memory: killed process" in ln.lower()]
    current_count = len(oom_lines)

    state = _load_state()
    prev_count = state.get("oom_count_24h", 0)
    initialized = state.get("oom_initialized", False)

    if not initialized:
        # Primera ejecución: solo guardar estado, no alertar por históricos
        state["oom_count_24h"] = current_count
        state["oom_initialized"] = True
        _save_state(state)
    elif current_count > prev_count:
        new = current_count - prev_count
        alert = f"🚨 {new} OOM kill(s) NUEVO(S) detectado(s) (total 24h: {current_count})"
        alerts.append(alert)
        notify(alert, "oom:kills")
        state["oom_count_24h"] = current_count
        _save_state(state)
    elif current_count == 0 and prev_count > 0:
        # Resetear si no hay OOMs (nuevo día limpio)
        state["oom_count_24h"] = 0
        _save_state(state)

    return alerts


def check_vps_memory() -> list[str]:
    """Revisa RAM libre del VPS."""
    alerts = []
    out = _run(["free"])
    for line in out.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            total = int(parts[1])
            available = int(parts[6])
            free_pct = (available / total) * 100
            if free_pct < VPS_MEM_THRESHOLD:
                alert = f"VPS con solo {free_pct:.1f}% RAM libre ({available//1024}MB / {total//1024}MB)"
                alerts.append(alert)
                notify(alert, "vps:memory")
            break
    return alerts


def check_swap() -> list[str]:
    """Revisa uso de swap."""
    alerts = []
    out = _run(["free"])
    for line in out.splitlines():
        if line.startswith("Swap:"):
            parts = line.split()
            total = int(parts[1])
            used = int(parts[2])
            if total > 0:
                used_pct = (used / total) * 100
                if used_pct >= SWAP_THRESHOLD:
                    alert = f"Swap al {used_pct:.1f}% ({used//1024}MB / {total//1024}MB)"
                    alerts.append(alert)
                    notify(alert, "vps:swap")
            break
    return alerts


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
def main() -> int:
    log("=" * 50)
    log("Iniciando chequeo de salud...")

    all_alerts: list[str] = []
    all_alerts.extend(check_container_memory())
    all_alerts.extend(check_container_restarts())
    all_alerts.extend(check_oom_kills())
    all_alerts.extend(check_vps_memory())
    all_alerts.extend(check_swap())

    if not all_alerts:
        log("✅ Todo OK — sin alertas")
    else:
        log(f"⚠️  Se generaron {len(all_alerts)} alerta(s)")

    log("Chequeo finalizado")
    return 0 if not all_alerts else 1


if __name__ == "__main__":
    sys.exit(main())
