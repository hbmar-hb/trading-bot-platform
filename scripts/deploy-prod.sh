#!/bin/bash
set -e

# Deploy de producción
# Rama: main
# Directorio: /home/deploy/apps/trading-bot-platform

cd /home/deploy/apps/trading-bot-platform

echo "[deploy-prod] Actualizando rama main..."
git fetch origin
git checkout main
git pull origin main

echo "[deploy-prod] Reconstruyendo contenedores..."
docker compose up -d --build

echo "[deploy-prod] Aplicando migraciones..."
docker compose exec backend alembic upgrade head

echo "[deploy-prod] Listo. Producción desplegada."
