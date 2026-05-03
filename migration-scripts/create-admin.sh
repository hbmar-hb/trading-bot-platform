#!/bin/bash
# Asegura que las columnas existen
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user';"
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false;"

# Genera hash desde el backend
PASSWORD=$(grep '^PASSWORD=' /root/reset-password.sh | cut -d'"' -f2)
echo "Generando hash para usuario..."
HASH=$(docker exec trading-bot-platform-backend-1 python -c "
from passlib.context import CryptContext
ctx = CryptContext(schemes=['bcrypt'])
print(ctx.hash('$PASSWORD'))
")

# Inserta o actualiza el usuario
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "
INSERT INTO users (id, username, email, hashed_password, is_active, role, email_verified)
VALUES (gen_random_uuid(), 'Marci526', 'marcial.herreros@gmail.com', '$HASH', true, 'admin', true)
ON CONFLICT (username) DO UPDATE SET hashed_password = EXCLUDED.hashed_password, role = 'admin';
"
docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "SELECT username, email, role, is_active FROM users;"
