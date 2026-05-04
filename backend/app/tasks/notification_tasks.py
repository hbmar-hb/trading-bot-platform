from celery import shared_task

from app.services.notifier import (
    notify_auto_optimized,
    notify_error,
    notify_sl_moved,
    notify_trade_closed,
    notify_trade_opened,
    notify_trade_partial,
)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_opened")
def trade_opened(bot_name: str, symbol: str, side: str, entry: float, sl: float, chat_id: str | None = None, is_limit: bool = False) -> None:
    notify_trade_opened(bot_name, symbol, side, entry, sl, chat_id=chat_id, is_limit=is_limit)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_partial")
def trade_partial(
    bot_name: str, symbol: str, side: str, tp_level: int,
    close_percent: float, fill_price: float, partial_pnl: float,
    chat_id: str | None = None
) -> None:
    notify_trade_partial(bot_name, symbol, side, tp_level, close_percent, fill_price, partial_pnl, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_closed")
def trade_closed(bot_name: str, symbol: str, side: str, pnl: float, chat_id: str | None = None) -> None:
    notify_trade_closed(bot_name, symbol, side, pnl, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.sl_moved")
def sl_moved(bot_name: str, symbol: str, side: str, old_sl: float, new_sl: float, chat_id: str | None = None) -> None:
    notify_sl_moved(bot_name, symbol, side, old_sl, new_sl, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.error_alert")
def error_alert(bot_name: str, error: str, chat_id: str | None = None) -> None:
    notify_error(bot_name, error, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.auto_optimized")
def auto_optimized(bot_name: str, symbol: str, changes: dict, health_score: int, crisis_mode: bool = False) -> None:
    notify_auto_optimized(bot_name, symbol, changes, health_score, crisis_mode)
