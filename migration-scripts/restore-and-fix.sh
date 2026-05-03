#!/bin/bash
echo "=== Estado actual de la BD ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "\dt"

echo "=== Restaurando backup ==="
docker exec -i trading-bot-platform-postgres-1 psql -U admin -d tradingbot < /root/backup_trading_20260502_235208.sql

echo "=== Verificando usuarios ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT username, email FROM users;"

echo "=== Corrigiendo version Alembic ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "DELETE FROM alembic_version; INSERT INTO alembic_version VALUES ('006_add_missing_columns');"

echo "=== Reiniciando backend ==="
docker restart trading-bot-platform-backend-1
echo "Listo"
