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
from app.services.cache import publish_position_update
from app.services.database import AsyncSessionLocal
from app.services.dynamic_risk_manager import (
    EmergencyBrake,
    ScaleOutProfit,
    TimeDecayExit,
    _dynamic_risk_config,
)

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
                logger.warning(
                    f"TrailingWorker error evaluando posición {position.id} ({position.symbol} {position.side}): {exc}"
                )

    async def _evaluate_position(
        self,
        position: Position,
        bot: BotConfig,
        current_price: Decimal,
    ) -> None:
        from app.services.cache import sync_redis
        if sync_redis.exists(f"kill_switch:position:{position.id}"):
            return

        entry      = position.entry_price
        current_sl = position.current_sl_price or Decimal("0")
        side       = position.side
        symbol     = position.symbol
        extra      = dict(position.extra_config or {})

        # ── Stop Loss hit (paper only) ────────────────────────────────────────
        # Para exchanges reales el SL se ejecuta en el exchange; para paper
        # no hay orden activa, así que lo cerramos aquí cuando el precio lo toca.
        if position.exchange == "paper" and current_sl > 0:
            sl_hit = (
                (side == "long"  and current_price <= current_sl) or
                (side == "short" and current_price >= current_sl)
            )
            if sl_hit:
                from app.services.cache import sync_redis
                dedup_key = f"sl_hit:inflight:{position.id}"
                if sync_redis.exists(dedup_key):
                    return
                sync_redis.setex(dedup_key, 120, "1")
                from app.tasks.sl_update_tasks import execute_stop_loss
                execute_stop_loss.delay(
                    position_id=str(position.id),
                    sl_price=float(current_sl),
                    reason="sl_hit",
                )
                logger.info(
                    f"🛑 SL HIT (paper): {symbol} {side} "
                    f"precio={current_price} SL={current_sl}"
                )
                return

        # Profit como % del precio de entrada
        if side == "long":
            profit_pct = (current_price - entry) / entry * Decimal("100")
        else:
            profit_pct = (entry - current_price) / entry * Decimal("100")

        # ── Distancia de riesgo inicial (en % del precio) ─────────────────────
        # Almacenada por bot_activator cuando la IA abre la posición.
        # Para bots no-IA o posiciones legacy: derivamos del bot config.
        initial_risk_pct = Decimal(str(extra.get("initial_risk_pct", 0)))
        if initial_risk_pct <= 0:
            sl_pct = Decimal(str(bot.initial_sl_percentage or 0))
            initial_risk_pct = (
                sl_pct / Decimal(str(bot.leverage))
                if bot.use_roi_percentage and bot.leverage and bot.leverage > 1
                else sl_pct
            )

        # R-múltiplo: profit expresado en unidades del riesgo inicial
        # Ejemplo: initial_risk=2%, profit=3% → R=1.5 (ganó 1.5 veces el riesgo)
        r_multiple = (profit_pct / initial_risk_pct) if initial_risk_pct > 0 else Decimal("0")

        # Candidate new SL — populated by TDE, BE, trailing, dynamic SL
        new_sl: Decimal | None = None

        # ── Dynamic Risk Manager (post-entry) ─────────────────────────────────
        # Priority: Emergency Brake > Scale-Out > Time Decay > legacy TP/BE/Trailing
        dr_config = _dynamic_risk_config(bot)
        if not dr_config.get("enabled", True):
            dr_config = {}

        atr_14 = Decimal(str(extra.get("signal_atr", 0))) or None
        if atr_14 and atr_14 <= 0:
            atr_14 = None

        # 1. Emergency Brake
        eb_cfg = dr_config.get("emergency_brake", {})
        if eb_cfg.get("enabled", True):
            eb_result = EmergencyBrake.evaluate(
                position, current_price, atr_14=atr_14, user_cfg=eb_cfg
            )
            if eb_result["action"] == "EMERGENCY_REDUCE":
                from app.services.cache import sync_redis
                dedup_key = f"emergency_reduce:inflight:{position.id}"
                if not sync_redis.exists(dedup_key):
                    sync_redis.setex(dedup_key, 60, "1")
                    from app.tasks.dynamic_risk_tasks import execute_emergency_reduce
                    execute_emergency_reduce.delay(
                        position_id=str(position.id),
                        reduce_by_pct=eb_result["reduce_by"],
                        new_sl_price=eb_result.get("new_sl"),
                        reason=eb_result["reason"],
                    )
                    logger.info(
                        f"🚨 Emergency brake encolado: {symbol} {side} "
                        f"reduce={eb_result['reduce_by']:.0%} reason={eb_result['reason']}"
                    )
                return  # Stop further evaluation for this position this cycle

        # 2. Scale-Out Profit
        sop_cfg = dr_config.get("scale_out", {})
        if sop_cfg.get("enabled", True):
            sop_result = ScaleOutProfit.evaluate(
                position, current_price, atr_14=atr_14, user_cfg=sop_cfg
            )
            if sop_result["action"] == "SCALE_OUT":
                from app.services.cache import sync_redis
                dedup_key = f"scale_out:inflight:{position.id}:{sop_result['level']}"
                if not sync_redis.exists(dedup_key):
                    sync_redis.setex(dedup_key, 60, "1")
                    from app.tasks.dynamic_risk_tasks import execute_scale_out
                    execute_scale_out.delay(
                        position_id=str(position.id),
                        level=sop_result["level"],
                        close_pct=sop_result["close_pct"],
                        new_sl_price=sop_result.get("new_sl"),
                        reason=sop_result["reason"],
                    )
                    logger.info(
                        f"📐 Scale-out encolado: {symbol} {side} "
                        f"level={sop_result['level']:.2%} close={sop_result['close_pct']:.0%}"
                    )
                return  # One action per tick to avoid race conditions

        # 3. Time Decay Exit
        tde_cfg = dr_config.get("time_decay", {})
        if tde_cfg.get("enabled", True):
            tde_result = TimeDecayExit.evaluate(
                position, current_price, user_cfg=tde_cfg, bot_timeframe=bot.timeframe
            )
            if tde_result["action"] == "TIME_EXIT":
                from app.services.cache import sync_redis
                dedup_key = f"time_exit:inflight:{position.id}"
                if not sync_redis.exists(dedup_key):
                    sync_redis.setex(dedup_key, 60, "1")
                    from app.tasks.dynamic_risk_tasks import execute_time_exit
                    execute_time_exit.delay(
                        position_id=str(position.id),
                        reason=tde_result["reason"],
                    )
                    logger.info(
                        f"⏰ Time exit encolado: {symbol} {side} reason={tde_result['reason']}"
                    )
                return
            elif tde_result["action"] == "PROTECT_PROFIT":
                # Pass the protected SL as a candidate to be merged with BE/trailing
                if tde_result.get("new_sl"):
                    tde_sl = Decimal(str(tde_result["new_sl"]))
                    if should_move_trailing_sl(current_sl, tde_sl, side):
                        if new_sl is None:
                            new_sl = tde_sl
                        elif side == "long":
                            new_sl = max(new_sl, tde_sl)
                        else:
                            new_sl = min(new_sl, tde_sl)
                        extra["time_decay_protected"] = True
                        # Persist extra_config update
                        async with AsyncSessionLocal() as db_write:
                            from sqlalchemy import update as sa_update
                            from app.models.position import Position as PositionModel
                            await db_write.execute(
                                sa_update(PositionModel)
                                .where(PositionModel.id == position.id)
                                .values(extra_config=extra)
                            )
                            await db_write.commit()

        # ── 4. Take Profits (legacy + SAPP unified) ───────────────────────────
        sapp_tp_prices = extra.get("sapp_tp_prices", [])
        sapp_levels = {tp.get("level") for tp in sapp_tp_prices}

        # 4a. Legacy current_tp_prices — skip levels covered by SAPP to avoid double-fire
        tps = position.current_tp_prices or []
        for tp in tps:
            if tp.get("hit"):
                continue
            tp_level = tp.get("level", "?")
            if tp_level in sapp_levels:
                continue
            tp_price  = Decimal(str(tp["price"]))
            close_pct = tp["close_percent"]
            tp_reached = (
                (side == "long"  and current_price >= tp_price) or
                (side == "short" and current_price <= tp_price)
            )
            if tp_reached:
                from app.services.cache import sync_redis
                dedup_key = f"tp_execute:inflight:{position.id}:{tp_level}"
                if sync_redis.exists(dedup_key):
                    logger.debug(f"TP{tp_level} ya en curso para {symbol} {position.id}, saltando")
                    break
                sync_redis.setex(dedup_key, 300, "1")

                from app.tasks.sl_update_tasks import execute_take_profit
                execute_take_profit.delay(
                    position_id=str(position.id),
                    tp_level=tp_level,
                    tp_price=float(tp_price),
                    close_percent=float(close_pct),
                )
                logger.info(
                    f"TP{tp_level} alcanzado: {side} {symbol} "
                    f"R={r_multiple:.2f} precio={current_price} tp={tp_price} cierre={close_pct}%"
                )
                break  # solo un TP por ciclo para evitar condición de carrera

        # 4b. SAPP TP levels (precalculados en bot_activator)
        if sapp_tp_prices:
            for tp in sapp_tp_prices:
                if tp.get("hit"):
                    continue
                tp_price = Decimal(str(tp["price"]))
                close_pct = tp["close_percent"]
                tp_level = tp.get("level", "?")
                tp_reached = (
                    (side == "long"  and current_price >= tp_price) or
                    (side == "short" and current_price <= tp_price)
                )
                if tp_reached:
                    from app.services.cache import sync_redis
                    dedup_key = f"sapp_tp_execute:inflight:{position.id}:{tp_level}"
                    if sync_redis.exists(dedup_key):
                        break
                    sync_redis.setex(dedup_key, 300, "1")

                    from app.tasks.sl_update_tasks import execute_take_profit
                    execute_take_profit.delay(
                        position_id=str(position.id),
                        tp_level=f"SAPP{tp_level}",
                        tp_price=float(tp_price),
                        close_percent=float(close_pct),
                    )
                    logger.info(
                        f"SAPP TP{tp_level} alcanzado: {side} {symbol} "
                        f"R={r_multiple:.2f} precio={current_price} tp={tp_price} cierre={close_pct}%"
                    )
                    break  # Un TP por ciclo

        # ── 2. Breakeven (structural override from position.extra_config) ────
        # Use signal-adjusted breakeven config if available (computed by bot_activator
        # based on forward levels distance). Falls back to bot config.
        sapp_plan = extra.get("dynamic_plan")
        sapp_tp_levels = (sapp_plan or {}).get("tp_levels", [])
        be_cfg = extra.get("adjusted_breakeven_config") or bot.breakeven_config or {}
        if not be_cfg:
            be_cfg = {"enabled": True, "activation_r": 1.0, "lock_profit": 0.2}

        # 3-stage strategy: check if breakeven should activate AFTER TP1 hit
        be_after_tp1 = extra.get("breakeven_after_tp1", False)
        tp1_hit = any(
            t.get("level") == 1 and t.get("hit")
            for t in (position.current_tp_prices or [])
        )

        if be_cfg.get("enabled"):
            trigger_breakeven = False
            if be_after_tp1 and tp1_hit:
                trigger_breakeven = True
                logger.debug(
                    f"Breakeven triggered after TP1 hit: {symbol} {side}"
                )
            else:
                # SAPP override: usar R-múltiplo del plan si existe
                if sapp_tp_levels:
                    activation_r = Decimal(str(sapp_tp_levels[0].get("r_multiple", 1.0)))
                else:
                    activation_r = Decimal(str(be_cfg.get("activation_r", be_cfg.get("activation_profit", 999))))
                be_threshold = initial_risk_pct * activation_r if initial_risk_pct > 0 else activation_r
                if profit_pct >= be_threshold:
                    trigger_breakeven = True

            if trigger_breakeven:
                be_price = calculate_breakeven_price(
                    entry, side,
                    Decimal(str(be_cfg.get("lock_profit", 0))),
                    bot.leverage, bot.use_roi_percentage,
                )
                if should_move_trailing_sl(current_sl, be_price, side):
                    new_sl = be_price

        # ── 3. Trailing Stop (structural override from position.extra_config) ─
        # Use signal-adjusted trailing config if available. Prevents trailing from
        # activating BEFORE the price reaches the first structural forward level.
        tr_cfg = extra.get("adjusted_trailing_config") or bot.trailing_config or {}
        if not tr_cfg:
            tr_cfg = {"enabled": True, "activation_r": 1.5, "callback_rate": 1.0}

        if tr_cfg.get("enabled"):
            # SAPP override: usar R-múltiplo del TP2 del plan si existe
            if len(sapp_tp_levels) >= 2:
                activation_r = Decimal(str(sapp_tp_levels[1].get("r_multiple", 2.5)))
            else:
                activation_r = Decimal(str(tr_cfg.get("activation_r", tr_cfg.get("activation_profit", 999))))
            tr_threshold = initial_risk_pct * activation_r if initial_risk_pct > 0 else activation_r

            callback_rate = Decimal(str(tr_cfg.get("callback_rate", 1.0)))
            # Post-TP1: callback más agresivo (50%) para proteger ganancias
            if extra.get("trailing_activated_after_tp1"):
                callback_rate = callback_rate * Decimal("0.5")

            if profit_pct >= tr_threshold:
                trailing_sl = calculate_trailing_sl(
                    current_price, side, callback_rate,
                    bot.leverage, bot.use_roi_percentage,
                )
                if should_move_trailing_sl(current_sl, trailing_sl, side):
                    if new_sl is None:
                        new_sl = trailing_sl
                    elif side == "long":
                        new_sl = max(new_sl, trailing_sl)
                    else:
                        new_sl = min(new_sl, trailing_sl)

        # ── 4. Stop Dinámico — Híbrido Mecánico + Estructural ─────────────────
        # Mecánico: avanza cada step_r de profit.
        # Estructural: avanza a niveles estructurales invalidados (EQ lows superados
        # en long, EQ highs perforados en short).
        # El más conservador (más cercano al precio) gana.
        dy_cfg = bot.dynamic_sl_config or {}
        if dy_cfg.get("enabled"):
            max_steps = int(dy_cfg.get("max_steps", 0))
            structural_sl: Decimal | None = None

            # ── 4a. Structural SL from support levels ─────────────────────────
            # support_levels contains EQ lows / bull FVGs below entry (LONG)
            # or EQ highs / bear FVGs above entry (SHORT).
            # As price moves favorably, these levels become "invalidated" and
            # can be used as new SL (support becomes trailing floor).
            # Margin: price must exceed level by 0.5% to avoid whipsaw activation.
            _STRUCTURAL_MARGIN = Decimal("0.005")
            support_levels = extra.get("support_levels", [])
            if support_levels:
                if side == "long":
                    # LONG: find highest support level that price has ALREADY surpassed
                    # with margin (current_price > level * 1.005)
                    structural_candidates = [
                        Decimal(str(l["price"]))
                        for l in support_levels
                        if current_price > Decimal(str(l["price"])) * (Decimal("1") + _STRUCTURAL_MARGIN)
                    ]
                    if structural_candidates:
                        structural_sl = max(structural_candidates)
                else:
                    # SHORT: find highest support level (closest to entry) that price has ALREADY broken
                    # with margin (current_price < level * 0.995).
                    # support_levels now contains EQ lows / bull FVGs BELOW entry.
                    structural_candidates = [
                        Decimal(str(l["price"]))
                        for l in support_levels
                        if current_price < Decimal(str(l["price"])) * (Decimal("1") - _STRUCTURAL_MARGIN)
                    ]
                    if structural_candidates:
                        # FASE 1J FIX: para SHORT, el nivel más cercano al precio actual es el más bajo
                        # de los candidatos (no el más alto). El SL debe estar justo arriba del precio,
                        # no en la estratosfera.
                        structural_sl = min(structural_candidates)

            # ── 4b. Mechanical SL (R-multiple steps) ──────────────────────────
            mechanical_sl: Decimal | None = None
            if initial_risk_pct > 0:
                step_r = Decimal(str(dy_cfg.get("step_r", dy_cfg.get("step_percent", 0.5))))
                steps_earned = int(r_multiple / step_r) if (step_r > 0 and r_multiple > 0) else 0
                if max_steps > 0:
                    steps_earned = min(steps_earned, max_steps)

                steps_applied = int(extra.get("dynamic_sl_steps", 0))
                if steps_earned > steps_applied:
                    effective_step_pct = initial_risk_pct * step_r
                    mechanical_sl = calculate_dynamic_sl_price(
                        entry, side,
                        initial_risk_pct,
                        effective_step_pct,
                        steps_earned,
                        leverage=None,
                        use_roi=False,
                    )

            # ── 4c. Hybrid: most conservative (closest to price) wins ─────────
            if structural_sl is not None and mechanical_sl is not None:
                if side == "long":
                    dynamic_sl = max(structural_sl, mechanical_sl)
                else:
                    dynamic_sl = min(structural_sl, mechanical_sl)
                chosen = "hybrid"
            elif structural_sl is not None:
                dynamic_sl = structural_sl
                chosen = "structural"
            elif mechanical_sl is not None:
                dynamic_sl = mechanical_sl
                chosen = "mechanical"
            else:
                dynamic_sl = None
                chosen = "none"

            if dynamic_sl is not None and should_move_trailing_sl(current_sl, dynamic_sl, side):
                if new_sl is None:
                    new_sl = dynamic_sl
                elif side == "long":
                    new_sl = max(new_sl, dynamic_sl)
                else:
                    new_sl = min(new_sl, dynamic_sl)

                if chosen == "mechanical" or chosen == "hybrid":
                    extra["dynamic_sl_steps"] = steps_earned
                extra["dynamic_sl_source"] = chosen
                async with AsyncSessionLocal() as db_write:
                    from sqlalchemy import update as sa_update
                    from app.models.position import Position as PositionModel
                    await db_write.execute(
                        sa_update(PositionModel)
                        .where(PositionModel.id == position.id)
                        .values(extra_config=extra)
                    )
                    await db_write.commit()
                await publish_position_update(
                    str(bot.user_id),
                    {
                        "position_id": str(position.id),
                        "status": "open",
                        "action": "dynamic_sl_step",
                        "dynamic_sl_source": chosen,
                        "r_multiple": float(r_multiple),
                        "symbol": symbol,
                    }
                )
                logger.debug(
                    f"Stop dinámico ({chosen}): {side} {symbol} "
                    f"R={r_multiple:.2f} SL {current_sl:.4f}→{dynamic_sl:.4f}"
                )
            else:
                # Fallback legacy: % fijos para bots non-IA sin riesgo almacenado
                step_pct = Decimal(str(dy_cfg.get("step_percent", 0)))
                if step_pct > 0:
                    steps_earned = get_dynamic_sl_step(
                        entry, current_price, side, step_pct,
                        bot.leverage, bot.use_roi_percentage,
                    )
                    if max_steps > 0:
                        steps_earned = min(steps_earned, max_steps)

                    steps_applied = int(extra.get("dynamic_sl_steps", 0))
                    if steps_earned > steps_applied:
                        dynamic_sl = calculate_dynamic_sl_price(
                            entry, side,
                            bot.initial_sl_percentage,
                            step_pct,
                            steps_earned,
                            bot.leverage, bot.use_roi_percentage,
                        )
                        if should_move_trailing_sl(current_sl, dynamic_sl, side):
                            if new_sl is None:
                                new_sl = dynamic_sl
                            elif side == "long":
                                new_sl = max(new_sl, dynamic_sl)
                            else:
                                new_sl = min(new_sl, dynamic_sl)

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
                            await publish_position_update(
                                str(bot.user_id),
                                {
                                    "position_id": str(position.id),
                                    "status": "open",
                                    "action": "dynamic_sl_step",
                                    "dynamic_sl_steps": steps_earned,
                                    "symbol": symbol,
                                }
                            )
                            logger.debug(
                                f"Stop dinámico (legacy): {side} {symbol} "
                                f"paso {steps_applied}→{steps_earned} "
                                f"SL {current_sl:.4f}→{dynamic_sl:.4f}"
                            )

        if new_sl is None:
            return

        # ── 5. Verificar mejora mínima (evitar spam al exchange) ──────────────
        min_move = current_price * MIN_IMPROVEMENT_PCT
        if abs(new_sl - current_sl) < min_move:
            return

        # ── 6. Dedup Redis: evitar múltiples tasks para la misma posición ─────
        from app.services.cache import sync_redis
        dedup_key = f"sl_update:inflight:{position.id}"
        if sync_redis.exists(dedup_key):
            logger.debug(f"SL update ya en curso para {symbol} {position.id}, saltando")
            return
        sync_redis.setex(dedup_key, 30, "1")

        # ── 7. Encolar actualización de SL ────────────────────────────────────
        from app.tasks.sl_update_tasks import update_stop_loss
        update_stop_loss.delay(
            position_id=str(position.id),
            new_sl_price=float(new_sl),
        )
        logger.debug(
            f"SL encolado: {side} {symbol} "
            f"R={r_multiple:.2f} {current_sl:.4f} → {new_sl:.4f} (precio={current_price})"
        )


trailing_worker = TrailingWorker()
