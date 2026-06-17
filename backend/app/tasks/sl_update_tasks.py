"""
Celery tasks para actualización de Stop Loss y ejecución de Take Profits.

Separadas de order_tasks para poder priorizar colas:
  sl_updates > notifications > default
"""
import asyncio
import copy
import re
import time
import uuid
from decimal import Decimal

from celery import shared_task
from loguru import logger

_BINGX_RATE_LIMIT_CODE = "100410"
_MAX_RATE_LIMIT_WAIT_S = 300


def _bingx_rate_limit_wait(exc_str: str) -> int | None:
    if _BINGX_RATE_LIMIT_CODE not in exc_str:
        return None
    try:
        m = re.search(r'after\s+(\d{13})', exc_str)
        if not m:
            return None
        unblock_ms = int(m.group(1))
        return max(1, (unblock_ms - int(time.time() * 1000)) // 1000 + 2)
    except Exception:
        return None


def _run_async(coro, timeout: float | None = None):
    """
    Ejecuta una corrutina reutilizando el event loop disponible.
    Evita 'Event loop is closed' en workers Celery forkeados.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if timeout is not None:
        coro = asyncio.wait_for(coro, timeout=timeout)
    return loop.run_until_complete(coro)


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=2,
    queue="sl_updates",
    name="app.tasks.sl_update_tasks.update_stop_loss",
)
def update_stop_loss(
    self,
    position_id: str,
    new_sl_price: float,
) -> dict:
    """
    Modifica el Stop Loss de una posición abierta en el exchange.

    Flujo:
      1. Cargar posición + bot + exchange_account de DB (sync)
      2. Llamar al exchange para cancelar SL viejo y colocar nuevo (async)
      3. Actualizar DB y logar evento
    """
    from app.services.cache import sync_redis
    dedup_key = f"sl_update:inflight:{position_id}"
    try:
        _run_async(_execute_sl_update(uuid.UUID(position_id), Decimal(str(new_sl_price))), timeout=60)
        return {"status": "ok", "position_id": position_id, "new_sl": new_sl_price}

    except Exception as exc:
        exc_str = str(exc)
        logger.error(f"Error actualizando SL posición {position_id}: {exc_str[:200]}")
        wait_s = _bingx_rate_limit_wait(exc_str)
        if wait_s is not None and wait_s <= _MAX_RATE_LIMIT_WAIT_S and self.request.retries < self.max_retries:
            logger.warning(f"[SL] BingX rate-limit — reintentando en {wait_s}s")
            raise self.retry(exc=exc, countdown=wait_s)
        retry_in = 2 ** (self.request.retries + 1)   # 2, 4, 8, 16, 32 s
        raise self.retry(exc=exc, countdown=retry_in)
    finally:
        # Liberar el candado de dedup para que el worker pueda encolar el siguiente movimiento legítimo
        sync_redis.delete(dedup_key)


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=5,
    queue="orders",
    name="app.tasks.sl_update_tasks.execute_take_profit",
)
def execute_take_profit(
    self,
    position_id: str,
    tp_level: int | str,
    tp_price: float,
    close_percent: float,
) -> dict:
    """
    Cierra un % de la posición cuando se alcanza un TP.
    Marca el TP como hit en la DB para no ejecutarlo dos veces.
    """
    from app.services.cache import sync_redis
    dedup_key = f"tp_execute:inflight:{position_id}:{tp_level}"
    sapp_dedup_key = f"sapp_tp_execute:inflight:{position_id}:{tp_level}"
    try:
        _run_async(_execute_tp(
            uuid.UUID(position_id),
            tp_level,
            Decimal(str(tp_price)),
            Decimal(str(close_percent)),
        ), timeout=120)
        return {"status": "ok", "position_id": position_id, "tp_level": tp_level}
    except Exception as exc:
        exc_str = str(exc)
        logger.error(f"Error ejecutando TP{tp_level} posición {position_id}: {exc_str[:200]}")

        # 101205: BingX dice que no hay posición — ya fue cerrada externamente, no reintentar
        if "101205" in exc_str or "No position to close" in exc_str:
            logger.warning(f"[TP] Posición {position_id} ya no existe en exchange — ignorando TP{tp_level}")
            return {"status": "skipped", "reason": "position_not_on_exchange"}
        
        # InvalidOrder: cantidad menor que precisión mínima — reintentar no ayuda
        if "must be greater than minimum amount precision" in exc_str or "InvalidOrder" in exc_str:
            logger.warning(f"[TP] Posición {position_id}: cantidad inválida para exchange — ignorando TP{tp_level}")
            return {"status": "skipped", "reason": "invalid_amount_precision"}

        wait_s = _bingx_rate_limit_wait(exc_str)
        if wait_s is not None and wait_s <= _MAX_RATE_LIMIT_WAIT_S and self.request.retries < self.max_retries:
            logger.warning(f"[TP] BingX rate-limit — reintentando en {wait_s}s")
            raise self.retry(exc=exc, countdown=wait_s)
        raise self.retry(exc=exc, countdown=5 ** (self.request.retries + 1))


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="orders",
    name="app.tasks.sl_update_tasks.execute_stop_loss",
)
def execute_stop_loss(
    self,
    position_id: str,
    sl_price: float,
    reason: str = "sl_hit",
) -> dict:
    """
    Cierra una posición al 100% cuando se toca el Stop Loss.
    Para paper trading el exchange no ejecuta la orden, así que lo hacemos aquí.
    """
    try:
        _run_async(_execute_sl_hit(uuid.UUID(position_id), Decimal(str(sl_price)), reason), timeout=60)
        return {"status": "ok", "position_id": position_id}
    except Exception as exc:
        exc_str = str(exc)
        logger.error(f"Error ejecutando SL posición {position_id}: {exc_str[:200]}")

        if "101205" in exc_str or "No position to close" in exc_str or "already closed" in exc_str.lower():
            logger.warning(f"[SL] Posición {position_id} ya no existe en exchange — ignorando")
            return {"status": "skipped", "reason": "position_not_on_exchange"}

        wait_s = _bingx_rate_limit_wait(exc_str)
        if wait_s is not None and wait_s <= _MAX_RATE_LIMIT_WAIT_S and self.request.retries < self.max_retries:
            logger.warning(f"[SL] BingX rate-limit — reintentando en {wait_s}s")
            raise self.retry(exc=exc, countdown=wait_s)
        raise self.retry(exc=exc, countdown=5 ** (self.request.retries + 1))
    finally:
        from app.services.cache import sync_redis
        sync_redis.delete(f"sl_hit:inflight:{position_id}")


async def _execute_sl_hit(
    position_id: uuid.UUID,
    sl_price: Decimal,
    reason: str,
) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.services.cache import publish_position_update_sync
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.id == position_id, Position.status == "open")
        )
        row = result.one_or_none()
        if not row:
            logger.warning(f"Posición {position_id} no encontrada o ya cerrada")
            return

        position, bot = row

        # Crear exchange apropiado (paper o real)
        if bot.is_paper_trading:
            paper_balance = await db.execute(
                select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
            )
            paper_balance = paper_balance.scalar_one()
            exchange = create_paper_exchange(paper_balance, bot_id=str(bot.id))
        else:
            acc_result = await db.execute(
                select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
            )
            account = acc_result.scalar_one()
            exchange = create_exchange(account)

        order = None
        fill_price = None
        position_already_closed = False
        try:
            order = await exchange.close_position(
                position.symbol, position.side, position.quantity
            )
            fill_price = order.fill_price
        except Exception as exc:
            msg = str(exc)
            if "already closed" in msg.lower() or "no position" in msg.lower():
                logger.warning(
                    f"[SL] Posición {position.symbol} ya cerrada en exchange, saltando"
                )
                position_already_closed = True
            else:
                raise
        finally:
            await exchange.close()

        if not position_already_closed:
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.realized_pnl = (
                (fill_price - position.entry_price) * position.quantity
                if position.side == "long"
                else (position.entry_price - fill_price) * position.quantity
            )
            pnl = position.realized_pnl
        else:
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.quantity = Decimal("0")
            pnl = Decimal("0")

        db.add(BotLog(
            bot_id=bot.id,
            event_type="sl_hit",
            message=(
                f"SL alcanzado: cerrada posición {position.symbol} {position.side} "
                f"@ {fill_price if fill_price else sl_price} | PnL={pnl:.2f} USDT"
            ),
            metadata={
                "sl_price": float(sl_price),
                "fill_price": float(fill_price) if fill_price else None,
                "pnl": float(pnl),
                "reason": reason,
                "already_closed": position_already_closed,
            },
        ))

        await db.commit()
        publish_position_update_sync(
            str(bot.user_id),
            {
                "position_id": str(position_id),
                "status": "closed",
                "action": "sl_hit",
                "symbol": position.symbol,
                "pnl": float(pnl),
            }
        )

        if not position_already_closed:
            from app.models.user import User
            from app.tasks.notification_tasks import trade_closed
            user_result = await db.execute(select(User).where(User.id == bot.user_id))
            user = user_result.scalar_one_or_none()
            if user and user.telegram_chat_id and user.notify_on_close:
                trade_closed.delay(
                    bot_name=bot.bot_name,
                    symbol=position.symbol,
                    side=position.side,
                    pnl=float(position.realized_pnl),
                    chat_id=user.telegram_chat_id,
                    source="ai_bot" if position.source == "ai_bot" else "bot",
                    entry_price=float(position.entry_price) if position.entry_price else None,
                    exit_price=float(fill_price) if fill_price else None,
                    quantity=float(position.quantity) if position.quantity else None,
                    leverage=int(position.leverage) if position.leverage else None,
                    timeframe=bot.timeframe,
                )

        logger.info(
            f"SL ejecutado: {position.symbol} {position.side} "
            f"@ {fill_price if fill_price else sl_price} pnl={pnl:.2f}"
        )


async def _execute_tp(
    position_id: uuid.UUID,
    tp_level: int | str,
    tp_price: Decimal,
    close_percent: Decimal,
) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.services.cache import publish_position_update_sync
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal

    # Normalize TP level — supports legacy int (1,2) and SAPP str ("SAPP1")
    if isinstance(tp_level, str) and tp_level.startswith("SAPP"):
        _tp_level_num = int(tp_level.replace("SAPP", ""))
        _is_sapp = True
    else:
        _tp_level_num = int(tp_level)
        _is_sapp = False

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.id == position_id, Position.status == "open")
        )
        row = result.one_or_none()
        if not row:
            logger.warning(f"Posición {position_id} no encontrada o ya cerrada")
            return

        position, bot = row
        extra = dict(position.extra_config or {})

        # ── Find TP entry ──
        # Check legacy current_tp_prices first
        tps = copy.deepcopy(list(position.current_tp_prices or []))
        tp_entry = next((t for t in tps if t.get("level") == _tp_level_num), None)

        # If not found, check SAPP plan inside extra_config
        sapp_tp_prices = extra.get("sapp_tp_prices", [])
        sapp_entry = None
        if not tp_entry and sapp_tp_prices:
            sapp_entry = next((t for t in sapp_tp_prices if t.get("level") == _tp_level_num), None)

        # Guard: already hit
        if (tp_entry and tp_entry.get("hit")) or (sapp_entry and sapp_entry.get("hit")):
            logger.info(f"TP{tp_level} ya ejecutado para posición {position_id}, ignorando")
            return

        # Calcular cantidad a cerrar
        original_qty = Decimal(str(
            extra.get("original_quantity", float(position.quantity))
        ))
        close_qty = (original_qty * close_percent / Decimal("100")).quantize(Decimal("0.001"))
        close_qty = min(close_qty, position.quantity)

        # Crear exchange apropiado (paper o real)
        if bot.is_paper_trading:
            paper_balance = await db.execute(
                select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
            )
            paper_balance = paper_balance.scalar_one()
            exchange = create_paper_exchange(paper_balance, bot_id=str(bot.id))
        else:
            acc_result = await db.execute(
                select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
            )
            account = acc_result.scalar_one()
            exchange = create_exchange(account)

        order = None
        fill_price = None
        position_already_closed = False
        exchange_close_ok = False
        try:
            try:
                order = await exchange.close_position(position.symbol, position.side, close_qty)
                fill_price = order.fill_price
                exchange_close_ok = True
            except Exception as exc:
                msg = str(exc)
                if "already closed" in msg.lower() or "no position" in msg.lower():
                    logger.warning(
                        f"[TP] Posición {position.symbol} ya cerrada en exchange "
                        f"(probablemente por TP order previo). Saltando cierre manual."
                    )
                    position_already_closed = True
                    exchange_close_ok = True  # Exchange state is closed — safe to mark hit
                else:
                    raise

            # Validar fill_price antes de calcular PnL
            if not position_already_closed and (not fill_price or fill_price <= 0):
                logger.warning(
                    f"[TP] fill_price inválido ({fill_price}) para {position.symbol}, "
                    f"usando entry_price como fallback"
                )
                fill_price = position.entry_price

            # ── ONLY mark hit AFTER successful exchange close ──
            if exchange_close_ok:
                if tp_entry:
                    tp_entry["hit"] = True
                    position.current_tp_prices = tps
                if sapp_entry:
                    sapp_entry["hit"] = True
                    extra["sapp_tp_prices"] = sapp_tp_prices
                    position.extra_config = extra

            if not position_already_closed:
                position.quantity -= close_qty

                all_tps_hit = all(t.get("hit") for t in tps)
                # Also consider SAPP TPs if they exist
                if sapp_tp_prices:
                    all_sapp_hit = all(t.get("hit") for t in sapp_tp_prices)
                    all_tps_hit = all_tps_hit and all_sapp_hit

                partial_pnl = (
                    (fill_price - position.entry_price) * close_qty
                    if position.side == "long"
                    else (position.entry_price - fill_price) * close_qty
                )
                if close_percent >= Decimal("100") or position.quantity <= Decimal("0") or all_tps_hit:
                    position.status = "closed"
                    position.closed_at = datetime.now(timezone.utc)
                position.realized_pnl = (position.realized_pnl or Decimal("0")) + partial_pnl

                pnl = partial_pnl
            else:
                position.status = "closed"
                position.closed_at = datetime.now(timezone.utc)
                position.quantity = Decimal("0")
                pnl = Decimal("0")

            # Commit core state BEFORE post-TP1 exchange ops (cancel TP2 / place BE SL)
            # If those fail, at least the DB records the hit and remaining qty correctly.
            await db.commit()

            # ── Post-TP1 handling ───────────────────────────
            is_3stage = extra.get("tp_strategy") == "3stage_40_30_30"
            if not position_already_closed and _tp_level_num == 1 and close_percent < Decimal("100") and position.quantity > Decimal("0"):
                if not is_3stage:
                    tp2_entry = next((t for t in tps if t.get("level") == 2), None)
                    if tp2_entry:
                        tp2_order_id = tp2_entry.get("order_id")
                        if tp2_order_id:
                            try:
                                await exchange.cancel_order(position.symbol, str(tp2_order_id))
                                logger.info(f"[TP] TP2 cancelado tras TP1 — {position.symbol}")
                            except Exception as exc:
                                logger.warning(f"[TP] Error cancelando TP2 tras TP1: {exc}")

                if position.exchange_sl_order_id:
                    try:
                        await exchange.cancel_order(
                            position.symbol, position.exchange_sl_order_id
                        )
                        logger.info(f"[TP] SL cancelado tras TP1 — {position.symbol}")
                    except Exception as exc:
                        logger.warning(f"[TP] Error cancelando SL tras TP1: {exc}")

                # Read BE lock_profit from signal-adjusted config, bot config, or fallback
                be_cfg = extra.get("adjusted_breakeven_config") or (bot.breakeven_config or {})
                lock_profit = Decimal(str(be_cfg.get("lock_profit", 0.1)))

                from app.core.risk_manager import calculate_breakeven_price
                be_sl = calculate_breakeven_price(
                    entry_price=position.entry_price,
                    side=position.side,
                    lock_profit=lock_profit,
                    leverage=bot.leverage,
                    use_roi=bot.use_roi_percentage,
                )
                try:
                    new_sl_order_id = await exchange.place_stop_loss(
                        symbol=position.symbol,
                        side=position.side,
                        quantity=position.quantity,
                        sl_price=be_sl,
                    )
                    position.current_sl_price = be_sl
                    position.exchange_sl_order_id = new_sl_order_id
                    logger.info(
                        f"[TP] Nuevo SL en BE tras TP1 — {position.symbol} "
                        f"SL={be_sl} qty={position.quantity}"
                    )
                except Exception as exc:
                    logger.error(
                        f"[TP] Error colocando nuevo SL tras TP1: {exc}"
                    )

                extra["trailing_activated_after_tp1"] = True
                position.extra_config = extra

                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="trailing_activated",
                    message=(
                        f"Trailing activado tras TP1: {position.symbol} "
                        f"remanente={position.quantity} SL→BE@{be_sl}"
                    ),
                    metadata={
                        "tp_level": _tp_level_num,
                        "remaining_qty": float(position.quantity),
                        "new_sl": float(be_sl),
                        "action": "trailing_free",
                    },
                ))

            if position_already_closed:
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="tp_hit",
                    message=(
                        f"TP{tp_level} detectado pero posición ya cerrada en exchange: "
                        f"{position.symbol} — posiblemente por TP/SL order previo"
                    ),
                    metadata={
                        "tp_level":      tp_level,
                        "tp_price":      float(tp_price),
                        "close_percent": float(close_percent),
                        "close_qty":     float(close_qty),
                        "already_closed": True,
                    },
                ))
            else:
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="tp_hit",
                    message=(
                        f"TP{tp_level} alcanzado: cerrado {close_percent}% "
                        f"a {fill_price} | PnL parcial={pnl:.2f} USDT"
                    ),
                    metadata={
                        "tp_level":      tp_level,
                        "tp_price":      float(tp_price),
                        "fill_price":    float(fill_price),
                        "close_percent": float(close_percent),
                        "close_qty":     float(close_qty),
                        "partial_pnl":   float(pnl),
                    },
                ))

            await db.commit()
            publish_position_update_sync(
                str(bot.user_id),
                {"position_id": str(position_id), "status": position.status, "action": "tp_hit", "tp_level": tp_level, "symbol": position.symbol}
            )
            if position_already_closed:
                logger.info(
                    f"TP{tp_level} posición ya cerrada: {position.symbol} {position.side} "
                    f"(detectado por trailing worker, exchange la cerró antes)"
                )
            else:
                logger.info(
                    f"TP{tp_level} ejecutado: {position.symbol} {position.side} "
                    f"cierre={close_percent}% qty={close_qty} @ {fill_price} pnl={pnl:.2f}"
                )

            if not position_already_closed:
                from app.models.user import User
                from app.tasks.notification_tasks import trade_partial, trade_closed
                user_result = await db.execute(select(User).where(User.id == bot.user_id))
                user = user_result.scalar_one_or_none()
                if user and user.telegram_chat_id:
                    if position.status == "closed" and user.notify_on_close:
                        trade_closed.delay(
                            bot_name=bot.bot_name,
                            symbol=position.symbol,
                            side=position.side,
                            pnl=float(position.realized_pnl),
                            chat_id=user.telegram_chat_id,
                            source="ai_bot" if position.source == "ai_bot" else "bot",
                            entry_price=float(position.entry_price) if position.entry_price else None,
                            exit_price=float(fill_price) if fill_price else None,
                            quantity=float(original_qty) if original_qty else None,
                            leverage=int(position.leverage) if position.leverage else None,
                            timeframe=bot.timeframe,
                        )
                    elif position.status == "open" and user.notify_on_partial:
                        trade_partial.delay(
                            bot_name=bot.bot_name,
                            symbol=position.symbol,
                            side=position.side,
                            tp_level=tp_level,
                            close_percent=float(close_percent),
                            fill_price=float(fill_price),
                            partial_pnl=float(pnl),
                            chat_id=user.telegram_chat_id,
                        )
        finally:
            await exchange.close()


async def _execute_sl_update(position_id: uuid.UUID, new_sl_price: Decimal) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.services.cache import publish_position_update_sync
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        # Cargar posición con bot y cuenta
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.id == position_id, Position.status == "open")
        )
        row = result.one_or_none()
        if not row:
            logger.warning(f"Posición {position_id} no encontrada o ya cerrada")
            return

        position, bot = row

        # Guardia de obsolescencia: si el SL en DB ya está cerca del valor solicitado,
        # otra tarea se adelantó — no tiene sentido llamar al exchange ni notificar.
        current_sl = position.current_sl_price or Decimal("0")
        if current_sl > 0 and abs(new_sl_price - current_sl) / current_sl < Decimal("0.002"):
            logger.debug(
                f"[SL] Salto mínimo no alcanzado para {position_id} "
                f"({current_sl:.4f} → {new_sl_price:.4f}), ignorando"
            )
            return

        # Crear exchange apropiado (paper o real)
        if bot.is_paper_trading:
            paper_balance = await db.execute(
                select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
            )
            paper_balance = paper_balance.scalar_one()
            exchange = create_paper_exchange(paper_balance, bot_id=str(bot.id))
        else:
            acc_result = await db.execute(
                select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
            )
            account = acc_result.scalar_one()
            exchange = create_exchange(account)
        try:
            new_order_id = await exchange.modify_stop_loss(
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                old_order_id=position.exchange_sl_order_id or "",
                new_sl_price=new_sl_price,
            )
        finally:
            await exchange.close()

        # Actualizar posición
        old_sl = position.current_sl_price
        position.current_sl_price = new_sl_price
        position.exchange_sl_order_id = new_order_id

        # Log
        db.add(BotLog(
            bot_id=bot.id,
            event_type="sl_moved",
            message=(
                f"SL actualizado: {old_sl:.4f} → {new_sl_price:.4f} "
                f"({position.side} {position.symbol})"
            ),
            metadata={
                "old_sl":    float(old_sl) if old_sl else None,
                "new_sl":    float(new_sl_price),
                "order_id":  new_order_id,
            },
        ))

        await db.commit()
        publish_position_update_sync(
            str(bot.user_id),
            {"position_id": str(position_id), "status": position.status, "action": "sl_update", "current_sl_price": float(position.current_sl_price), "symbol": position.symbol}
        )

        # Notificación Telegram — solo si el SL realmente cambió de valor
        old_sl_val = float(old_sl) if old_sl else 0.0
        new_sl_val = float(new_sl_price)
        sl_actually_changed = abs(new_sl_val - old_sl_val) > old_sl_val * 0.0001 if old_sl_val else True
        if sl_actually_changed:
            from app.models.user import User
            from app.tasks.notification_tasks import sl_moved
            user_result = await db.execute(select(User).where(User.id == bot.user_id))
            user = user_result.scalar_one_or_none()
            if user and user.telegram_chat_id and user.notify_on_close:
                sl_moved.delay(
                    bot_name=bot.bot_name,
                    symbol=position.symbol,
                    side=position.side,
                    old_sl=old_sl_val,
                    new_sl=new_sl_val,
                    chat_id=user.telegram_chat_id,
                )

        logger.info(
            f"SL actualizado: {position.symbol} {old_sl} → {new_sl_price}"
        )


# ── Breakeven monitor: activates BE by R-multiple (not only after TP1) ───────

async def _check_and_activate_breakeven() -> dict:
    """
    Revisa todas las posiciones abiertas y activa breakeven cuando
    el precio alcanza el R-multiple configurado.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.bot_config import BotConfig
    from app.models.bot_log import BotLog
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.services.cache import get_price, publish_position_update_sync
    from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
    from app.core.risk_manager import calculate_breakeven_price

    activated = 0
    skipped = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.status == "open")
        )
        rows = result.all()

        for position, bot in rows:
            extra = dict(position.extra_config or {})

            # Skip if BE already activated
            if extra.get("breakeven_activated"):
                skipped += 1
                continue

            # Skip legacy positions that rely on after-TP1 BE
            if extra.get("breakeven_after_tp1") is True:
                skipped += 1
                continue

            # Get BE config: signal-adjusted > bot config > fallback
            be_cfg = extra.get("adjusted_breakeven_config") or (bot.breakeven_config or {})
            activation_r = float(be_cfg.get("activation_r", 1.0))
            lock_profit = Decimal(str(be_cfg.get("lock_profit", 0.1)))

            if activation_r >= 900:  # Disabled (legacy 999R)
                skipped += 1
                continue

            # Get current price
            current_price = await get_price(position.symbol)
            if current_price is None:
                # Fallback: fetch from exchange
                try:
                    if bot.is_paper_trading:
                        paper_balance = await db.execute(
                            select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
                        )
                        paper_balance = paper_balance.scalar_one()
                        exchange = create_paper_exchange(paper_balance)
                    else:
                        acc_result = await db.execute(
                            select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
                        )
                        account = acc_result.scalar_one()
                        exchange = create_exchange(account)

                    ticker = await exchange.fetch_ticker(position.symbol)
                    current_price = float(ticker["last"]) if ticker else None
                    await exchange.close()
                except Exception:
                    current_price = None

            if current_price is None:
                errors += 1
                continue

            # Calculate current R-multiple
            entry_f = float(position.entry_price)
            sl_f = float(position.current_sl_price) if position.current_sl_price else entry_f
            if entry_f <= 0 or sl_f <= 0:
                continue

            sl_distance = abs(entry_f - sl_f)
            if sl_distance <= 0:
                continue

            price_move = current_price - entry_f if position.side == "long" else entry_f - current_price
            current_r = price_move / sl_distance if sl_distance > 0 else 0.0

            if current_r < activation_r:
                continue

            # BE activation triggered — calculate BE price
            try:
                be_sl = calculate_breakeven_price(
                    entry_price=position.entry_price,
                    side=position.side,
                    lock_profit=lock_profit,
                    leverage=bot.leverage,
                    use_roi=bot.use_roi_percentage,
                )
            except Exception:
                errors += 1
                continue

            # Validate BE price is better than current SL
            if position.side == "long" and float(be_sl) <= sl_f:
                logger.debug(
                    f"[BE_MONITOR] {position.symbol}: BE {be_sl} <= current SL {sl_f}, skipping"
                )
                skipped += 1
                continue
            if position.side == "short" and float(be_sl) >= sl_f:
                logger.debug(
                    f"[BE_MONITOR] {position.symbol}: BE {be_sl} >= current SL {sl_f}, skipping"
                )
                skipped += 1
                continue

            # Place new SL at BE
            try:
                if bot.is_paper_trading:
                    paper_balance = await db.execute(
                        select(PaperBalance).where(PaperBalance.id == bot.paper_balance_id)
                    )
                    paper_balance = paper_balance.scalar_one()
                    exchange = create_paper_exchange(paper_balance)
                else:
                    acc_result = await db.execute(
                        select(ExchangeAccount).where(ExchangeAccount.id == bot.exchange_account_id)
                    )
                    account = acc_result.scalar_one()
                    exchange = create_exchange(account)

                # Cancel old SL
                if position.exchange_sl_order_id:
                    try:
                        await exchange.cancel_order(position.symbol, position.exchange_sl_order_id)
                    except Exception as exc:
                        logger.warning(f"[BE_MONITOR] Error cancelando SL viejo: {exc}")

                # Place new SL
                new_sl_order_id = await exchange.place_stop_loss(
                    symbol=position.symbol,
                    side=position.side,
                    quantity=position.quantity,
                    sl_price=be_sl,
                )
                await exchange.close()

                # Update position
                position.current_sl_price = be_sl
                position.exchange_sl_order_id = new_sl_order_id
                extra["breakeven_activated"] = True
                extra["breakeven_r_at_activation"] = round(current_r, 2)
                position.extra_config = extra

                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="breakeven_activated",
                    message=(
                        f"BE activado por R-multiple: {position.symbol} "
                        f"@{current_price:.4f} (R={current_r:.2f} >= {activation_r}) "
                        f"SL→{be_sl}"
                    ),
                    metadata={
                        "symbol": position.symbol,
                        "current_price": current_price,
                        "current_r": round(current_r, 2),
                        "activation_r": activation_r,
                        "be_sl": float(be_sl),
                        "lock_profit": float(lock_profit),
                    },
                ))
                await db.commit()
                publish_position_update_sync(
                    str(bot.user_id),
                    {
                        "position_id": str(position.id),
                        "status": "open",
                        "action": "breakeven_activated",
                        "symbol": position.symbol,
                        "current_sl_price": float(be_sl),
                        "current_r": round(current_r, 2),
                    }
                )
                activated += 1
                logger.info(
                    f"[BE_MONITOR] BE activado: {position.symbol} R={current_r:.2f} "
                    f"SL→{be_sl} (lock={lock_profit}%)"
                )

            except Exception as exc:
                errors += 1
                logger.error(f"[BE_MONITOR] Error activando BE para {position.symbol}: {exc}")
                try:
                    await exchange.close()
                except Exception:
                    pass

    return {"activated": activated, "skipped": skipped, "errors": errors}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    queue="sl_updates",
    name="app.tasks.sl_update_tasks.monitor_breakeven_activation",
)
def monitor_breakeven_activation(self) -> dict:
    """
    Celery task periódico: revisa posiciones abiertas y activa breakeven
    cuando el precio alcanza el R-multiple configurado.
    """
    try:
        result = _run_async(_check_and_activate_breakeven(), timeout=120)
        return result
    except Exception as exc:
        logger.error(f"[BE_MONITOR_TASK] Error: {exc}")
        raise self.retry(exc=exc, countdown=30)
