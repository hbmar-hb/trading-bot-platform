#!/bin/bash
set -e

# Deploy de desarrollo
# Rama: develop
# Directorio: /home/deploy/apps/trading-bot-platform-dev

cd /home/deploy/apps/trading-bot-platform-dev

echo "[deploy-dev] Actualizando rama develop..."
git fetch origin
git checkout develop
git pull origin develop

echo "[deploy-dev] Reconstruyendo contenedores..."
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev-env.yml \
  -f docker-compose.dev.yml \
  --env-file .env.dev \
  up -d --build

echo "[deploy-dev] Aplicando migraciones..."
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev-env.yml \
  -f docker-compose.dev.yml \
  --env-file .env.dev \
  exec backend alembic upgrade head

echo "[deploy-dev] Listo. Desarrollo desplegado."
