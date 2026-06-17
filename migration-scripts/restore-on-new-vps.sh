#!/bin/bash
# =============================================================================
# RESTORE EN VPS NUEVO — Ejecutar como root en 167.233.99.178
# Restaura el paquete de migración completo
# Uso: bash restore-on-new-vps.sh /tmp/migration_XXXXXX
# =============================================================================

set -e

MIGRATE_DIR="${1:-/tmp/migration_latest}"
NEW_USER="deploy"
APPS_DIR="/home/${NEW_USER}/apps"
PROJECT_DIR="${APPS_DIR}/trading-bot-platform"
DOMAIN="${DOMAIN:-}"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   RESTORE EN VPS NUEVO — Trading Bot Platform                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Validaciones ──
if [ ! -d "$MIGRATE_DIR" ]; then
    echo "❌ ERROR: Directorio de migración no encontrado: $MIGRATE_DIR"
    echo "   Uso correcto: bash $0 /ruta/a/migration_XXXXXX"
    exit 1
fi

if [ "$EUID" -ne 0 ]; then
    echo "❌ ERROR: Este script debe ejecutarse como root"
    exit 1
fi

if [ -z "$DOMAIN" ]; then
    echo "⚠️  ADVERTENCIA: Variable DOMAIN no definida."
    echo "   Si tienes un dominio configurado, ejecuta primero:"
    echo "   export DOMAIN=tudominio.com"
    echo ""
    read -p "¿Quieres continuar sin dominio (modo IP)? [s/N]: " CONTINUE
    if [[ ! "$CONTINUE" =~ ^[Ss]$ ]]; then
        echo "Abortando. Ejecuta: export DOMAIN=tudominio.com && bash $0 $MIGRATE_DIR"
        exit 1
    fi
fi

# ── 1. Copiar proyecto ──
echo "🚀 [1/8] Instalando proyecto en ${PROJECT_DIR}..."
rm -rf "$PROJECT_DIR"
mkdir -p "$APPS_DIR"
cp -r "${MIGRATE_DIR}/project" "$PROJECT_DIR"
chown -R "${NEW_USER}:${NEW_USER}" "$APPS_DIR"
echo "   ✓ Proyecto instalado"

# ── 2. Verificar .env ──
echo "🚀 [2/8] Verificando configuración .env..."
if [ ! -f "${PROJECT_DIR}/.env" ]; then
    echo "   ❌ No se encontró .env. Abortando."
    exit 1
fi

# Actualizar .env para producción si es necesario
sed -i 's/^ENV=.*/ENV=production/' "${PROJECT_DIR}/.env"
sed -i 's/^DEBUG=.*/DEBUG=false/' "${PROJECT_DIR}/.env"
if [ -n "$DOMAIN" ]; then
    sed -i "s|^FRONTEND_URL=.*|FRONTEND_URL=https://${DOMAIN}|" "${PROJECT_DIR}/.env"
    sed -i "s|^API_BASE_URL=.*|API_BASE_URL=https://${DOMAIN}/api|" "${PROJECT_DIR}/.env"
fi
echo "   ✓ .env configurado para producción"

# ── 3. Crear volúmenes de Docker y restaurar datos ──
echo "🚀 [3/8] Restaurando volúmenes de Docker..."

# Función para restaurar un volumen
restore_volume() {
    local tar_file="$1"
    local vol_name="$2"
    if [ -f "$tar_file" ]; then
        docker volume rm "$vol_name" 2>/dev/null || true
        docker volume create "$vol_name"
        docker run --rm -v "${vol_name}:/target" -v "$(dirname $tar_file):/backup" alpine \
            tar xzf "/backup/$(basename $tar_file)" -C /target
        echo "   ✓ ${vol_name} restaurado"
    else
        echo "   ⚠ $(basename $tar_file) no encontrado, creando volumen vacío"
        docker volume create "$vol_name" 2>/dev/null || true
    fi
}

cd "$PROJECT_DIR"

restore_volume "${MIGRATE_DIR}/postgres_data.tar.gz" "trading-bot-platform_postgres_data"
restore_volume "${MIGRATE_DIR}/redis_data.tar.gz" "trading-bot-platform_redis_data"
restore_volume "${MIGRATE_DIR}/ai_models.tar.gz" "trading-bot-platform_ai_models"
restore_volume "${MIGRATE_DIR}/celery_beat_data.tar.gz" "trading-bot-platform_celery_beat_data"

echo "   ✓ Volúmenes restaurados"

# ── 4. Construir y levantar servicios ──
echo "🚀 [4/8] Construyendo e iniciando servicios con Docker Compose..."
cd "$PROJECT_DIR"

