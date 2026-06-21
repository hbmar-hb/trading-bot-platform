# Guia de Migracion a Hetzner Cloud

> **Nota:** Los precios, nombres de servidor y dominios de ejemplo (p. ej. `tudominio.com`, `trading.tudominio.com`, CPX21 a 7,50 EUR/mes) son **orientativos** y pueden haber cambiado. Ajusta IPs, dominios y tarifas a tu situación real antes de seguir la guía.

## Resumen
Migrar Trading Bot Platform desde tu PC Windows local a un VPS en Hetzner Cloud.

---

## FASE 0: Preparativos locales (antes de tocar Hetzner)

### 0.1 Generar backup de PostgreSQL
```powershell
# Ejecutar en PowerShell desde la carpeta migration-scripts
cd migration-scripts
.\backup-local.ps1
```
Esto crea un archivo como `backup_trading_20250101_143022.sql`.

### 0.2 Preparar archivos de configuracion
Ya tienes listos en esta carpeta (`migration-scripts/`):
- `setup-vps.sh` — Script de configuracion inicial del VPS
- `nginx-trading.conf` — Configuracion de Nginx
- `hetzner_deploy_key` / `.pub` — Clave SSH para acceso seguro

---

## FASE 1: Crear VPS en Hetzner (manual)

### 1.1 Registrar cuenta
1. Ve a [console.hetzner.cloud](https://console.hetzner.cloud)
2. Registrate con email y verifica
3. Anade metodo de pago (tarjeta o PayPal)
4. **Verificacion de identidad:** sube foto de tu DNI/pasaporte (obligatorio para la primera vez)

### 1.2 Crear servidor
1. En el panel, haz clic en **"Add Server"**
2. Ubicacion: **Falkenstein** o **Nuremberg** (Alemania)
3. Tipo: **CPX21** (4 vCPU ARM, 8 GB RAM, 80 GB NVMe) = 7,50 EUR/mes
4. Sistema: **Ubuntu 24.04**
5. Redes: IPv4 publica
6. **SSH Keys:** Pega el contenido de `hetzner_deploy_key.pub`
7. Firewall: marca **"Create Firewall"** y abre puertos:
   - TCP 22 (SSH)
   - TCP 80 (HTTP)
   - TCP 443 (HTTPS)
8. Nombre del servidor: `trading-bot-vps`
9. Clic en **"Create & Buy"**

### 1.3 Comprar dominio
1. Ve a [namecheap.com](https://namecheap.com) o [cloudflare.com](https://cloudflare.com)
2. Compra un dominio (ej: `tudominio.com`, ~10 EUR/anio)
3. Ve a **DNS Management** y crea un registro:
   - Tipo: **A**
   - Host: `trading`
   - Valor: **IP de tu VPS** (la ves en el panel de Hetzner)
   - TTL: Automatico
4. Espera 5-30 minutos a que se propague el DNS

---

## FASE 2: Configurar VPS (automatico)

### 2.1 Conectar por SSH y ejecutar setup
```bash
# Desde Windows PowerShell o Git Bash
ssh -i migration-scripts/hetzner_deploy_key root@IP_DEL_VPS
```

Una vez dentro del VPS como root:
```bash
# Actualizar e instalar todo
apt update && apt upgrade -y
apt install -y docker.io docker-compose-plugin git nginx certbot python3-certbot-nginx ufw fail2ban

# Habilitar Docker
systemctl enable docker && systemctl start docker

# Crear usuario deploy
adduser --gecos "" deploy
usermod -aG docker deploy
usermod -aG sudo deploy

# Copiar clave SSH
mkdir -p /home/deploy/.ssh
cat > /home/deploy/.ssh/authorized_keys << 'EOF'
PEGA_AQUI_EL_CONTENIDO_DE_hetzner_deploy_key.pub
EOF
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# Seguridad SSH
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# Fail2ban
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

exit
```

### 2.2 Copiar script setup completo (alternativa)
En lugar de pegar comando a comando, tambien puedes:
```bash
# Desde tu PC Windows, copiar el script al VPS
scp -i migration-scripts/hetzner_deploy_key migration-scripts/setup-vps.sh root@IP_DEL_VPS:/root/

# Luego ejecutarlo en el VPS
ssh -i migration-scripts/hetzner_deploy_key root@IP_DEL_VPS "bash /root/setup-vps.sh"
```

---

## FASE 3: Desplegar aplicacion

### 3.1 Clonar repo y preparar entorno
```bash
# Conectar como usuario deploy
ssh -i migration-scripts/hetzner_deploy_key deploy@IP_DEL_VPS

# Clonar
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/hbmar-hb/trading-bot-platform.git
cd trading-bot-platform

# Crear .env (copiar desde tu PC local)
# Debes copiar el archivo .env de tu PC Windows al VPS
```

### 3.2 Copiar .env desde Windows al VPS
```powershell
# Desde PowerShell en tu PC local
$VPS_IP = "IP_DEL_VPS"
scp -i migration-scripts/hetzner_deploy_key .env deploy@${VPS_IP}:~/apps/trading-bot-platform/
```

### 3.3 Actualizar .env para produccion
Edita el `.env` en el VPS:
```bash
nano ~/apps/trading-bot-platform/.env
```

Cambiar estas variables:
```
ENV=production
DEBUG=false
FRONTEND_URL=https://trading.tudominio.com
API_BASE_URL=https://trading.tudominio.com/api
```

### 3.4 Copiar backup de PostgreSQL y restaurar
```powershell
# Desde tu PC Windows
$VPS_IP = "IP_DEL_VPS"
$BACKUP = "backup_trading_20250101_143022.sql"  # El que generaste
scp -i migration-scripts/hetzner_deploy_key migration-scripts/$BACKUP deploy@${VPS_IP}:~/apps/trading-bot-platform/
```

En el VPS:
```bash
cd ~/apps/trading-bot-platform

# Levantar solo PostgreSQL primero
DOMAIN=trading.tudominio.com docker compose -f docker-compose.prod.yml up -d postgres

# Esperar a que este listo (10 segundos)
sleep 10

# Restaurar datos
docker exec -i trading-bot-platform-postgres-1 psql -U admin -d tradingbot < backup_trading_*.sql
```

### 3.5 Levantar toda la aplicacion
```bash
cd ~/apps/trading-bot-platform
DOMAIN=trading.tudominio.com docker compose -f docker-compose.prod.yml up -d --build
```

Verificar que todo esta corriendo:
```bash
docker compose -f docker-compose.prod.yml ps
```

---

## FASE 4: Configurar Nginx + SSL

### 4.1 Configurar Nginx
```bash
# Como root en el VPS
sudo su

# Copiar configuracion
cp /home/deploy/apps/trading-bot-platform/migration-scripts/nginx-trading.conf /etc/nginx/sites-available/trading

# Editar el dominio
sed -i 's/server_name _;/server_name trading.tudominio.com;/' /etc/nginx/sites-available/trading

# Activar sitio
rm -f /etc/nginx/sites-enabled/default
ln -s /etc/nginx/sites-available/trading /etc/nginx/sites-enabled/

# Verificar y recargar
nginx -t
systemctl reload nginx
```

### 4.2 Obtener certificado SSL (Let's Encrypt)
```bash
certbot --nginx -d trading.tudominio.com
```
Sigue las instrucciones. Selecciona:
- `2: Redirect` (redirige HTTP a HTTPS automaticamente)

Certbot renueva automaticamente via cron.

---

## FASE 5: Verificar

Abre en navegador:
- `https://trading.tudominio.com` → Debe cargar el frontend
- `https://trading.tudominio.com/api/v1/auth/login` → Debe devolver JSON del backend

---

## FASE 6: Auto-deploy con GitHub Actions (opcional)

Puedes configurar deploy automatico cuando hagas push a master:

### Opcion A: GitHub Actions + SSH al VPS
Crea un secret `VPS_SSH_KEY` en GitHub con la clave privada `hetzner_deploy_key`.

### Opcion B: GitHub Actions runner self-hosted en el VPS
Instala el runner en el VPS:
```bash
cd ~/apps
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.319.1.tar.gz -L https://github.com/actions/runner/releases/download/v2.319.1/actions-runner-linux-x64-2.319.1.tar.gz
tar xzf actions-runner-linux-x64-2.319.1.tar.gz
./config.sh --url https://github.com/hbmar-hb/trading-bot-platform --token TU_TOKEN
./run.sh
```

Luego actualiza `.github/workflows/deploy.yml` para usar `runs-on: self-hosted`.

---

## Troubleshooting

### PostgreSQL no levanta
```bash
docker compose -f docker-compose.prod.yml logs postgres
```

### Nginx error 502 (Bad Gateway)
```bash
# Verificar que backend esta corriendo
docker compose -f docker-compose.prod.yml logs backend
# Verificar puertos
netstat -tlnp | grep 8100
```

### SSL no funciona
```bash
# Verificar certificado
certbot certificates
# Renovar manualmente si es necesario
certbot renew --dry-run
```

### Acceso SSH denegado
```bash
# Desde la consola web de Hetzner (VNC), verificar:
cat /home/deploy/.ssh/authorized_keys
# Debe contener la clave publica de hetzner_deploy_key.pub
```

---

## Costo mensual estimado
| Servicio | Costo |
|----------|-------|
| Hetzner CPX21 (VPS) | 7,50 EUR/mes |
| Dominio .com | ~10 EUR/anio |
| **Total mensual** | **~8,30 EUR/mes** |
