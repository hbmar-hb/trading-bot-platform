"""Bot Activator — bridges AI Confluence signals to real exchange orders.

Called after an AISignal with STRONG+CLEAR quality is persisted.
Finds BotConfigs with ai_signal_mode=True matching the signal's ticker,
places market orders with the AI signal's pre-computed SL/TP levels.

Flow per bot:
  1. Quality filter  — STRONG + CLEAR only
  2. Score filter    — ai_signal_config.min_score threshold
  3. Concurrency cap — ai_signal_config.max_concurrent open positions
  4. Set leverage    — from bot.leverage
  5. Size position   — bot.position_value (% equity or fixed USDT)
  6. Open position   — market order via exchange factory
  7. Place SL        — ai signal's stop_loss price
  8. Record Position + BotLog
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger

from app.models.ai_signal import AISignal
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.models.position import Position
from app.services.database import SessionLocal

# Max age in candle-multiples before a signal is considered stale
_STALE_CANDLES = 3

_TF_MINUTES: dict[str, int] = {
    "1m": 1,   "3m": 3,    "5m": 5,    "15m": 15,  "30m": 30,
    "1h": 60,  "2h": 120,  "4h": 240,  "8h": 480,  "12h": 720,
    "1d": 1440, "1w": 10080,
}


def _signal_is_stale(sig: AISignal) -> bool:
    """Return True when signal is older than 3 candles of its timeframe."""
    tf_min   = _TF_MINUTES.get(sig.timeframe, 60)
    max_age  = tf_min * _STALE_CANDLES
    st = sig.signal_time
    if st.tzinfo is None:
        st = st.replace(tzinfo=timezone.utc)
    age_min = (datetime.now(timezone.utc) - st).total_seconds() / 60
    return age_min > max_age


def _arun(coro):
    return asyncio.run(coro)


# ── Public entry point ────────────────────────────────────────────────────────

def activate(ai_signal_id: str) -> dict:
    """Dispatch orders for all AI bots matching the given signal."""
    with SessionLocal() as db:
        sig = db.query(AISignal).filter(
            AISignal.id == uuid.UUID(ai_signal_id)
        ).first()

        if not sig:
            return {"activated": 0, "reason": "signal_not_found"}

        # Quality gate — only STRONG + CLEAR signals reach bots
        if sig.quality_tier != "STRONG" or sig.anti_fake_status != "CLEAR":
            logger.info(
                f"[ACTIVATOR] {sig.ticker} filtered — "
                f"tier={sig.quality_tier} status={sig.anti_fake_status}"
            )
            return {"activated": 0, "reason": "quality_filter"}

        # Staleness gate — reject if price likely moved past entry zone
        if _signal_is_stale(sig):
            tf_min  = _TF_MINUTES.get(sig.timeframe, 60)
            max_age = tf_min * _STALE_CANDLES
            logger.info(
                f"[ACTIVATOR] {sig.ticker} signal stale — "
                f"signal_time={sig.signal_time.isoformat()} "
                f"max_age={max_age}min tf={sig.timeframe}"
            )
            return {"activated": 0, "reason": "stale_signal"}

        # Telegram/Discord alert — fires for every STRONG+CLEAR non-stale signal
        try:
            from app.tasks.notification_tasks import ai_signal_alert
            htf_bias = (sig.features or {}).get("htf_bias")
            ai_signal_alert.delay(
                ticker      = sig.ticker,
                timeframe   = sig.timeframe,
                direction   = sig.direction,
                score       = float(sig.score),
                quality_score = float(sig.quality_score),
                confidence  = sig.confidence,
                entry       = float(sig.entry_price),
                sl          = float(sig.stop_loss),
                tp1         = float(sig.take_profit_1),
                tp2         = float(sig.take_profit_2),
                components  = sig.components or {},
                warnings    = (sig.warnings or [])[:3],
                htf_bias    = htf_bias,
            )
        except Exception as _alert_exc:
            logger.warning(f"[ACTIVATOR] Alert dispatch failed: {_alert_exc}")

        bots = (
            db.query(BotConfig)
            .filter(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
                BotConfig.symbol == sig.ccxt_symbol,
            )
            .all()
        )

        if not bots:
            logger.debug(f"[ACTIVATOR] No AI bots configured for {sig.ccxt_symbol}")
            return {"activated": 0, "reason": "no_matching_bots"}

        activated, results = 0, []
        for bot in bots:
            cfg = bot.ai_signal_config or {}
            min_score    = cfg.get("min_score", 60)
            max_conc     = cfg.get("max_concurrent", 1)

            if sig.score < min_score:
                logger.info(f"[ACTIVATOR] {bot.bot_name}: score {sig.score} < min {min_score}")
                continue

            open_count = (
                db.query(Position)
                .filter(Position.bot_id == bot.id, Position.status == "open")
                .count()
            )
            if open_count >= max_conc:
                logger.info(f"[ACTIVATOR] {bot.bot_name}: max_concurrent={max_conc} reached")
                continue

            try:
                res = _execute_for_bot(db, bot, sig)
                results.append(res)
                activated += 1
            except Exception as exc:
                logger.error(
                    f"[ACTIVATOR] Error on bot {bot.bot_name}: {exc}",
                    exc_info=True,
                )
                db.add(BotLog(
                    bot_id=bot.id,
                    event="ai_activation_error",
                    metadata={"error": str(exc)[:500], "ai_signal_id": str(sig.id)},
                ))
                db.commit()

        return {"activated": activated, "results": results}


# ── Per-bot execution ─────────────────────────────────────────────────────────

def _execute_for_bot(db, bot: BotConfig, sig: AISignal) -> dict:
    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.paper_balance import PaperBalance

    if bot.is_paper_trading:
        paper = db.query(PaperBalance).filter(
            PaperBalance.id == bot.paper_balance_id
        ).first()
        if not paper:
            raise ValueError("PaperBalance not found")
        exchange = create_paper_exchange(paper)
    else:
        if not bot.exchange_account:
            raise ValueError("No exchange_account on bot")
        exchange = create_exchange(bot.exchange_account)

    # Set leverage
    _arun(exchange.set_leverage(bot.symbol, bot.leverage, sig.direction))

    # Size position
    balance_info = _arun(exchange.get_equity())
    equity = float(balance_info.total_equity)

    if bot.position_sizing_type == "percentage":
        notional = equity * float(bot.position_value) / 100.0
    else:
        notional = float(bot.position_value)

    entry_ref = float(sig.entry_price)
    quantity  = Decimal(str(round(notional * bot.leverage / entry_ref, 6)))

    logger.info(
        f"[ACTIVATOR] {bot.bot_name} | {sig.direction.upper()} {sig.ticker} | "
        f"qty={quantity} entry≈{entry_ref} sl={sig.stop_loss} tp1={sig.take_profit_1}"
    )

    # Open position (market)
    if sig.direction == "long":
        order = _arun(exchange.open_long(sig.ticker, quantity))
    else:
        order = _arun(exchange.open_short(sig.ticker, quantity))

    fill_price = order.fill_price or Decimal(str(entry_ref))

    # Place stop loss
    sl_order_id = _arun(
        exchange.place_stop_loss(
            sig.ticker, sig.direction, quantity, Decimal(str(sig.stop_loss))
        )
    )

    # Place TP1 (60%) and TP2 (40%) as TAKE_PROFIT_MARKET orders
    qty_tp1 = Decimal(str(round(float(quantity) * 0.60, 6)))
    qty_tp2 = quantity - qty_tp1
    tp1_order_id: str | None = None
    tp2_order_id: str | None = None
    try:
        tp1_order_id = _arun(
            exchange.place_take_profit(
                sig.ticker, sig.direction, qty_tp1, Decimal(str(sig.take_profit_1))
            )
        )
        tp2_order_id = _arun(
            exchange.place_take_profit(
                sig.ticker, sig.direction, qty_tp2, Decimal(str(sig.take_profit_2))
            )
        )
        logger.info(
            f"[ACTIVATOR] TP orders placed — TP1={tp1_order_id} TP2={tp2_order_id}"
        )
    except Exception as tp_exc:
        logger.warning(
            f"[ACTIVATOR] TP order placement failed (position open, SL placed): {tp_exc}"
        )

    # Determine exchange name
    exchange_name = (
        bot.exchange_account.exchange if bot.exchange_account else "paper"
    )

    # Record position
    position = Position(
        bot_id                = bot.id,
        exchange              = exchange_name,
        symbol                = sig.ticker,
        side                  = sig.direction,
        entry_price           = fill_price,
        quantity              = quantity,
        leverage              = bot.leverage,
        current_sl_price      = Decimal(str(sig.stop_loss)),
        current_tp_prices     = [
            {"level": 1, "price": float(sig.take_profit_1), "close_percent": 60, "hit": False, "order_id": tp1_order_id},
            {"level": 2, "price": float(sig.take_profit_2), "close_percent": 40, "hit": False, "order_id": tp2_order_id},
        ],
        exchange_order_id     = order.order_id,
        exchange_sl_order_id  = sl_order_id,
        status                = "open",
        extra_config          = {
            "source":         "ai_signal",
            "ai_signal_id":   str(sig.id),
            "score":          sig.score,
            "confidence":     sig.confidence,
            "quality_tier":   sig.quality_tier,
        },
    )
    db.add(position)

    db.add(BotLog(
        bot_id   = bot.id,
        event    = "ai_signal_activated",
        metadata = {
            "ai_signal_id":  str(sig.id),
            "direction":     sig.direction,
            "score":         sig.score,
            "quality_tier":  sig.quality_tier,
            "fill_price":    float(fill_price),
            "sl":            float(sig.stop_loss),
            "tp1":           float(sig.take_profit_1),
            "tp2":           float(sig.take_profit_2),
            "order_id":      order.order_id,
            "tp1_order_id":  tp1_order_id,
            "tp2_order_id":  tp2_order_id,
        },
    ))
    db.commit()

    return {
        "bot_id":     str(bot.id),
        "bot_name":   bot.bot_name,
        "order_id":   order.order_id,
        "fill_price": float(fill_price),
    }
