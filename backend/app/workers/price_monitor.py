"""
Monitoriza los precios de los símbolos de los bots activos,
posiciones abiertas (manuales, paper, bots) y los publica en
Redis (cache + pub/sub).

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
from app.models.position import Position
from app.services.cache import async_redis, set_price
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
        """Devuelve todos los pares únicos que necesitan precio en tiempo real:
        - Bots activos/pausados (reales y paper)
        - Posiciones abiertas o pendientes (manuales app, bots, paper)
        - Posiciones manuales externas guardadas en Redis por el unified endpoint.
        """
        pairs: list[tuple[str, str]] = []
        seen = set()

        def _add(exchange: str, symbol: str) -> None:
            pair = (exchange, symbol)
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)

        async with AsyncSessionLocal() as db:
            # ── 1. Bots con exchange real ──────────────────────────
            result = await db.execute(
                select(ExchangeAccount.exchange, BotConfig.symbol)
                .join(BotConfig, BotConfig.exchange_account_id == ExchangeAccount.id)
                .where(BotConfig.status.in_(["active", "paused"]))
                .distinct()
            )
            for row in result.all():
                _add(row[0], row[1])

            # ── 2. Bots de paper trading ───────────────────────────
            paper_result = await db.execute(
                select(BotConfig.symbol)
                .where(
                    BotConfig.paper_balance_id.is_not(None),
                    BotConfig.status.in_(["active", "paused"]),
                )
                .distinct()
            )
            for row in paper_result.all():
                _add("bingx", row[0])

            # ── 3. Posiciones abiertas/pendientes (DB) ─────────────
            # Cubre bots reales, app_manual y paper.  Usa el exchange
            # guardado en la posición; para paper cae a bingx.
            pos_result = await db.execute(
                select(Position.exchange, Position.symbol)
                .where(Position.status.in_(["open", "pending_limit"]))
                .distinct()
            )
            for row in pos_result.all():
                exchange = row[0].lower() if row[0] else "bingx"
                if exchange in ("paper", "unknown"):
                    exchange = "bingx"
                _add(exchange, row[1])

        # ── 4. Posiciones manuales externas (Redis) ──────────────
        # El endpoint /positions/unified guarda aquí los símbolos
        # que encuentra en el exchange para que también tengan precio.
        try:
            raw = await async_redis.get("manual_position_symbols")
            if raw:
                import json
                manual_symbols = json.loads(raw)
                for item in manual_symbols:
                    exchange = item.get("exchange", "bingx").lower()
                    symbol = item.get("symbol")
                    if symbol:
                        _add(exchange, symbol)
        except Exception:
            pass

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
