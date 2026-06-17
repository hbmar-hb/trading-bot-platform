#!/usr/bin/env python3
"""
Importa una posición huérfana del exchange a la base de datos.

Uso:
    cd /app && PYTHONPATH=/app python scripts/import_orphan_position.py

Esto permite que el sistema gestione la posión con SL/TP/trailing automático.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.models.position import Position
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.exchanges.factory import create_exchange
from sqlalchemy import select


# ── Configuración de la posición huérfana ──
BOT_NAME = "XRPbot_15m"
EXCHANGE = "bingx"


async def import_orphan() -> dict:
    async with AsyncSessionLocal() as db:
        # 1. Obtener bot con exchange_account
        from sqlalchemy.orm import selectinload
        bot_result = await db.execute(
            select(BotConfig)
            .options(selectinload(BotConfig.exchange_account))
            .where(BotConfig.bot_name == BOT_NAME)
        )
        bot = bot_result.scalar_one_or_none()
        if not bot:
            return {"status": "error", "reason": f"Bot {BOT_NAME} not found"}

        if not bot.exchange_account:
            return {"status": "error", "reason": "Bot has no exchange account"}

        # 2. Verificar que no existe ya una posición abierta para este bot
        existing = await db.execute(
            select(Position).where(
                Position.bot_id == bot.id,
                Position.status == "open",
            )
        )
        if existing.scalar_one_or_none():
            return {"status": "error", "reason": "Bot already has an open position in DB"}

        # 3. Obtener posición desde exchange
        exchange = create_exchange(bot.exchange_account)
        try:
            live_positions = await exchange.get_open_positions()
            live_pos = next(
                (p for p in live_positions if p.symbol == bot.symbol and p.side == "long"),
                None,
            )
            if not live_pos:
                return {"status": "error", "reason": f"No open {bot.symbol} position found on exchange"}
        finally:
            await exchange.close()

        # 4. Calcular SL/TP basado en configuración del bot
        entry = Decimal(str(live_pos.entry_price))
        qty = Decimal(str(live_pos.quantity))
        leverage = int(live_pos.leverage or 3)

        # SL: initial_sl_percentage del bot
        sl_pct = Decimal(str(bot.initial_sl_percentage)) / Decimal("100")
        sl_price = entry * (Decimal("1") - sl_pct) if live_pos.side == "long" else entry * (Decimal("1") + sl_pct)

        # TP: basado en take_profits del bot
        tp_records = []
        for i, tp_cfg in enumerate(bot.take_profits or [], start=1):
            profit_pct = Decimal(str(tp_cfg.get("profit_percent", "0"))) / Decimal("100")
            close_pct = int(tp_cfg.get("close_percent", "20"))
            tp_price = entry * (Decimal("1") + profit_pct) if live_pos.side == "long" else entry * (Decimal("1") - profit_pct)
            tp_records.append({
                "level": i,
                "price": float(tp_price.quantize(Decimal("0.0001"))),
                "close_percent": close_pct,
                "hit": False,
                "order_id": None,
            })

        # 5. Crear posición
        position = Position(
            bot_id=bot.id,
            exchange=EXCHANGE,
            symbol=bot.symbol,
            side=live_pos.side,
            entry_price=entry,
            quantity=qty,
            leverage=leverage,
            current_sl_price=sl_price.quantize(Decimal("0.0001")),
            current_tp_prices=tp_records,
            exchange_order_id=str(live_pos.exchange_position_id or ""),
            exchange_position_id=str(live_pos.exchange_position_id or ""),
            source="external_import",
            status="open",
            unrealized_pnl=Decimal(str(live_pos.unrealized_pnl or 0)),
            extra_config={
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "original_entry_price": float(entry),
                "import_reason": "orphan_position_reconciliation",
                "initial_sl_price": float(sl_price.quantize(Decimal("0.0001"))),
                "tp_strategy": f"{len(tp_records)}stage_bot_config",
                "breakeven_after_tp1": True,
            },
        )
        db.add(position)

        # 6. Log
        db.add(BotLog(
            bot_id=bot.id,
            event_type="position_imported",
            message=(
                f"Orphan position imported from exchange: {bot.symbol} {live_pos.side} "
                f"qty={float(qty)} entry={float(entry)} SL={float(sl_price):.4f}"
            ),
            metadata={
                "symbol": bot.symbol,
                "side": live_pos.side,
                "quantity": float(qty),
                "entry_price": float(entry),
                "sl_price": float(sl_price),
                "tp_prices": tp_records,
                "exchange_position_id": str(live_pos.exchange_position_id or ""),
            },
        ))

        await db.commit()
        await db.refresh(position)

        return {
            "status": "imported",
            "position_id": str(position.id),
            "symbol": bot.symbol,
            "side": live_pos.side,
            "quantity": float(qty),
            "entry_price": float(entry),
            "sl_price": float(sl_price),
            "tp_prices": tp_records,
            "exchange_position_id": str(live_pos.exchange_position_id or ""),
        }


if __name__ == "__main__":
    result = asyncio.run(import_orphan())
    print(result)
