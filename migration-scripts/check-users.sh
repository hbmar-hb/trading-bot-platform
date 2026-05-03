#!/bin/bash
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT username, email, is_active FROM users;"
