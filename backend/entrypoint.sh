#!/bin/sh
set -e

echo "[entrypoint] Esperando a que PostgreSQL esté listo..."
until python -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        host=os.environ.get('POSTGRES_HOST', 'postgres'),
        port=os.environ.get('POSTGRES_PORT', '5432'),
        dbname=os.environ.get('POSTGRES_DB', 'tradingbot'),
        user=os.environ.get('POSTGRES_USER', 'admin'),
        password=os.environ.get('POSTGRES_PASSWORD', ''),
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
  sleep 1
done
echo "[entrypoint] PostgreSQL listo."

echo "[entrypoint] Ejecutando migraciones Alembic..."
alembic upgrade head
echo "[entrypoint] Migraciones aplicadas."

echo "[entrypoint] Arrancando servidor..."
exec "$@"
