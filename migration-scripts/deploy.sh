#!/bin/bash
# =============================================================================
# Script de deploy automatico en VPS Hetzner
# Ejecutar como usuario deploy en ~/apps/trading-bot-platform
# =============================================================================

set -e

DOMAIN=${DOMAIN:-"trading.tudominio.com"}
COMPOSE_FILE="docker-compose.prod.yml"

echo "=== Deploy Trading Bot Platform ==="
echo "Dominio: $DOMAIN"
echo ""

cd ~/apps/trading-bot-platform

echo "=== 1. Pull ultimos cambios ==="
git pull origin master

echo "=== 2. Reconstruir y levantar contenedores ==="
DOMAIN=$DOMAIN docker compose -f $COMPOSE_FILE up -d --build

echo "=== 3. Limpiar imagenes viejas ==="
docker image prune -f

echo "=== 4. Estado de los servicios ==="
docker compose -f $COMPOSE_FILE ps

echo ""
echo "=== Deploy completado ==="
echo "URL: https://$DOMAIN"
