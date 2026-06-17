"""
Reconciliador de posiciones al arrancar.

Compara las posiciones marcadas como 'open' en la DB
con las posiciones realmente abiertas en cada exchange.
Bidireccional:
  - DB → Exchange: cierra fantasmas en DB si ya no existen en exchange
  - Exchange → DB: alerta sobre posiciones huérfanas (abiertas en exchange pero NO en DB)

Se ejecuta en el lifespan de FastAPI antes de aceptar tráfico.
"""
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from app.exchanges.factory import create_exchange, create_paper_exchange
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.models.exchange_account import ExchangeAccount
from app.models.paper_balance import PaperBalance
from app.models.position import Position
from app.services.database import AsyncSessionLocal


async def _alert_orphan_positions(
    db,
    account: ExchangeAccount,
    live_positions: list,
    db_open_positions: list[Position],
    exchange,
) -> None:
    """Detecta posiciones abiertas en el exchange que no están en la BD y las cierra."""
    db_symbols_side = {(p.symbol, p.side) for p in db_open_positions if p.status == "open"}
    db_position_ids = {p.exchange_position_id for p in db_open_positions if p.exchange_position_id}

    orphans = []
    for pos in live_positions:
        pos_id = str(pos.exchange_position_id or "")
        pos_key = (pos.symbol, pos.side)
        if pos_key not in db_symbols_side and pos_id not in db_position_ids:
            orphans.append(pos)

    if not orphans:
        return

    # Intentar encontrar un bot para cada símbolo huérfano (para logging contextual)
    for pos in orphans:
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
        bot_name = bot.bot_name if bot else "NO_BOT"
        bot_id = bot.id if bot else None

        msg = (
            f"ORPHAN POSITION: {pos.symbol} {pos.side} qty={pos.quantity} "
            f"entry={pos.entry_price} id={pos.exchange_position_id} on {account.exchange}. "
            f"NOT tracked in DB — AUTO-CLOSING to free capital."
        )
        logger.critical(f"[RECONCILER] {msg}")

        if bot_id:
            db.add(BotLog(
                bot_id=bot_id,
                event_type="error",
                message=msg,
            ))

        # ── AUTO-CLOSE ORPHAN ──
        try:
            await exchange.close_position(
                pos.symbol,
                side=pos.side,
                quantity=float(pos.quantity),
            )
            logger.info(
                f"[RECONCILER] Orphan position closed: {pos.symbol} {pos.side} "
                f"qty={pos.quantity}"
            )
            if bot_id:
                db.add(BotLog(
                    bot_id=bot_id,
                    event_type="orphan_position_auto_closed",
                    message=f"Auto-closed orphan {pos.side} position on {pos.symbol}",
                    metadata={"symbol": pos.symbol, "side": pos.side, "quantity": float(pos.quantity)},
                ))
        except Exception as close_exc:
            logger.error(
                f"[RECONCILER] FAILED to auto-close orphan {pos.symbol} {pos.side}: {close_exc}"
            )

    # Persistir en Redis para que el frontend/WS pueda mostrar alertas
    try:
        from app.services.cache import async_redis
        import json
        orphan_data = [
            {
                "symbol": p.symbol,
                "side": p.side,
                "quantity": str(p.quantity),
                "entry_price": str(p.entry_price),
                "unrealized_pnl": str(p.unrealized_pnl or 0),
                "exchange_position_id": str(p.exchange_position_id or ""),
                "exchange": account.exchange,
                "account_id": str(account.id),
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            for p in orphans
        ]
        await async_redis.setex(
            f"orphan_positions:{account.exchange}:{account.id}",
            300,
            json.dumps(orphan_data),
        )
    except Exception as redis_exc:
        logger.warning(f"[RECONCILER] Failed to cache orphan positions in Redis: {redis_exc}")


async def sync_open_positions() -> None:
    logger.info("Reconciler: sincronizando posiciones abiertas con exchanges...")

    async with AsyncSessionLocal() as db:
        closed_count = 0
        orphan_count = 0

        # ═══════════════════════════════════════════════════════════
        # 1. RECONCILIAR POSICIONES DE EXCHANGE REAL (DB ↔ Exchange)
        # ═══════════════════════════════════════════════════════════
        # Obtener TODAS las cuentas de exchange activas para detectar
        # posiciones huérfanas incluso cuando la BD está vacía.
        accounts_result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active == True)
        )
        all_accounts = accounts_result.scalars().all()

        # Obtener posiciones abiertas en la BD por cuenta
        result_real = await db.execute(
            select(Position, BotConfig, ExchangeAccount)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(ExchangeAccount, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(Position.status == "open", BotConfig.exchange_account_id.is_not(None))
        )
        rows_real = result_real.all()

        # Agrupar posiciones DB por cuenta
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

                # 1a. DB → Exchange: cerrar fantasmas en DB
                for position, bot in db_positions:
                    if position.symbol not in live_symbols:
                        position.status = "closed"
                        position.closed_at = datetime.now(timezone.utc)
                        db.add(BotLog(
                            bot_id=bot.id,
                            event_type="error",
                            message=(
                                f"Posición {position.symbol} cerrada en exchange "
                                f"mientras el bot estaba offline — sincronizada al arrancar"
                            ),
                        ))
                        closed_count += 1
                        logger.warning(
                            f"Reconciler: {position.symbol} ({account.exchange}) "
                            f"cerrada en exchange, actualizada en DB"
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
                            f"[RECONCILER] {position.symbol} uPnL updated: {float(new_pnl):.4f} USDT"
                        )

                # 1b. Exchange → DB: detectar huérfanas
                db_open_for_account = [p for p, _ in db_positions]
                await _alert_orphan_positions(db, account, live_positions, db_open_for_account, exchange)
                orphan_count += len([
                    p for p in live_positions
                    if (p.symbol, p.side) not in {(pos.symbol, pos.side) for pos in db_open_for_account}
                    and str(p.exchange_position_id or "") not in {pos.exchange_position_id for pos in db_open_for_account if pos.exchange_position_id}
                ])

            except Exception as exc:
                logger.error(
                    f"Reconciler: error consultando {account.exchange}/{account.label}: {exc}"
                )
            finally:
                await exchange.close()

        # ═══════════════════════════════════════════════════════════
        # 2. RECONCILIAR POSICIONES DE PAPER TRADING
        # ═══════════════════════════════════════════════════════════
        result_paper = await db.execute(
            select(Position, BotConfig, PaperBalance)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(PaperBalance, BotConfig.paper_balance_id == PaperBalance.id)
            .where(Position.status == "open", BotConfig.paper_balance_id.is_not(None))
        )
        rows_paper = result_paper.all()

        if rows_paper:
            # Agrupar por paper balance
            by_paper_account: dict[str, dict] = {}
            for position, bot, paper_balance in rows_paper:
                pid = str(paper_balance.id)
                if pid not in by_paper_account:
                    by_paper_account[pid] = {"paper_balance": paper_balance, "positions": []}
                by_paper_account[pid]["positions"].append((position, bot))

            for pid, data in by_paper_account.items():
                paper_balance: PaperBalance = data["paper_balance"]
                db_positions: list[tuple[Position, BotConfig]] = data["positions"]

                exchange = create_paper_exchange(paper_balance)
                try:
                    live_positions = await exchange.get_open_positions()
                    # Símbolos con posición abierta en paper trading
                    live_symbols = {p.symbol for p in live_positions}

                    for position, bot in db_positions:
                        if position.symbol not in live_symbols:
                            # La posición se cerró en el simulador
                            position.status = "closed"
                            position.closed_at = datetime.now(timezone.utc)

                            db.add(BotLog(
                                bot_id=bot.id,
                                event_type="error",
                                message=(
                                    f"Posición {position.symbol} PAPER cerrada "
                                    f"mientras el bot estaba offline — sincronizada al arrancar"
                                ),
                            ))
                            closed_count += 1
                            logger.warning(
                                f"Reconciler: {position.symbol} (PAPER/{paper_balance.label}) "
                                f"cerrada, actualizada en DB"
                            )

                except Exception as exc:
                    logger.error(
                        f"Reconciler: error consultando paper balance {paper_balance.label}: {exc}"
                    )
                finally:
                    await exchange.close()

        # ═══════════════════════════════════════════════════════════
        # 3. COMMIT Y LOG FINAL
        # ═══════════════════════════════════════════════════════════
        await db.commit()
        total_positions = len(rows_real) + len(rows_paper)
        logger.info(
            f"Reconciler: completado — {total_positions} posición(es) revisada(s), "
            f"{closed_count} sincronizada(s), {orphan_count} huérfana(s) detectada(s)"
        )
