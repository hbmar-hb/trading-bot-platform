"""
Rate limiter simple en memoria para endpoints de auth.
Limpia entradas antiguas automaticamente cada 100 requests.
"""
import time
from collections import defaultdict
from fastapi import HTTPException, status


class InMemoryRateLimiter:
    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._store: dict[str, list[float]] = defaultdict(list)
        self._cleanup_counter = 0

    def check(self, key: str):
        now = time.time()
        timestamps = self._store[key]
        # Filtrar solo los del ventana actual
        self._store[key] = [t for t in timestamps if now - t < self.window]
        if len(self._store[key]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos. Espera un momento e intenta de nuevo.",
            )
        self._store[key].append(now)

        # Limpieza periodica de claves antiguas
        self._cleanup_counter += 1
        if self._cleanup_counter >= 100:
            self._cleanup_counter = 0
            self._cleanup(now)

    def _cleanup(self, now: float):
        stale = [k for k, timestamps in self._store.items() if not any(now - t < self.window for t in timestamps)]
        for k in stale:
            del self._store[k]


# Limiters dedicados
login_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)
register_limiter = InMemoryRateLimiter(max_requests=3, window_seconds=300)
