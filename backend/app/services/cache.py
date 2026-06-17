"""
Cliente Redis centralizado.

- async_redis: para FastAPI / workers asyncio
- sync_redis:  para Celery tasks (síncronas)

Canales pub/sub:
  price_updates     → {type, symbol, price, timestamp}
  position_updates  → {type, user_id, position_id, ...}
  balance_updates   → {type, account_id, total_equity, ...}
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone

import redis
import redis.asyncio as aioredis

from config.settings import settings


def _sign_message(data: dict) -> str:
    """Firma un mensaje dict con HMAC-SHA256 usando ENCRYPTION_KEY."""
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hmac.new(settings.encryption_key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_redis_message(data: dict) -> bool:
    """Verifica la firma HMAC de un mensaje Redis."""
    expected_sig = data.pop("sig", None)
    if not expected_sig:
        return False
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    computed = hmac.new(settings.encryption_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, computed)

# ─── Clientes ────────────────────────────────────────────────

async_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
sync_redis  = redis.from_url(settings.redis_url, decode_responses=True)

# ─── TTLs ────────────────────────────────────────────────────
PRICE_TTL   = 10    # 10 s — precio stale si price_monitor falla
BALANCE_TTL = 120   # 2 min

# ─── Precios ─────────────────────────────────────────────────

async def get_price(symbol: str) -> float | None:
    val = await async_redis.get(f"price:{symbol}")
    return float(val) if val else None


async def get_price_change(symbol: str) -> float | None:
    """Obtiene el cambio porcentual 24h del símbolo."""
    val = await async_redis.get(f"price_change:{symbol}")
    return float(val) if val else None


async def set_price(symbol: str, price: float, change_24h: float = 0.0) -> None:
    await async_redis.setex(f"price:{symbol}", PRICE_TTL, str(price))
    await async_redis.setex(f"price_change:{symbol}", PRICE_TTL, str(change_24h))
    msg = {
        "type":      "price_update",
        "symbol":    symbol,
        "price":     price,
        "change_24h": change_24h,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    msg["sig"] = _sign_message(msg)
    await async_redis.publish("price_updates", json.dumps(msg))


# ─── Balances ────────────────────────────────────────────────

async def get_balance(account_id: str) -> dict | None:
    val = await async_redis.get(f"balance:{account_id}")
    return json.loads(val) if val else None


async def set_balance(account_id: str, total_equity: float, available: float) -> None:
    data = {"total_equity": total_equity, "available_balance": available}
    await async_redis.setex(f"balance:{account_id}", BALANCE_TTL, json.dumps(data))
    msg = {
        "type":       "balance_update",
        "account_id": account_id,
        **data,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }
    msg["sig"] = _sign_message(msg)
    await async_redis.publish("balance_updates", json.dumps(msg))


# ─── Estado de salud de exchanges ────────────────────────────

async def set_exchange_health(exchange: str, status: str) -> None:
    await async_redis.setex(f"health:{exchange}", 360, status)


def set_exchange_health_sync(exchange: str, status: str) -> None:
    sync_redis.setex(f"health:{exchange}", 360, status)


async def get_exchange_health(exchange: str) -> str | None:
    return await async_redis.get(f"health:{exchange}")


# ─── Publish desde FastAPI (async) ───────────────────────────

async def publish_position_update(user_id: str, position_data: dict) -> None:
    """Usado desde rutas FastAPI (contexto async)."""
    msg = {
        "type":    "position_update",
        "user_id": user_id,
        **position_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    msg["sig"] = _sign_message(msg)
    await async_redis.publish("position_updates", json.dumps(msg))


# ─── Publish desde Celery (sync) ─────────────────────────────

def publish_position_update_sync(user_id: str, position_data: dict) -> None:
    """Usado desde tasks Celery (contexto síncrono)."""
    msg = {
        "type":    "position_update",
        "user_id": user_id,
        **position_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    msg["sig"] = _sign_message(msg)
    sync_redis.publish("position_updates", json.dumps(msg))


# �"?�"?�"? Notificaciones in-app �"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?

def publish_notification_sync(user_id: str, notification_data: dict) -> None:
    """Publica una notificación in-app vía Redis para entregar por WebSocket."""
    msg = {
        "type": "notification",
        "user_id": user_id,
        **notification_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    msg["sig"] = _sign_message(msg)
    sync_redis.publish("notification_updates", json.dumps(msg))


# Tokens temporales (password reset / email verification)

RESET_TOKEN_TTL = 172800    # 48 horas
VERIFY_TOKEN_TTL = 86400    # 24 horas


def set_password_reset_token(user_id: str, token: str) -> None:
    sync_redis.setex(f"pwreset:{token}", RESET_TOKEN_TTL, user_id)


def get_password_reset_user(token: str) -> str | None:
    return sync_redis.get(f"pwreset:{token}")


def delete_password_reset_token(token: str) -> None:
    sync_redis.delete(f"pwreset:{token}")


def set_email_verification_token(user_id: str, token: str) -> None:
    sync_redis.setex(f"emailverify:{token}", VERIFY_TOKEN_TTL, user_id)


def get_email_verification_user(token: str) -> str | None:
    return sync_redis.get(f"emailverify:{token}")


def delete_email_verification_token(token: str) -> None:
    sync_redis.delete(f"emailverify:{token}")


# ─── Blacklist de access tokens (logout) ─────────────────────

ACCESS_TOKEN_BLACKLIST_PREFIX = "token_blacklist"


async def blacklist_access_token(jti: str, ttl_seconds: int) -> None:
    """Añade un jti a la blacklist con TTL = tiempo restante de vida del token."""
    await async_redis.setex(f"{ACCESS_TOKEN_BLACKLIST_PREFIX}:{jti}", ttl_seconds, "1")


def blacklist_access_token_sync(jti: str, ttl_seconds: int) -> None:
    """Versión síncrona para usar desde Celery tasks."""
    sync_redis.setex(f"{ACCESS_TOKEN_BLACKLIST_PREFIX}:{jti}", ttl_seconds, "1")


async def is_access_token_blacklisted(jti: str) -> bool:
    return bool(await async_redis.exists(f"{ACCESS_TOKEN_BLACKLIST_PREFIX}:{jti}"))


def is_access_token_blacklisted_sync(jti: str) -> bool:
    return bool(sync_redis.exists(f"{ACCESS_TOKEN_BLACKLIST_PREFIX}:{jti}"))


# ─── Temp tokens 2FA (single-use) ────────────────────────────

TEMP_TOKEN_TTL = 600   # 10 minutos (más que los 5 min de expiración del JWT)


def consume_temp_token(token: str) -> bool:
    """Marca un temp_token como consumido. Devuelve False si ya estaba consumido."""
    key = f"temp_token_consumed:{token}"
    if sync_redis.exists(key):
        return False
    sync_redis.setex(key, TEMP_TOKEN_TTL, "1")
    return True


def is_temp_token_consumed(token: str) -> bool:
    return bool(sync_redis.exists(f"temp_token_consumed:{token}"))
