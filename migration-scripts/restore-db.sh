#!/bin/bash
docker exec -i trading-bot-platform-postgres-1 psql -U admin -d tradingbot < /root/backup_trading_20260502_235208.sql
echo "Base de datos restaurada correctamente"
