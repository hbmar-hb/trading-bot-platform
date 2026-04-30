"""
Monitoriza el balance (equity) de las cuentas de paper trading con bots activos.

Similar al balance_monitor pero para cuentas paper:
- Calcula equity = available_balance + unrealized_pnl de posiciones abiertas
- Actualiza la DB (paper_balances.total_equity)
- Publica en Redis para que el frontend lo consuma vía WS o polling.

Se ejecuta como background task asyncio en el lifespan de FastAPI.
"""
import asyncio

from loguru import logger
from sqlalchemy import select

from app.exchanges.factory import create_paper_exchange
from app.models.bot_config import BotConfig
from app.models.paper_balance import PaperBalance
from app.services.cache import set_balance
from app.services.database import AsyncSessionLocal

POLL_INTERVAL = 30   # segundos


class PaperBalanceMonitor:

    async def run(self) -> None:
        logger.info("PaperBalanceMonitor arrancado")
        try:
            while True:
                try:
                    await self._cycle()
                except Exception as exc:
                    logger.warning(f"PaperBalanceMonitor ciclo fallido: {exc}")
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("PaperBalanceMonitor detenido")

    async def _cycle(self) -> None:
        paper_balances = await self._get_active_paper_balances()
        if not paper_balances:
            return

        tasks = [self._fetch_paper_balance(pb) for pb in paper_balances]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_paper_balance(self, paper_balance: PaperBalance) -> None:
        """Calcula y actualiza el equity de una cuenta paper."""
        exchange = create_paper_exchange(paper_balance)
        try:
            equity_info = await exchange.get_equity()

            # Actualizar en DB
            async with AsyncSessionLocal() as db:
                # Refrescar instancia para estar en la sesión actual
                db.add(paper_balance)
                paper_balance.total_equity = equity_info.total_equity
                paper_balance.available_balance = equity_info.available_balance
                await db.commit()

            # Publicar en Redis (mismo formato que cuentas reales)
            await set_balance(
                account_id=str(paper_balance.id),
                total_equity=float(equity_info.total_equity),
                available=float(equity_info.available_balance),
            )

            logger.debug(
                f"PaperBalanceMonitor: {paper_balance.label} "
                f"equity={equity_info.total_equity:.2f} "
                f"available={equity_info.available_balance:.2f}"
            )
        except Exception as exc:
            logger.warning(
                f"Error paper balance {paper_balance.label}: {exc}"
            )
        finally:
            await exchange.close()

    async def _get_active_paper_balances(self) -> list[PaperBalance]:
        """Devuelve PaperBalances que tienen al menos un bot activo."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PaperBalance)
                .join(BotConfig, BotConfig.paper_balance_id == PaperBalance.id)
                .where(BotConfig.status == "active")
                .distinct()
            )
            return result.scalars().all()


paper_balance_monitor = PaperBalanceMonitor()
