#!/bin/bash
echo "=== Eliminando BOM del backup ==="
sed -i '1s/^\xef\xbb\xbf//' /root/backup_trading_20260502_235208.sql

echo "=== Limpiando tablas existentes ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "
TRUNCATE TABLE bot_logs, signal_logs, exchange_trades, positions, bot_configs, paper_balances, exchange_accounts, refresh_tokens, trading_signals, users CASCADE;
"

echo "=== Restaurando backup ==="
docker exec -i trading-bot-platform-postgres-1 psql -U admin -d tradingbot < /root/backup_trading_20260502_235208.sql 2>&1 | grep -E "ERROR|COPY|INSERT" | head -30

echo "=== Verificando usuarios ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT username, email FROM users;"

echo "=== Corrigiendo Alembic ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "DELETE FROM alembic_version; INSERT INTO alembic_version VALUES ('006_add_missing_columns');"

docker restart trading-bot-platform-backend-1
echo "=== Listo ==="
