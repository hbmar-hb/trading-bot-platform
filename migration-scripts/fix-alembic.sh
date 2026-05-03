#!/bin/bash
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "DELETE FROM alembic_version; INSERT INTO alembic_version VALUES ('006_add_missing_columns');"
echo "Alembic version actualizado"
docker restart trading-bot-platform-backend-1
echo "Backend reiniciado"
