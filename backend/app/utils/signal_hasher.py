"""
Genera un hash único por señal para garantizar idempotencia.

TradingView puede reintentar el envío de una alerta si no recibe 200 a tiempo.
El hash agrupa la señal en una ventana de 30 segundos para absorber esos reintentos
sin procesar la misma señal dos veces.
"""
import hashlib
import json
import uuid
from datetime import datetime


def generate_signal_hash(
    bot_id: uuid.UUID,
    action: str,
    received_at: datetime,
    price: float | None = None,
) -> str:
    """
    Genera SHA-256 de: bot_id + action + price_redondeado + ventana_30s

    Args:
        bot_id:      UUID del bot que recibe la señal
        action:      'long', 'short' o 'close'
        received_at: timestamp de recepción (con timezone)
        price:       precio del activo en el momento de la señal (opcional)

    Returns:
        String hexadecimal de 64 caracteres
    """
    # Redondear al bloque de 30 segundos para absorber reintentos de TV
    bucket_second = (received_at.second // 30) * 30
    bucket = received_at.replace(second=bucket_second, microsecond=0)

    payload = {
        "bot_id": str(bot_id),
        "action": action.strip().lower(),
        "price": round(price, 4) if price is not None else None,
        "bucket": bucket.isoformat(),
    }

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
