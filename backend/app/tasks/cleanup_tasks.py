from celery import shared_task
from datetime import datetime, timedelta
from loguru import logger


@shared_task(name="app.tasks.cleanup_tasks.delete_old_logs")
def delete_old_logs(days_to_keep: int = 30) -> dict:
    """Elimina BotLogs y SignalLogs más antiguos que days_to_keep días."""
    from app.models.bot_log import BotLog
    from app.models.signal_log import SignalLog
    from app.services.database import SessionLocal

    cutoff = datetime.utcnow() - timedelta(days=days_to_keep)

    with SessionLocal() as db:
        deleted_bot = db.query(BotLog).filter(BotLog.created_at < cutoff).delete()
        deleted_sig = db.query(SignalLog).filter(SignalLog.received_at < cutoff).delete()
        db.commit()

    logger.info(
        f"Cleanup: eliminados {deleted_bot} bot_logs y {deleted_sig} signal_logs "
        f"anteriores a {cutoff.date()}"
    )
    return {"deleted_bot_logs": deleted_bot, "deleted_signal_logs": deleted_sig}
