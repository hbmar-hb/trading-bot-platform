#!/bin/bash
echo "=== Columnas de users ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "\d users"
echo "=== Version Alembic ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT * FROM alembic_version;"
echo "=== Symbol en bot_configs ==="
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT column_name, character_maximum_length FROM information_schema.columns WHERE table_name='bot_configs' AND column_name='symbol';"
