# Guía de Migración — VPS Nuevo

> **Nota:** La IP `167.233.99.178` y los recursos listados en esta guía son un **ejemplo concreto de una migración realizada**. Reemplázalos por la IP, tamaño de servidor y recursos de tu VPS destino antes de ejecutar los comandos.

Migrar Trading Bot Platform desde el VPS actual al nuevo servidor con más capacidad.

---

## 📊 Comparativa de recursos

| Recurso | VPS Actual | VPS Nuevo |
|---------|-----------|-----------|
| vCPU | Insuficiente | 4 vCPU |
| RAM | Insuficiente | 8 GB |
| Disco | ? | 160 GB |
| IP | Actual | 167.233.99.178 |

**Requisitos del proyecto:**
- PostgreSQL: 2GB RAM / 2 CPU
- Backend: 1.5GB RAM / 1.5 CPU
- Celery Worker: 1.5GB RAM / 1.5 CPU
- Redis: 512MB RAM / 0.5 CPU
- Frontend: 128MB RAM / 0.25 CPU
- **Total mínimo recomendado: ~6GB RAM — el nuevo VPS con 8GB lo gestiona perfectamente.**

---

## 🚀 Proceso de migración (3 fases)

### FASE 1: Preparar paquete en el VPS actual (servidor viejo)

Ejecuta en el VPS actual:

```bash
cd /home/deploy/apps/trading-bot-platform/migration-scripts
chmod +x prepare-migration.sh
bash prepare-migration.sh
```

Esto generará un archivo en `/tmp/` similar a:
```
/tmp/trading-bot-migration-20260610_120000.tar.gz
```

**Incluye:**
- Backup fresco de PostgreSQL
- Backup de Redis (dump.rdb)
- Todo el código del proyecto (sin node_modules)
- Archivo `.env` completo
- Volúmenes de Docker exportados (postgres_data, redis_data, ai_models, celery_beat_data)
- Metadatos de la migración

---

### FASE 2: Configurar el VPS nuevo (167.233.99.178)

#### Paso 2.1 — Conectar por consola web de Hetzner

Como aún no tienes SSH configurado:
1. Entra al panel de Hetzner → Consola web (VNC) de tu nuevo servidor
2. Loguéate como `root` (contraseña que te enviaron por email)
3. Cambia la contraseña de root si te lo piden

#### Paso 2.2 — Ejecutar setup del VPS

Dentro del nuevo VPS como root:

```bash
# Descargar el script directamente
curl -o /root/setup-new-vps.sh \
  https://raw.githubusercontent.com/hbmar-hb/trading-bot-platform/main/migration-scripts/setup-new-vps.sh

# O copiar desde el VPS viejo
# scp /home/deploy/apps/trading-bot-platform/migration-scripts/setup-new-vps.sh root@167.233.99.178:/root/

# Ejecutar
bash /root/setup-new-vps.sh
```

Esto instala:
- Docker + Docker Compose plugin
- Git, Nginx, Certbot, UFW, fail2ban
- Usuario `deploy` con permisos de Docker
- Seguridad básica (SSH solo key, firewall, fail2ban)

#### Paso 2.3 — Copiar tu clave SSH pública

Aún como root en el nuevo VPS:

```bash
mkdir -p /home/deploy/.ssh
# PEGA aquí tu clave pública. Ejemplo:
echo "ssh-ed25519 AAAAC3NzaC... tu@email.com" >> /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

---

### FASE 3: Transferir y restaurar

#### Paso 3.1 — Transferir el paquete de migración

Desde el **VPS actual (viejo)**:

```bash
# Busca el archivo generado
ls -lh /tmp/trading-bot-migration-*.tar.gz

# Transferir al nuevo VPS
scp /tmp/trading-bot-migration-*.tar.gz root@167.233.99.178:/root/
```

> Si no tienes acceso SSH root al nuevo VPS aún, alternativa:
> ```bash
> # En el nuevo VPS, descargar con wget/curl desde un servicio temporal
> # O usar la consola web de Hetzner para subir archivos
> ```

#### Paso 3.2 — Extraer y ejecutar restore

Conéctate al **nuevo VPS** como root:

```bash
# Extraer paquete
tar xzf /root/trading-bot-migration-*.tar.gz -C /tmp/

