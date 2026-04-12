"""
Endpoint WebSocket para actualizaciones en tiempo real.

El token JWT se pasa como query param porque los WebSockets
no soportan el header Authorization de forma estándar.

Uso desde el frontend:
  const ws = new WebSocket(`ws://localhost:8000/ws?token=<access_token>`)
"""
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt

from app.api.websocket.manager import ws_manager
from config.settings import settings

router = APIRouter(tags=["websocket"])


def _get_user_id_from_token(token: str) -> uuid.UUID | None:
    """Valida el JWT y devuelve el user_id, o None si es inválido."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        sub = payload.get("sub")
        return uuid.UUID(sub) if sub else None
    except (JWTError, ValueError):
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    # Autenticar antes de aceptar la conexión
    user_id = _get_user_id_from_token(token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id_str = str(user_id)
    await ws_manager.connect(websocket, user_id_str)

    try:
        # Mantener la conexión viva recibiendo mensajes del cliente
        # (el cliente puede enviar pings o comandos en el futuro)
        while True:
            data = await websocket.receive_text()
            # Por ahora ignoramos mensajes entrantes del cliente
            # Futuro: suscripción a símbolos específicos
            _ = data

    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket, user_id_str)
