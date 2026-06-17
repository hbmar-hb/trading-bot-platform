from celery import shared_task

from app.services.notifier import (
    notify_ai_signal,
    notify_auto_optimized,
    notify_error,
    notify_kill_switch,
    notify_position_override,
    notify_sl_moved,
    notify_trade_closed,
    notify_trade_opened,
    notify_trade_partial,
    notify_trade_rejected,
    notify_watchlist_coverage_alert,
)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_opened")
def trade_opened(
    bot_name: str, symbol: str, side: str, entry: float, sl: float,
    chat_id: str | None = None, is_limit: bool = False, source: str = "bot",
    tp1: float | None = None, tp2: float | None = None, tp3: float | None = None,
    trailing_config: dict | None = None,
    breakeven_config: dict | None = None,
    dynamic_sl_config: dict | None = None,
    leverage: int | None = None,
    risk_pct: float | None = None,
    quantity: float | None = None,
    order_id: str | None = None,
    signal_id: str | None = None,
    explanation: str | None = None,
    autopilot_status: str = "Aprobado",
    timeframe: str | None = None,
) -> None:
    notify_trade_opened(
        bot_name, symbol, side, entry, sl,
        chat_id=chat_id, is_limit=is_limit, source=source,
        tp1=tp1, tp2=tp2, tp3=tp3,
        trailing_config=trailing_config,
        breakeven_config=breakeven_config,
        dynamic_sl_config=dynamic_sl_config,
        leverage=leverage,
        risk_pct=risk_pct,
        quantity=quantity,
        order_id=order_id,
        signal_id=signal_id,
        explanation=explanation,
        autopilot_status=autopilot_status,
        timeframe=timeframe,
    )


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_partial")
def trade_partial(
    bot_name: str, symbol: str, side: str, tp_level: int,
    close_percent: float, fill_price: float, partial_pnl: float,
    chat_id: str | None = None, source: str = "bot"
) -> None:
    notify_trade_partial(bot_name, symbol, side, tp_level, close_percent, fill_price, partial_pnl, chat_id=chat_id, source=source)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_closed")
def trade_closed(
    bot_name: str, symbol: str, side: str, pnl: float,
    chat_id: str | None = None, source: str = "bot",
    entry_price: float | None = None,
    exit_price: float | None = None,
    quantity: float | None = None,
    leverage: int | None = None,
    timeframe: str | None = None,
) -> None:
    notify_trade_closed(
        bot_name, symbol, side, pnl,
        chat_id=chat_id, source=source,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        leverage=leverage,
        timeframe=timeframe,
    )


@shared_task(queue="notifications", name="app.tasks.notification_tasks.sl_moved")
def sl_moved(bot_name: str, symbol: str, side: str, old_sl: float, new_sl: float, chat_id: str | None = None) -> None:
    notify_sl_moved(bot_name, symbol, side, old_sl, new_sl, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.error_alert")
def error_alert(bot_name: str, error: str, chat_id: str | None = None) -> None:
    notify_error(bot_name, error, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.auto_optimized")
def auto_optimized(bot_name: str, symbol: str, changes: dict, health_score: int, crisis_mode: bool = False) -> None:
    notify_auto_optimized(bot_name, symbol, changes, health_score, crisis_mode)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.trade_rejected")
def trade_rejected(bot_name: str, symbol: str, side: str, reason: str, chat_id: str | None = None) -> None:
    notify_trade_rejected(bot_name, symbol, side, reason, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.position_override")
def position_override(closed_bot_name: str, opened_bot_name: str, symbol: str, side: str, chat_id: str | None = None) -> None:
    notify_position_override(closed_bot_name, opened_bot_name, symbol, side, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.kill_switch_alert")
def kill_switch_alert(
    user_name: str, closed: int, paused: int, pnl: float, elapsed: float,
    chat_id: str | None = None
) -> None:
    notify_kill_switch(user_name, closed, paused, pnl, elapsed, chat_id=chat_id)


@shared_task(queue="notifications", name="app.tasks.notification_tasks.ai_signal_alert")
def ai_signal_alert(
    ticker: str, timeframe: str, direction: str,
    score: float, quality_score: float, confidence: str,
    entry: float, sl: float, tp1: float, tp2: float,
    components: dict, warnings: list,
    htf_bias: str | None = None,
) -> None:
    notify_ai_signal(
        ticker, timeframe, direction,
        score, quality_score, confidence,
        entry, sl, tp1, tp2,
        components, warnings, htf_bias=htf_bias,
    )


@shared_task(queue="notifications", name="app.tasks.notification_tasks.watchlist_coverage_alert")
def watchlist_coverage_alert(bots: list[dict]) -> None:
    notify_watchlist_coverage_alert(bots)