# Detectar directorio extraído
MIGRATE_DIR=$(ls -d /tmp/migration_* | sort | tail -n1)
echo "Directorio de migración: $MIGRATE_DIR"

# Si tienes dominio, exportarlo (opcional pero recomendado)
export DOMAIN=tudominio.com

# Ejecutar restore
bash $MIGRATE_DIR/project/migration-scripts/restore-on-new-vps.sh $MIGRATE_DIR
```

El script `restore-on-new-vps.sh` hará automáticamente:
1. Copiar el proyecto a `/home/deploy/apps/trading-bot-platform`
2. Ajustar `.env` a modo producción
3. Restaurar los volúmenes de Docker (datos de PostgreSQL, Redis, modelos AI)
4. Restaurar la base de datos desde el backup SQL
5. Construir e iniciar todos los contenedores
6. Configurar Nginx como reverse proxy
7. Solicitar certificado SSL (si definiste DOMAIN)
8. Configurar PgBouncer

---

## ✅ Verificación post-migración

```bash
# Conectar al nuevo VPS como deploy
ssh deploy@167.233.99.178
cd ~/apps/trading-bot-platform

# Verificar contenedores
docker compose -f docker-compose.prod.yml ps

# Ver logs
docker compose -f docker-compose.prod.yml logs -f --tail=100

# Probar API
curl http://localhost:8100/health
curl http://localhost:8100/api/v1/auth/login -X POST \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test"}'
```

### Acceso desde navegador

| Modo | URL |
|------|-----|
| Sin dominio | `http://167.233.99.178:8080` |
| Con dominio + SSL | `https://tudominio.com` |

---

## 🔧 Troubleshooting

### PostgreSQL no levanta
```bash
docker compose -f docker-compose.prod.yml logs postgres
# Si el volumen tiene corrupción, restaura solo desde SQL:
docker volume rm trading-bot-platform_postgres_data
docker volume create trading-bot-platform_postgres_data
docker compose -f docker-compose.prod.yml up -d postgres
sleep 10
docker exec -i trading-bot-platform-postgres-1 psql -U admin -d tradingbot < backup_postgres_*.sql
```

### Nginx error 502
```bash
# Verificar backend
docker compose -f docker-compose.prod.yml logs backend
netstat -tlnp | grep 8100

# Recargar nginx
sudo nginx -t && sudo systemctl reload nginx
```

### Error de PgBouncer (auth failed)
```bash
cd ~/apps/trading-bot-platform
python3 -c "
import hashlib, os
pw = os.environ.get('POSTGRES_PASSWORD', 'TU_PASSWORD')
user = os.environ.get('POSTGRES_USER', 'admin')
print(f'\"{user}\" \"md5' + hashlib.md5((pw + user).encode()).hexdigest() + '\"')
" > docker/pgbouncer/userlist.txt
docker compose -f docker-compose.prod.yml restart pgbouncer
```

### Permisos de Docker
```bash
sudo usermod -aG docker $USER
# Cerrar sesión y volver a entrar
```

---

## 📁 Archivos creados para esta migración

| Archivo | Descripción |
|---------|-------------|
| `prepare-migration.sh` | Script para ejecutar en VPS actual (genera paquete) |
| `setup-new-vps.sh` | Script para configurar el VPS nuevo desde cero |
| `restore-on-new-vps.sh` | Script para restaurar todo en el VPS nuevo |
| `MIGRATE_TO_NEW_VPS.md` | Esta guía |

---

## 📝 Checklist final

- [ ] Backup generado en VPS actual (`prepare-migration.sh`)
- [ ] VPS nuevo configurado (`setup-new-vps.sh`)
- [ ] Clave SSH copiada a usuario `deploy`
- [ ] Paquete transferido al nuevo VPS
- [ ] Restore ejecutado exitosamente
- [ ] Contenedores corriendo (`docker compose ps`)
- [ ] Nginx respondiendo (`curl localhost`)
- [ ] API respondiendo (`curl localhost:8100/health`)
- [ ] SSL funcionando (si aplica dominio)
- [ ] DNS apuntando a 167.233.99.178 (si aplica dominio)
- [ ] App accesible desde navegador
