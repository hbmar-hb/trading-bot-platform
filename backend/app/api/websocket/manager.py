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

    # ── Gestión de conexiones ─────────────────────────���───────

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)
        logger.debug(f"WS conectado: user={user_id} total={self._count()}")

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.debug(f"WS desconectado: user={user_id} total={self._count()}")

    # ── Broadcast ─────────────────────────────────────────────

    async def broadcast_to_all(self, message: dict) -> None:
        """Precio — va a todos los clientes conectados."""
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
        msg_type = data.get("type", "")

        if msg_type == "price_update":
            await self.broadcast_to_all(data)

        elif msg_type in ("position_update", "balance_update"):
            user_id = data.get("user_id")
            if user_id:
                await self.broadcast_to_user(user_id, data)

    # ── Utils ─────────────────────────────────────────────────

    def _count(self) -> int:
        return sum(len(s) for s in self._connections.values())


# Singleton — compartido entre el endpoint WS y el lifespan
ws_manager = WebSocketManager()
