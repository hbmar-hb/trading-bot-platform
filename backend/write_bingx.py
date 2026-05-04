code = '''
"""
Conector BingX via CCXT (perpetual futures).
"""
import time
from decimal import Decimal

import ccxt.async_support as ccxt

from app.exchanges.base import BalanceInfo, BaseExchange, OpenPosition, OrderResult


class BingXExchange(BaseExchange):

    def __init__(self, api_key: str, secret: str, testnet: bool = False):
        self._client = ccxt.bingx({
            "apiKey": api_key,
            "secret": secret,
            "options": {"defaultType": "swap"},
        })
        if testnet:
            self._client.set_sandbox_mode(True)

    async def ping(self) -> float:
        start = time.monotonic()
        await self._client.fetch_time()
        return (time.monotonic() - start) * 1000

    async def get_equity(self) -> BalanceInfo:
        balance = await self._client.fetch_balance({"type": "swap"})
        usdt = balance.get("USDT", {})
        return BalanceInfo(
            total_equity=Decimal(str(usdt.get("total", 0))),
            available_balance=Decimal(str(usdt.get("free", 0))),
            unrealized_pnl=Decimal(str(usdt.get("unrealizedPnl", 0))),
        )

    async def get_price(self, symbol: str) -> Decimal:
        ticker = await self._client.fetch_ticker(symbol)
        return Decimal(str(ticker["last"]))

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._client.set_leverage(leverage, symbol)

    async def open_long(self, symbol: str, quantity: Decimal) -> OrderResult:
        order = await self._client.create_market_buy_order(symbol, float(quantity))
        return self._parse_order(order, "long")

    async def open_short(self, symbol: str, quantity: Decimal) -> OrderResult:
        order = await self._client.create_market_sell_order(symbol, float(quantity))
        return self._parse_order(order, "short")

    async def close_position(self, symbol: str, side: str, quantity: Decimal) -> OrderResult:
        params = {"reduceOnly": True}
        if side == "long":
            order = await self._client.create_market_sell_order(symbol, float(quantity), params=params)
        else:
            order = await self._client.create_market_buy_order(symbol, float(quantity), params=params)
        return self._parse_order(order, side)

    async def place_stop_loss(self, symbol: str, side: str, quantity: Decimal, sl_price: Decimal) -> str:
        sl_side = "sell" if side == "long" else "buy"
        order = await self._client.create_order(
            symbol=symbol, type="stopMarket", side=sl_side, amount=float(quantity),
            params={"stopPrice": float(sl_price), "reduceOnly": True},
        )
        return str(order["id"])

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            await self._client.cancel_order(order_id, symbol)
            return True
        except ccxt.OrderNotFound:
            return True
        except Exception:
            return False

    async def get_open_positions(self) -> list[OpenPosition]:
        raw = await self._client.fetch_positions()
        result = []
        for p in raw:
            contracts = float(p.get("contracts") or 0)
            if contracts <= 0:
                continue
            result.append(OpenPosition(
                symbol=p["symbol"],
                side="long" if p["side"] == "long" else "short",
                entry_price=Decimal(str(p["entryPrice"])),
                quantity=Decimal(str(contracts)),
                unrealized_pnl=Decimal(str(p.get("unrealizedPnl") or 0)),
                exchange_position_id=str(p.get("id", "")),
            ))
        return result

    async def get_candles(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> list[dict]:
        ohlcv = await self._client.fetch_ohlcv(symbol, timeframe, limit=limit)
        return [{"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in ohlcv]

    async def get_markets(self) -> list[str]:
        markets = await self._client.fetch_markets()
        return sorted(m["symbol"] for m in markets if m.get("type") == "swap" and m.get("active"))

    async def close(self) -> None:
        await self._client.close()

    async def get_trade_history(self, symbol=None, limit=100, since=None):
        from loguru import logger
        trades = []
        seen_ids = set()
        try:
            logger.info("BingX: Solicitando historial de posiciones")
            params = {"limit": min(limit, 100)}
            if since:
                params["startTime"] = since
            if symbol:
                params["symbol"] = symbol.replace(":", "")
            positions = await self._client.fetch_positions_history(params)
            logger.info(f"BingX: Recibidas {len(positions)} posiciones")
            for pos in positions:
                info = pos.get("info", {})
                status = info.get("positionStatus") or info.get("status")
                if status and status.upper() != "CLOSED":
                    continue
                trade_id = str(info.get("positionId") or info.get("orderId") or pos.get("id", ""))
                if not trade_id or trade_id in seen_ids:
                    continue
                seen_ids.add(trade_id)
                sym = pos.get("symbol", "") or info.get("symbol", "")
                if ":" not in sym and "USDT" in sym.upper():
                    sym = f"{sym}:USDT"
                pnl = None
                if "profit" in info:
                    pnl = Decimal(str(info["profit"]))
                elif "realisedProfit" in info:
                    pnl = Decimal(str(info["realisedProfit"]))
                elif "realizedPnl" in info:
                    pnl = Decimal(str(info["realizedPnl"]))
                side = "long"
                pos_side = info.get("positionSide") or info.get("side")
                if pos_side:
                    side = "long" if pos_side.upper() in ("LONG", "BUY") else "short"
                qty = Decimal(str(info.get("volume") or info.get("positionAmt") or pos.get("contracts", 0)))
                price = Decimal(str(info.get("avgPrice") or info.get("entryPrice") or pos.get("entryPrice", 0)))
                close_time = info.get("closeTime") or info.get("updateTime") or pos.get("timestamp", 0)
                trades.append({
                    "id": trade_id, "symbol": sym, "side": side, "quantity": qty,
                    "price": price, "pnl": pnl, "fee": Decimal(str(info.get("commission") or 0)),
                    "fee_asset": "USDT", "timestamp": close_time, "order_type": "market", "raw": info,
                })
            logger.info(f"BingX: {len(trades)} trades con PnL")
        except Exception as e:
            logger.error(f"BingX fetchPositionsHistory falló: {e}")
        return trades

    @staticmethod
    def _parse_order(order, side):
        fill_price = order.get("average") or order.get("price") or 0
        return OrderResult(
            order_id=str(order["id"]), symbol=order["symbol"], side=side,
            quantity=Decimal(str(order.get("filled") or order.get("amount") or 0)),
            fill_price=Decimal(str(fill_price)),
        )
'''
with open('app/exchanges/bingx.py', 'w') as f:
    f.write(code.strip())
print('Done')
