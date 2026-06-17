#!/bin/bash
# =============================================================================
# SETUP VPS NUEVO — Ejecutar como root en 167.233.99.178
# Configura el servidor nuevo para recibir la migración
# =============================================================================

set -e

NEW_USER="deploy"
PROJECT_DIR="/home/${NEW_USER}/apps/trading-bot-platform"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   SETUP VPS NUEVO — Trading Bot Platform                     ║"
echo "║   167.233.99.178 | 4vCPU | 8GB RAM | 160GB Disk              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Actualizar sistema ──
echo "🔧 [1/8] Actualizando sistema..."
apt-get update && apt-get upgrade -y

# ── 2. Instalar Docker ──
echo "🔧 [2/8] Instalando Docker y Docker Compose..."
apt-get install -y ca-certificates curl gnupg lsb-release
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker
systemctl start docker

# ── 3. Instalar utilidades ──
echo "🔧 [3/8] Instalando utilidades (git, nginx, certbot, ufw, fail2ban)..."
apt-get install -y git nginx certbot python3-certbot-nginx ufw fail2ban rsync

# ── 4. Crear usuario deploy ──
echo "🔧 [4/8] Creando usuario ${NEW_USER}..."
if ! id "$NEW_USER" &>/dev/null; then
    adduser --gecos "" "$NEW_USER"
fi
usermod -aG docker "$NEW_USER"
usermod -aG sudo "$NEW_USER"

# ── 5. Configurar SSH (deshabilitar password, solo keys) ──
echo "🔧 [5/8] Configurando SSH (solo key auth)..."
sed -i 's/#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd

# ── 6. Configurar firewall ──
echo "🔧 [6/8] Configurando UFW..."
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ── 7. Configurar fail2ban ──
echo "🔧 [7/8] Configurando fail2ban..."
cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 3
EOF
systemctl enable fail2ban
systemctl restart fail2ban

# ── 8. Preparar estructura ──
echo "🔧 [8/8] Preparando estructura de directorios..."
mkdir -p "$PROJECT_DIR"
rm -f /etc/nginx/sites-enabled/default
chown -R "${NEW_USER}:${NEW_USER}" /home/${NEW_USER}

# ── Resumen ──
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   VPS NUEVO LISTO PARA RECIBIR LA MIGRACION                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 PASOS MANUALES PENDIENTES:"
echo ""
echo "   1. Copia tu clave SSH pública al nuevo usuario:"
echo "      mkdir -p /home/${NEW_USER}/.ssh"
echo "      echo 'TU_CLAVE_PUBLICA_SSH' >> /home/${NEW_USER}/.ssh/authorized_keys"
echo "      chown -R ${NEW_USER}:${NEW_USER} /home/${NEW_USER}/.ssh"
echo "      chmod 700 /home/${NEW_USER}/.ssh"
echo "      chmod 600 /home/${NEW_USER}/.ssh/authorized_keys"
echo ""
echo "   2. Transfiere el paquete de migración desde el VPS viejo:"
echo "      (Ejecuta en el VPS viejo):"
echo "      scp /tmp/trading-bot-migration-*.tar.gz root@167.233.99.178:/root/"
echo ""
echo "   3. Extrae y ejecuta el restore:"
echo "      ssh root@167.233.99.178"
echo "      tar xzf /root/trading-bot-migration-*.tar.gz -C /tmp/"
echo "      MIGRATE_DIR=\$(ls -d /tmp/migration_* | sort | tail -n1)"
echo "      bash \$MIGRATE_DIR/project/migration-scripts/restore-on-new-vps.sh \$MIGRATE_DIR"
echo ""
