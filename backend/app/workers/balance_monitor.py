"""
Monitoriza el balance (equity) de las cuentas de exchange con bots activos.
Publica en Redis para que el risk_manager pueda usarlo sin llamar al exchange.

Intervalo más lento que el price_monitor (30s) — el balance no cambia tan rápido.
"""
import asyncio

from loguru import logger
from sqlalchemy import select

from app.exchanges.factory import create_exchange
from app.models.bot_config import BotConfig
from app.models.exchange_account import ExchangeAccount
from app.services.cache import set_balance
from app.services.database import AsyncSessionLocal

POLL_INTERVAL = 30   # segundos


class BalanceMonitor:

    async def run(self) -> None:
        logger.info("BalanceMonitor arrancado")
        try:
            while True:
                try:
                    await self._cycle()
                except Exception as exc:
                    logger.warning(f"BalanceMonitor ciclo fallido: {exc}")
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("BalanceMonitor detenido")

    async def _cycle(self) -> None:
        accounts = await self._get_active_accounts()
        if not accounts:
            return

        tasks = [self._fetch_balance(account) for account in accounts]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_balance(self, account: ExchangeAccount) -> None:
        exchange = create_exchange(account)
        try:
            balance = await exchange.get_equity()
            await set_balance(
                account_id=str(account.id),
                total_equity=float(balance.total_equity),
                available=float(balance.available_balance),
            )
        except Exception as exc:
            logger.warning(f"Error balance {account.exchange}/{account.label}: {exc}")
        finally:
            await exchange.close()

    async def _get_active_accounts(self) -> list[ExchangeAccount]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ExchangeAccount)
                .join(BotConfig, BotConfig.exchange_account_id == ExchangeAccount.id)
                .where(BotConfig.status == "active")
                .distinct()
            )
            return result.scalars().all()


balance_monitor = BalanceMonitor()
