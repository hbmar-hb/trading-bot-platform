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
from app.services.database import SessionLocal
from loguru import logger


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
        return create_paper_exchange(paper_balance)
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
        except Exception as exc:
            # Error de exchange u otro inesperado: propagar para que Celery reintente
            logger.exception(f"Error de exchange en señal {signal_id}: {exc}")
            _mark_signal_error(db, uuid.UUID(signal_id), str(exc))
            raise  # Celery reintentará


def _arun(coro):
    """
    Ejecuta una corrutina en un loop nuevo y la cierra inmediatamente.
    No reutiliza ninguna conexión del proceso padre — seguro con fork.
    """
    return asyncio.run(coro)


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

        _open_position(db, bot, signal_id, action, effective_price)
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
) -> None:
    # Determinar el exchange para verificar conflictos
    account_id_for_conflict = bot.exchange_account_id or f"paper_{bot.paper_balance_id}"
    
    # Verificar conflictos con otros bots (síncrono con psycopg2)
    conflict = db.query(BotConfig).filter(
        BotConfig.symbol == bot.symbol,
        BotConfig.exchange_account_id == bot.exchange_account_id,
        BotConfig.status == "active",
        BotConfig.id != bot.id,
    ).first()
    if conflict:
        msg = f"Conflicto: bot '{conflict.bot_name}' ya opera {bot.symbol} en esta cuenta"
        logger.warning(msg)
        _log_event(db, bot.id, "conflict_rejected", msg)
        raise _BusinessError(msg)

    # Verificar si hay posición abierta del LADO OPUESTO
    opposite_side = "short" if side == "long" else "long"
    opposite_pos = db.query(Position).filter(
        Position.symbol == bot.symbol,
        Position.status == "open",
        Position.bot_id == bot.id,
        Position.side == opposite_side,
    ).first()
    
    if opposite_pos:
        # Calcular PnL no realizado para decidir si hacer flip
        if price:
            current_price = Decimal(str(price))
        else:
            async def _get_price():
                exchange = _get_exchange_for_bot(db, bot)
                try:
                    return await exchange.get_price(bot.symbol)
                finally:
                    await exchange.close()
            current_price = _arun(_get_price())
        entry = opposite_pos.entry_price
        qty = opposite_pos.quantity
        
        if opposite_pos.side == "long":
            unrealized_pnl = (current_price - entry) * qty
        else:
            unrealized_pnl = (entry - current_price) * qty
        
        logger.info(f"[ENGINE] Posición {opposite_side} abierta con PnL: {unrealized_pnl:.2f} USDT")
        
        # Solo hacer flip si está en PÉRDIDA (PnL negativo)
        if unrealized_pnl < 0:
            logger.info(f"[ENGINE] PnL negativo, cerrando {opposite_side} y abriendo {side}")
            _close_position(db, bot, signal_id, position_to_close=opposite_pos)
            db.commit()
        else:
            # Posición en profit, ignorar señal opuesta (dejar correr)
            msg = f"Posición {opposite_side} en profit ({unrealized_pnl:.2f} USDT), ignorando señal de {side}"
            logger.warning(f"[ENGINE] {msg}")
            _log_event(db, bot.id, "signal_ignored_profit", msg)
            raise _BusinessError(msg)
    
    # Verificar si hay posición del MISMO lado abierta (después de cerrar la opuesta)
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
            
            # Validar cantidad mínima
            if quantity <= Decimal("0"):
                raise ValueError(f"Cantidad calculada es 0 o negativa: {quantity}. Verifica el sizing y el balance.")
            
            await exchange.set_leverage(bot.symbol, bot.leverage, side)

            # Si se proporcionó un precio, usarlo (orden limit)
            entry_price_arg = Decimal(str(price)) if price else None
            logger.info(f"[ENGINE] Price param received: {price}, entry_price_arg: {entry_price_arg}, order_type: {'limit' if entry_price_arg else 'market'}")
            
            if side == "long":
                order = await exchange.open_long(bot.symbol, quantity, entry_price_arg)
            else:
                order = await exchange.open_short(bot.symbol, quantity, entry_price_arg)

            is_limit = entry_price_arg is not None
            if is_limit:
                # Limit order: no position open yet, skip SL placement
                return order, None, None
            else:
                sl_price    = risk_manager.calculate_sl_price(order.fill_price, side, bot.initial_sl_percentage)
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
            entry_price, side, Decimal(str(tp_cfg["profit_percent"]))
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
    logger.info(f"{mode_str}{'Orden limit' if is_limit_order else 'Posición abierta'}: {side} {bot.symbol} @ {entry_price}")


def _close_position(
    db: Session,
    bot: BotConfig,
    signal_id: uuid.UUID,
    position_to_close: Position | None = None,
) -> None:
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
            if position.exchange_sl_order_id:
                await exchange.cancel_order(bot.symbol, position.exchange_sl_order_id)
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
    _mark_signal_processed(db, signal_id)
    _log_event(db, bot.id, "order_closed",
        f"Cerrado {bot.symbol} @ {order.fill_price} | PnL={position.realized_pnl:.2f} USDT",
        metadata={"close_price": float(order.fill_price)}
    )
    db.commit()


# ─── Helpers DB (síncronos) ───────────────────────────────────

def _get_active_bot(db: Session, bot_id: uuid.UUID) -> BotConfig | None:
    return db.query(BotConfig).filter(
        BotConfig.id == bot_id,
        BotConfig.status == "active",
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
