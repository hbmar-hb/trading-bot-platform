#!/bin/bash
PASSWORD="Capnegret240323"
USERNAME="Marci526"

HASH=$(docker exec trading-bot-platform-backend-1 python -c "
from passlib.context import CryptContext
ctx = CryptContext(schemes=['bcrypt'])
print(ctx.hash('$PASSWORD'))
")

docker exec trading-bot-platform-postgres-1 psql -U admin -d tradingbot -c "UPDATE users SET hashed_password='$HASH' WHERE username='$USERNAME';"
echo "Password actualizado para $USERNAME"
