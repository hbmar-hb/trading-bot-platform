"""
Global platform constants — single source of truth for timeframes,
so we don't have divergent lists across backend, frontend, and Celery tasks.

Minimum timeframe: 15m (no 1m, 3m, 5m).
"""
from __future__ import annotations

# ── Timeframes ───────────────────────────────────────────────────────────────
# Ordered from fastest to slowest.  These are the ONLY timeframes the platform
# accepts for AI scanning, bot creation, and watchlist entries.
VALID_TIMEFRAMES: list[str] = [
    "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w",
]

VALID_TIMEFRAMES_SET: set[str] = set(VALID_TIMEFRAMES)

# Higher-timeframe map used for HTF bias confirmation in the confluence engine.
# Every LTF *must* have an HTF mapping so the scanner can fetch bias context.
HTF_MAP: dict[str, str] = {
    "15m": "1h",
    "30m": "2h",
    "1h":  "4h",
    "2h":  "8h",
    "4h":  "1d",
    "6h":  "1d",
    "8h":  "1d",
    "12h": "3d",
    "1d":  "1w",
    "3d":  "1w",
    "1w":  "1M",
}

# Seconds per timeframe — used by outcome tracker to count elapsed candles.
TF_SECONDS: dict[str, int] = {
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
}

# Minutes per timeframe — used by bot activator for staleness checks.
TF_MINUTES: dict[str, int] = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
    "3d": 4320,
    "1w": 10080,
}


# Special value that tells the scanner / bot to auto-select the best timeframe
AUTO_TIMEFRAME = "auto"

# Timeframe fallback chain: when primary TF has no signal, cascade upward.
# Maps each TF to a list of higher TFs to try, in order.
TF_FALLBACK_CHAIN: dict[str, list[str]] = {
    "15m": ["30m", "1h", "4h", "1d"],
    "30m": ["1h", "2h", "4h", "1d"],
    "1h":  ["2h", "4h", "1d", "3d"],
    "2h":  ["4h", "8h", "1d", "3d"],
    "4h":  ["6h", "8h", "1d", "3d"],
    "6h":  ["8h", "12h", "1d", "3d"],
    "8h":  ["12h", "1d", "3d"],
    "12h": ["1d", "3d", "1w"],
    "1d":  ["3d", "1w"],
    "3d":  ["1w"],
    "1w":  [],
}


def validate_timeframe(tf: str | None, allow_auto: bool = False) -> str:
    """Return canonical timeframe or raise ValueError.

    Args:
        allow_auto: if True, "auto" is accepted as a valid value.
    """
    if not tf:
        raise ValueError("Timeframe is required")
    cleaned = str(tf).strip().lower()
    if allow_auto and cleaned == AUTO_TIMEFRAME:
        return cleaned
    if cleaned not in VALID_TIMEFRAMES_SET:
        raise ValueError(
            f"Invalid timeframe '{tf}'. Allowed: {', '.join(VALID_TIMEFRAMES)}"
            + (" or 'auto'" if allow_auto else "")
        )
    return cleaned


# Lower-timeframe confirmation map for CDC (Change of Character) validation.
# When the main scanner finds a setup on the primary TF, the confirmation
# scanner verifies the CHoCH on the mapped CDC TF.
CDC_MAP: dict[str, str] = {
    "15m": "5m",
    "30m": "5m",
    "1h":  "15m",
    "2h":  "15m",
    "4h":  "1h",
    "6h":  "1h",
    "8h":  "1h",
    "12h": "4h",
    "1d":  "4h",
    "3d":  "1d",
    "1w":  "1d",
}


def htf_for(timeframe: str) -> str | None:
    """Return the higher timeframe used for bias confirmation."""
    return HTF_MAP.get(timeframe)


def cdc_for(timeframe: str) -> str | None:
    """Return the lower confirmation timeframe for CDC validation."""
    return CDC_MAP.get(timeframe)
