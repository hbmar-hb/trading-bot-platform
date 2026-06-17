"""
Gestor de conexiones WebSocket + listener de Redis pub/sub.

Arquitectura:
  - Clientes conectados: dict[user_id → set[WebSocket]]
  - Redis listener: tarea asyncio que escucha price_updates,
    position_updates y balance_updates, y hace broadcast a los clientes

Mensajes que el frontend recibe:
  {type: "price_update",    symbol, price, timestamp}
  {type: "position_update", user_id, position_id, ...}
  {type: "balance_update",  account_id, total_equity, ...}
"""
import asyncio
import json

from fastapi import WebSocket
from loguru import logger


class WebSocketManager:

    def __init__(self):
        # user_id (str) → conjunto de websockets activos
        self._connections: dict[str, set[WebSocket]] = {}
        # symbol (str) → conjunto de websockets suscritos a ese símbolo
        self._symbol_subs: dict[str, set[WebSocket]] = {}
        # websocket → set de símbolos suscritos (para cleanup en disconnect)
        self._ws_symbols: dict[WebSocket, set[str]] = {}

    # ── Gestión de conexiones ─────────────────────────────────

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        # websocket.accept() is already called by the route handler (ws.py)
        self._connections.setdefault(user_id, set()).add(websocket)
        logger.debug(f"WS conectado: user={user_id} total={self._count()}")

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        # Limpiar índice por usuario
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]

        # Limpiar suscripciones por símbolo
        symbols = self._ws_symbols.pop(websocket, set())
        for symbol in symbols:
            if symbol in self._symbol_subs:
                self._symbol_subs[symbol].discard(websocket)
                if not self._symbol_subs[symbol]:
                    del self._symbol_subs[symbol]

        logger.debug(f"WS desconectado: user={user_id} total={self._count()}")

    # ── Suscripciones por símbolo ─────────────────────────────

    def subscribe_symbols(self, websocket: WebSocket, symbols: list[str]) -> None:
        """Suscribe un websocket a updates de precio de los símbolos dados."""
        current = self._ws_symbols.setdefault(websocket, set())
        for symbol in symbols:
            if symbol not in current:
                current.add(symbol)
                self._symbol_subs.setdefault(symbol, set()).add(websocket)
        logger.debug(f"WS suscrito a {len(symbols)} símbolos")

    def unsubscribe_symbols(self, websocket: WebSocket, symbols: list[str]) -> None:
        """Desuscribe un websocket de los símbolos dados."""
        current = self._ws_symbols.get(websocket, set())
        for symbol in symbols:
            current.discard(symbol)
            if symbol in self._symbol_subs:
                self._symbol_subs[symbol].discard(websocket)
                if not self._symbol_subs[symbol]:
                    del self._symbol_subs[symbol]

    def get_user_symbols(self, user_id: str) -> list[str]:
        """Devuelve los símbolos activos de un usuario desde la base de datos."""
        # Nota: este método se usa de forma sincrónica en el contexto async,
        # por lo que la query debe hacerse en el endpoint y pasarse aquí.
        return []

    # ── Broadcast ─────────────────────────────────────────────

    async def broadcast_price(self, symbol: str, message: dict) -> None:
        """Precio — solo a los clientes suscritos a ese símbolo. O(1) lookup."""
        subscribers = self._symbol_subs.get(symbol)
        if not subscribers:
            return

        dead: list[WebSocket] = []
        for ws in list(subscribers):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            # Limpiar de todos los índices
            self._cleanup_ws(ws)

    async def broadcast_to_all(self, message: dict) -> None:
        """Mensajes globales — va a todos los clientes conectados."""
        dead: list[tuple[str, WebSocket]] = []

        for user_id, sockets in list(self._connections.items()):
            for ws in list(sockets):
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append((user_id, ws))

        for user_id, ws in dead:
            self.disconnect(ws, user_id)

    async def broadcast_to_user(self, user_id: str, message: dict) -> None:
        """Posición / balance — solo al usuario propietario."""
        dead: list[WebSocket] = []

        for ws in list(self._connections.get(user_id, set())):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, user_id)

    async def broadcast_chat_message(self, message: dict, target_user_ids: set[str] | None = None) -> None:
        """Chat — si target_user_ids es None, va a todos (sala pública). Si es un set, solo a esos usuarios."""
        dead: list[tuple[str, WebSocket]] = []

        for user_id, sockets in list(self._connections.items()):
            if target_user_ids is not None and user_id not in target_user_ids:
                continue
            for ws in list(sockets):
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append((user_id, ws))

        for user_id, ws in dead:
            self.disconnect(ws, user_id)

    # ── Redis listener ────────────────────────────────────────

    async def start_redis_listener(self) -> None:
        """
        Tarea asyncio de larga duración.
        Escucha los canales Redis y hace forward a los clientes WS.
        Iniciar en el lifespan de FastAPI.
        """
        import redis.asyncio as aioredis
        from config.settings import settings

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        logger.info("WebSocketManager: Redis listener arrancado")

        try:
            async with r.pubsub() as pubsub:
                await pubsub.subscribe(
                    "price_updates",
                    "position_updates",
                    "balance_updates",
                    "notification_updates",
                )
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        await self._dispatch(data)
                    except Exception as exc:
                        logger.debug(f"WS listener error: {exc}")
        except asyncio.CancelledError:
            logger.info("WebSocketManager: Redis listener detenido")
        finally:
            await r.aclose()

    async def _dispatch(self, data: dict) -> None:
        from app.services.cache import verify_redis_message

        if not verify_redis_message(data):
            logger.warning("WS listener: mensaje Redis con firma inválida descartado")
            return

        msg_type = data.get("type", "")

        if msg_type == "price_update":
            symbol = data.get("symbol")
            if symbol:
                await self.broadcast_price(symbol, data)
            else:
                # Fallback si no hay symbol (no debería pasar)
                await self.broadcast_to_all(data)

        elif msg_type in ("position_update", "balance_update", "notification"):
            user_id = data.get("user_id")
            if user_id:
                await self.broadcast_to_user(user_id, data)

    # ── Utils ─────────────────────────────────────────────────

    def _count(self) -> int:
        return sum(len(s) for s in self._connections.values())

    def get_online_user_ids(self) -> set[str]:
        """Devuelve los IDs de usuario que tienen al menos una conexión WS activa."""
        return set(self._connections.keys())

    def _cleanup_ws(self, websocket: WebSocket) -> None:
        """Elimina un websocket de todos los índices sin duplicar lógica."""
        # Encontrar user_id
        user_id: str | None = None
        for uid, sockets in list(self._connections.items()):
            if websocket in sockets:
                user_id = uid
                break
        if user_id:
            self.disconnect(websocket, user_id)
        else:
            # Fallback: limpiar solo suscripciones por símbolo
            symbols = self._ws_symbols.pop(websocket, set())
            for symbol in symbols:
                if symbol in self._symbol_subs:
                    self._symbol_subs[symbol].discard(websocket)
                    if not self._symbol_subs[symbol]:
                        del self._symbol_subs[symbol]


# Singleton — compartido entre el endpoint WS y el lifespan
ws_manager = WebSocketManager()
