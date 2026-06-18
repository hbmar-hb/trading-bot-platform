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
        "app.tasks.ai_drift_monitor_task",
        "app.tasks.ai_scan_task",
        "app.tasks.circuit_breaker_task",
        "app.tasks.drawdown_guard",
        "app.tasks.reconcile_task",
        "app.tasks.kill_switch_task",
        "app.tasks.divergence_tracker_task",
        "app.tasks.confidence_decay_task",
        "app.tasks.deployment_gate_task",
        "app.tasks.ai_optimal_config_task",
        "app.tasks.watchlist_coverage_task",
        "app.tasks.llm_threshold_optimizer",
        "app.tasks.activator_calibration_task",
        "app.tasks.dynamic_risk_tasks",
        "app.tasks.llm_tasks",
        "app.tasks.rejected_signal_audit_task",
        "app.tasks.rejection_feedback_task",
        "app.tasks.mc_optimizer_task",
        "app.tasks.slippage_recalibration_task",
        "app.tasks.confirmation_scan_task",
        "app.tasks.shadow_monitor_task",
    ],
)

celery_app.conf.update(
    # Cola por defecto: el worker escucha default, no celery
    task_default_queue="default",

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

    # Resultado expira en 1h (reduce presión en Redis a escala)
    result_expires=3600,

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
        # Health check de exchanges: cada 10 minutos
        "health-check-exchanges": {
            "task": "app.tasks.health_check_tasks.check_exchanges",
            "schedule": 600.0,
        },
        # Sincronización automática de trades: cada hora
        "sync-exchange-trades": {
            "task": "app.tasks.sync_tasks.sync_all_accounts_trades_task",
            "schedule": 3600.0,
        },
        # Reintentos automáticos de SL pendientes (bloqueados por BingX 109400)
        "retry-pending-sl-orders": {
            "task": "app.tasks.sl_retry_tasks.retry_pending_sl_orders",
            "schedule": 60.0,  # cada 60 segundos (reducido para ahorrar memoria)
        },
        # Auto-optimización periódica de bots habilitados: cada 10 minutos
        "auto-optimize-all-bots": {
            "task": "app.tasks.optimizer_tasks.auto_optimize_all_bots_task",
            "schedule": 600.0,  # cada 10 minutos (reducido para ahorrar memoria)
        },
        # Revisar órdenes límite pendientes: cada 60 segundos
        "check-limit-orders": {
            "task": "app.tasks.limit_order_tasks.check_limit_orders",
            "schedule": 300.0,
        },
        # Motor ICT: escanea bots con ict_scan_enabled=True cada 10 minutos
        # El throttle interno por timeframe evita señales redundantes
        "ict-scan-all": {
            "task": "app.tasks.ict_scan_tasks.ict_scan_all",
            "schedule": 600.0,
        },
        # AI outcome tracker: etiqueta señales PENDING cada 15 minutos
        "ai-track-outcomes": {
            "task": "app.tasks.ai_outcome_tracker.track_outcomes",
            "schedule": 900.0,
        },
        # XGBoost Anti-Fake retrain: cada 6 horas (reentrena si ≥24h o ≥50 señales nuevas)
        "ai-retrain-daily": {
            "task": "app.tasks.ai_retrain_task.retrain_anti_fake",
            "schedule": 21600.0,  # 6 horas
        },
        # Per-bot model retrain: cada 1 hora (timeframe-aware + hybrid sample threshold)
        "ai-retrain-bots-hourly": {
            "task": "app.tasks.ai_retrain_task.retrain_bot_models",
            "schedule": 3600.0,  # 1 hora
        },
        # LLM threshold optimizer: analiza diagnósticos y AUTO-APPLY ajustes cada 24h
        "llm-threshold-opt": {
            "task": "app.tasks.llm_threshold_optimizer.analyze_and_apply",
            "schedule": 86400.0,  # 24 horas
        },
        # Auto-resume bots after kill_switch cooldown
        "kill-switch-auto-resume": {
            "task": "app.tasks.kill_switch_task.auto_resume_after_kill_switch",
            "schedule": 1800.0,  # cada 30 minutos
        },
        # Activator threshold auto-calibration
        "activator-threshold-calibration": {
            "task": "app.tasks.activator_calibration_task.calibrate_thresholds",
            "schedule": 43200.0,  # cada 12 horas
        },
        # Feature drift monitor: revisa drift PSI cada 4 horas
        "ai-drift-monitor": {
            "task": "app.tasks.ai_drift_monitor_task.monitor_feature_drift",
            "schedule": 14400.0,  # 4 horas
        },
        # AI watchlist scanner: escanea todos los pares del watchlist cada 15 minutos
        # Persiste resultados en ai_latest_scans para que el dashboard esté siempre actualizado.
        # El intervalo es 15 min porque un scan completo de ~120 pares puede tardar >10 min.
        "ai-scan-watchlists": {
            "task": "app.tasks.ai_scan_task.scan_all_watchlists",
            "schedule": 900.0,
        },
        # SMC Confirmation Entry scanner: revisa watchlist cada 5 minutos
        # Promueve setups a AISignal cuando el LTF (5m) confirma CDC
        "confirmation-scan-watchlist": {
            "task": "app.tasks.confirmation_scan_task.scan_confirmation_watchlist",
            "schedule": 300.0,
        },
        # MC Setup Optimizer: optimiza parámetros de estrategias Monte Carlo cada 12 horas
        "mc-setup-optimizer": {
            "task": "app.tasks.mc_optimizer_task.optimize_mc_setups",
            "schedule": 43200.0,  # 12 horas
        },
        # Circuit breaker: pausa bots AI con 3 pérdidas consecutivas
        "ai-circuit-breakers": {
            "task": "app.tasks.circuit_breaker_task.check_circuit_breakers",
            "schedule": 1800.0,  # cada 30 minutos
        },
        # Drawdown guard: pausa bots si drawdown diario excede límite
        "drawdown-guard": {
            "task": "app.tasks.drawdown_guard.check_daily_drawdown",
            "schedule": 1800.0,  # cada 30 minutos
        },
        # Reconciliación periódica: sincroniza posiciones DB vs exchange
        "periodic-reconcile": {
            "task": "app.tasks.reconcile_task.periodic_reconcile",
            "schedule": 1800.0,  # cada 30 minutos
        },
        # Breakeven monitor: activa BE por R-multiple cada 2 minutos
        "monitor-breakeven-activation": {
            "task": "app.tasks.sl_update_tasks.monitor_breakeven_activation",
            "schedule": 120.0,  # cada 2 minutos
        },
        # Auto-reactivación post-circuit-breaker: revisa bots pausados cada 15 min
        # (ya incluida en check_circuit_breakers, pero schedule se mantiene)
        # Watchlist coverage check: alerta si bot activo no recibe señales >1h
        "watchlist-coverage-check": {
            "task": "app.tasks.watchlist_coverage_task.check_watchlist_coverage",
            "schedule": 1800.0,  # cada 30 minutos
        },
        # Refresh optimal AI config: recalcula config óptima cada hora para bots IA auto-config
        "refresh-ai-optimal-configs": {
            "task": "app.tasks.ai_optimal_config_task.refresh_optimal_configs",
            "schedule": 3600.0,  # cada 1 hora
        },
        # Paper vs Real divergence scan: cada 4 horas
        "divergence-tracker-scan": {
            "task": "app.tasks.divergence_tracker_task.run_divergence_scan_task",
            "schedule": 14400.0,  # cada 4 horas
            "kwargs": {"days": 7},
        },
        # Confidence decay tracker: cada 30 minutos (tras outcome tracker)
        "confidence-decay-track": {
            "task": "app.tasks.confidence_decay_task.track_confidence_decay",
            "schedule": 1800.0,  # cada 30 minutos
            "kwargs": {"window_size": 50},
        },
        # Deployment Gate: cada 1 hora
        "deployment-gate-evaluate": {
            "task": "app.tasks.deployment_gate_task.evaluate_deployment_gate_task",
            "schedule": 3600.0,  # cada 1 hora
        },
        # Rejected signal audit: cada 6 horas
        "rejected-signal-audit": {
            "task": "app.tasks.rejected_signal_audit_task.audit_rejected_signals",
            "schedule": 21600.0,  # 6 horas
            "kwargs": {"batch_size": 200},
        },
        # Rejection feedback calibration: cada 6 horas (offset 30 min after audit)
        "rejection-feedback-calibration": {
            "task": "app.tasks.rejection_feedback_task.calibrate_from_rejections",
            "schedule": 21600.0,  # 6 horas
        },
        # FASE 3A: Slippage predictor recalibration — cada 4 horas
        "slippage-predictor-recalibration": {
            "task": "app.tasks.slippage_recalibration_task.recalibrate_slippage_predictor",
            "schedule": 14400.0,  # 4 horas
            "kwargs": {"lookback_days": 3, "min_samples": 10},
        },
        # Shadow mode (Fase D) health check — cada 5 minutos
        "shadow-mode-monitor": {
            "task": "app.tasks.shadow_monitor_task.run_shadow_monitor",
            "schedule": 300.0,
        },
    },
)
