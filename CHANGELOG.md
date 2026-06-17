# Changelog

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
