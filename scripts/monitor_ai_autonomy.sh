#!/bin/bash
# =============================================================================
# monitor_ai_autonomy.sh — Monitoreo de logs para autonomía AI
# =============================================================================
# Uso: ./scripts/monitor_ai_autonomy.sh [modo]
#
# Modos:
#   all       → Todo lo relacionado con autonomía AI (default)
#   recovery  → Solo auto-reactivación post-circuit-breaker
#   watchlist → Solo health-check de cobertura de watchlist
#   signals   → Señales AI, activaciones y rechazos
#   realtime  → Logs en tiempo real (follow)
# =============================================================================

MODE="${1:-all}"
CONTAINER="trading-bot-platform-backend-1"
WORKER="trading-bot-platform-celery_worker-1"
BEAT="trading-bot-platform-celery_beat-1"

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_container() {
    local name="$1"
    if ! docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
        log_error "Contenedor ${name} no está corriendo"
        return 1
    fi
    return 0
}

show_header() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║           🤖 MONITOR DE AUTONOMÍA AI — $(date '+%Y-%m-%d %H:%M:%S')           ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
}

# ── Modo: recovery ───────────────────────────────────────────────────────────
mode_recovery() {
    log_info "Buscando auto-reactivaciones post-circuit-breaker..."
    docker logs "$WORKER" --since 24h 2>/dev/null | grep -i "AUTO-REACTIVATED" || \
        log_warn "No hay reactivaciones en las últimas 24h"
    echo ""
    log_info "Buscando circuit breakers activados..."
    docker logs "$WORKER" --since 24h 2>/dev/null | grep -i "CIRCUIT BREAKER" || \
        log_warn "No hay eventos de circuit breaker en las últimas 24h"
}

# ── Modo: watchlist ──────────────────────────────────────────────────────────
mode_watchlist() {
    log_info "Buscando alertas de cobertura de watchlist..."
    docker logs "$WORKER" --since 24h 2>/dev/null | grep -i "WATCHLIST CHECK" || \
        log_ok "No hay bots fuera de watchlist en las últimas 24h"
}

# ── Modo: signals ────────────────────────────────────────────────────────────
mode_signals() {
    log_info "Resumen de señales AI (últimas 24h)..."
    docker logs "$WORKER" --since 24h 2>/dev/null | grep -i "SEÑAL IA\|AI SIGNAL\|ACTIVADO\|RECHAZADO" || \
        log_warn "No hay señales registradas en las últimas 24h"
}

# ── Modo: all ────────────────────────────────────────────────────────────────
mode_all() {
    show_header

    # Estado de contenedores
    log_info "Estado de contenedores:"
    for c in "$CONTAINER" "$WORKER" "$BEAT"; do
        if check_container "$c"; then
            status=$(docker inspect --format='{{.State.Status}}' "$c" 2>/dev/null)
            health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "N/A")
            log_ok "  $c: $status (health: $health)"
        fi
    done
    echo ""

    # Auto-reactivación
    mode_recovery
    echo ""

    # Watchlist coverage
    mode_watchlist
    echo ""

    # Señales
    mode_signals
    echo ""

    # Métricas de última hora
    log_info "Métricas de última hora:"
    docker logs "$WORKER" --since 1h 2>/dev/null | grep -c "SEÑAL IA" 2>/dev/null | xargs -I{} echo -e "  ${GREEN}Señales IA generadas:${NC} {}"
    docker logs "$WORKER" --since 1h 2>/dev/null | grep -c "AUTO-REACTIVATED" 2>/dev/null | xargs -I{} echo -e "  ${GREEN}Reactivaciones:${NC} {}"
    docker logs "$WORKER" --since 1h 2>/dev/null | grep -c "WATCHLIST CHECK" 2>/dev/null | xargs -I{} echo -e "  ${YELLOW}Alertas watchlist:${NC} {}"
    docker logs "$WORKER" --since 1h 2>/dev/null | grep -c "CIRCUIT BREAKER" 2>/dev/null | xargs -I{} echo -e "  ${RED}Circuit breakers:${NC} {}"

    echo ""
    log_info "Comandos útiles:"
    echo "  ./scripts/monitor_ai_autonomy.sh realtime   # Ver logs en tiempo real"
    echo "  ./scripts/monitor_ai_autonomy.sh recovery   # Solo reactivaciones"
    echo "  ./scripts/monitor_ai_autonomy.sh watchlist  # Solo cobertura watchlist"
    echo ""
}

# ── Modo: realtime ───────────────────────────────────────────────────────────
mode_realtime() {
    log_info "Siguiendo logs en tiempo real (Ctrl+C para salir)..."
    echo "  Filtrando: CIRCUIT BREAKER | WATCHLIST | AUTO-REACTIVATED | SEÑAL IA"
    echo ""
    docker logs -f --tail 50 "$WORKER" 2>/dev/null | grep --color=always -i "CIRCUIT BREAKER\|WATCHLIST\|AUTO-REACTIVATED\|SEÑAL IA\|ACTIVADO\|RECHAZADO"
}

# ── Main ─────────────────────────────────────────────────────────────────────
case "$MODE" in
    all)       mode_all ;;
    recovery)  show_header; mode_recovery ;;
    watchlist) show_header; mode_watchlist ;;
    signals)   show_header; mode_signals ;;
    realtime)  mode_realtime ;;
    *)
        echo "Uso: $0 {all|recovery|watchlist|signals|realtime}"
        exit 1
        ;;
esac
