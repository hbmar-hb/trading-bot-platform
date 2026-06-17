"""
Orquestador principal del trading.

Usa sesión SÍNCRONA (psycopg2) para la DB — compatible con Celery fork.
Las llamadas al exchange (CCXT/async) se ejecutan con asyncio.run()
en un loop limpio y efímero, sin reutilizar conexiones del proceso padre.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core import risk_manager
from app.exchanges.base import BaseExchange
from app.exchanges.factory import create_exchange, create_paper_exchange
from app.exchanges.paper import PaperExchange
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.models.paper_balance import PaperBalance
from app.models.position import Position
from app.models.signal_log import SignalLog
from app.services.cache import publish_position_update_sync
from app.services.database import SessionLocal
from loguru import logger

# Celery task para auto-optimización (import lazy para evitar circular deps)
_auto_optimize_bot_task = None

def _get_auto_optimize_task():
    global _auto_optimize_bot_task
    if _auto_optimize_bot_task is None:
        from app.tasks.optimizer_tasks import auto_optimize_bot_task
        _auto_optimize_bot_task = auto_optimize_bot_task
    return _auto_optimize_bot_task


# Celery tasks para notificaciones (lazy import)
_notification_tasks = None

def _get_notification_tasks():
    global _notification_tasks
    if _notification_tasks is None:
        from app.tasks import notification_tasks
        _notification_tasks = notification_tasks
    return _notification_tasks


class _BusinessError(Exception):
    """Error de lógica de negocio — no reintentar (bot inactivo, conflicto, etc.)."""


def _get_exchange_for_bot(db: Session, bot: BotConfig) -> BaseExchange:
    """
    Obtiene la instancia de exchange apropiada para el bot.
    
    Si es paper trading, crea un PaperExchange.
    Si es trading real, crea el exchange correspondiente (BingX, Bitunix).
    """
    if bot.is_paper_trading:
        # Cargar el paper balance
        paper_balance = db.query(PaperBalance).filter(
            PaperBalance.id == bot.paper_balance_id
        ).first()
        
        if not paper_balance:
            raise ValueError(f"PaperBalance {bot.paper_balance_id} no encontrado")
        
        logger.info(f"[ENGINE] Usando PAPER TRADING para bot {bot.id} - {paper_balance.label}")
        return create_paper_exchange(paper_balance, bot_id=str(bot.id))
    else:
        # Exchange real
        if not bot.exchange_account:
            raise ValueError(f"Bot {bot.id} no tiene exchange_account asignado")
        
        logger.info(f"[ENGINE] Usando EXCHANGE REAL para bot {bot.id} - {bot.exchange_account.exchange}")
        return create_exchange(bot.exchange_account)


def execute_signal(
    bot_id: str,
    signal_id: str,
    action: str,
    price: float | None,
) -> None:
    """Punto de entrada desde el Celery task — todo síncrono.

    Los errores de lógica de negocio (bot inactivo, conflicto) se capturan y
    guardan en signal_log. Los errores de exchange se propagan para que Celery
    pueda reintentar automáticamente.
    """
    with SessionLocal() as db:
        try:
            _process(db, uuid.UUID(bot_id), uuid.UUID(signal_id), action, price)
        except _BusinessError as exc:
            # Error esperado: guardar y no reintentar
            logger.warning(f"Señal {signal_id} rechazada: {exc}")
            _mark_signal_error(db, uuid.UUID(signal_id), str(exc))
            _notify_error_if_configured(db, bot_id, str(exc))
        except Exception as exc:
            # Error de exchange u otro inesperado: propagar para que Celery reintente
            logger.exception(f"Error de exchange en señal {signal_id}: {exc}")
            _mark_signal_error(db, uuid.UUID(signal_id), str(exc))
            raise  # Celery reintentará


def _arun(coro):
    """
    Ejecuta una corrutina en el event loop del thread.
    Reutiliza el loop existente para mantener vivas las sesiones aiohttp
    de ccxt.async_support. El loop se cierra cuando el thread de Celery muere.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─── Lógica principal ─────────────────────────────────────────

