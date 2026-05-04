#!/bin/bash
# =============================================================================
# Setup inicial del VPS en Hetzner para Trading Bot Platform
# Ejecutar como root en el VPS recién creado
# =============================================================================

set -e

echo "=== 1. Actualizando sistema ==="
apt update && apt upgrade -y

echo "=== 2. Instalando Docker + Docker Compose ==="
apt install -y docker.io docker-compose-plugin
systemctl enable docker
systemctl start docker

echo "=== 3. Instalando dependencias ==="
apt install -y git nginx certbot python3-certbot-nginx ufw fail2ban

echo "=== 4. Creando usuario deploy ==="
adduser --gecos "" deploy
usermod -aG docker deploy
usermod -aG sudo deploy

echo "=== 5. Configurando SSH (solo key auth) ==="
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

echo "=== 6. Copiando clave SSH pública ==="
mkdir -p /home/deploy/.ssh
# El usuario debe copiar manualmente el contenido de hetzner_deploy_key.pub aquí:
# echo "TU_CLAVE_PUBLICA" >> /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

echo "=== 7. Configurando UFW (firewall) ==="
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "=== 8. Configurando Fail2ban ==="
cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
EOF
systemctl enable fail2ban
systemctl restart fail2ban

echo "=== 9. Configurando Nginx (estructura) ==="
rm -f /etc/nginx/sites-enabled/default
mkdir -p /var/www/html

echo "=== Setup completado ==="
echo ""
echo "PASOS MANUALES PENDIENTES:"
echo "  1. Copiar tu clave publica a /home/deploy/.ssh/authorized_keys"
echo "  2. Cambiar de usuario: su - deploy"
echo "  3. Clonar repo: git clone https://github.com/hbmar-hb/trading-bot-platform.git"
echo "  4. Copiar .env al proyecto"
echo "  5. Ejecutar: cd trading-bot-platform && docker compose up -d"
