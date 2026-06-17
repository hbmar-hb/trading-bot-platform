#!/bin/bash
# =============================================================================
# PREPARAR MIGRACION — Ejecutar en el VPS ACTUAL
# Crea un paquete completo listo para transferir al nuevo VPS
# =============================================================================

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MIGRATE_DIR="/tmp/migration_${TIMESTAMP}"
PACKAGE="/tmp/trading-bot-migration-${TIMESTAMP}.tar.gz"
PROJECT_DIR="/home/deploy/apps/trading-bot-platform"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   PREPARANDO PAQUETE DE MIGRACION                            ║"
echo "║   VPS origen → VPS nuevo (167.233.99.178)                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Validaciones ──
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ ERROR: No se encontró el proyecto en $PROJECT_DIR"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "❌ ERROR: No se encontró .env en $PROJECT_DIR"
    exit 1
fi

mkdir -p "$MIGRATE_DIR"

# ── 1. Backup fresco de PostgreSQL ──
echo "📦 [1/6] Generando backup fresco de PostgreSQL..."
DB_CONTAINER=$(docker ps --format "{{.Names}}" | grep postgres | head -n1)
if [ -n "$DB_CONTAINER" ]; then
    docker exec "$DB_CONTAINER" pg_dumpall -U admin > "${MIGRATE_DIR}/backup_postgres_${TIMESTAMP}.sql"
    echo "   ✓ Backup SQL: backup_postgres_${TIMESTAMP}.sql"
    ls -lh "${MIGRATE_DIR}/backup_postgres_${TIMESTAMP}.sql"
else
    echo "   ⚠ No se encontró contenedor PostgreSQL corriendo. Buscando backups existentes..."
    LATEST_BACKUP=$(ls -t ${PROJECT_DIR}/backup_*.sql 2>/dev/null | head -n1)
    if [ -n "$LATEST_BACKUP" ]; then
        cp "$LATEST_BACKUP" "${MIGRATE_DIR}/"
        echo "   ✓ Copiado backup existente: $(basename $LATEST_BACKUP)"
    else
        echo "   ❌ No hay backup disponible. Abortando."
        exit 1
    fi
fi

# ── 2. Backup de Redis (opcional, datos en memoria) ──
echo "📦 [2/6] Generando backup de Redis..."
REDIS_CONTAINER=$(docker ps --format "{{.Names}}" | grep redis | head -n1)
if [ -n "$REDIS_CONTAINER" ]; then
    docker exec "$REDIS_CONTAINER" redis-cli -a "$(grep REDIS_PASSWORD ${PROJECT_DIR}/.env | cut -d= -f2)" --no-auth-warning SAVE 2>/dev/null || true
    docker cp "${REDIS_CONTAINER}:/data/dump.rdb" "${MIGRATE_DIR}/redis_dump.rdb" 2>/dev/null && echo "   ✓ Redis dump.rdb copiado" || echo "   ⚠ No se pudo copiar dump.rdb"
else
    echo "   ⚠ Redis no está corriendo"
fi

# ── 3. Copiar proyecto completo ──
echo "📦 [3/6] Copiando proyecto completo (sin node_modules)..."
rsync -a --exclude='node_modules' --exclude='__pycache__' --exclude='.pytest_cache' \
      --exclude='*.pyc' --exclude='.git/objects' \
      "$PROJECT_DIR/" "${MIGRATE_DIR}/project/"
echo "   ✓ Proyecto copiado"

# ── 4. Exportar volúmenes de Docker ──
echo "📦 [4/6] Exportando volúmenes de Docker..."

# Postgres data
POSTGRES_VOL=$(docker volume ls -q | grep postgres_data | head -n1)
if [ -n "$POSTGRES_VOL" ]; then
    docker run --rm -v "${POSTGRES_VOL}:/source" -v "${MIGRATE_DIR}:/backup" alpine \
        tar czf /backup/postgres_data.tar.gz -C /source .
    echo "   ✓ postgres_data.tar.gz"
fi

# Redis data
REDIS_VOL=$(docker volume ls -q | grep redis_data | head -n1)
if [ -n "$REDIS_VOL" ]; then
    docker run --rm -v "${REDIS_VOL}:/source" -v "${MIGRATE_DIR}:/backup" alpine \
        tar czf /backup/redis_data.tar.gz -C /source .
    echo "   ✓ redis_data.tar.gz"
fi

# AI models
AI_VOL=$(docker volume ls -q | grep ai_models | head -n1)
if [ -n "$AI_VOL" ]; then
    docker run --rm -v "${AI_VOL}:/source" -v "${MIGRATE_DIR}:/backup" alpine \
        tar czf /backup/ai_models.tar.gz -C /source .
    echo "   ✓ ai_models.tar.gz"
fi

# Celery beat data
BEAT_VOL=$(docker volume ls -q | grep celery_beat_data | head -n1)
if [ -n "$BEAT_VOL" ]; then
    docker run --rm -v "${BEAT_VOL}:/source" -v "${MIGRATE_DIR}:/backup" alpine \
        tar czf /backup/celery_beat_data.tar.gz -C /source .
    echo "   ✓ celery_beat_data.tar.gz"
fi

# ── 5. Guardar metadatos ──
echo "📦 [5/6] Guardando metadatos de la migración..."
cat > "${MIGRATE_DIR}/MIGRATION_INFO.txt" << EOF
MIGRACION TRADING BOT PLATFORM
==============================
Fecha origen: $(date -Iseconds)
Servidor origen: $(hostname -I | awk '{print $1}')
Servidor destino: 167.233.99.178
Tamaño proyecto: $(du -sh ${PROJECT_DIR} | cut -f1)

Contenedores activos al momento del backup:
$(docker ps --format "{{.Names}} ({{.Image}})" | sort)

Volúmenes exportados:
$(ls -1 ${MIGRATE_DIR}/*.tar.gz 2>/dev/null)

Backup PostgreSQL:
$(ls -1 ${MIGRATE_DIR}/*.sql 2>/dev/null)
EOF
echo "   ✓ Metadatos guardados"

# ── 6. Empaquetar todo ──
echo "📦 [6/6] Empaquetando todo en un solo archivo..."
tar czf "$PACKAGE" -C "$(dirname $MIGRATE_DIR)" "$(basename $MIGRATE_DIR)"
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   PAQUETE DE MIGRACION LISTO                                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Archivo: $PACKAGE"
echo "Tamaño:  $(du -sh $PACKAGE | cut -f1)"
echo ""
echo "📋 SIGUIENTES PASOS:"
echo "   1. Transfiere este archivo al nuevo VPS:"
echo "      scp $PACKAGE root@167.233.99.178:/root/"
echo ""
echo "   2. Conéctate al nuevo VPS y ejecuta el restore:"
echo "      ssh root@167.233.99.178"
echo "      tar xzf /root/$(basename $PACKAGE) -C /tmp/"
echo "      cd /tmp/$(basename $MIGRATE_DIR)/project"
echo "      bash migration-scripts/restore-on-new-vps.sh /tmp/$(basename $MIGRATE_DIR)"
echo ""

# Limpiar directorio temporal (mantener el tar.gz)
rm -rf "$MIGRATE_DIR"