def _process(
    db: Session,
    bot_id: uuid.UUID,
    signal_id: uuid.UUID,
    action: str,
    price: float | None,
) -> None:
    bot = _get_active_bot(db, bot_id)
    if not bot:
        raise _BusinessError("Bot no activo en el momento de ejecución")

    action = action.strip().lower()
    
    # Cargar signal_log para verificar si es manual o webhook
    signal_log = db.query(SignalLog).filter(SignalLog.id == signal_id).first()
    raw_payload = signal_log.raw_payload if signal_log else {}
    
    # Solo usar price como orden limit si es señal MANUAL con order_type=limit
    # Las señales de webhook siempre usan market (el price es informativo de TV)
    is_manual_limit = (
        raw_payload.get("source") == "manual" and 
        raw_payload.get("order_type") == "limit" and
        price is not None
    )
    effective_price = price if is_manual_limit else None
    
    logger.info(f"[ENGINE] Signal source: {raw_payload.get('source', 'webhook')}, "
                f"action: {action}, is_manual_limit: {is_manual_limit}")

    # Determinar source de la señal
    signal_source = raw_payload.get("source", "webhook")
    if is_manual_limit:
        signal_source = "manual"
    
    if action in ("long", "short"):
        # Validación post-delay: si el bot tiene confirmación configurada y la señal
        # trajo precio de referencia, verificar que el precio actual confirma la dirección
        confirmation_minutes = getattr(bot, "signal_confirmation_minutes", 0) or 0
        signal_price = raw_payload.get("price")
        if confirmation_minutes > 0 and signal_price and not is_manual_limit:
            try:
                ref_price = Decimal(str(signal_price))
                async def _confirm_price():
                    exchange = _get_exchange_for_bot(db, bot)
                    try:
                        return await exchange.get_price(bot.symbol)
                    finally:
                        await exchange.close()
                current = _arun(_confirm_price())
                # LONG: precio actual debe seguir por encima del precio de la señal
                # SHORT: precio actual debe seguir por debajo del precio de la señal
                if action == "long" and current < ref_price:
                    msg = f"Señal LONG cancelada: precio actual {current} < precio señal {ref_price} (señal falsa)"
                    logger.warning(f"[ENGINE] {msg}")
                    _log_event(db, bot.id, "signal_cancelled_confirmation", msg)
                    raise _BusinessError(msg)
                elif action == "short" and current > ref_price:
                    msg = f"Señal SHORT cancelada: precio actual {current} > precio señal {ref_price} (señal falsa)"
                    logger.warning(f"[ENGINE] {msg}")
                    _log_event(db, bot.id, "signal_cancelled_confirmation", msg)
                    raise _BusinessError(msg)
                logger.info(f"[ENGINE] Confirmación OK: {action} @ señal={ref_price}, actual={current}")
            except _BusinessError:
                raise
            except Exception as e:
                logger.warning(f"[ENGINE] No se pudo verificar precio de confirmación: {e}, ejecutando igualmente")

        _open_position(db, bot, signal_id, action, effective_price, source=signal_source)
    elif action == "close":
        _close_position(db, bot, signal_id)
    else:
        raise _BusinessError(f"Acción desconocida: {action}")


