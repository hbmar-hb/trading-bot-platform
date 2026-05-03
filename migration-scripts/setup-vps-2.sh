#!/bin/bash
set -e

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

echo "=== 6. Configurando UFW (firewall) ==="
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "=== 7. Configurando Fail2ban ==="
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

echo "=== 8. Configurando Nginx (estructura) ==="
rm -f /etc/nginx/sites-enabled/default
mkdir -p /var/www/html

echo "=== Setup completado ==="
