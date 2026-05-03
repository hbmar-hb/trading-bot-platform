#!/bin/bash
set -e

# Preparar directorio como deploy
mkdir -p /home/deploy/actions-runner
chown deploy:deploy /home/deploy/actions-runner

# Descargar y extraer como deploy
su - deploy -c "
cd /home/deploy/actions-runner
curl -o actions-runner-linux-arm64-2.334.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.334.0/actions-runner-linux-arm64-2.334.0.tar.gz
tar xzf ./actions-runner-linux-arm64-2.334.0.tar.gz
./config.sh --url https://github.com/hbmar-hb/trading-bot-platform --token B6AYN7K2IMK3A6HG3OTYEUDJ6ZYD2 --unattended --name trading-vps
"

# Instalar como servicio (requiere root)
cd /home/deploy/actions-runner
./svc.sh install deploy
./svc.sh start
echo "=== Runner instalado y corriendo ==="
