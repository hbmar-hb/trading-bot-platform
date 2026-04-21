import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, auth, bots, charting, exchange_accounts, exchange_trades, manual_trade, optimizer, paper_trading, positions, users, webhook, ws
from app.api.websocket.manager import ws_manager
from app.services.logger import setup_logging
from app.workers.balance_monitor import balance_monitor
from app.workers.price_monitor import price_monitor
from app.workers.trailing_worker import trailing_worker

# Configurar logging al importar el módulo
setup_logging(debug=os.getenv("DEBUG", "false").lower() == "true")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────
    # 1. Seed usuario admin si DB está vacía (solo en desarrollo)
    if os.getenv("ENV") == "development":
        from app.core.seed import seed_first_user_if_empty
        await seed_first_user_if_empty()

    # 2. Sincronizar posiciones con exchanges al arrancar
    from app.core.reconciler import sync_open_positions
    await sync_open_positions()

    # 3. Arrancar workers como background tasks asyncio
    background_tasks = [
        asyncio.create_task(price_monitor.run(),         name="price_monitor"),
        asyncio.create_task(balance_monitor.run(),       name="balance_monitor"),
        asyncio.create_task(trailing_worker.run(),       name="trailing_worker"),
        asyncio.create_task(ws_manager.start_redis_listener(), name="ws_redis_listener"),
    ]

    yield

    # ── SHUTDOWN ─────────────────────────────────────────────
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)


app = FastAPI(
    title="Trading Bot Platform",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5274,http://localhost:80,http://localhost:8080"
).split(",")

# Add wildcard for external access (any IP/domain)
_cors_origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(exchange_accounts.router)
app.include_router(paper_trading.router)
app.include_router(bots.router)
app.include_router(positions.router)
app.include_router(exchange_trades.router)
app.include_router(analytics.router)
app.include_router(optimizer.router)
app.include_router(charting.router)
app.include_router(manual_trade.router)
app.include_router(webhook.router)
app.include_router(ws.router)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}
