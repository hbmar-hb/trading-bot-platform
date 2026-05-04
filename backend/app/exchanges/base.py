"""
Interfaz abstracta que todos los exchanges deben implementar.
Añadir un exchange nuevo = crear una clase que herede de BaseExchange
y registrarla en factory.py.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


# ─── Tipos de datos de retorno ────────────────────────────────

@dataclass
class BalanceInfo:
    total_equity: Decimal
    available_balance: Decimal
    unrealized_pnl: Decimal = Decimal("0")


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str           # 'long' | 'short'
    quantity: Decimal
    fill_price: Decimal
    sl_order_id: str | None = None


@dataclass
class OpenPosition:
    """Snapshot de posición activa — usado por el reconciler al arrancar."""
    symbol: str
    side: str           # 'long' | 'short'
    entry_price: Decimal
    quantity: Decimal
    unrealized_pnl: Decimal
    exchange_position_id: str = ""


# ─── Interfaz abstracta ───────────────────────────────────────

class BaseExchange(ABC):
    """
    Todos los métodos son async.
    El caller es responsable de cerrar la sesión llamando a close().
    """

    # ── Conectividad ──────────────────────────────────────────

    @abstractmethod
    async def ping(self) -> float:
        """
        Verifica conectividad.
        Devuelve latencia en ms. Lanza excepción si no hay conexión.
        """

    # ── Cuenta ────────────────────────────────────────────────

    @abstractmethod
    async def get_equity(self) -> BalanceInfo:
        """Equity de la cuenta en USDT (para position sizing)."""

    # ── Precio ────────────────────────────────────────────────

    @abstractmethod
    async def get_price(self, symbol: str) -> Decimal:
        """Último precio de mercado del símbolo."""

    # ── Apalancamiento ────────────────────────────────────────

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int, side: str | None = None) -> None:
        """Configura el apalancamiento antes de abrir posición."""

    # ── Órdenes de entrada ────────────────────────────────────

    @abstractmethod
    async def open_long(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        """
        Abre posición larga.
        Si price es None → orden de mercado.
        Si price se proporciona → orden limit.
        """

    @abstractmethod
    async def open_short(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        """
        Abre posición corta.
        Si price es None → orden de mercado.
        Si price se proporciona → orden limit.
        """

    # ── Cierre de posición ────────────────────────────────────

    @abstractmethod
    async def close_position(
        self, symbol: str, side: str, quantity: Decimal
    ) -> OrderResult:
        """Cierra total o parcialmente una posición a precio de mercado."""

    # ── Stop Loss ─────────────────────────────────────────────

    @abstractmethod
    async def place_stop_loss(
        self, symbol: str, side: str, quantity: Decimal, sl_price: Decimal
    ) -> str:
        """
        Coloca una orden de stop loss.
        Devuelve el order_id del SL en el exchange.
        """

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancela una orden. Devuelve True si se canceló correctamente."""

    async def modify_stop_loss(
        self, symbol: str, side: str, quantity: Decimal,
        old_order_id: str, new_sl_price: Decimal
    ) -> str:
        """
        Modifica el precio de un SL existente.
        Implementación por defecto: cancela y re-crea (compatible con todos los exchanges).
        Los exchanges que soportan modificación directa pueden sobreescribir este método.
        Devuelve el nuevo order_id.
        """
        await self.cancel_order(symbol, old_order_id)
        return await self.place_stop_loss(symbol, side, quantity, new_sl_price)

    # ── Reconciliación ────────────────────────────────────────

    @abstractmethod
    async def get_open_positions(self) -> list[OpenPosition]:
        """Lista de posiciones abiertas (usado por reconciler al arrancar)."""

    # ── Utilidades ────────────────────────────────────────────

    async def calculate_quantity(
        self,
        symbol: str,
        equity: Decimal,
        sizing_type: str,   # 'percentage' | 'fixed'
        sizing_value: Decimal,
        leverage: int,
    ) -> Decimal:
        """
        Calcula la cantidad de contratos a abrir.

        percentage: sizing_value = % del equity (e.g. 2.0 → 2%)
        fixed:      sizing_value = USDT fijos a usar como margen
        """
        price = await self.get_price(symbol)

        if sizing_type == "percentage":
            margin_usdt = equity * (sizing_value / Decimal("100"))
        else:
            margin_usdt = sizing_value

        notional = margin_usdt * Decimal(leverage)
        # Truncar a 3 decimales para evitar problemas de precisión
        return (notional / price).quantize(Decimal("0.001"))

    async def get_markets(self) -> list[str]:
        """
        Lista de símbolos de futuros perpetuos disponibles.
        Implementación por defecto vacía — los exchanges pueden sobreescribir.
        """
        return []

    async def get_candles(
        self, symbol: str, timeframe: str = "1h", limit: int = 200
    ) -> list[dict]:
        """
        Velas OHLCV para el símbolo y timeframe indicados.
        Devuelve lista de {time, open, high, low, close, volume}
        donde time es Unix timestamp en segundos.
        Los exchanges deben sobreescribir este método.
        """
        raise NotImplementedError(f"get_candles no implementado para {type(self).__name__}")

    @abstractmethod
    async def close(self) -> None:
        """Cierra la sesión / conexión del cliente."""

    # ── Historial de trades ───────────────────────────────────

    async def get_open_orders(self) -> list[dict]:
        """
        Lista de órdenes limit abiertas (pendientes de ejecución).
        Devuelve lista de dicts con: id, symbol, side, quantity, price, order_type
        Implementación por defecto vacía — los exchanges pueden sobreescribir.
        """
        return []

    async def get_trade_history(
        self, symbol: str | None = None, limit: int = 100, since: int | None = None
    ) -> list[dict]:
        """
        Historial de trades ejecutados (fills/orders cerrados).
        Devuelve lista de dicts con:
        - id: str (ID del trade en el exchange)
        - symbol: str
        - side: 'long' | 'short'
        - quantity: Decimal
        - price: Decimal
        - pnl: Decimal | None
        - fee: Decimal
        - fee_asset: str
        - timestamp: int (ms)
        - order_type: str
        
        Implementación por defecto vacía — los exchanges deben sobreescribir.
        """
        return []
