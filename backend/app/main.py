import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.dependencies import require_2fa_if_enabled
from app.api.routes import ai, analytics, assistant, auth, bots, charting, chat, exchange_accounts, exchange_trades, manual_trade, montecarlo, optimizer, paper_trading, portfolio, positions, telegram, trading_signals, users, webhook, ws, admin_system
from app.api.websocket.manager import ws_manager
from app.services.logger import setup_logging
from app.workers.balance_monitor import balance_monitor
from app.workers.paper_balance_monitor import paper_balance_monitor
from app.workers.price_monitor import price_monitor
from app.workers.trailing_worker import trailing_worker


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # Evitar clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Evitar MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Forzar HTTPS en producción (HSTS 1 año + preload)
        if os.getenv("ENV") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        # Política de referrer
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CSP básica
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' ws: wss:;"
        return response

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
        asyncio.create_task(price_monitor.run(),          name="price_monitor"),
        asyncio.create_task(balance_monitor.run(),        name="balance_monitor"),
        asyncio.create_task(paper_balance_monitor.run(),  name="paper_balance_monitor"),
        asyncio.create_task(trailing_worker.run(),        name="trailing_worker"),
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

_env = os.getenv("ENV", "development")
_cors_origins = os.getenv("CORS_ORIGINS", "")

if _env == "production":
    if not _cors_origins:
        raise RuntimeError("CORS_ORIGINS debe estar definido en producción")
    _origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
else:
    _origins = [o.strip() for o in _cors_origins.split(",") if o.strip()] or [
        "http://localhost:5173",
        "http://localhost:5274",
        "http://localhost:80",
        "http://localhost:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(SecurityHeadersMiddleware)

# ─── Routers ─────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(
    users.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(
    exchange_accounts.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(
    paper_trading.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(
    bots.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(
    positions.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(
    exchange_trades.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(analytics.router)
app.include_router(
    optimizer.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(charting.router)
app.include_router(
    trading_signals.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(
    manual_trade.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(telegram.router)
app.include_router(webhook.router)
app.include_router(chat.router)
app.include_router(ai.router)
app.include_router(assistant.router)
app.include_router(
    portfolio.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(ws.router)
app.include_router(
    montecarlo.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)
app.include_router(
    admin_system.router,
    dependencies=[Depends(require_2fa_if_enabled)],
)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}