# Primero levantar solo postgres para restaurar el backup SQL si existe
SQL_BACKUP=$(ls -1 ${MIGRATE_DIR}/backup_postgres_*.sql 2>/dev/null | head -n1)
if [ -n "$SQL_BACKUP" ]; then
    echo "   → Levantando PostgreSQL para restaurar backup SQL..."
    docker compose -f docker-compose.prod.yml up -d postgres
    echo "   → Esperando 15 segundos a que PostgreSQL esté listo..."
    sleep 15
    
    echo "   → Restaurando backup SQL..."
    DB_USER=$(grep POSTGRES_USER .env | cut -d= -f2)
    DB_NAME=$(grep POSTGRES_DB .env | cut -d= -f2)
    
    # Intentar restaurar con el usuario correcto
    docker exec -i trading-bot-platform-postgres-1 psql -U "${DB_USER:-admin}" -d "${DB_NAME:-tradingbot}" < "$SQL_BACKUP" 2>/dev/null || \
    docker exec -i trading-bot-platform-postgres-1 psql -U "${DB_USER:-admin}" < "$SQL_BACKUP"
    echo "   ✓ Base de datos restaurada desde SQL"
fi

# Ahora levantar todo
echo "   → Levantando todos los servicios..."
if [ -n "$DOMAIN" ]; then
    DOMAIN="$DOMAIN" docker compose -f docker-compose.prod.yml up -d --build
else
    docker compose -f docker-compose.prod.yml up -d --build
fi

echo "   ✓ Servicios iniciados"

# ── 5. Configurar Nginx ──
echo "🚀 [5/8] Configurando Nginx..."
cp "${PROJECT_DIR}/migration-scripts/nginx-trading.conf" /etc/nginx/sites-available/trading

if [ -n "$DOMAIN" ]; then
    sed -i "s/server_name _;/server_name ${DOMAIN};/" /etc/nginx/sites-available/trading
fi

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/trading /etc/nginx/sites-enabled/trading

nginx -t && systemctl reload nginx
echo "   ✓ Nginx configurado"

# ── 6. SSL (si hay dominio) ──
echo "🚀 [6/8] Configurando SSL..."
if [ -n "$DOMAIN" ]; then
    if ! certbot certificates 2>/dev/null | grep -q "$DOMAIN"; then
        echo "   → Solicitando certificado para ${DOMAIN}..."
        certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@${DOMAIN} || \
        certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@localhost
        echo "   ✓ Certificado SSL instalado"
    else
        echo "   ✓ Certificado SSL ya existe"
    fi
else
    echo "   ⚠ Modo IP — SSL no configurado (usa certbot manualmente cuando tengas dominio)"
fi

# ── 7. Configurar PgBouncer userlist ──
echo "🚀 [7/8] Configurando PgBouncer..."
PGBOUNCER_DIR="${PROJECT_DIR}/docker/pgbouncer"
if [ -f "${PGBOUNCER_DIR}/userlist.txt" ]; then
    echo "   ✓ userlist.txt ya existe"
else
    echo "   → Generando userlist.txt..."
    DB_PASS=$(grep POSTGRES_PASSWORD "${PROJECT_DIR}/.env" | cut -d= -f2)
    DB_USER=$(grep POSTGRES_USER "${PROJECT_DIR}/.env" | cut -d= -f2)
    HASH=$(python3 -c "import hashlib; print('md5' + hashlib.md5(b'${DB_PASS}${DB_USER}').hexdigest())" 2>/dev/null || \
           python3 -c "import hashlib; print('md5' + hashlib.md5(('${DB_PASS}' + '${DB_USER}').encode()).hexdigest())")
    echo "\"${DB_USER}\" \"${HASH}\"" > "${PGBOUNCER_DIR}/userlist.txt"
    echo "   ✓ userlist.txt generado"
fi

# ── 8. Healthcheck final ──
echo "🚀 [8/8] Verificando servicios..."
sleep 10

echo ""
echo "   Estado de contenedores:"
docker compose -f docker-compose.prod.yml ps --format "table {{.Name}}\t{{.Status}}\t{{.State}}"

echo ""
echo "   URLs disponibles:"
if [ -n "$DOMAIN" ]; then
    echo "     → Frontend: https://${DOMAIN}"
    echo "     → API:      https://${DOMAIN}/api"
    echo "     → Health:   https://${DOMAIN}/health"
else
    echo "     → Frontend: http://167.233.99.178:8080"
    echo "     → API:      http://167.233.99.178:8100"
    echo "     → Health:   http://167.233.99.178:8100/health"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   MIGRACION COMPLETADA ✅                                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 POST-MIGRACION:"
echo "   • Revisa los logs: docker compose -f docker-compose.prod.yml logs -f"
echo "   • Si usas dominio, apunta el DNS A a: 167.233.99.178"
echo "   • Para SSL manual más tarde: certbot --nginx -d TU_DOMINIO"
echo ""
echo "   Cambia al usuario deploy para gestionar el proyecto:"
echo "   su - deploy"
echo "   cd ~/apps/trading-bot-platform"
echo ""
