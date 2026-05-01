from celery import shared_task

from app.services.notifier import (
    notify_auto_optimized,
    notify_error,
    notify_trade_closed,
    notify_trade_opened,
)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_opened")
def trade_opened(bot_name: str, symbol: str, side: str, entry: float, sl: float) -> None:
    notify_trade_opened(bot_name, symbol, side, entry, sl)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_closed")
def trade_closed(bot_name: str, symbol: str, side: str, pnl: float) -> None:
    notify_trade_closed(bot_name, symbol, side, pnl)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.error_alert")
def error_alert(bot_name: str, error: str) -> None:
    notify_error(bot_name, error)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.auto_optimized")
def auto_optimized(bot_name: str, symbol: str, changes: dict, health_score: int, crisis_mode: bool = False) -> None:
    notify_auto_optimized(bot_name, symbol, changes, health_score, crisis_mode)
