"""
Conector Bitget via CCXT (perpetual futures).

Bitget usa el mismo formato de símbolo CCXT que BingX para futuros perpetuos:
  BTC/USDT:USDT, ETH/USDT:USDT, etc.

Este conector sigue la interfaz BaseExchange y reutiliza los patrones de BingX,
adaptando los parámetros específicos de Bitget cuando sea necesario.
"""
import time
from decimal import Decimal

import ccxt.async_support as ccxt

from app.exchanges.base import BalanceInfo, BaseExchange, OpenPosition, OrderResult


class BitgetExchange(BaseExchange):

    def __init__(self, api_key: str, secret: str, testnet: bool = False):
        self._client = ccxt.bitget({
            "apiKey": api_key,
            "secret": secret,
            "options": {"defaultType": "swap"},
            "timeout": 30000,
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

    async def set_leverage(self, symbol: str, leverage: int, side: str | None = None) -> None:
        # Bitget acepta holdSide: long/short para aislar el leverage por dirección
        params = {}
        if side in ("long", "short"):
            params["holdSide"] = "long" if side == "long" else "short"
        await self._client.set_leverage(leverage, symbol, params)

    async def calculate_quantity(
        self,
        symbol: str,
        equity: Decimal,
        sizing_type: str,
        sizing_value: Decimal,
        leverage: int,
    ) -> Decimal:
        from loguru import logger

        if not self._client.markets:
            await self._client.load_markets()

        price = await self.get_price(symbol)

        if sizing_type == "percentage":
            margin_usdt = equity * (sizing_value / Decimal("100"))
        else:
            margin_usdt = sizing_value

        notional = margin_usdt * Decimal(leverage)
        raw_qty = notional / price

        market = self._client.market(symbol)
        amount_precision = market.get("precision", {}).get("amount")
        if amount_precision:
            qty = Decimal(str(self._client.amount_to_precision(symbol, float(raw_qty))))
        else:
            qty = raw_qty.quantize(Decimal("0.001"))

        min_amount = float((market.get("limits") or {}).get("amount", {}).get("min") or 0)
        min_notional = float((market.get("limits") or {}).get("cost", {}).get("min") or 0)

        logger.info(
            f"[Bitget] calculate_quantity: symbol={symbol}, equity={equity}, "
            f"sizing={sizing_type}/{sizing_value}, leverage={leverage}x, "
            f"price={price}, notional={notional:.4f} USDT, qty={qty}, "
            f"min_amount={min_amount}, min_notional={min_notional}"
        )

        adjusted = False
        original_qty = qty
        if min_amount and float(qty) < min_amount:
            qty = Decimal(str(self._client.amount_to_precision(symbol, min_amount)))
            adjusted = True
            logger.warning(
                f"[Bitget] Cantidad ajustada al mínimo del exchange: {original_qty} → {qty} "
                f"(min_amount={min_amount})"
            )

        if min_notional and float(qty * price) < min_notional:
            target_qty = Decimal(str(min_notional)) / price
            qty = Decimal(str(self._client.amount_to_precision(symbol, float(target_qty))))
            adjusted = True
            logger.warning(
                f"[Bitget] Cantidad ajustada por min_notional: {original_qty} → {qty} "
                f"(min_notional={min_notional} USDT)"
            )

        if adjusted:
            actual_margin = (qty * price) / Decimal(leverage)
            logger.warning(
                f"[Bitget] Riesgo real será ~{actual_margin:.2f} USDT (vs {margin_usdt:.2f} USDT configurado)"
            )

        return qty

    async def open_long(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        from loguru import logger
        if not self._client.markets:
            await self._client.load_markets()
        qty_precise = Decimal(str(self._client.amount_to_precision(symbol, float(quantity))))
        logger.info(f"[Bitget] open_long: symbol={symbol}, quantity={quantity} → {qty_precise}, price={price}")
        if qty_precise <= Decimal("0"):
            raise ValueError(f"Quantity must be greater than 0, got {qty_precise}")
        params = {"holdSide": "long"}
        if price:
            price_precise = Decimal(str(self._client.price_to_precision(symbol, float(price))))
            order = await self._client.create_limit_buy_order(symbol, float(qty_precise), float(price_precise), params=params)
        else:
            order = await self._client.create_market_buy_order(symbol, float(qty_precise), params=params)
        return self._parse_order(order, "long")

    async def open_short(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        from loguru import logger
        if not self._client.markets:
            await self._client.load_markets()
        qty_precise = Decimal(str(self._client.amount_to_precision(symbol, float(quantity))))
        logger.info(f"[Bitget] open_short: symbol={symbol}, quantity={quantity} → {qty_precise}, price={price}")
        if qty_precise <= Decimal("0"):
            raise ValueError(f"Quantity must be greater than 0, got {qty_precise}")
        params = {"holdSide": "short"}
        if price:
            price_precise = Decimal(str(self._client.price_to_precision(symbol, float(price))))
            order = await self._client.create_limit_sell_order(symbol, float(qty_precise), float(price_precise), params=params)
        else:
            order = await self._client.create_market_sell_order(symbol, float(qty_precise), params=params)
        return self._parse_order(order, "short")

    async def close_position(self, symbol: str, side: str, quantity: Decimal) -> OrderResult:
        from loguru import logger
        if not self._client.markets:
            await self._client.load_markets()

        actual_qty = await self._get_actual_position_qty(symbol, side)
        requested_qty = float(quantity)
        if actual_qty is not None and actual_qty > 0:
            qty_float = min(requested_qty, actual_qty)
            logger.info(f"[Bitget] close_position: requested={requested_qty}, actual={actual_qty}, using={qty_float}")
        else:
            qty_float = requested_qty
            logger.info(f"[Bitget] close_position: posición no encontrada en exchange, usando qty solicitada {qty_float}")

        market = self._client.market(symbol)
        min_amount = float((market.get("limits") or {}).get("amount", {}).get("min") or 0)
        amount_precision = market.get("precision", {}).get("amount")
        if amount_precision:
            qty_float = float(self._client.amount_to_precision(symbol, qty_float))

        logger.info(f"[Bitget] close_position: symbol={symbol}, side={side}, qty={qty_float}, min={min_amount}")

        if min_amount and qty_float < min_amount:
            if actual_qty and actual_qty > 0:
                logger.warning(f"[Bitget] qty {qty_float} < min {min_amount}, cerrando posición completa")
                qty_float = float(self._client.amount_to_precision(symbol, actual_qty))
            else:
                logger.warning(f"[Bitget] qty {qty_float} < min {min_amount} y no hay posición real")
                raise ccxt.ExchangeError("Position already closed")

        params = {"holdSide": "long" if side == "long" else "short"}
        try:
            if side == "long":
                order = await self._client.create_market_sell_order(symbol, qty_float, params=params)
            else:
                order = await self._client.create_market_buy_order(symbol, qty_float, params=params)
            logger.info(f"[Bitget] close order result: {order}")
            return self._parse_order(order, side)
        except ccxt.ExchangeError as e:
            logger.error(f"[Bitget] close_position failed: {type(e).__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"[Bitget] close_position failed: {type(e).__name__}: {e}")
            raise

    async def _get_actual_position_qty(self, symbol: str, side: str) -> float | None:
        from loguru import logger
        try:
            positions = await self._client.fetch_positions([symbol])
            for p in positions:
                if p.get("side") == side:
                    contracts = float(p.get("contracts") or 0)
                    if contracts > 0:
                        return contracts
            return 0.0
        except Exception as e:
            logger.warning(f"[Bitget] _get_actual_position_qty error: {e}")
            return None

    async def place_stop_loss(self, symbol: str, side: str, quantity: Decimal, sl_price: Decimal) -> str:
        if not self._client.markets:
            await self._client.load_markets()
        sl_price_str = self._client.price_to_precision(symbol, float(sl_price))
        sl_order_side = "sell" if side == "long" else "buy"
        params = {
            "triggerPrice": float(sl_price_str),
            "holdSide": "long" if side == "long" else "short",
        }
        order = await self._client.create_order(
            symbol=symbol,
            type="market",
            side=sl_order_side,
            amount=float(quantity),
            params=params,
        )
        return str(order["id"])

    async def place_take_profit(self, symbol: str, side: str, quantity: Decimal, tp_price: Decimal) -> str:
        if not self._client.markets:
            await self._client.load_markets()
        tp_price_str = self._client.price_to_precision(symbol, float(tp_price))
        tp_order_side = "sell" if side == "long" else "buy"
        params = {
            "triggerPrice": float(tp_price_str),
            "holdSide": "long" if side == "long" else "short",
        }
        order = await self._client.create_order(
            symbol=symbol,
            type="market",
            side=tp_order_side,
            amount=float(quantity),
            params=params,
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
        if not self._client.markets:
            await self._client.load_markets()
        raw = await self._client.fetch_positions()
        result = []
        for p in raw:
            contracts = float(p.get("contracts") or 0)
            if contracts <= 0:
                continue
            entry_price = p.get("entryPrice") or p.get("info", {}).get("avgPrice") or 0
            side_raw = p.get("side") or p.get("info", {}).get("holdSide", "long")
            leverage_raw = p.get("leverage") or p.get("info", {}).get("leverage")
            result.append(OpenPosition(
                symbol=p["symbol"],
                side="long" if str(side_raw).lower() in ("long", "buy") else "short",
                entry_price=Decimal(str(entry_price or 0)),
                quantity=Decimal(str(contracts)),
                unrealized_pnl=Decimal(str(p.get("unrealizedPnl") or 0)),
                exchange_position_id=str(p.get("id") or p.get("info", {}).get("posId") or ""),
                leverage=int(leverage_raw) if leverage_raw else None,
            ))
        return result

    async def get_candles(self, symbol: str, timeframe: str = "1h", limit: int = 200, since: int | None = None) -> list[dict]:
        ohlcv = await self._client.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        return [
            {"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in ohlcv
        ]

    async def get_markets(self) -> list[str]:
        markets = await self._client.fetch_markets()
        return sorted(m["symbol"] for m in markets if m.get("type") == "swap" and m.get("active"))

    async def get_open_orders(self) -> list[dict]:
        from loguru import logger
        if not self._client.markets:
            await self._client.load_markets()
        try:
            orders = await self._client.fetch_open_orders()
            result = []
            for o in orders:
                order_type = str(o.get("type", "")).lower()
                if order_type != "limit":
                    continue
                pos_side = (o.get("info", {}).get("holdSide") or "long").lower()
                result.append({
                    "id": str(o.get("id", "")),
                    "symbol": o.get("symbol", ""),
                    "side": pos_side,
                    "quantity": Decimal(str(o.get("amount") or o.get("remaining") or 0)),
                    "price": Decimal(str(o.get("price") or 0)),
                    "order_type": order_type,
                })
            logger.info(f"[Bitget] get_open_orders: {len(result)} órdenes limit abiertas")
            return result
        except Exception as e:
            logger.warning(f"[Bitget] get_open_orders error: {e}")
            return []

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _parse_order(order, side):
        from loguru import logger
        logger.info(f"[Bitget] Parsing order: {order}")
        try:
            fill_price = order.get("average") or order.get("price") or 0
            filled_qty = order.get("filled") or order.get("amount") or 0
            return OrderResult(
                order_id=str(order.get("id") or order.get("orderId") or "unknown"),
                symbol=order.get("symbol") or "",
                side=side,
                quantity=Decimal(str(filled_qty)) if filled_qty is not None else Decimal(0),
                fill_price=Decimal(str(fill_price)) if fill_price is not None else Decimal(0),
            )
        except Exception as e:
            logger.error(f"[Bitget] Error parsing order: {e}, order={order}")
            raise
