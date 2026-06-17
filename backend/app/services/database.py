from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from config.settings import settings


# ─────────────────────────────────────────────────────────────
# Base para todos los modelos SQLAlchemy
# ─────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────
# Async engine + session — FastAPI / workers asyncio
# ─────────────────────────────────────────────────────────────
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"statement_cache_size": 0},  # required for PgBouncer transaction pooling
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Dependency para inyectar en rutas FastAPI."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def managed_async_session(fn):
    """Run an async callable inside a managed async session with automatic cleanup.
    Use this in Celery tasks or background jobs instead of manual session handling.
    
    Args:
        fn: Async callable that accepts an AsyncSession and returns a value.
    """
    async with AsyncSessionLocal_task() as session:
        try:
            async with session.begin():
                return await fn(session)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ─────────────────────────────────────────────────────────────
# Async engine (NullPool) — Celery tasks only
# NullPool creates a fresh connection per session and closes it
# immediately, so there are no pooled connections that could be
# attached to a closed event loop when asyncio.run() is called
# repeatedly in the same forked Celery worker process.
# ─────────────────────────────────────────────────────────────
async_engine_task = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=NullPool,
    connect_args={"statement_cache_size": 0},  # required for PgBouncer transaction pooling
)

AsyncSessionLocal_task = async_sessionmaker(
    async_engine_task,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─────────────────────────────────────────────────────────────
# Sync engine + session — Celery tasks / Alembic
# ─────────────────────────────────────────────────────────────
sync_engine = create_engine(
    settings.database_url_sync,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
)
