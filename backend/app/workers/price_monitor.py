"""
Monitoriza los precios de los símbolos de los bots activos
y los publica en Redis (cache + pub/sub).

Usa clientes públicos de cada exchange (sin credenciales — precios son públicos).
Se ejecuta como background task asyncio en el lifespan de FastAPI.
"""
import asyncio
from collections import defaultdict

import ccxt.async_support as ccxt
from loguru import logger
from sqlalchemy import select

from app.models.bot_config import BotConfig
from app.models.exchange_account import ExchangeAccount
from app.services.cache import set_price
from app.services.database import AsyncSessionLocal

POLL_INTERVAL = 2   # segundos entre ciclos


class PriceMonitor:

    def __init__(self):
        # Clientes públicos (sin auth) por nombre de exchange
        self._clients: dict[str, ccxt.Exchange] = {}

    async def run(self) -> None:
        logger.info("PriceMonitor arrancado")
        try:
            while True:
                try:
                    await self._cycle()
                except Exception as exc:
                    logger.warning(f"PriceMonitor ciclo fallido: {exc}")
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("PriceMonitor detenido")
        finally:
            await self._close_clients()

    async def _cycle(self) -> None:
        # 1. Obtener (exchange, symbol) únicos de bots activos
        pairs = await self._get_active_pairs()
        if not pairs:
            return

        # 2. Agrupar por exchange
        by_exchange: dict[str, set[str]] = defaultdict(set)
        for exchange_name, symbol in pairs:
            by_exchange[exchange_name].add(symbol)

        # 3. Fetch precios por exchange en paralelo
        tasks = [
            self._fetch_exchange_prices(exchange_name, symbols)
            for exchange_name, symbols in by_exchange.items()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_exchange_prices(
        self, exchange_name: str, symbols: set[str]
    ) -> None:
        client = self._get_client(exchange_name)
        for symbol in symbols:
            try:
                ccxt_symbol = _to_ccxt_symbol(symbol, exchange_name)
                ticker = await client.fetch_ticker(ccxt_symbol)
                price = float(ticker["last"])
                # Obtener cambio porcentual 24h (puede estar en 'percentage' o 'change')
                change_24h = 0.0
                if "percentage" in ticker and ticker["percentage"] is not None:
                    change_24h = float(ticker["percentage"])
                elif "change" in ticker and ticker["change"] is not None:
                    # Calcular porcentaje si solo tenemos el cambio absoluto
                    if price > 0:
                        change_24h = (float(ticker["change"]) / (price - float(ticker["change"]))) * 100
                await set_price(symbol, price, change_24h)
            except Exception as exc:
                logger.debug(f"Error precio {exchange_name}/{symbol}: {exc}")

    async def _get_active_pairs(self) -> list[tuple[str, str]]:
        """Devuelve todos los pares únicos de todos los bots (activos y pausados)
        para mostrar precios en tiempo real en la lista de bots.
        Incluye bots de paper trading (usan bingx como fuente pública)."""
        async with AsyncSessionLocal() as db:
            # Bots con exchange real
            result = await db.execute(
                select(ExchangeAccount.exchange, BotConfig.symbol)
                .join(BotConfig, BotConfig.exchange_account_id == ExchangeAccount.id)
                .where(BotConfig.status.in_(["active", "paused"]))
                .distinct()
            )
            pairs = list(result.all())

            # Bots de paper trading — usan bingx como fuente pública de precio
            paper_result = await db.execute(
                select(BotConfig.symbol)
                .where(
                    BotConfig.paper_balance_id.is_not(None),
                    BotConfig.status.in_(["active", "paused"]),
                )
                .distinct()
            )
            for row in paper_result.all():
                pair = ("bingx", row[0])
                if pair not in pairs:
                    pairs.append(pair)

            return pairs

    def _get_client(self, exchange_name: str) -> ccxt.Exchange:
        if exchange_name not in self._clients:
            if exchange_name == "bingx":
                self._clients["bingx"] = ccxt.bingx({
                    "options": {"defaultType": "swap"},
                })
            elif exchange_name == "bitunix":
                # Bitunix: reutilizar bingx como fallback de precio público
                # TODO: reemplazar con cliente público de Bitunix cuando esté disponible
                self._clients["bitunix"] = ccxt.bingx({
                    "options": {"defaultType": "swap"},
                })
            else:
                raise ValueError(f"Exchange no soportado: {exchange_name}")
        return self._clients[exchange_name]

    async def _close_clients(self) -> None:
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass


def _to_ccxt_symbol(symbol: str, exchange: str) -> str:
    """
    Asegura que el símbolo esté en formato CCXT (BASE/QUOTE:SETTLE).
    Si ya está en formato CCXT (contiene '/') lo devuelve tal cual.
    Si está en formato compacto (BTCUSDT) lo convierte.
    """
    # Ya en formato CCXT — no tocar
    if "/" in symbol:
        return symbol

    # Conversión genérica: BTCUSDT → BTC/USDT:USDT
    if symbol.endswith("USDT"):
        base = symbol[:-4]
        return f"{base}/USDT:USDT"

    return symbol


# Instancia singleton — la usa el lifespan
price_monitor = PriceMonitor()
