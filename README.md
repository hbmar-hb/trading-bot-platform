# Trading Bot Platform

Plataforma de trading automatizado de criptomonedas orientada a futuros perpetuos. Combina bots configurables, análisis técnico ICT/SMC, inteligencia artificial, gestión de riesgo institucional y ejecución en exchanges reales o en simulación (paper trading).

---

## ¿Qué puedes hacer con esta plataforma?

- **Operar de forma automática** en exchanges como BingX y Bitunix usando bots configurables.
- **Probar estrategias sin riesgo** mediante cuentas de paper trading.
- **Recibir señales de IA** generadas con análisis técnico avanzado (ICT/SMC) y evaluadas por un ensemble de machine learning.
- **Backtestear y simular estrategias propias** con el módulo Monte Carlo.
- **Gestionar riesgo agregado** con portfolio manager, circuit breakers, deployment gates y apalancamiento dinámico.
- **Monitorizar la salud del sistema** desde el panel de administración.
- **Colaborar con tu equipo** a través del chat interno con salas y roles.

---

## Stack tecnológico (a alto nivel)

- **Frontend:** aplicación web en React servida por Nginx.
- **Backend:** API REST/WebSocket en FastAPI, tareas periódicas con Celery.
- **Base de datos:** PostgreSQL.
- **Caché / colas / pub-sub:** Redis.
- **Infraestructura:** Docker Compose.
- **Opcional:** Ollama para modelos de lenguaje locales que alimentan el asistente y tips del Scanner Live.

---

## Requisitos

- Docker y Docker Compose.
- Git.
- Acceso a cuentas de exchange si quieres operar en real.
- Para usar el asistente local: una instancia de Ollama accesible desde los contenedores (ver `docker-compose.yml` y el servicio opcional `ollama-bridge`).

---

## Arranque local

1. Clona el repositorio.
2. Copia `.env.example` a `.env` y rellena las variables:
   ```bash
   cp .env.example .env
   ```
3. Genera las claves de seguridad que se indican en `.env.example`.
4. Levanta los servicios:
   ```bash
   docker compose up -d
   ```
5. Accede al frontend en `http://localhost` y a la API en `http://localhost:8100`.

> Consulta `.env.example` para una descripción detallada de cada variable. Nunca subas el archivo `.env` a Git.

---

## Estructura del repositorio

```
├── backend/            # API, motores de señal, IA, ejecución y gestión de riesgo
├── frontend/           # Aplicación web React
├── docker/             # Configuraciones de PostgreSQL, Redis y PgBouncer
├── migration-scripts/  # Guías y scripts para migraciones y despliegue en VPS
├── scripts/            # Scripts de utilidad y monitorización
├── docker-compose*.yml # Definición de servicios (dev / prod)
├── CHANGELOG.md        # Bitácora de cambios del producto
├── IA_ENGINE_USER_REPORT.md    # Guía de usuario del motor IA
├── IA_ENGINE_ARCHITECTURE.md   # Arquitectura técnica del motor IA
└── IA_ENGINE_DEV_REPORT.md     # Informe de desarrollo del motor IA
```

---

## Mapa de documentación

| Documento | Para quién | Qué cubre |
|-----------|------------|-----------|
| `CHANGELOG.md` | Todos | Cambios recientes, nuevas funcionalidades y fixes. |
| `IA_ENGINE_USER_REPORT.md` | Usuario final | Guía completa del motor IA: scanner, backtest, validación, métricas, Monte Carlo, chat y asistente. |
| `IA_ENGINE_ARCHITECTURE.md` | Usuario técnico / admin | Arquitectura, pipeline de decisiones, métricas de modelo, shadow mode y gates. |
| `IA_ENGINE_DEV_REPORT.md` | Desarrolladores | Pipeline de entrenamiento, servicios y decisiones técnicas del motor IA. |
| `frontend/src/pages/DocumentationPage.jsx` | Usuario final | Documentación embebida en la aplicación (accesible desde el menú **Docs**). |
| `migration-scripts/MIGRATION_GUIDE.md` | Admin / DevOps | Migración inicial a VPS Hetzner. |
| `migration-scripts/MIGRATE_TO_NEW_VPS.md` | Admin / DevOps | Migración del VPS actual a un servidor nuevo. |
| `migration-scripts/MIGRATION_DATACONTROL.md` | Admin / DevOps | Despliegue del frontend estático DataControl en el mismo VPS. |

---

## Roles de usuario

La plataforma distingue tres roles:

- **`rol1`**: experiencia limitada. Puede usar chat, paper trading, optimizador y señales de trading básicas.
- **`moderator`**: acceso a motor IA, Monte Carlo y gestión avanzada de bots.
- **`admin`**: acceso total, incluyendo gestión de usuarios, panel de administración del sistema y kill switch de emergencia.

Más detalles en `IA_ENGINE_USER_REPORT.md`.

---

## Primeros pasos recomendados

1. Accede con las credenciales proporcionadas por el administrador.
2. Revisa el **Dashboard** para ver equity, posiciones abiertas y bots activos.
3. Configura una cuenta **paper** desde el menú **Paper**.
4. Crea tu primer bot en **Bots → Nuevo bot** y selecciona el modo de activación que prefieras (Webhook, Indicador o IA).
5. Si usas IA, revisa la guía del motor IA antes de activar tiers inferiores.

---

## Seguridad y responsabilidad

- Guarda las API keys de los exchanges con permisos de solo lectura y trading. No actives retiros.
- Empieza siempre con paper trading para validar estrategias nuevas.
- El trading automatizado conlleva riesgo. La plataforma incluye múltiples mecanismos de protección, pero no elimina la posibilidad de pérdidas.

---

*Última actualización de esta guía: 2026-06-20.*
