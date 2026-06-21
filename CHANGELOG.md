# Changelog

## 2026-06-20 — Sincronización de Documentación

### 📚 Documentación

- Creado `README.md` raíz con descripción de la plataforma, stack, requisitos, arranque local, estructura de carpetas y mapa de documentación.
- Actualizada `IA_ENGINE_USER_REPORT.md` con las nuevas funcionalidades de junio de 2026: panel expandido, Scanner Live, Dashboard IA, Monte Carlo, roles, chat y asistente.
- Actualizada la documentación embebida en la aplicación (`DocumentationPage.jsx`) con secciones para Scanner Live, Monte Carlo, Chat, Roles, Administración del Sistema y Asistente de IA.
- Revisadas las guías de migración para marcar datos de ejemplo (IP, dominios, costos) y evitar confusiones.

## 2026-06-18 — Scanner Live, Monte Carlo, Admin System y Asistente

### 🚀 Nuevas Funcionalidades

- **Scanner Live** — Nueva pestaña en IA Engine que muestra el escaneo del mercado en tiempo real: pares analizados, señales generadas, rechazos por gates, KPIs de las últimas 24h y consejos generados por un LLM local.
- **Módulo Monte Carlo** — Permite crear estrategias en Python, ejecutar backtests históricos y lanzar simulaciones de equity con múltiples métodos (shuffle, bootstrap, perturbación de parámetros, equity path). Requiere rol `moderator`.
- **Panel de Administración del Sistema** — Nuevo panel exclusivo para `admin` con checks de infraestructura, logs, salud de base de datos, modelos ML, Celery, exchange y shadow mode.
- **Asistente de IA** — Widget flotante de chat que responde dudas sobre la plataforma usando un modelo local vía Ollama (requiere configuración del puente `ollama-bridge`).
- **Chat interno** — Salas estilo Discord con mensajería en tiempo real por WebSocket, salas privadas, menciones, selector de color y reacciones.

### 🔐 Roles y Seguridad

- Nuevo sistema de roles: `admin`, `moderator` y `rol1`.
- `rol1` tiene acceso restringido a funcionalidades básicas (chat, paper trading, optimizador y señales).
- Flujos de autenticación mejorados: verificación de email, recuperación de contraseña, cambio forzado de contraseña y generador de contraseñas.

### ⚡ Mejoras

- Mayor resiliencia en el escaneo IA: manejo de duplicados, race conditions y recuperación ante fallos de fetch de velas.
- Publicación de eventos en tiempo real para señales duplicadas y errores del scanner.
- Mejoras en shadow mode y candidate model para la promoción automática de modelos.

### 🛠️ Infraestructura

- Servicio opcional `ollama-bridge` en `docker-compose.yml` para exponer Ollama local dentro de los contenedores.
- Ajustes en Nginx para rutas `/api/` y `/assistant`.
- Recuperación masiva del repositorio desde backup de emergencia el 17 de junio de 2026.

## 2026-06-12 — Verificación y fixes de Analytics

### 🐛 Bug Fixes

- **`roi_percent.toFixed is not a function` en TradeDetailModal** — Todos los valores numéricos decimales provenientes del backend (PnL, ROI, valor de posición) se convierten con `parseFloat` / `Number` antes de formatear, evitando crashes cuando Pydantic serializa `Decimal` como string.
- **Duración media en Analytics siempre mostraba `0.0h`** — `_compute_summary_from_trades` ahora calcula `avg_duration_hours` desde `opened_at` / `closed_at` de `exchange_trades`, conectando la métrica con datos reales.

### ✅ Verificación

- Se validaron todos los endpoints de Analytics (`/analytics/summary`, `/pnl-chart`, `/activity-heatmap`, `/hourly-distribution`, `/trades-detail`) con el usuario `test_rol1` y datos de prueba: métricas globales, por bot, curva de equity, heatmap, distribución horaria y detalle de trades responden correctamente.
- Se verificó aislamiento por `user_id`: `test_rol1` solo ve sus propios trades/bots.

## 2026-05-10 — IA Engine Rediseño + Fixes Críticos

### 🐛 Bug Fixes

- **`UnboundLocalError: pd` en IA Engine** — Corregido import duplicado de `pandas as pd` dentro de `confluence_engine.py` que hacía crashear el escaneo cuando el mercado generaba una señal real.
- **Frontend sobrescribía watchlist al limpiar localStorage** — `AIPage.jsx` ahora recupera la watchlist del backend primero antes de usar `localStorage`, evitando que se pierdan los pares configurados.
- **Disco 100% lleno** — Liberados ~12 GB eliminando swapfile, caché de Docker, apt y logs rotados. PostgreSQL y nginx restaurados a funcionamiento normal.

### 🚀 Nuevas Funcionalidades — Panel Expandido del IA Engine

- **Panel expandido debajo del grid** — Al pulsar una caja del escáner ya no se abre un modal; aparece un panel anclado debajo con toda la información del par.
- **3 pestañas internas:**
  - **Detalle** — Gráfico ICT en tiempo real con Order Blocks, FVGs, EQ highs/lows y contexto textual.
  - **Backtest** — Resumen ejecutivo (total señales, resueltas, win rate, avg PnL) + tabla plegable con el histórico filtrado por par.
  - **Validación** — Resumen + tabla heurística filtrada por par (tier, status, win rate, avg PnL) con selector de días (7/30/90).
- **Marca de selección** — Check azul en la esquina de la caja activa + ring azul de selección.
- **Toggle de selección** — Click en la caja seleccionada la desmarca y cierra el panel.
- **Gráfico persistente** — Al navegar entre pestañas el gráfico no se destruye; permanece montado para evitar recargas negras.

### ⚡ Mejoras de Backend

- **XGBoost Anti-Fake síncrono** — El endpoint `POST /ai/model/train` ahora ejecuta el entrenamiento en el momento (`asyncio.to_thread`) en lugar de encolarlo en Celery.
- **Macro Context discreto** — La barra de alertas macro solo aparece cuando hay información relevante (funding extremo/alto, eventos próximos o recomendación avoid/caution). Oculta automáticamente en condiciones neutrales.

### 🛠️ Infraestructura

- Backup de seguridad de la base de datos creado en `/home/deploy/backup/`.
- Watchlist del usuario restaurada desde backup (12 pares).
- Nginx configurado con `Cache-Control: no-cache` para `index.html` para invalidar caché del navegador tras deploys.

---

## Cómo usar el nuevo Panel Expandido

1. **Seleccionar un par** — Pulsa cualquier caja del escáner. Aparecerá ✓ azul y se abrirá el panel debajo.
2. **Navegar pestañas** — Usa los tabs *Detalle | Backtest | Validación* dentro del panel.
3. **Ver detalle del backtest** — En la pestaña Backtest, pulsa "Ver detalle" para expandir la tabla completa de señales.
4. **Cambiar días en validación** — En Validación, selecciona 7d / 30d / 90d para ajustar la ventana histórica.
5. **Deseleccionar** — Pulsa la misma caja de nuevo o el botón ✕ del panel para cerrarlo.
