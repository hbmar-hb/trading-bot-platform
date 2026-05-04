"""
Conector Bitunix - Implementación con nonce correcto (32 bits = 8 chars hex).
"""
import hashlib
import json
import secrets
import time
from decimal import Decimal

import httpx

from app.exchanges.base import BalanceInfo, BaseExchange, OpenPosition, OrderResult


class BitunixExchange(BaseExchange):
    """
    Conector Bitunix usando formato correcto según documentación oficial.
    Nonce: 32 bits = 4 bytes = 8 caracteres hexadecimales
    """

    BASE_URL = "https://fapi.bitunix.com"

    def __init__(self, api_key: str, secret: str, testnet: bool = False):
        self._api_key = api_key
        self._secret = secret
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=15.0,
            headers={"Content-Type": "application/json"}
        )

    def _generate_nonce(self) -> str:
        """
        Genera nonce de 32 bits (4 bytes = 8 caracteres hex).
        Documentación: "cadena aleatoria de exactamente 32 bits"
        """
        # 32 bits = 4 bytes = 8 caracteres hexadecimales
        return secrets.token_hex(4)  # 4 bytes = 8 chars hex

    def _sign(self, nonce: str, timestamp: str, query_params: str, body: str) -> str:
        """
        Firma según documentación:
        1. digest = SHA256(nonce + timestamp + api-key + queryParams + body)
        2. sign = SHA256(digest + secretKey)
        """
        # Paso 3: Crear digest
        digest_input = nonce + timestamp + self._api_key + query_params + body
        digest = hashlib.sha256(digest_input.encode('utf-8')).hexdigest()
        
        # Paso 4: Crear firma final
        sign_input = digest + self._secret
        return hashlib.sha256(sign_input.encode('utf-8')).hexdigest()

    async def _request(self, method: str, path: str, params: dict = None, body: dict = None) -> dict:
        """Realiza petición autenticada."""
        from loguru import logger
        
        # Generar nonce (8 chars hex = 32 bits) y timestamp
        nonce = self._generate_nonce()
        timestamp = str(int(time.time() * 1000))
        
        # Preparar query params ordenados alfabéticamente
        query_params = ""
        if params:
            sorted_params = sorted(params.items())
            query_params = "&".join([f"{k}={v}" for k, v in sorted_params])
        
        # Preparar body (JSON sin espacios)
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        
        # Generar firma
        signature = self._sign(nonce, timestamp, query_params, body_str)
        
        # Headers
        headers = {
            "api-key": self._api_key,
            "sign": signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "Content-Type": "application/json",
        }
        
        logger.info("=" * 60)
        logger.info(f"[BITUNIX] {method} {path}")
        logger.info(f"[BITUNIX] Nonce (8 chars): {nonce}")
        logger.info(f"[BITUNIX] Timestamp: {timestamp}")
        logger.info(f"[BITUNIX] Query params: '{query_params}'")
        logger.info(f"[BITUNIX] Body: '{body_str[:100]}'")
        logger.info(f"[BITUNIX] Sign: {signature[:50]}...")
        
        try:
            if method.upper() == "GET":
                resp = await self._client.get(path, headers=headers, params=params)
            else:
                resp = await self._client.post(path, headers=headers, content=body_str)
            
            text = resp.text
            logger.info(f"[BITUNIX] Status: {resp.status_code}")
            logger.info(f"[BITUNIX] Response: {text[:500]}")
            
            try:
                return json.loads(text) if text else {}
            except:
                return {"raw": text}
            
        except Exception as e:
            logger.error(f"[BITUNIX] Error: {type(e).__name__}: {str(e)[:200]}")
            raise

    async def verify_credentials(self) -> dict:
        """Verifica credenciales."""
        from loguru import logger
        
        logger.info("=" * 70)
        logger.info("BITUNIX VERIFICATION - NONCE 32 BITS (8 chars)")
        logger.info("=" * 70)
        
        tests = [
            ("GET", "api/v1/futures/account", None, None),
            ("POST", "api/v1/futures/account/change_margin_mode", None, {"symbol": "BTCUSDT", "marginMode": "ISOLATED", "marginCoin": "USDT"}),
        ]
        
        for method, path, params, body in tests:
            try:
                logger.info(f"\n[TEST] {method} {path}")
                result = await self._request(method, path, params=params, body=body)
                
                code = result.get("code")
                msg = result.get("msg", "")
                
                logger.info(f"[TEST] Result code: {code}, msg: {msg}")
                
                if code == 0:
                    return {
                        "success": True,
                        "message": "Conexión exitosa",
                        "data": result.get("data"),
                    }
                    
            except Exception as e:
                logger.error(f"[TEST] Error: {str(e)[:200]}")
        
        return {
            "success": False,
            "error": "Failed",
            "message": "No se pudo conectar. Revisa los logs.",
        }

    async def ping(self) -> float:
        import time as time_module
        start = time_module.monotonic()
        try:
            await self._request("GET", "api/v1/time")
        except:
            pass
        return (time_module.monotonic() - start) * 1000

    async def get_equity(self) -> BalanceInfo:
        result = await self._request("GET", "api/v1/futures/account")
        data = result.get("data", {})
        if isinstance(data, list) and data:
            data = data[0]
        return BalanceInfo(
            total_equity=Decimal(str(data.get("equity", 0))),
            available_balance=Decimal(str(data.get("availableBalance", 0))),
            unrealized_pnl=Decimal(str(data.get("unrealizedPnL", 0))),
        )

    async def get_price(self, symbol: str) -> Decimal:
        result = await self._request("GET", "api/v1/futures/market/ticker", params={"symbol": symbol})
        data = result.get("data", {})
        if isinstance(data, list) and data:
            data = data[0]
        return Decimal(str(data.get("last", 0)))

    async def set_leverage(self, symbol: str, leverage: int, side: str = None) -> None:
        await self._request("POST", "api/v1/futures/account/change_leverage", 
                           body={"symbol": symbol, "leverage": leverage})

    async def open_long(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        # TODO: Implementar soporte para órdenes limit en Bitunix
        return await self._place_order(symbol, "BUY", quantity, "long")

    async def open_short(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        # TODO: Implementar soporte para órdenes limit en Bitunix
        return await self._place_order(symbol, "SELL", quantity, "short")

    async def close_position(self, symbol: str, side: str, quantity: Decimal) -> OrderResult:
        close_side = "SELL" if side == "long" else "BUY"
        return await self._place_order(symbol, close_side, quantity, side, reduce_only=True)

    async def _place_order(self, symbol: str, side: str, quantity: Decimal, position_side: str, reduce_only: bool = False) -> OrderResult:
        body = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": str(quantity),
        }
        if reduce_only:
            body["reduceOnly"] = True
        
        result = await self._request("POST", "api/v1/futures/order", body=body)
        order = result.get("data", {})
        
        return OrderResult(
            order_id=str(order.get("orderId", "")),
            symbol=symbol,
            side=position_side,
            quantity=Decimal(str(order.get("executedQty", quantity))),
            fill_price=Decimal(str(order.get("avgPrice", 0))),
        )

    async def place_stop_loss(self, symbol: str, side: str, quantity: Decimal, sl_price: Decimal) -> str:
        sl_side = "SELL" if side == "long" else "BUY"
        body = {
            "symbol": symbol,
            "side": sl_side.upper(),
            "type": "STOP_MARKET",
            "stopPrice": str(sl_price),
            "quantity": str(quantity),
            "reduceOnly": True,
        }
        result = await self._request("POST", "api/v1/futures/order", body=body)
        return str(result.get("data", {}).get("orderId", ""))

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            await self._request("POST", "api/v1/futures/order/cancel", 
                               body={"symbol": symbol, "orderId": order_id})
            return True
        except:
            return False

    async def get_open_positions(self) -> list[OpenPosition]:
        result = await self._request("GET", "api/v1/futures/positions")
        positions = result.get("data", [])
        if not isinstance(positions, list):
            return []
        
        result_list = []
        for p in positions:
            qty = Decimal(str(p.get("positionAmt", 0)))
            if qty == 0:
                continue
            
            side_str = p.get("positionSide", "").upper()
            if side_str in ["LONG", "BUY"]:
                side = "long"
            elif side_str in ["SHORT", "SELL"]:
                side = "short"
            else:
                side = "long" if qty > 0 else "short"
                qty = abs(qty)
            
            result_list.append(OpenPosition(
                symbol=p.get("symbol", ""),
                side=side,
                entry_price=Decimal(str(p.get("entryPrice", 0))),
                quantity=qty,
                unrealized_pnl=Decimal(str(p.get("unrealizedPnL", 0))),
                exchange_position_id=str(p.get("positionId", "")),
            ))
        
        return result_list

    async def close(self) -> None:
        await self._client.aclose()
