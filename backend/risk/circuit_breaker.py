"""Circuit Breaker — stops trading after 3 confident failures.

Evaluación 1: Critical for production. Counts only CONFIDENT predictions that fail.
Auto-recovery in 30 minutes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Literal

from loguru import logger

from app.services.cache import sync_redis

CircuitState = Literal["CLOSED", "OPEN", "HALF_OPEN"]

_KEY = "circuit_breaker:ai_signals"
_FAILURE_THRESHOLD = 3
_TIMEOUT_MINUTES = 30
_CONFIDENCE_THRESHOLD = 0.7  # Only count failures where model was confident


@dataclass(frozen=True)
class CircuitStatus:
    state: CircuitState
    failures: int
    last_failure: datetime | None
    allows_trading: bool


class CircuitBreaker:
    """Circuit breaker for AI signal execution.

    States:
        CLOSED     → Normal operation, counting failures
        OPEN       → Trading blocked after 3 confident failures
        HALF_OPEN  → Allowing 1 test trade after timeout

    Usage:
        cb = CircuitBreaker()
        if not cb.allow_trade():
            return  # Skip signal
        cb.record(predicted_prob=0.75, actual_outcome="FAILURE")
    """

    def __init__(self):
        self.state: CircuitState = "CLOSED"
        self.failures = 0
        self.last_failure: datetime | None = None
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def allow_trade(self) -> bool:
        """Check if trading is currently allowed."""
        self._load()

        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            if self._timeout_expired():
                self.state = "HALF_OPEN"
                self.failures = 0
                self._save()
                logger.info("[CircuitBreaker] OPEN → HALF_OPEN (timeout expired)")
                return True
            return False

        if self.state == "HALF_OPEN":
            return True  # Allow the test trade

        return True

    def record(self, predicted_prob: float, actual_outcome: str) -> None:
        """Record an outcome. Only counts confident failures."""
        self._load()

        # Evaluación 1: Count only predictions with confidence >= 0.7 that fail
        if predicted_prob >= _CONFIDENCE_THRESHOLD and actual_outcome == "FAILURE":
            self.failures += 1
            self.last_failure = datetime.now(timezone.utc)

            if self.failures >= _FAILURE_THRESHOLD:
                if self.state != "OPEN":
                    self.state = "OPEN"
                    logger.warning(
                        f"[CircuitBreaker] OPEN after {self.failures} confident failures"
                    )
                    self._alert_critical()
            else:
                logger.info(
                    f"[CircuitBreaker] Failure {self.failures}/{_FAILURE_THRESHOLD} "
                    f"(prob={predicted_prob:.3f})"
                )

            self._save()
            return

        # If HALF_OPEN and trade succeeds → close breaker
        if self.state == "HALF_OPEN" and actual_outcome == "SUCCESS":
            self.state = "CLOSED"
            self.failures = 0
            self.last_failure = None
            self._save()
            logger.info("[CircuitBreaker] HALF_OPEN → CLOSED (test trade succeeded)")
            return

        # If HALF_OPEN and trade fails → re-open
        if self.state == "HALF_OPEN" and actual_outcome == "FAILURE":
            self.state = "OPEN"
            self.failures = 1
            self.last_failure = datetime.now(timezone.utc)
            self._save()
            logger.warning("[CircuitBreaker] HALF_OPEN → OPEN (test trade failed)")
            return

    def status(self) -> CircuitStatus:
        """Return current circuit breaker status."""
        self._load()
        return CircuitStatus(
            state=self.state,
            failures=self.failures,
            last_failure=self.last_failure,
            allows_trading=self.allow_trade(),
        )

    # ── Persistence (Redis) ───────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            data = sync_redis.get(_KEY)
            if data:
                payload = json.loads(data)
                self.state = payload.get("state", "CLOSED")
                self.failures = payload.get("failures", 0)
                last = payload.get("last_failure")
                self.last_failure = datetime.fromisoformat(last) if last else None
        except Exception as exc:
            logger.warning(f"[CircuitBreaker] Failed to load state: {exc}")
            self.state = "CLOSED"
            self.failures = 0
            self.last_failure = None

    def _save(self) -> None:
        try:
            payload = {
                "state": self.state,
                "failures": self.failures,
                "last_failure": self.last_failure.isoformat() if self.last_failure else None,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            sync_redis.setex(_KEY, timedelta(hours=2), json.dumps(payload))
        except Exception as exc:
            logger.warning(f"[CircuitBreaker] Failed to save state: {exc}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _timeout_expired(self) -> bool:
        if self.last_failure is None:
            return True
        elapsed = datetime.now(timezone.utc) - self.last_failure
        return elapsed > timedelta(minutes=_TIMEOUT_MINUTES)

    def _alert_critical(self) -> None:
        """Emit critical alert. Can be extended to send notifications."""
        logger.critical(
            f"🚨 CIRCUIT BREAKER OPEN — {self.failures} confident failures. "
            f"Trading halted for {_TIMEOUT_MINUTES} minutes."
        )


# ── Convenience functions ────────────────────────────────────────────────────

def get_circuit_breaker() -> CircuitBreaker:
    """Get or create the global circuit breaker instance."""
    return CircuitBreaker()


def circuit_allows_trading() -> bool:
    """One-liner to check if trading is allowed."""
    return CircuitBreaker().allow_trade()
