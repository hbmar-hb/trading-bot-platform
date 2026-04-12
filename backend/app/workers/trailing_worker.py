"""
Trailing Stop / Breakeven / Take Profit worker.

Arquitectura reactiva:
  1. Suscribe al canal Redis "price_updates"
  2. Por cada precio nuevo, evalúa TODAS las posiciones abiertas con ese símbolo
  3. Si algún stop/TP necesita ejecutarse, encola un Celery task

Esto mantiene el worker ligero y sin llamadas al exchange — el Celery task
gestiona la llamada real y los reintentos.
"""
import asyncio
import json
from decimal import Decimal

from loguru import logger
from sqlalchemy import select

from app.core.risk_manager import (
    calculate_breakeven_price,
    calculate_dynamic_sl_price,
    calculate_trailing_sl,
    get_dynamic_sl_step,
    should_move_trailing_sl,
)
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.services.database import AsyncSessionLocal

# Umbral mínimo de mejora del SL para evitar spam al exchange (0.1% del precio)
MIN_IMPROVEMENT_PCT = Decimal("0.001")


class TrailingWorker:

    async def run(self) -> None:
        import redis.asyncio as aioredis
        from config.settings import settings

        logger.info("TrailingWorker arrancado — escuchando price_updates")
        r = aioredis.from_url(settings.redis_url, decode_responses=True)

        try:
            async with r.pubsub() as pubsub:
                await pubsub.subscribe("price_updates")
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        symbol = data.get("symbol")
                        price  = Decimal(str(data.get("price", 0)))
                        if symbol and price > 0:
                            await self._evaluate(symbol, price)
                    except Exception as exc:
                        logger.debug(f"TrailingWorker error procesando mensaje: {exc}")
        except asyncio.CancelledError:
            logger.info("TrailingWorker detenido")
        finally:
            await r.aclose()

    async def _evaluate(self, symbol: str, current_price: Decimal) -> None:
        """Evalúa todas las posiciones abiertas con este símbolo."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Position, BotConfig)
                .join(BotConfig, Position.bot_id == BotConfig.id)
                .where(
                    Position.symbol == symbol,
                    Position.status == "open",
                )
            )
            rows = result.all()

        for position, bot in rows:
            try:
                await self._evaluate_position(position, bot, current_price)
            except Exception as exc:
                logger.debug(
                    f"Error evaluando posición {position.id} con precio {current_price}: {exc}"
                )

    async def _evaluate_position(
        self,
        position: Position,
        bot: BotConfig,
        current_price: Decimal,
    ) -> None:
        entry      = position.entry_price
        current_sl = position.current_sl_price or Decimal("0")
        side       = position.side
        symbol     = position.symbol

        # Calcular profit actual (%)
        if side == "long":
            profit_pct = (current_price - entry) / entry * Decimal("100")
        else:
            profit_pct = (entry - current_price) / entry * Decimal("100")

        # ── 1. Take Profits ───────────────────────────────────
        tps = position.current_tp_prices or []
        for tp in tps:
            if tp.get("hit"):
                continue
            tp_price    = Decimal(str(tp["price"]))
            close_pct   = tp["close_percent"]   # % de la posición a cerrar
            tp_level    = tp.get("level", "?")

            tp_reached = (
                (side == "long"  and current_price >= tp_price) or
                (side == "short" and current_price <= tp_price)
            )
            if tp_reached:
                from app.tasks.sl_update_tasks import execute_take_profit
                execute_take_profit.delay(
                    position_id=str(position.id),
                    tp_level=tp_level,
                    tp_price=float(tp_price),
                    close_percent=float(close_pct),
                )
                logger.info(
                    f"TP{tp_level} alcanzado: {side} {symbol} "
                    f"precio={current_price} tp={tp_price} cierre={close_pct}%"
                )
                # Solo un TP por ciclo para evitar condición de carrera
                break

        # ── 2. Breakeven ──────────────────────────────────────
        new_sl: Decimal | None = None

        be_cfg = bot.breakeven_config or {}
        if (
            be_cfg.get("enabled")
            and profit_pct >= Decimal(str(be_cfg.get("activation_profit", 999)))
        ):
            be_price = calculate_breakeven_price(
                entry, side, Decimal(str(be_cfg.get("lock_profit", 0)))
            )
            if should_move_trailing_sl(current_sl, be_price, side):
                new_sl = be_price

        # ── 3. Trailing stop ──────────────────────────────────
        tr_cfg = bot.trailing_config or {}
        if (
            tr_cfg.get("enabled")
            and profit_pct >= Decimal(str(tr_cfg.get("activation_profit", 999)))
        ):
            trailing_sl = calculate_trailing_sl(
                current_price, side, Decimal(str(tr_cfg.get("callback_rate", 0)))
            )
            if should_move_trailing_sl(current_sl, trailing_sl, side):
                if new_sl is None:
                    new_sl = trailing_sl
                else:
                    new_sl = max(new_sl, trailing_sl) if side == "long" else min(new_sl, trailing_sl)

        # ── 4. Stop dinámico por pasos ───────────────────────
        dy_cfg = bot.dynamic_sl_config or {}
        if dy_cfg.get("enabled"):
            step_pct  = Decimal(str(dy_cfg.get("step_percent", 0)))
            max_steps = int(dy_cfg.get("max_steps", 0))  # 0 = ilimitado

            if step_pct > 0:
                steps_earned = get_dynamic_sl_step(entry, current_price, side, step_pct)
                if max_steps > 0:
                    steps_earned = min(steps_earned, max_steps)

                extra        = dict(position.extra_config or {})
                steps_applied = int(extra.get("dynamic_sl_steps", 0))

                if steps_earned > steps_applied:
                    dynamic_sl = calculate_dynamic_sl_price(
                        entry, side,
                        bot.initial_sl_percentage,
                        step_pct,
                        steps_earned,
                    )
                    if should_move_trailing_sl(current_sl, dynamic_sl, side):
                        if new_sl is None:
                            new_sl = dynamic_sl
                        else:
                            new_sl = (
                                max(new_sl, dynamic_sl) if side == "long"
                                else min(new_sl, dynamic_sl)
                            )
                        # Persistir pasos aplicados en DB inmediatamente
                        # para que el próximo tick no repita el mismo paso
                        extra["dynamic_sl_steps"] = steps_earned
                        async with AsyncSessionLocal() as db_write:
                            from sqlalchemy import update as sa_update
                            from app.models.position import Position as PositionModel
                            await db_write.execute(
                                sa_update(PositionModel)
                                .where(PositionModel.id == position.id)
                                .values(extra_config=extra)
                            )
                            await db_write.commit()
                        logger.debug(
                            f"Stop dinámico: {side} {symbol} paso {steps_applied}→{steps_earned} "
                            f"SL {current_sl:.4f}→{dynamic_sl:.4f}"
                        )

        if new_sl is None:
            return

        # ── 5. Verificar mejora mínima (evitar spam) ──────────
        min_move = current_price * MIN_IMPROVEMENT_PCT
        if abs(new_sl - current_sl) < min_move:
            return

        # ── 6. Encolar actualización de SL ────────────────────
        from app.tasks.sl_update_tasks import update_stop_loss
        update_stop_loss.delay(
            position_id=str(position.id),
            new_sl_price=float(new_sl),
        )
        logger.debug(
            f"SL encolado: {side} {symbol} "
            f"{current_sl:.4f} → {new_sl:.4f} (precio={current_price})"
        )


trailing_worker = TrailingWorker()
