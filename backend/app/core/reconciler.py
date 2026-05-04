"""
Reconciliador de posiciones al arrancar.

Compara las posiciones marcadas como 'open' en la DB
con las posiciones realmente abiertas en cada exchange.
Si hay discrepancias (cerradas en el exchange pero no en DB),
las marca como cerradas para mantener consistencia.

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


async def sync_open_positions() -> None:
    logger.info("Reconciler: sincronizando posiciones abiertas con exchanges...")

    async with AsyncSessionLocal() as db:
        closed_count = 0

        # ═══════════════════════════════════════════════════════════
        # 1. RECONCILIAR POSICIONES DE EXCHANGE REAL
        # ═══════════════════════════════════════════════════════════
        result_real = await db.execute(
            select(Position, BotConfig, ExchangeAccount)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(ExchangeAccount, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(Position.status == "open", BotConfig.exchange_account_id.is_not(None))
        )
        rows_real = result_real.all()

        if rows_real:
            # Agrupar por exchange account para minimizar llamadas a la API
            by_account: dict[str, dict] = {}
            for position, bot, account in rows_real:
                aid = str(account.id)
                if aid not in by_account:
                    by_account[aid] = {"account": account, "positions": []}
                by_account[aid]["positions"].append((position, bot))

            for aid, data in by_account.items():
                account: ExchangeAccount = data["account"]
                db_positions: list[tuple[Position, BotConfig]] = data["positions"]

                exchange = create_exchange(account)
                try:
                    live_positions = await exchange.get_open_positions()
                    # Símbolos con posición real abierta en el exchange
                    live_symbols = {p.symbol for p in live_positions}

                    for position, bot in db_positions:
                        if position.symbol not in live_symbols:
                            # La posición se cerró en el exchange (manualmente, SL hit, etc.)
                            # mientras el backend estaba caído
                            position.status = "closed"
                            position.closed_at = datetime.now(timezone.utc)
                            # PnL desconocido — el exchange ya no tiene el dato fácilmente
                            # Se puede enriquecer consultando el historial de trades del exchange

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
            f"{closed_count} sincronizada(s)"
        )
