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
    },
)