def _open_position(
    db: Session,
    bot: BotConfig,
    signal_id: uuid.UUID,
    side: str,
    price: float | None,
    source: str = "webhook",
) -> None:
    """
    Abre una posición aplicando el sistema de conflictos v2.
    
    Args:
        source: Fuente de la señal — "webhook" | "indicator" | "manual"
    """
    # Normalizar source a los valores guardados en Position
    position_source = {
        "webhook": "bot_ext",
        "indicator": "bot_int",
        "manual": "app_manual",
    }.get(source, source)
    from app.core.conflict_resolver import get_conflicting_positions, resolve_conflict

    # 0. Cerrar posición contraria del PROPIO bot si existe
    own_opposite = db.query(Position).filter(
        Position.bot_id == bot.id,
        Position.symbol == bot.symbol,
        Position.status == "open",
        Position.side != side,
    ).first()

    if own_opposite:
        logger.info(
            f"[ENGINE] Cerrando posición contraria {own_opposite.side} "
            f"del propio bot {bot.bot_name} para abrir {side}"
        )
        # No pasar signal_id para no marcar la señal nueva como procesada antes de abrir
        _close_position(db, bot, None, position_to_close=own_opposite)
        db.commit()

    # 1. Resolver conflictos con otras posiciones
    conflicting = get_conflicting_positions(db, bot)
    result = resolve_conflict(db, bot, side, source, conflicting)

    if result["action"] == "reject":
        msg = result["reason"]
        logger.warning(f"[ENGINE] {msg}")
        _log_event(db, bot.id, "conflict_rejected", msg)
        # Notificar Telegram
        from app.models.user import User
        user = db.query(User).filter(User.id == bot.user_id).first()
        if user and user.telegram_chat_id:
            notif = _get_notification_tasks()
            notif.trade_rejected.delay(
                bot_name=bot.bot_name,
                symbol=bot.symbol,
                side=side,
                reason=msg,
                chat_id=user.telegram_chat_id,
            )
        raise _BusinessError(msg)
    
    # 2. Cerrar posiciones contrarias si la config lo indica
    for pos_to_close in result.get("close_positions", []):
        logger.info(f"[ENGINE] Cerrando posición {pos_to_close.side} de {pos_to_close.bot_id} para abrir {side}")
        _close_position(db, bot, signal_id, position_to_close=pos_to_close)
        db.commit()
    
    # 3. Verificar si hay posición del MISMO lado en ESTE bot (después de cerrar contrarias)
    same_side_pos = db.query(Position).filter(
        Position.symbol == bot.symbol,
        Position.status == "open",
        Position.bot_id == bot.id,
        Position.side == side,
    ).first()
    
    if same_side_pos:
        msg = f"El bot {bot.bot_name} ya tiene una posición {side} abierta en {bot.symbol}"
        logger.warning(msg)
        raise _BusinessError(msg)

    # Llamadas al exchange — async aisladas en loops efímeros
    async def _do_exchange():
        exchange = _get_exchange_for_bot(db, bot)
        try:
            balance  = await exchange.get_equity()
            logger.info(f"[ENGINE] Balance: equity={balance.total_equity}, available={balance.available_balance}")
            logger.info(f"[ENGINE] Bot config: sizing_type={bot.position_sizing_type}, sizing_value={bot.position_value}, leverage={bot.leverage}")
            
            quantity = await exchange.calculate_quantity(
                symbol=bot.symbol,
                equity=balance.total_equity,
                sizing_type=bot.position_sizing_type,
                sizing_value=bot.position_value,
                leverage=bot.leverage,
            )
            logger.info(f"[ENGINE] Calculated quantity: {quantity}")
            
            if quantity <= Decimal("0"):
                raise ValueError(
                    f"Cantidad calculada es 0 o negativa: {quantity:.3f}. "
                    f"Bot={bot.bot_name}, equity={balance.total_equity} USDT, "
                    f"sizing={bot.position_sizing_type}/{bot.position_value}, leverage={bot.leverage}x. "
                    f"Aumenta el balance, el % de sizing o el apalancamiento."
                )
            
            try:
                await exchange.set_leverage(bot.symbol, bot.leverage, side)
            except Exception as lev_exc:
                logger.warning(
                    f"[ENGINE] {bot.bot_name} set_leverage({bot.leverage}x) failed: {lev_exc}. "
                    f"Continuing with exchange's current leverage."
                )

            # Si se proporcionó un precio, usarlo (orden limit)
            entry_price_arg = Decimal(str(price)) if price else None
            logger.info(f"[ENGINE] Price param received: {price}, entry_price_arg: {entry_price_arg}, order_type: {'limit' if entry_price_arg else 'market'}")
            
            if side == "long":
                order = await exchange.open_long(bot.symbol, quantity, entry_price_arg)
            else:
                order = await exchange.open_short(bot.symbol, quantity, entry_price_arg)

            # Verify real leverage after open (critical for risk calculations)
            try:
                live_positions = await exchange.get_open_positions()
                live_pos = next(
                    (p for p in live_positions if p.symbol == bot.symbol and p.side == side),
                    None,
                )
                if live_pos and live_pos.leverage and live_pos.leverage != bot.leverage:
                    logger.warning(
                        f"[ENGINE] {bot.bot_name} leverage MISMATCH: expected={bot.leverage}x, "
                        f"exchange={live_pos.leverage}x. Risk calculations will use expected value."
                    )
            except Exception as lev_verify_exc:
                logger.debug(f"[ENGINE] Could not verify real leverage after open: {lev_verify_exc}")

            is_limit = entry_price_arg is not None
            if is_limit:
                # Limit order: no position open yet, skip SL placement
                return order, None, None
            else:
                sl_price    = risk_manager.calculate_sl_price(
                    order.fill_price, side, bot.initial_sl_percentage,
                    bot.leverage, bot.use_roi_percentage
                )
                sl_order_id = await exchange.place_stop_loss(bot.symbol, side, order.quantity, sl_price)
                return order, sl_price, sl_order_id
        finally:
            await exchange.close()

    order, sl_price, sl_order_id = _arun(_do_exchange())
    is_limit_order = price is not None
    # For limit orders use the requested limit price; for market use actual fill price
    entry_price = Decimal(str(price)) if is_limit_order else order.fill_price

    # Determinar el nombre del exchange para guardar
    exchange_name = "paper" if bot.is_paper_trading else bot.exchange_account.exchange

    tp_records = []
    for i, tp_cfg in enumerate(bot.take_profits):
        tp_price = risk_manager.calculate_tp_price(
            entry_price, side, Decimal(str(tp_cfg["profit_percent"])),
            bot.leverage, bot.use_roi_percentage
        )
        tp_records.append({
            "level": i + 1,
            "price": float(tp_price),
            "close_percent": tp_cfg["close_percent"],
            "hit": False,
        })

    position_status = "pending_limit" if is_limit_order else "open"
    position = Position(
        bot_id=bot.id,
        exchange=exchange_name,
        symbol=bot.symbol,
        side=side,
        entry_price=entry_price,
        quantity=order.quantity,
        leverage=bot.leverage,
        current_sl_price=sl_price,
        current_tp_prices=tp_records,
        exchange_order_id=order.order_id,
        exchange_sl_order_id=sl_order_id,
        source=position_source,
        status=position_status,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(position)
    _mark_signal_processed(db, signal_id)

    mode_str = "[PAPER] " if bot.is_paper_trading else ""
    event_type = "limit_order_placed" if is_limit_order else "order_opened"
    _log_event(db, bot.id, event_type,
        f"{mode_str}{side.upper()} {bot.symbol} | qty={order.quantity} limit={entry_price}" if is_limit_order
        else f"{mode_str}{side.upper()} {bot.symbol} | qty={order.quantity} entry={entry_price} SL={sl_price}",
        metadata={
            "order_id": order.order_id,
            "entry_price": float(entry_price),
            "sl_price": float(sl_price) if sl_price else None,
            "quantity": float(order.quantity),
            "paper_trading": bot.is_paper_trading,
            "is_limit": is_limit_order,
        }
    )
    db.commit()
    publish_position_update_sync(
        str(bot.user_id),
        {"position_id": str(position.id), "status": position.status, "action": "open", "symbol": bot.symbol, "side": side}
    )
    logger.info(f"{mode_str}{'Orden limit' if is_limit_order else 'Posición abierta'}: {side} {bot.symbol} @ {entry_price}")

    # Notificación Telegram al usuario si está configurada
    from app.models.user import User
    user = db.query(User).filter(User.id == bot.user_id).first()
    if user and user.telegram_chat_id and user.notify_on_open:
        notif = _get_notification_tasks()
        notif.trade_opened.delay(
            bot_name=bot.bot_name,
            symbol=bot.symbol,
            side=side,
            entry=float(entry_price),
            sl=float(sl_price) if sl_price else 0.0,
            chat_id=user.telegram_chat_id,
            is_limit=is_limit_order,
            source=position_source,
            timeframe=bot.timeframe,
        )


def close_position_for_bot(
    db: Session,
    bot: BotConfig,
    signal_id: uuid.UUID | None = None,
    position_to_close: Position | None = None,
) -> Position:
    """
    Cierra la posición abierta de un bot.
    
    Si se pasa position_to_close, cierra esa posición específica.
    Si no, busca la posición abierta del bot.
    
    Puede ser llamado desde engine (procesamiento de señal) o desde
    bot_activator (cuando IA cierra una posición de señal).
    """
    # Si se pasa una posición específica, usarla; si no, buscar la del bot
    position = position_to_close or db.query(Position).filter(
        Position.bot_id == bot.id,
        Position.status == "open",
    ).first()

    if not position:
        raise _BusinessError("No hay posición abierta para cerrar")

    async def _do_close():
        exchange = _get_exchange_for_bot(db, bot)
        try:
            # Cancelar SL
            if position.exchange_sl_order_id:
                try:
                    await exchange.cancel_order(bot.symbol, position.exchange_sl_order_id)
                except Exception as exc:
                    logger.warning(f"[ENGINE] Error cancelando SL al cerrar: {exc}")
            # Cancelar TP orders (OCO soft)
            for tp in position.current_tp_prices or []:
                tp_order_id = tp.get("order_id")
                if tp_order_id:
                    try:
                        await exchange.cancel_order(bot.symbol, str(tp_order_id))
                    except Exception as exc:
                        logger.warning(f"[ENGINE] Error cancelando TP al cerrar: {exc}")
            return await exchange.close_position(bot.symbol, position.side, position.quantity)
        finally:
            await exchange.close()

    order = _arun(_do_close())

    position.status = "closed"
    position.closed_at = datetime.now(timezone.utc)
    position.realized_pnl = (
        (order.fill_price - position.entry_price) * position.quantity
        if position.side == "long"
        else (position.entry_price - order.fill_price) * position.quantity
    )
    
    mode_str = "[PAPER] " if bot.is_paper_trading else ""
    if signal_id:
        _mark_signal_processed(db, signal_id)
    _log_event(db, bot.id, "order_closed",
        f"{mode_str}Cerrado {bot.symbol} @ {order.fill_price} | PnL={position.realized_pnl:.2f} USDT",
        metadata={"close_price": float(order.fill_price)}
    )
    db.commit()
    publish_position_update_sync(
        str(bot.user_id),
        {"position_id": str(position.id), "status": "closed", "action": "close", "symbol": bot.symbol, "side": position.side, "realized_pnl": float(position.realized_pnl)}
    )

    # Notificación Telegram al usuario si está configurada
    from app.models.user import User
    user = db.query(User).filter(User.id == bot.user_id).first()
    if user and user.telegram_chat_id and user.notify_on_close:
        notif = _get_notification_tasks()
        notif.trade_closed.delay(
            bot_name=bot.bot_name,
            symbol=bot.symbol,
            side=position.side,
            pnl=float(position.realized_pnl),
            chat_id=user.telegram_chat_id,
            source=position.source,
            entry_price=float(position.entry_price) if position.entry_price else None,
            exit_price=float(order.fill_price) if order and order.fill_price else None,
            quantity=float(position.quantity) if position.quantity else None,
            leverage=int(position.leverage) if position.leverage else None,
            timeframe=bot.timeframe,
        )

    # Disparar auto-optimización si el bot lo tiene habilitado
    if bot.auto_optimize_enabled:
        try:
            task = _get_auto_optimize_task()
            task.delay(str(bot.id))
            logger.info(f"[ENGINE] Auto-optimize disparado para bot {bot.bot_name} tras cierre de posición")
        except Exception as e:
            logger.warning(f"[ENGINE] No se pudo disparar auto-optimize para {bot.bot_name}: {e}")

    # Disparar recalibración de config AI óptima si el bot tiene modo AI autónomo
    if position.source == "ai_bot" and bot.ai_optimal_config_enabled:
        try:
            from app.tasks.ai_optimal_config_task import refresh_optimal_configs
            refresh_optimal_configs.delay(bot_id=str(bot.id))
            logger.info(
                f"[ENGINE] AI optimal config recalibration triggered for bot {bot.bot_name} "
                f"after closing AI position"
            )
        except Exception as e:
            logger.warning(
                f"[ENGINE] Could not trigger AI config refresh for {bot.bot_name}: {e}"
            )
    
    return position


# Alias privado para compatibilidad con código existente
_close_position = close_position_for_bot


# ─── Helpers DB (síncronos) ───────────────────────────────────

def _notify_error_if_configured(db: Session, bot_id: str, error: str) -> None:
    """Envía notificación de error al usuario del bot si tiene Telegram configurado."""
    try:
        from app.models.user import User
        bot = db.query(BotConfig).filter(BotConfig.id == uuid.UUID(bot_id)).first()
        if bot:
            user = db.query(User).filter(User.id == bot.user_id).first()
            if user and user.telegram_chat_id:
                notif = _get_notification_tasks()
                notif.error_alert.delay(
                    bot_name=bot.bot_name,
                    error=error,
                    chat_id=user.telegram_chat_id,
                )
    except Exception:
        pass


def _get_active_bot(db: Session, bot_id: uuid.UUID) -> BotConfig | None:
    # Manual bots are kept paused (they're position trackers, not scheduled bots)
    # but still need to execute when triggered explicitly.
    from sqlalchemy import or_
    return db.query(BotConfig).filter(
        BotConfig.id == bot_id,
        or_(
            BotConfig.status == "active",
            BotConfig.bot_name.like("[MANUAL]%"),
        ),
    ).first()


def _mark_signal_processed(db: Session, signal_id: uuid.UUID) -> None:
    signal = db.query(SignalLog).filter(SignalLog.id == signal_id).first()
    if signal:
        signal.processed = True
        signal.processed_at = datetime.now(timezone.utc)


def _mark_signal_error(db: Session, signal_id: uuid.UUID, error: str) -> None:
    signal = db.query(SignalLog).filter(SignalLog.id == signal_id).first()
    if signal:
        signal.processed = True
        signal.processed_at = datetime.now(timezone.utc)
        signal.error_message = error[:500]
    db.commit()


def _log_event(
    db: Session,
    bot_id: uuid.UUID,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    db.add(BotLog(bot_id=bot_id, event_type=event_type, message=message, metadata=metadata))
