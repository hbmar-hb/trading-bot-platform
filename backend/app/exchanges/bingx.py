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
            "timeout": 30000,  # 30s max per HTTP call
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
        # BingX requiere side: LONG, SHORT, o BOTH
        side_param = "BOTH"
        if side == "long":
            side_param = "LONG"
        elif side == "short":
            side_param = "SHORT"
        await self._client.set_leverage(leverage, symbol, {"side": side_param})

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

        # Use the exchange's actual step size instead of hardcoded 0.001
        market = self._client.market(symbol)
        amount_precision = market.get("precision", {}).get("amount")
        if amount_precision:
            qty = Decimal(str(self._client.amount_to_precision(symbol, float(raw_qty))))
        else:
            qty = raw_qty.quantize(Decimal("0.001"))

        # Check against exchange minimum order size
        min_amount = float((market.get("limits") or {}).get("amount", {}).get("min") or 0)
        min_notional = float((market.get("limits") or {}).get("cost", {}).get("min") or 0)

        logger.info(
            f"[BingX] calculate_quantity: symbol={symbol}, equity={equity}, "
            f"sizing={sizing_type}/{sizing_value}, leverage={leverage}x, "
            f"price={price}, notional={notional:.4f} USDT, qty={qty}, "
            f"min_amount={min_amount}, min_notional={min_notional}"
        )

        # Auto-adjust to exchange minimums instead of failing
        adjusted = False
        original_qty = qty
        if min_amount and float(qty) < min_amount:
            qty = Decimal(str(self._client.amount_to_precision(symbol, min_amount)))
            adjusted = True
            logger.warning(
                f"[BingX] Cantidad ajustada al mínimo del exchange: {original_qty} → {qty} "
                f"(min_amount={min_amount})"
            )

        if min_notional and float(qty * price) < min_notional:
            target_qty = Decimal(str(min_notional)) / price
            qty = Decimal(str(self._client.amount_to_precision(symbol, float(target_qty))))
            adjusted = True
            logger.warning(
                f"[BingX] Cantidad ajustada por min_notional: {original_qty} → {qty} "
                f"(min_notional={min_notional} USDT)"
            )

        if adjusted:
            actual_margin = (qty * price) / Decimal(leverage)
            logger.warning(
                f"[BingX] Riesgo real será ~{actual_margin:.2f} USDT (vs {margin_usdt:.2f} USDT configurado)"
            )

        return qty

    async def open_long(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        from loguru import logger
        if not self._client.markets:
            await self._client.load_markets()
        # Round quantity to exchange precision before sending
        qty_precise = Decimal(str(self._client.amount_to_precision(symbol, float(quantity))))
        logger.info(f"[BingX] open_long: symbol={symbol}, quantity={quantity} → {qty_precise}, price={price}")
        if qty_precise <= Decimal("0"):
            raise ValueError(f"Quantity must be greater than 0, got {qty_precise}")
        if price:
            price_precise = Decimal(str(self._client.price_to_precision(symbol, float(price))))
            order = await self._client.create_limit_buy_order(
                symbol, float(qty_precise), float(price_precise), params={"positionSide": "LONG"}
            )
        else:
            order = await self._client.create_market_buy_order(
                symbol, float(qty_precise), params={"positionSide": "LONG"}
            )
        return self._parse_order(order, "long")

    async def open_short(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        from loguru import logger
        if not self._client.markets:
            await self._client.load_markets()
        # Round quantity to exchange precision before sending
        qty_precise = Decimal(str(self._client.amount_to_precision(symbol, float(quantity))))
        logger.info(f"[BingX] open_short: symbol={symbol}, quantity={quantity} → {qty_precise}, price={price}")
        if qty_precise <= Decimal("0"):
            raise ValueError(f"Quantity must be greater than 0, got {qty_precise}")
        if price:
            price_precise = Decimal(str(self._client.price_to_precision(symbol, float(price))))
            order = await self._client.create_limit_sell_order(
                symbol, float(qty_precise), float(price_precise), params={"positionSide": "SHORT"}
            )
        else:
            order = await self._client.create_market_sell_order(
                symbol, float(qty_precise), params={"positionSide": "SHORT"}
            )
        return self._parse_order(order, "short")

    async def close_position(self, symbol: str, side: str, quantity: Decimal) -> OrderResult:
        from loguru import logger
        position_side = "LONG" if side == "long" else "SHORT"
        close_side = "sell" if side == "long" else "buy"

        if not self._client.markets:
            await self._client.load_markets()

        # Obtener la cantidad real desde el exchange (safety check)
        actual_qty = await self._get_actual_position_qty(symbol, side)
        requested_qty = float(quantity)
        if actual_qty is not None and actual_qty > 0:
            # Respetar la cantidad solicitada (cierre parcial), pero nunca cerrar más de lo existente
            qty_float = min(requested_qty, actual_qty)
            logger.info(
                f"BingX close_position: requested={requested_qty}, actual={actual_qty}, "
                f"using={qty_float} (symbol={symbol}, side={side})"
            )
        else:
            qty_float = requested_qty
            logger.info(f"BingX close_position: posición no encontrada en exchange, usando qty solicitada {qty_float}")

        market = self._client.market(symbol)
        min_amount = float((market.get("limits") or {}).get("amount", {}).get("min") or 0)

        # Redondear al step size del mercado
        amount_precision = market.get("precision", {}).get("amount")
        if amount_precision:
            qty_float = float(self._client.amount_to_precision(symbol, qty_float))

        logger.info(f"BingX close_position: symbol={symbol}, side={side}, qty={qty_float}, min={min_amount}")

        if min_amount and qty_float < min_amount:
            if actual_qty and actual_qty > 0:
                # Cierre parcial es menor que el mínimo del exchange — cerrar toda la posición
                # para no dejar cantidades residuales que no se pueden cerrar
                logger.warning(
                    f"BingX: qty {qty_float} < min {min_amount}, cerrando posición completa "
                    f"actual_qty={actual_qty} en lugar de cierre parcial"
                )
                qty_float = float(self._client.amount_to_precision(symbol, actual_qty))
            else:
                logger.warning(f"BingX: qty {qty_float} < min {min_amount} y no hay posición real")
                raise ccxt.ExchangeError("Position already closed")

        try:
            if side == "long":
                order = await self._client.create_market_sell_order(
                    symbol, qty_float, params={"positionSide": position_side}
                )
            else:
                order = await self._client.create_market_buy_order(
                    symbol, qty_float, params={"positionSide": position_side}
                )
            logger.info(f"BingX close order result: {order}")
            return self._parse_order(order, side)
        except ccxt.ExchangeError as e:
            msg = str(e)
            if "No position to close" in msg or "101205" in msg:
                logger.warning(f"BingX: posición ya cerrada en exchange — {symbol}")
                raise ccxt.ExchangeError("Position already closed")
            logger.error(f"BingX close_position failed: {type(e).__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"BingX close_position failed: {type(e).__name__}: {e}")
            raise

    async def _get_actual_position_qty(self, symbol: str, side: str) -> float | None:
        """Consulta la cantidad real de la posición abierta en el exchange."""
        from loguru import logger
        try:
            positions = await self._client.fetch_positions([symbol])
            position_side = "long" if side == "long" else "short"
            for p in positions:
                if p.get("side") == position_side:
                    contracts = float(p.get("contracts") or 0)
                    if contracts > 0:
                        return contracts
            return 0.0
        except Exception as e:
            logger.warning(f"BingX _get_actual_position_qty error: {e}")
            return None

    async def place_stop_loss(self, symbol: str, side: str, quantity: Decimal, sl_price: Decimal) -> str:
        sl_order_side = "sell" if side == "long" else "buy"
        position_side = "LONG" if side == "long" else "SHORT"
        # Redondear al tick size del mercado para evitar InvalidOrder
        if not self._client.markets:
            await self._client.load_markets()
        sl_price_str = self._client.price_to_precision(symbol, float(sl_price))
        order = await self._client.create_order(
            symbol=symbol, type="STOP_MARKET", side=sl_order_side, amount=float(quantity),
            params={"stopPrice": float(sl_price_str), "positionSide": position_side},
        )
        return str(order["id"])

    async def place_take_profit(self, symbol: str, side: str, quantity: Decimal, tp_price: Decimal) -> str:
        tp_order_side = "sell" if side == "long" else "buy"
        position_side = "LONG" if side == "long" else "SHORT"
        if not self._client.markets:
            await self._client.load_markets()
        tp_price_str = self._client.price_to_precision(symbol, float(tp_price))
        # Hedge mode: BingX rejects reduceOnly on TP/SL orders.
        # positionSide is sufficient to identify which position to close.
        order = await self._client.create_order(
            symbol=symbol, type="TAKE_PROFIT_MARKET", side=tp_order_side, amount=float(quantity),
            params={"stopPrice": float(tp_price_str), "positionSide": position_side},
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
            side_raw = p.get("side") or p.get("info", {}).get("positionSide", "long")
            leverage_raw = p.get("leverage") or p.get("info", {}).get("leverage")
            result.append(OpenPosition(
                symbol=p["symbol"],
                side="long" if str(side_raw).lower() in ("long", "buy") else "short",
                entry_price=Decimal(str(entry_price or 0)),
                quantity=Decimal(str(contracts)),
                unrealized_pnl=Decimal(str(p.get("unrealizedPnl") or 0)),
                exchange_position_id=str(p.get("id") or p.get("info", {}).get("positionId") or ""),
                leverage=int(leverage_raw) if leverage_raw else None,
            ))
        return result

    async def get_candles(self, symbol: str, timeframe: str = "1h", limit: int = 200, since: int | None = None) -> list[dict]:
        ohlcv = await self._client.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        return [{"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in ohlcv]

    async def get_markets(self) -> list[str]:
        markets = await self._client.fetch_markets()
        return sorted(m["symbol"] for m in markets if m.get("type") == "swap" and m.get("active"))

    async def close(self) -> None:
        await self._client.close()

    async def get_open_orders(self) -> list[dict]:
        """Devuelve órdenes limit abiertas (pendientes de ejecución) en BingX."""
        from loguru import logger
        if not self._client.markets:
            await self._client.load_markets()
        try:
            orders = await self._client.fetch_open_orders()
            result = []
            for o in orders:
                order_type = str(o.get("type", "")).lower()
                raw_type = o.get("info", {}).get("type") or o.get("info", {}).get("orderType") or ""
                logger.info(f"BingX open order: symbol={o.get('symbol')} type={order_type} raw_type={raw_type} price={o.get('price')} side={o.get('side')} positionSide={o.get('info',{}).get('positionSide')}")
                # Solo incluir órdenes limit puras (excluir SL, TP, trigger, stop)
                if order_type != "limit":
                    continue
                pos_side = (o.get("info", {}).get("positionSide") or "LONG").upper()
                side = "long" if pos_side == "LONG" else "short"
                result.append({
                    "id": str(o.get("id", "")),
                    "symbol": o.get("symbol", ""),
                    "side": side,
                    "quantity": Decimal(str(o.get("amount") or o.get("remaining") or 0)),
                    "price": Decimal(str(o.get("price") or 0)),
                    "order_type": order_type,
                })
            logger.info(f"BingX get_open_orders: {len(result)} órdenes limit abiertas")
            return result
        except Exception as e:
            logger.warning(f"BingX get_open_orders error: {e}")
            return []

    async def get_trade_history(self, symbol=None, limit=100, since=None, extra_symbols=None):
        from loguru import logger
        from decimal import Decimal
        trades = []
        seen_ids = set()
        
        try:
            logger.info(f"BingX: Solicitando historial de trades desde {since}")
            
            if symbol:
                symbols_to_check = [symbol]
            else:
                # Obtener todos los símbolos con posiciones abiertas o recientes desde el exchange
                # directamente — no usamos una lista hardcodeada
                try:
                    if not self._client.markets:
                        await self._client.load_markets()
                    raw_positions = await self._client.fetch_positions()
                    active_symbols = {
                        p["symbol"] for p in raw_positions
                        if float(p.get("contracts") or 0) > 0
                    }
                except Exception:
                    active_symbols = set()

                # Obtener también los símbolos de órdenes recientes cerradas (sin filtro de símbolo)
                # BingX permite fetch_closed_orders sin símbolo específico
                recent_symbols = set()
                try:
                    recent_orders = await self._client.fetch_closed_orders(
                        symbol=None, since=since, limit=100
                    )
                    for o in recent_orders:
                        if o.get("symbol"):
                            recent_symbols.add(o["symbol"])
                except Exception:
                    pass

                symbols_to_check = list(active_symbols | recent_symbols)

                # Incluir símbolos extra proporcionados por el caller (p.ej. posiciones cerradas recientes)
                if extra_symbols:
                    extra_set = set(extra_symbols)
                    new_extras = extra_set - set(symbols_to_check)
                    if new_extras:
                        symbols_to_check.extend(list(new_extras))
                        logger.info(f"BingX: Añadidos {len(new_extras)} símbolos extra de posiciones cerradas recientes")

                # Si no encontramos nada (exchange vacío o error), caer en lista base
                if not symbols_to_check:
                    symbols_to_check = [
                        'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT',
                        'DOGE/USDT:USDT', 'BNB/USDT:USDT', 'AVAX/USDT:USDT', 'LINK/USDT:USDT',
                        'ARB/USDT:USDT', 'OP/USDT:USDT', 'SUI/USDT:USDT', 'APT/USDT:USDT',
                    ]

                logger.info(f"BingX: Revisando {len(symbols_to_check)} símbolos detectados automáticamente")
            
            for sym in symbols_to_check:
                try:
                    # Paginación: obtener múltiples páginas de órdenes para histórico completo
                    all_orders = []
                    page_size = 100
                    max_pages = 5  # Hasta 500 órdenes por símbolo
                    last_order_id = None
                    
                    for page in range(max_pages):
                        try:
                            params = {"limit": page_size}
                            if last_order_id:
                                params["fromId"] = last_order_id
                            
                            orders = await self._client.fetch_closed_orders(sym, since=since, limit=page_size, params=params)
                            
                            if not orders:
                                break
                            
                            all_orders.extend(orders)
                            
                            # Si recibimos menos de page_size, no hay más páginas
                            if len(orders) < page_size:
                                break
                            
                            # El último ID para la siguiente página
                            last_order_id = orders[-1].get("id")
                            
                        except Exception as e:
                            logger.debug(f"BingX: Error en página {page} de {sym}: {e}")
                            break
                    
                    # Procesar todas las órdenes obtenidas
                    for o in all_orders:
                        if o.get("status") != "closed":
                            continue
                        
                        trade_id = str(o.get("id") or "")
                        if not trade_id or trade_id in seen_ids:
                            continue
                        seen_ids.add(trade_id)
                        
                        # Verificar timestamp contra el filtro de fecha
                        timestamp = o.get("timestamp", 0)
                        if since and timestamp and timestamp < since:
                            continue  # Fuera del rango de fechas
                        
                        # Normalizar símbolo
                        sym_norm = o.get("symbol", sym)
                        if ":" not in sym_norm and "USDT" in sym_norm.upper():
                            sym_norm = f"{sym_norm}:USDT"
                        
                        # Obtener profit del campo 'profit' en info
                        info = o.get("info", {})
                        pnl = None
                        profit_val = info.get("profit")
                        if profit_val is not None:
                            try:
                                pnl_val = Decimal(str(profit_val))
                                if pnl_val != 0:
                                    pnl = pnl_val
                            except:
                                pass
                        
                        # Solo incluir trades con PnL (posiciones realmente cerradas)
                        if pnl is None:
                            continue
                        
                        # BingX positionSide indica la dirección real de la posición (LONG/SHORT)
                        # No confundir con 'side' de la orden (BUY/SELL) que es el lado de la orden de cierre
                        position_side = info.get("positionSide", "").upper()
                        if position_side == "LONG":
                            side = "long"
                        elif position_side == "SHORT":
                            side = "short"
                        else:
                            side = "long" if o.get("side") == "buy" else "short"
                        qty = Decimal(str(o.get("filled") or o.get("amount") or 0))
                        price = Decimal(str(o.get("average") or o.get("price") or 0))
                        
                        trades.append({
                            "id": trade_id, "symbol": sym_norm, "side": side, "quantity": qty,
                            "price": price, "pnl": pnl, 
                            "fee": Decimal(str(o.get("fee", {}).get("cost") or 0)),
                            "fee_asset": o.get("fee", {}).get("currency") or "USDT",
                            "timestamp": timestamp, 
                            "order_type": o.get("type", "market"),
                            "raw": info,
                        })
                        
                except Exception as e:
                    logger.debug(f"BingX: Error en {sym}: {e}")
                    continue
                    
            logger.info(f"BingX: {len(trades)} trades con PnL obtenidos")
            
        except Exception as e:
            logger.error(f"BingX get_trade_history fallo: {e}")
            
        return sorted(trades, key=lambda x: x.get("timestamp", 0), reverse=True)[:limit]

    @staticmethod
    def _parse_order(order, side):
        from loguru import logger
        logger.info(f"Parsing order: {order}")
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
            logger.error(f"Error parsing order: {e}, order={order}")
            raise
