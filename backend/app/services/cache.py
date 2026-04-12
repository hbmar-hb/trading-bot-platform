"""
Cliente Redis centralizado.

- async_redis: para FastAPI / workers asyncio
- sync_redis:  para Celery tasks (síncronas)

Canales pub/sub:
  price_updates     → {type, symbol, price, timestamp}
  position_updates  → {type, user_id, position_id, ...}
  balance_updates   → {type, account_id, total_equity, ...}
"""
import json
from datetime import datetime, timezone

import redis
import redis.asyncio as aioredis

from config.settings import settings

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
    await async_redis.publish("price_updates", json.dumps({
        "type":      "price_update",
        "symbol":    symbol,
        "price":     price,
        "change_24h": change_24h,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))


# ─── Balances ────────────────────────────────────────────────

async def get_balance(account_id: str) -> dict | None:
    val = await async_redis.get(f"balance:{account_id}")
    return json.loads(val) if val else None


async def set_balance(account_id: str, total_equity: float, available: float) -> None:
    data = {"total_equity": total_equity, "available_balance": available}
    await async_redis.setex(f"balance:{account_id}", BALANCE_TTL, json.dumps(data))
    await async_redis.publish("balance_updates", json.dumps({
        "type":       "balance_update",
        "account_id": account_id,
        **data,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }))


# ─── Estado de salud de exchanges ────────────────────────────

async def set_exchange_health(exchange: str, status: str) -> None:
    await async_redis.setex(f"health:{exchange}", 360, status)


async def get_exchange_health(exchange: str) -> str | None:
    return await async_redis.get(f"health:{exchange}")


# ─── Publish desde Celery (sync) ─────────────────────────────

def publish_position_update_sync(user_id: str, position_data: dict) -> None:
    """Usado desde tasks Celery (contexto síncrono)."""
    sync_redis.publish("position_updates", json.dumps({
        "type":    "position_update",
        "user_id": user_id,
        **position_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))
