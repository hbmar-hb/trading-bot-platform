"""Periodic reconciliation task — runs every 5 minutes via Celery Beat.

Checks that DB 'open' positions still exist on the exchange.
Closes phantom positions in DB if the exchange no longer has them.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.reconcile_task.periodic_reconcile",
    queue="default",
)
def periodic_reconcile(self) -> dict:
    try:
        return _run_async(_reconcile_async())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


async def _reconcile_async() -> dict:
    from app.models.bot_config import BotConfig
    from app.models.exchange_account import ExchangeAccount
    from app.models.paper_balance import PaperBalance
    from app.models.position import Position
    from app.models.bot_log import BotLog
    from app.exchanges.factory import create_exchange, create_paper_exchange

    async with AsyncSessionLocal() as db:
        closed_count = 0
        orphan_count = 0

        # 1. Reconciliar posiciones reales (DB ↔ Exchange)
        # Obtener TODAS las cuentas activas para detectar huérfanas aunque la BD esté vacía
        accounts_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active == True)
        )
        all_accounts = accounts_result.scalars().all()

        result_real = await db.execute(
            select(Position, BotConfig, ExchangeAccount)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(ExchangeAccount, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(Position.status == "open", BotConfig.exchange_account_id.is_not(None))
        )
        rows_real = result_real.all()

        db_positions_by_account: dict[str, list[tuple[Position, BotConfig]]] = {}
        for position, bot, account in rows_real:
            aid = str(account.id)
            db_positions_by_account.setdefault(aid, []).append((position, bot))

        for account in all_accounts:
            aid = str(account.id)
            db_positions = db_positions_by_account.get(aid, [])

            exchange = create_exchange(account)
            try:
                live_positions = await exchange.get_open_positions()
                live_symbols = {p.symbol for p in live_positions}

                # 1a. DB → Exchange: cerrar fantasmas
                for position, bot in db_positions:
                    if position.symbol not in live_symbols:
                        position.status = "closed"
                        position.closed_at = datetime.now(timezone.utc)
                        # CRITICAL FIX: capture realized_pnl before losing it
                        # Use last known unrealized_pnl as best proxy for realized_pnl
                        if position.realized_pnl is None:
                            from decimal import Decimal
                            proxy_pnl = position.unrealized_pnl
                            if proxy_pnl is not None:
                                position.realized_pnl = Decimal(str(proxy_pnl))
                                logger.info(
                                    f"[RECONCILE] {position.symbol} realized_pnl set to "
                                    f"{float(proxy_pnl):.4f} (from last uPnL)"
                                )
                        db.add(BotLog(
                            bot_id=bot.id,
                            event_type="error",
                            message=(
                                f"Posición {position.symbol} cerrada en exchange "
                                f"detectada por reconciliación periódica "
                                f"(PnL={position.realized_pnl or 'N/A'})"
                            ),
                        ))
                        closed_count += 1
                        logger.warning(
                            f"[RECONCILE] {position.symbol} ({account.exchange}) "
                            f"closed on exchange, synced in DB"
                        )

                # 1c. Sync live metadata for open positions (uPnL, entry, qty)
                live_pos_by_symbol = {p.symbol: p for p in live_positions}
                for position, bot in db_positions:
                    if position.status != "open":
                        continue
                    live = live_pos_by_symbol.get(position.symbol)
                    if not live:
                        continue
                    from decimal import Decimal
                    new_pnl = Decimal(str(live.unrealized_pnl or 0))
                    if new_pnl != position.unrealized_pnl:
                        position.unrealized_pnl = new_pnl
                        logger.info(
                            f"[RECONCILE] {position.symbol} uPnL updated: {float(new_pnl):.4f} USDT"
                        )

                # 1b. Exchange → DB: detectar huérfanas
                db_open_for_account = [p for p, _ in db_positions]
                db_keys = {(p.symbol, p.side) for p in db_open_for_account if p.status == "open"}
                db_ids = {p.exchange_position_id for p in db_open_for_account if p.exchange_position_id}

                for pos in live_positions:
                    pos_id = str(pos.exchange_position_id or "")
                    if (pos.symbol, pos.side) not in db_keys and pos_id not in db_ids:
                        orphan_count += 1
                        bot_result = await db.execute(
                            select(BotConfig)
                            .where(
                                BotConfig.symbol == pos.symbol,
                                BotConfig.exchange_account_id == account.id,
                                BotConfig.status == "active",
                            )
                            .limit(1)
                        )
                        bot = bot_result.scalar_one_or_none()
                        bot_id = bot.id if bot else None

                        # Intentar auto-cerrar orphan en exchange
                        auto_closed = False
                        try:
                            from decimal import Decimal
                            await exchange.close_position(
                                pos.symbol,
                                side=pos.side,
                                quantity=Decimal(str(pos.quantity)),
                            )
                            auto_closed = True
                            logger.info(
                                f"[RECONCILE] Auto-closed orphan: {pos.symbol} {pos.side} qty={pos.quantity}"
                            )
                        except Exception as close_exc:
                            logger.error(
                                f"[RECONCILE] FAILED to auto-close orphan {pos.symbol} {pos.side}: {close_exc}"
                            )

                        if not auto_closed:
                            msg = (
                                f"ORPHAN POSITION: {pos.symbol} {pos.side} qty={pos.quantity} "
                                f"entry={pos.entry_price} id={pos.exchange_position_id} on {account.exchange}. "
                                f"NOT tracked in DB — capital blocked. Close via /positions/external/close."
                            )
                            logger.critical(f"[RECONCILE] {msg}")
                            if bot_id:
                                db.add(BotLog(bot_id=bot_id, event_type="error", message=msg))

            except Exception as exc:
                logger.error(
                    f"[RECONCILE] Error querying {account.exchange}/{account.label}: {exc}"
                )
            finally:
                await exchange.close()

        # 2. Reconciliar paper trading
        result_paper = await db.execute(
            select(Position, BotConfig, PaperBalance)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(PaperBalance, BotConfig.paper_balance_id == PaperBalance.id)
            .where(Position.status == "open", BotConfig.paper_balance_id.is_not(None))
        )
        rows_paper = result_paper.all()

        if rows_paper:
            by_paper: dict[str, dict] = {}
            for position, bot, paper in rows_paper:
                pid = str(paper.id)
                if pid not in by_paper:
                    by_paper[pid] = {"paper": paper, "positions": []}
                by_paper[pid]["positions"].append((position, bot))

            for pid, data in by_paper.items():
                paper: PaperBalance = data["paper"]
                db_positions = data["positions"]

                exchange = create_paper_exchange(paper)
                try:
                    live_positions = await exchange.get_open_positions()
                    live_symbols = {p.symbol for p in live_positions}

                    for position, bot in db_positions:
                        if position.symbol not in live_symbols:
                            position.status = "closed"
                            position.closed_at = datetime.now(timezone.utc)
                            db.add(BotLog(
                                bot_id=bot.id,
                                event_type="error",
                                message=(
                                    f"Posición {position.symbol} PAPER cerrada "
                                    f"detectada por reconciliación periódica"
                                ),
                            ))
                            closed_count += 1
                            logger.warning(
                                f"[RECONCILE] {position.symbol} (PAPER/{paper.label}) "
                                f"closed, synced in DB"
                            )
                except Exception as exc:
                    logger.error(
                        f"[RECONCILE] Error querying paper {paper.label}: {exc}"
                    )
                finally:
                    await exchange.close()

        await db.commit()
        total = len(rows_real) + len(rows_paper)
        logger.info(f"[RECONCILE] Checked {total} positions, {closed_count} synced, {orphan_count} orphan(s)")

    return {"checked": total, "synced": closed_count, "orphans": orphan_count}
