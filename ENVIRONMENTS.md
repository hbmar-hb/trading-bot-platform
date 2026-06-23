# Ambientes de Trading Bot Platform

Este proyecto dispone de dos ambientes totalmente aislados en el mismo servidor:

- **Producción** — para usuarios finales, moderadores y administradores.
- **Desarrollo** — para evolucionar y estabilizar nuevas funcionalidades sin afectar a producción.

## Estructura de directorios

```
/home/deploy/apps/trading-bot-platform          # Producción (rama main)
/home/deploy/apps/trading-bot-platform-dev      # Desarrollo (rama develop)
```

> **IMPORTANTE:** Trabaja siempre en `/home/deploy/apps/trading-bot-platform-dev`. Los cambios se promocionarán a producción mediante merge de `develop` a `main` y ejecución del script de deploy de producción.

## Ramas Git

| Ambiente  | Rama     | Directorio                                  |
|-----------|----------|---------------------------------------------|
| Producción| `main`   | `/home/deploy/apps/trading-bot-platform`    |
| Desarrollo| `develop`| `/home/deploy/apps/trading-bot-platform-dev`|

## Puertos y URLs

| Servicio          | Producción | Desarrollo |
|-------------------|------------|------------|
| Frontend          | 8080       | 8081       |
| Backend API/docs  | 8100       | 8101       |
| PostgreSQL        | 5433       | 5434       |
| Redis             | 6380       | 6381       |
| Flower (Celery)   | 5556       | 5557       |

- **Producción:** http://localhost:8080
- **Desarrollo:** http://localhost:8081
- **API producción:** http://localhost:8100/docs
- **API desarrollo:** http://localhost:8101/docs

## Levantar / parar ambientes

### Producción

```bash
cd /home/deploy/apps/trading-bot-platform
docker compose up -d --build
```

### Desarrollo

```bash
cd /home/deploy/apps/trading-bot-platform-dev
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev-env.yml \
  -f docker-compose.dev.yml \
  --env-file .env.dev \
  up -d --build
```

> El orden de los archivos `-f` es importante: `dev-env.yml` debe ir antes que `dev.yml` para que el puerto de Vite (5173) reemplace el de Nginx (80).

### Parar desarrollo

```bash
cd /home/deploy/apps/trading-bot-platform-dev
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev-env.yml \
  -f docker-compose.dev.yml \
  --env-file .env.dev \
  down
```

## Deploy automatizado

Se han añadido scripts para simplificar el deploy:

```bash
# Producción
/home/deploy/apps/trading-bot-platform/scripts/deploy-prod.sh

# Desarrollo
/home/deploy/apps/trading-bot-platform-dev/scripts/deploy-dev.sh
```

Ambos scripts actualizan la rama correspondiente, reconstruyen los contenedores y aplican las migraciones de Alembic.

## Flujo de trabajo recomendado

1. Trabaja exclusivamente en `/home/deploy/apps/trading-bot-platform-dev` (rama `develop`).
2. Haz commits y pruebas en desarrollo.
3. Cuando la funcionalidad esté estable:
   - Haz merge de `develop` a `main` (o un PR/MR si usas Git remoto).
   - Ejecuta `/home/deploy/apps/trading-bot-platform/scripts/deploy-prod.sh`.

## Notas técnicas

- Cada ambiente usa su propio nombre de proyecto Docker (`trading-bot-platform` y `trading-bot-platform-dev`), por lo que contenedores, redes y volúmenes están aislados.
- Las bases de datos son independientes (`tradingbot` en producción y `tradingbot_dev` en desarrollo).
- El archivo `.env.dev` no está versionado; se crea localmente a partir de `.env` de producción ajustando puertos y el nombre de la base de datos.
- La primera vez que se levanta desarrollo, el backend crea automáticamente un usuario `admin` con rol `admin`. Para acceder como `developer`, cámbialo directamente en la base de datos o usa el endpoint de gestión de usuarios una vez logueado.

## Solución de problemas

### Caché del navegador

Si después de un deploy no ves los cambios en el frontend, usa `Ctrl + F5` (o `Cmd + Shift + R` en macOS) para forzar la recarga.

### Migraciones

Si el backend de desarrollo no arranca por problemas de migraciones, ejecuta:

```bash
cd /home/deploy/apps/trading-bot-platform-dev
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev-env.yml \
  -f docker-compose.dev.yml \
  --env-file .env.dev \
  exec backend alembic upgrade head
```

### Reset completo de desarrollo

> **Advertencia:** esto borra todos los datos de desarrollo.

```bash
cd /home/deploy/apps/trading-bot-platform-dev
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev-env.yml \
  -f docker-compose.dev.yml \
  --env-file .env.dev \
  down -v
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev-env.yml \
  -f docker-compose.dev.yml \
  --env-file .env.dev \
  up -d --build
```
