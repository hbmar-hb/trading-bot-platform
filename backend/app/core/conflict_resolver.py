"""
Conflict Resolver v2 — Gestión de conflictos por fuente de señal.

Reglas simplificadas:
1. Mismo sentido → rechazar siempre (excepto manual)
2. Contrario con posición activa:
   a. Si auto_evaluate_profit está activo y la posición está en profit
      con tendencia favorable → rechazar automáticamente
   b. Si no, aplicar config ad hoc por fuente (close_and_open / keep_both / reject)
3. Manual siempre se permite (con confirmación en frontend)

Fuentes: "ia" | "webhook" | "indicator" | "manual"
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.models.bot_config import BotConfig
from app.models.position import Position


def get_conflicting_positions(
    db: Session,
    bot: BotConfig,
) -> list[tuple[Position, BotConfig]]:
    """
    Devuelve todas las posiciones abiertas en el mismo símbolo/cuenta
    que NO pertenecen a este bot.
    """
    from sqlalchemy import or_

    other_bots_query = db.query(BotConfig).filter(
        BotConfig.symbol == bot.symbol,
        BotConfig.id != bot.id,
        BotConfig.status == "active",
    )

    if bot.exchange_account_id:
        other_bots_query = other_bots_query.filter(
            BotConfig.exchange_account_id == bot.exchange_account_id
        )
    else:
        other_bots_query = other_bots_query.filter(
            BotConfig.paper_balance_id == bot.paper_balance_id
        )

    other_bots = other_bots_query.all()
    if not other_bots:
        return []

    other_bot_ids = [b.id for b in other_bots]

    positions = db.query(Position).filter(
        Position.bot_id.in_(other_bot_ids),
        Position.symbol == bot.symbol,
        Position.status.in_(["open", "closing"]),
    ).all()

    bot_map = {b.id: b for b in other_bots}
    result = []
    for pos in positions:
        other_bot = bot_map.get(pos.bot_id)
        if other_bot:
            result.append((pos, other_bot))

    return result


def _evaluate_profit_and_trend(
    db: Session,
    bot: BotConfig,
    position: Position,
) -> bool:
    """
    Evalúa si la posición existente está en profit y la tendencia
    de los últimos 15 minutos le acompaña.

    Retorna True si DEBE rechazarse la nueva señal (posición en profit
    con tendencia favorable).
    """
    import asyncio
    from app.core.engine import _get_exchange_for_bot, _arun

    # 1. Calcular PnL no realizado actual
    try:
        async def _get_price():
            exchange = _get_exchange_for_bot(db, bot)
            try:
                return await exchange.get_price(bot.symbol)
            finally:
                await exchange.close()

        current_price = _arun(_get_price())
    except Exception:
        # Si no podemos obtener precio, no rechazamos por precaución
        return False

    entry = position.entry_price
    qty = position.quantity

    if position.side == "long":
        unrealized_pnl = (current_price - entry) * qty
    else:
        unrealized_pnl = (entry - current_price) * qty

    # Si no está en profit, no rechazamos
    if unrealized_pnl <= 0:
        return False

    # 2. Evaluar tendencia de los últimos 15 minutos
    try:
        import ccxt.async_support as ccxt

        async def _get_trend():
            client = ccxt.bingx({"options": {"defaultType": "swap"}, "timeout": 10000})
            try:
                tf = "15m"
                ohlcv = await client.fetch_ohlcv(bot.symbol, tf, limit=4)
                if len(ohlcv) < 2:
                    return None
                # Comparar última vela con la anterior
                last_close = ohlcv[-1][4]
                prev_close = ohlcv[-2][4]
                return last_close > prev_close  # True = tendencia alcista
            finally:
                await client.close()

        trend_up = _arun(_get_trend())
        if trend_up is None:
            return False

        # Tendencia a favor de la posición existente
        if position.side == "long":
            trend_favorable = trend_up
        else:
            trend_favorable = not trend_up

        return trend_favorable

    except Exception:
        # Si falla la evaluación de tendencia, no rechazamos
        return False


def resolve_conflict(
    db: Session,
    bot: BotConfig,
    side: str,
    source: Literal["ia", "webhook", "indicator", "manual"],
    conflicting: list[tuple[Position, BotConfig]],
) -> dict:
    """
    Resuelve conflictos para una señal entrante.

    Args:
        db: Sesión de base de datos
        bot: Bot que recibe la señal
        side: "long" | "short" de la nueva señal
        source: Fuente de la señal (ia/webhook/indicator/manual)
        conflicting: Lista de (posición, bot) conflictivas

    Retorna:
        {
            "action": "open" | "reject",
            "close_positions": [Position, ...],  # posiciones a cerrar
            "reason": str | None,
        }
    """
    cfg = bot.conflict_config or {}

    # 1. Manual siempre puede abrir (la confirmación está en el frontend)
    if source == "manual":
        return {
            "action": "open",
            "close_positions": [],
            "reason": None,
        }

    # 2. Mismo sentido → rechazar siempre
    same_side = [pos for pos, _ in conflicting if pos.side == side]
    if same_side:
        return {
            "action": "reject",
            "close_positions": [],
            "reason": f"Ya existe posición {side.upper()} en {bot.symbol}",
        }

    # 3. Sin posición contraria → abrir libremente
    opposite = [pos for pos, _ in conflicting if pos.side != side]
    if not opposite:
        return {
            "action": "open",
            "close_positions": [],
            "reason": None,
        }

    # 4. Posición contraria existe
    # 4a. Regla general: evaluar profit + tendencia
    if cfg.get("auto_evaluate_profit", True):
        should_reject = _evaluate_profit_and_trend(db, bot, opposite[0])
        if should_reject:
            return {
                "action": "reject",
                "close_positions": [],
                "reason": f"Posición {opposite[0].side.upper()} en profit con tendencia favorable en {bot.symbol}",
            }

    # 4b. Configuración ad hoc por fuente
    opposite_cfg = cfg.get("opposite_direction", {}).get(source, "close_and_open")

    if opposite_cfg == "reject":
        return {
            "action": "reject",
            "close_positions": [],
            "reason": f"Configuración: rechazar contratendencia ({source}) en {bot.symbol}",
        }
    elif opposite_cfg == "keep_both":
        return {
            "action": "open",
            "close_positions": [],
            "reason": None,
        }
    else:  # close_and_open (default)
        return {
            "action": "open",
            "close_positions": opposite,
            "reason": None,
        }
