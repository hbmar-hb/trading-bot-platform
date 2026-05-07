from celery import Celery
from celery.schedules import crontab

from config.settings import settings

celery_app = Celery(
    "trading_bot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.order_tasks",
        "app.tasks.sl_update_tasks",
        "app.tasks.notification_tasks",
        "app.tasks.cleanup_tasks",
        "app.tasks.health_check_tasks",
        "app.tasks.sync_tasks",
        "app.tasks.sl_retry_tasks",
        "app.tasks.optimizer_tasks",
        "app.tasks.limit_order_tasks",
        "app.tasks.ict_scan_tasks",
        "app.tasks.ai_outcome_tracker",
        "app.tasks.bot_activator_task",
        "app.tasks.ai_retrain_task",
        "app.tasks.ai_scan_task",
        "app.tasks.circuit_breaker_task",
    ],
)

celery_app.conf.update(
    # Serialización
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Fiabilidad: acknowledge solo al completar, no al recibir
    task_acks_late=True,
    worker_prefetch_multiplier=1,   # un task a la vez por worker slot
    task_track_started=True,

    # Resultado expira en 24h (no almacenamos resultados indefinidamente)
    result_expires=86400,

    # Reintentos por defecto si el broker no está disponible
    broker_connection_retry_on_startup=True,

    # ─── Enrutamiento de tareas a colas específicas ──────────
    # En docker-compose el worker escucha: orders, sl_updates, notifications, default
    task_routes={
        "app.tasks.order_tasks.*":        {"queue": "orders"},
        "app.tasks.sl_update_tasks.*":    {"queue": "sl_updates"},
        "app.tasks.notification_tasks.*": {"queue": "notifications"},
        # cleanup y health_check van a la cola default
    },

    # ─── Tareas periódicas (Celery Beat) ─────────────────────
    beat_schedule={
        # Limpieza de logs: cada día a las 2 AM UTC
        "cleanup-old-logs": {
            "task": "app.tasks.cleanup_tasks.delete_old_logs",
            "schedule": crontab(hour=2, minute=0),
            "kwargs": {"days_to_keep": settings.cleanup_logs_days},
        },
        # Health check de exchanges: cada 5 minutos
        "health-check-exchanges": {
            "task": "app.tasks.health_check_tasks.check_exchanges",
            "schedule": 300.0,
        },
        # Sincronización automática de trades: cada hora
        "sync-exchange-trades": {
            "task": "app.tasks.sync_tasks.sync_all_accounts_trades_task",
            "schedule": 3600.0,
        },
        # Reintentos automáticos de SL pendientes (bloqueados por BingX 109400)
        "retry-pending-sl-orders": {
            "task": "app.tasks.sl_retry_tasks.retry_pending_sl_orders",
            "schedule": 30.0,  # cada 30 segundos
        },
        # Auto-optimización periódica de bots habilitados: cada 5 minutos
        "auto-optimize-all-bots": {
            "task": "app.tasks.optimizer_tasks.auto_optimize_all_bots_task",
            "schedule": 300.0,  # cada 5 minutos
        },
        # Revisar órdenes límite pendientes: cada 30 segundos
        "check-limit-orders": {
            "task": "app.tasks.limit_order_tasks.check_limit_orders",
            "schedule": 30.0,
        },
        # Motor ICT: escanea bots con ict_scan_enabled=True cada 60 segundos
        # El throttle interno por timeframe evita señales redundantes
        "ict-scan-all": {
            "task": "app.tasks.ict_scan_tasks.ict_scan_all",
            "schedule": 60.0,
        },
        # AI outcome tracker: etiqueta señales PENDING cada 15 minutos
        "ai-track-outcomes": {
            "task": "app.tasks.ai_outcome_tracker.track_outcomes",
            "schedule": 900.0,
        },
        # XGBoost Anti-Fake retrain semanal: domingos 03:00 UTC
        "ai-retrain-weekly": {
            "task": "app.tasks.ai_retrain_task.retrain_anti_fake",
            "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),
        },
        # AI watchlist scanner: escanea todos los pares del watchlist cada 5 minutos
        # Persiste resultados en ai_latest_scans para que el dashboard esté siempre actualizado
        "ai-scan-watchlists": {
            "task": "app.tasks.ai_scan_task.scan_all_watchlists",
            "schedule": 300.0,
        },
        # Circuit breaker: pausa bots AI con 3 pérdidas consecutivas
        "ai-circuit-breakers": {
            "task": "app.tasks.circuit_breaker_task.check_circuit_breakers",
            "schedule": 900.0,  # cada 15 minutos
        },
    },
)
