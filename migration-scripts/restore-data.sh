#!/bin/bash
echo "=== Limpiando datos actuales ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "
SET session_replication_role = replica;
TRUNCATE TABLE bot_logs, signal_logs, exchange_trades, positions, bot_configs, paper_balances, exchange_accounts, refresh_tokens, trading_signals, users CASCADE;
SET session_replication_role = DEFAULT;
"

echo "=== Restaurando datos ==="
docker exec -i trading-bot-platform-postgres-1 psql -U admin -d tradingbot < /root/data_only_20260503_003059.sql

echo "=== Verificando ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT username, role FROM users;"
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT COUNT(*) as bots FROM bot_configs;"

docker restart trading-bot-platform-backend-1
echo "=== Listo ==="
