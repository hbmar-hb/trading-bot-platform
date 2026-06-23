#!/bin/bash
set -euo pipefail

# =============================================================================
# Backup automático antes del deploy
# Guarda: base de datos PostgreSQL, modelos .pkl y .env
# =============================================================================

PROJECT_DIR="/home/deploy/apps/trading-bot-platform"
BACKUPS_DIR="${PROJECT_DIR}/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="deploy_backup_${TIMESTAMP}"
BACKUP_DIR="${BACKUPS_DIR}/${BACKUP_NAME}"
DUMP_FILE="${BACKUP_DIR}/database.sql"
MODELS_DIR="${PROJECT_DIR}/backend/ai/models"
ENV_FILE="${PROJECT_DIR}/.env"

mkdir -p "${BACKUP_DIR}"

cd "${PROJECT_DIR}"

# Backup de modelos de IA
if [ -d "${MODELS_DIR}" ]; then
    echo "Copiando modelos..."
    cp -r "${MODELS_DIR}" "${BACKUP_DIR}/models"
fi

# Backup de variables de entorno
if [ -f "${ENV_FILE}" ]; then
    echo "Copiando .env..."
    cp "${ENV_FILE}" "${BACKUP_DIR}/.env"
fi

# Backup de base de datos si PostgreSQL está corriendo
if docker compose -f docker-compose.yml ps postgres 2>/dev/null | grep -q "running"; then
    echo "Haciendo dump de PostgreSQL..."
    POSTGRES_USER=$(grep '^POSTGRES_USER=' "${ENV_FILE}" | head -1 | cut -d= -f2)
    POSTGRES_DB=$(grep '^POSTGRES_DB=' "${ENV_FILE}" | head -1 | cut -d= -f2)

    docker compose -f docker-compose.yml exec -T postgres \
        pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" > "${DUMP_FILE}"

    gzip "${DUMP_FILE}"
    echo "Dump comprimido: ${DUMP_FILE}.gz"
else
    echo "WARNING: PostgreSQL no está corriendo, se omite backup de base de datos" >&2
fi

# Empaquetar y limpiar directorio temporal
tar -czf "${BACKUP_DIR}.tar.gz" -C "${BACKUPS_DIR}" "${BACKUP_NAME}"
rm -rf "${BACKUP_DIR}"

# Mantener solo los últimos 10 backups de deploy
ls -1td "${BACKUPS_DIR}"/deploy_backup_*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm -f

echo ""
echo "Backup de deploy creado: ${BACKUP_DIR}.tar.gz"
