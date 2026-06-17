"""
Exchange de Paper Trading - Simulación de trading sin dinero real.

Implementa la misma interfaz que los exchanges reales pero todo se ejecuta
en memoria/local. Las operaciones no se envían a ningún exchange real.

Características:
- Balance ficticio inicial configurable
- Ejecución de órdenes simulada a precio de mercado
- Posiciones virtuales almacenadas en DB local
- Fees simulados (configurables)
- Slippage simulado (opcional)
"""
import asyncio
import random
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exchanges.base import BalanceInfo, BaseExchange, OpenPosition, OrderResult
from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal


class PaperExchange(BaseExchange):
    """
    Exchange simulado para Paper Trading.
    
    No requiere API keys. Las operaciones se guardan en la base de datos local.
    """

    def __init__(self, account_id: str, initial_balance: Decimal = Decimal("10000"), bot_id: str | None = None):
        """
        Args:
            account_id: ID de la cuenta paper en la base de datos
            initial_balance: Balance inicial en USDT (default: 10000)
            bot_id: UUID del bot que ejecuta la orden (para guardar en posiciones)
        """
        self.account_id = account_id
        self.bot_id = bot_id
        self._initial_balance = initial_balance
        self._fee_rate = Decimal("0.0005")  # 0.05% fee por operación (taker)
        self._slippage = Decimal("0.0001")  # 0.01% slippage simulado
        self._leverage = 1  # Se actualiza vía set_leverage() antes de cada trade

    # ── Conectividad ──────────────────────────────────────────

    async def ping(self) -> float:
        """Siempre responde inmediatamente."""
        return 1.0

    # ── Cuenta ────────────────────────────────────────────────

    async def get_equity(self) -> BalanceInfo:
        """Obtiene el balance de la cuenta paper."""
        try:
            async with AsyncSessionLocal() as db:
                balance = await self._get_or_create_balance(db)

                # Calcular unrealized PnL de posiciones abiertas
                positions = await self._get_open_positions(db)
                unrealized_pnl = Decimal("0")

                for pos in positions:
                    current_price = await self._get_market_price(pos.symbol)
                    if pos.side == "long":
                        unrealized_pnl += (current_price - pos.entry_price) * pos.quantity
                    else:
                        unrealized_pnl += (pos.entry_price - current_price) * pos.quantity

                return BalanceInfo(
                    total_equity=balance.available_balance + unrealized_pnl,
                    available_balance=balance.available_balance,
                    unrealized_pnl=unrealized_pnl,
                )
        except RuntimeError as exc:
            # Celery forked workers may inherit event-loop bound objects
            # (Redis, asyncpg connections) from the parent process.
            if "attached to a different loop" in str(exc) or "different loop" in str(exc):
                logger.warning(
                    f"[PAPER] get_equity loop mismatch for account {self.account_id}: {exc}. "
                    "Returning available balance as fallback."
                )
                # Fallback: query balance synchronously to avoid the broken loop
                from app.services.database import SessionLocal
                from sqlalchemy import select
                from app.models.paper_balance import PaperBalance

                def _sync_balance():
                    with SessionLocal() as db_sync:
                        result = db_sync.execute(
                            select(PaperBalance).where(PaperBalance.account_id == self.account_id)
                        )
                        bal = result.scalar_one_or_none()
                        if bal:
                            return Decimal(str(bal.available_balance))
                        return self._initial_balance

                available = await asyncio.to_thread(_sync_balance)
                return BalanceInfo(
                    total_equity=available,
                    available_balance=available,
                    unrealized_pnl=Decimal("0"),
                )
            raise

    # ── Precio ────────────────────────────────────────────────

    async def get_price(self, symbol: str) -> Decimal:
        """Obtiene precio de mercado simulado (usa el precio real del exchange)."""
        return await self._get_market_price(symbol)

    # ── Apalancamiento ────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int, side: str | None = None) -> None:
        """Paper trading: almacena leverage para usarlo en el cálculo de margen."""
        self._leverage = leverage
        logger.debug(f"[PAPER] Set leverage {symbol} x{leverage} (simulado)")

    # ── Órdenes de entrada ────────────────────────────────────

    async def open_long(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        """Abre posición larga simulada. El precio se usa si se proporciona (limit)."""
        return await self._open_position(symbol, "long", quantity, price)

    async def open_short(self, symbol: str, quantity: Decimal, price: Decimal | None = None) -> OrderResult:
        """Abre posición corta simulada. El precio se usa si se proporciona (limit)."""
        return await self._open_position(symbol, "short", quantity, price)

    # ── Cierre ────────────────────────────────────────────────

    async def close_position(
        self, symbol: str, side: str, quantity: Decimal
    ) -> OrderResult:
        """Cierra posición simulada."""
        async with AsyncSessionLocal() as db:
            # Buscar posición abierta
            position = await self._find_position(db, symbol, side)
            if not position:
                raise ValueError(f"No hay posición abierta en {symbol} {side}")
            
            # Precio de cierre con slippage simulado
            market_price = await self._get_market_price(symbol)
            close_price = self._apply_slippage(market_price, side, "close")
            
            # Calcular PnL
            if side == "long":
                pnl = (close_price - position.entry_price) * quantity
            else:
                pnl = (position.entry_price - close_price) * quantity
            
            # Calcular fee
            fee = close_price * quantity * self._fee_rate
            
            # Actualizar balance
            balance = await self._get_or_create_balance(db)
            balance.available_balance += (close_price * quantity) - fee + pnl
            
            # Cerrar o reducir posición
            if quantity >= position.quantity:
                # Cerrar completa
                position.status = "closed"
                position.closed_at = datetime.now(timezone.utc)
                position.realized_pnl = pnl
            else:
                # Cerrar parcial
                position.quantity -= quantity
            
            await db.commit()
            
            logger.info(
                f"[PAPER] Cerrada posición {side} {symbol} @ {close_price} "
                f"PnL={pnl:.2f} fee={fee:.2f}"
            )
            
            return OrderResult(
                order_id=f"paper_close_{uuid.uuid4().hex[:12]}",
                symbol=symbol,
                side=side,
                quantity=quantity,
                fill_price=close_price,
            )

    # ── Stop Loss ─────────────────────────────────────────────

    async def place_stop_loss(
        self, symbol: str, side: str, quantity: Decimal, sl_price: Decimal
    ) -> str:
        """Paper trading: guarda el SL en la posición para simulación."""
        async with AsyncSessionLocal() as db:
            position = await self._find_position(db, symbol, side)
            if position:
                position.current_sl_price = sl_price
                await db.commit()
            
            order_id = f"paper_sl_{uuid.uuid4().hex[:12]}"
            logger.debug(f"[PAPER] SL colocado {symbol} {side} @ {sl_price}")
            return order_id

    async def place_take_profit(
        self, symbol: str, side: str, quantity: Decimal, tp_price: Decimal
    ) -> str:
        """Paper trading: registra el TP sin enviar al exchange."""
        order_id = f"paper_tp_{uuid.uuid4().hex[:12]}"
        logger.debug(f"[PAPER] TP colocado {symbol} {side} @ {tp_price} id={order_id}")
        return order_id

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Paper trading: siempre devuelve True (no hay órdenes reales)."""
        logger.debug(f"[PAPER] Cancelada orden {order_id}")
        return True

    # ── Reconciliación ────────────────────────────────────────

    async def get_open_positions(self) -> list[OpenPosition]:
        """Devuelve posiciones abiertas simuladas."""
        async with AsyncSessionLocal() as db:
            db_positions = await self._get_open_positions(db)
            return [
                OpenPosition(
                    symbol=p.symbol,
                    side=p.side,
                    entry_price=p.entry_price,
                    quantity=p.quantity,
                    unrealized_pnl=Decimal("0"),  # Se calcula en tiempo real
                    exchange_position_id=f"paper_{p.id}",
                    leverage=p.leverage,
                )
                for p in db_positions
            ]

    # ── Lifecycle ─────────────────────────────────────────────

    async def close(self) -> None:
        """No requiere cleanup."""
        pass

    # ─── Métodos privados ─────────────────────────────────────

    async def _get_market_price(self, symbol: str) -> Decimal:
        """Obtiene precio de mercado real para simulación realista."""
        from app.services.cache import get_price

        # 1. Intentar desde Redis (precio en tiempo real del price monitor)
        price = await get_price(symbol)
        if price:
            return Decimal(str(price))

        # 2. Fallback: consultar BingX público (sin credenciales)
        import ccxt.async_support as ccxt
        from loguru import logger
        client = ccxt.bingx({"options": {"defaultType": "swap"}})
        try:
            ticker = await client.fetch_ticker(symbol)
            fetched = Decimal(str(ticker["last"]))
            logger.debug(f"[PAPER] Precio de mercado para {symbol} obtenido de BingX: {fetched}")
            return fetched
        except Exception as e:
            raise ValueError(f"Precio no disponible para {symbol}: {e}")
        finally:
            await client.close()

    async def _open_position(
        self, symbol: str, side: str, quantity: Decimal, limit_price: Decimal | None = None
    ) -> OrderResult:
        """Lógica común para abrir posiciones. Si limit_price se proporciona, se usa ese precio."""
        async with AsyncSessionLocal() as db:
            # Verificar balance disponible
            balance = await self._get_or_create_balance(db)
            
            # Precio de entrada
            if limit_price:
                # Orden limit: usar el precio especificado (sin slippage)
                entry_price = limit_price
            else:
                # Orden de mercado: precio actual con slippage
                market_price = await self._get_market_price(symbol)
                entry_price = self._apply_slippage(market_price, side, "open")
            
            # Calcular margen requerido respetando el apalancamiento real del bot
            notional = entry_price * quantity
            fee = notional * self._fee_rate
            # FIX FASE 1C: El margen real es notional / leverage
            # Antes: required = notional + fee (ignoraba leverage completamente)
            leverage = getattr(self, '_leverage', 1) or 1
            required = (notional / Decimal(leverage)) + fee
            
            if balance.available_balance < required:
                raise ValueError(
                    f"Balance insuficiente. Disponible: {balance.available_balance}, "
                    f"Requerido: {required}"
                )
            
            # Descontar del balance
            balance.available_balance -= required
            
            await db.commit()
            
            logger.info(
                f"[PAPER] Posición creada {side} {symbol} qty={quantity} "
                f"@ {entry_price} fee={fee:.2f}"
            )
            
            return OrderResult(
                order_id=f"paper_{uuid.uuid4().hex[:12]}",
                symbol=symbol,
                side=side,
                quantity=quantity,
                fill_price=entry_price,
            )

    def _apply_slippage(
        self, price: Decimal, side: str, action: str
    ) -> Decimal:
        """Aplica slippage simulado al precio."""
        slippage = price * self._slippage
        
        # Slippage desfavorable (pagas más en compra, recibes menos en venta)
        if (side == "long" and action == "open") or (side == "short" and action == "close"):
            return price + slippage  # Compra más caro
        else:
            return price - slippage  # Venta más barato

    async def _get_or_create_balance(self, db: AsyncSession):
        """Obtiene o crea el balance de la cuenta paper."""
        from app.models.paper_balance import PaperBalance
        import uuid as _uuid
        
        # 1. Buscar por account_id (string)
        result = await db.execute(
            select(PaperBalance).where(PaperBalance.account_id == self.account_id)
        )
        balance = result.scalar_one_or_none()
        
        # 2. Fallback: buscar por id (UUID) — útil cuando account_id es el UUID
        if not balance:
            try:
                uid = _uuid.UUID(self.account_id)
                result = await db.execute(
                    select(PaperBalance).where(PaperBalance.id == uid)
                )
                balance = result.scalar_one_or_none()
            except ValueError:
                pass
        
        if not balance:
            balance = PaperBalance(
                account_id=self.account_id,
                available_balance=self._initial_balance,
                total_equity=self._initial_balance,
            )
            db.add(balance)
            await db.commit()
            logger.info(f"[PAPER] Creada cuenta con balance inicial {self._initial_balance}")
        
        return balance

    async def _paper_balance_uuid(self, db: AsyncSession) -> uuid.UUID:
        """Convierte account_id a UUID para queries con BotConfig.paper_balance_id."""
        try:
            return uuid.UUID(self.account_id)
        except ValueError:
            from app.models.paper_balance import PaperBalance
            result = await db.execute(
                select(PaperBalance).where(PaperBalance.account_id == self.account_id)
            )
            pb = result.scalar_one_or_none()
            if pb:
                return pb.id
            raise ValueError(f"Cannot resolve paper_balance UUID for account_id={self.account_id}")

    async def _get_open_positions(self, db: AsyncSession):
        """Obtiene posiciones abiertas de esta cuenta paper."""
        from app.models.position import Position
        from app.models.bot_config import BotConfig
        
        result = await db.execute(
            select(Position)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(
                Position.exchange == "paper",
                Position.status == "open",
                BotConfig.paper_balance_id == await self._paper_balance_uuid(db),
            )
        )
        return result.scalars().all()

    async def _find_position(self, db: AsyncSession, symbol: str, side: str):
        """Busca posición abierta por símbolo y lado."""
        from app.models.position import Position
        from app.models.bot_config import BotConfig
        
        result = await db.execute(
            select(Position)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(
                Position.exchange == "paper",
                Position.symbol == symbol,
                Position.side == side,
                Position.status == "open",
                BotConfig.paper_balance_id == await self._paper_balance_uuid(db),
            )
        )
        return result.scalar_one_or_none()
