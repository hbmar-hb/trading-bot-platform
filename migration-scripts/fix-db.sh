#!/bin/bash
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "ALTER TABLE positions ADD COLUMN IF NOT EXISTS extra_config JSONB DEFAULT '{}';"
echo "Columna añadida correctamente"
