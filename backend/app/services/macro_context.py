"""Macro Context Service — funding rates, economic calendar, market regime.

Provides macro-level context to the AI scanner and bot activator
to avoid trading into high-risk windows (funding extremes, major news).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from loguru import logger

# In-memory simple cache (ttl seconds)
_cache: dict[str, tuple[Any, datetime]] = {}
CACHE_TTL_SEC = 300  # 5 min

_BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
_BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Thresholds
_FUNDING_HIGH = 0.0001      # 0.01% per 8h = ~10.95% annualized
_FUNDING_EXTREME = 0.0003   # 0.03% per 8h = ~32.85% annualized
_EVENT_WARNING_MINUTES = 60  # warn if High impact event within 60 min


def _cached(key: str, ttl: int = CACHE_TTL_SEC) -> Any | None:
    entry = _cache.get(key)
    if entry:
        data, ts = entry
        if datetime.now(timezone.utc) - ts < timedelta(seconds=ttl):
            return data
    return None


def _set_cache(key: str, data: Any) -> None:
    _cache[key] = (data, datetime.now(timezone.utc))


def fetch_funding_rate(symbol: str) -> dict:
    """Return latest funding rate for a USDT perpetual symbol."""
    cache_key = f"funding:{symbol.upper()}"
    cached = _cached(cache_key)
    if cached:
        return cached

    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(_BINANCE_FUNDING_URL, params={
                "symbol": symbol.upper().replace("/", ""),
                "limit": 1,
            })
            r.raise_for_status()
            rows = r.json()
            if not rows:
                return {"error": "no_data"}
            row = rows[0]
            rate = float(row["fundingRate"])
            # Annualized approx: 3 settlements/day * 365 * rate
            annual = rate * 3 * 365
            result = {
                "symbol": symbol.upper(),
                "funding_rate_8h": rate,
                "funding_rate_8h_pct": round(rate * 100, 4),
                "annualized_pct": round(annual * 100, 2),
                "mark_price": float(row.get("markPrice", 0)),
                "funding_time": datetime.fromtimestamp(
                    row["fundingTime"] / 1000, tz=timezone.utc
                ).isoformat(),
                "signal": (
                    "extreme" if abs(rate) >= _FUNDING_EXTREME
                    else "high" if abs(rate) >= _FUNDING_HIGH
                    else "neutral"
                ),
            }
            _set_cache(cache_key, result)
            return result
    except Exception as exc:
        logger.warning(f"[MACRO] Funding fetch failed for {symbol}: {exc}")
        return {"error": str(exc)}


def fetch_funding_history(symbol: str, limit: int = 90) -> list[dict]:
    """Fetch last N funding rate records for a symbol."""
    cache_key = f"funding_history:{symbol.upper()}:{limit}"
    cached = _cached(cache_key, ttl=1800)  # 30 min
    if cached:
        return cached

    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(_BINANCE_FUNDING_URL, params={
                "symbol": symbol.upper().replace("/", ""),
                "limit": limit,
            })
            r.raise_for_status()
            rows = r.json()
            result = []
            for row in rows:
                result.append({
                    "fundingRate": float(row["fundingRate"]),
                    "fundingTime": datetime.fromtimestamp(
                        row["fundingTime"] / 1000, tz=timezone.utc
                    ),
                    "markPrice": float(row.get("markPrice", 0)),
                })
            _set_cache(cache_key, result)
            return result
    except Exception as exc:
        logger.warning(f"[MACRO] Funding history fetch failed for {symbol}: {exc}")
        return []


def _correlation(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 2 or n != len(y):
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den_x = sum((xi - mx) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - my) ** 2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def compute_funding_dynamics(symbol: str) -> dict:
    """Compute funding rate dynamics beyond static value.

    Returns:
        change_8h: Change from previous funding
        acceleration: Second derivative (change of change)
        percentile_30d: Percentile of current rate in last 30 days
        price_divergence: Correlation between funding slope and price slope
        dynamics_signal: additional risk signal
    """
    history = fetch_funding_history(symbol, limit=90)
    if len(history) < 3:
        return {"error": "insufficient_history", "signal": "neutral"}

    # Sort by time ascending
    history.sort(key=lambda r: r["fundingTime"])

    rates = [h["fundingRate"] for h in history]
    prices = [h["markPrice"] for h in history if h["markPrice"] > 0]

    current_rate = rates[-1]
    prev_rate = rates[-2]
    prev2_rate = rates[-3] if len(rates) >= 3 else prev_rate

    change_8h = current_rate - prev_rate
    acceleration = (current_rate - prev_rate) - (prev_rate - prev2_rate)

    # Percentile in last 30 records (~10 days)
    window = rates[-30:] if len(rates) >= 30 else rates
    sorted_window = sorted(window)
    rank = sum(1 for r in sorted_window if r < current_rate)
    percentile_30d = (rank / len(sorted_window)) * 100 if sorted_window else 50.0

    # Price-funding divergence: correlation of slopes over last 20 periods
    price_divergence = 0.0
    if len(rates) >= 21 and len(prices) >= 21:
        rate_slopes = [rates[i] - rates[i - 1] for i in range(-20, 0)]
        price_slopes = [prices[i] - prices[i - 1] for i in range(-20, 0)]
        price_divergence = _correlation(rate_slopes, price_slopes)

    # Additional dynamics signal
    dynamics_signal = "neutral"
    if abs(current_rate) >= _FUNDING_EXTREME:
        dynamics_signal = "extreme"
    elif abs(current_rate) >= _FUNDING_HIGH:
        if acceleration > 0 and percentile_30d > 80:
            dynamics_signal = "worsening"
        else:
            dynamics_signal = "high"
    elif acceleration > 0 and percentile_30d > 70:
        dynamics_signal = "rising"

    return {
        "symbol": symbol.upper(),
        "funding_rate_8h": current_rate,
        "change_8h": round(change_8h, 6),
        "acceleration": round(acceleration, 6),
        "percentile_30d": round(percentile_30d, 1),
        "price_divergence": round(price_divergence, 3),
        "dynamics_signal": dynamics_signal,
        "history_length": len(history),
    }


def fetch_economic_calendar() -> list[dict]:
    """Return high-impact economic events from ForexFactory JSON feed."""
    cache_key = "macro:calendar"
    # Try shared Redis cache first (1h TTL, shared across workers)
    try:
        from app.services.cache import sync_redis
        raw = sync_redis.get(cache_key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass

    # Fallback to in-memory cache
    cached = _cached("calendar", ttl=1800)
    if cached:
        return cached

    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(_CALENDAR_URL)
            # If rate limited, return stale cache if available
            if r.status_code == 429:
                logger.warning("[MACRO] Calendar 429 — returning stale cache")
                stale = _cached("calendar", ttl=86400)  # accept up to 24h stale
                return stale if stale else []
            r.raise_for_status()
            rows = r.json()
            # Normalize and keep events from now - 2h up to + 24h
            now = datetime.now(timezone.utc)
            events = []
            for ev in rows:
                dt_str = ev.get("date", "")
                if not dt_str:
                    continue
                try:
                    # ISO format with offset, e.g. 2026-05-08T08:30:00-04:00
                    dt = datetime.fromisoformat(dt_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                minutes_until = (dt - now).total_seconds() / 60
                if minutes_until < -120 or minutes_until > 1440:
                    continue
                impact = ev.get("impact", "Low")
                events.append({
                    "title": ev.get("title", ""),
                    "country": ev.get("country", ""),
                    "time": dt.isoformat(),
                    "impact": impact,
                    "forecast": ev.get("forecast", ""),
                    "previous": ev.get("previous", ""),
                    "minutes_until": round(minutes_until),
                })
            # Sort by proximity
            events.sort(key=lambda x: abs(x["minutes_until"]))
            _set_cache("calendar", events)
            # Write to shared Redis cache
            try:
                from app.services.cache import sync_redis
                sync_redis.setex(cache_key, 3600, json.dumps(events))
            except Exception:
                pass
            return events
    except Exception as exc:
        logger.warning(f"[MACRO] Calendar fetch failed: {exc}")
        # Return stale cache as last resort
        stale = _cached("calendar", ttl=86400)
        return stale if stale else []


def get_macro_context(ticker: str) -> dict:
    """Full macro snapshot for a given ticker."""
    symbol = ticker.upper().replace("/", "").replace("USDT", "USDT")
    funding = fetch_funding_rate(symbol)
    calendar = fetch_economic_calendar()

    # Determine if ticker is crypto (skip currency-specific events)
    # For crypto, USD events (FOMC, NFP, CPI) matter most
    relevant_events = [
        e for e in calendar
        if e["impact"] in ("High", "Medium")
        and (
            e["country"] in ("USD", "ALL")
            or any(k in e["title"].upper() for k in ("FOMC", "FED", "CPI", "NFP", "GDP", "ECB", "BOE"))
        )
    ]

    high_impact_soon = [
        e for e in relevant_events
        if e["impact"] == "High" and 0 < e["minutes_until"] <= _EVENT_WARNING_MINUTES
    ]

    funding_signal = funding.get("signal", "neutral")
    funding_rate = funding.get("funding_rate_8h", 0)

    # Recommendation logic
    if high_impact_soon and funding_signal in ("high", "extreme"):
        recommendation = "avoid"
    elif high_impact_soon:
        recommendation = "caution"
    elif funding_signal == "extreme":
        recommendation = "avoid"
    elif funding_signal == "high":
        recommendation = "caution"
    else:
        recommendation = "proceed"

    return {
        "ticker": ticker,
        "funding": funding,
        "events": relevant_events[:10],  # top 10 relevant
        "high_impact_soon": high_impact_soon,
        "recommendation": recommendation,
        "warnings": [
            *(f"High funding rate: {funding_rate*100:.4f}%/8h" if funding_signal in ("high", "extreme") else []),
            *(f"Upcoming high-impact event: {e['title']} in {e['minutes_until']} min" for e in high_impact_soon),
        ],
    }


def macro_gate_for_signal(ticker: str, direction: str) -> dict:
    """Return gate decision for a specific signal direction.

    Uses both static funding rate AND funding dynamics for smarter gating.
    """
    ctx = get_macro_context(ticker)
    warnings = list(ctx.get("warnings", []))
    blocked = False
    sizing_adjustment = 1.0  # 1.0 = no change, 0.0 = block, 0.7 = reduce 30%

    funding = ctx.get("funding", {})
    rate = funding.get("funding_rate_8h", 0)

    # ── Static thresholds ────────────────────────────────────────────────────
    if rate > _FUNDING_EXTREME and direction == "long":
        warnings.append("Extreme positive funding — holding LONG is expensive")
        blocked = True
    elif rate < -_FUNDING_EXTREME and direction == "short":
        warnings.append("Extreme negative funding — holding SHORT is expensive")
        blocked = True

    # ── Funding dynamics ─────────────────────────────────────────────────────
    try:
        dynamics = compute_funding_dynamics(ticker)
        if "error" not in dynamics:
            accel = dynamics["acceleration"]
            pctile = dynamics["percentile_30d"]
            div = dynamics["price_divergence"]
            dyn_signal = dynamics["dynamics_signal"]

            # If funding is worsening against our direction
            if direction == "long" and rate > 0 and accel > 0 and pctile > 80:
                warnings.append(
                    f"Funding worsening for LONG: p{pctile:.0f}, accel={accel:.6f}"
                )
                sizing_adjustment = 0.7
                if pctile > 90:
                    blocked = True

            elif direction == "short" and rate < 0 and accel < 0 and pctile > 80:
                warnings.append(
                    f"Funding worsening for SHORT: p{pctile:.0f}, accel={accel:.6f}"
                )
                sizing_adjustment = 0.7
                if pctile > 90:
                    blocked = True

            # Price-funding divergence: if funding rises but price falls,
            # market may be absorbing the cost (conflicting signal)
            if abs(div) < 0.3 and abs(rate) >= _FUNDING_HIGH:
                warnings.append(
                    f"Price-funding divergence weak (r={div:.2f}) — uncertain regime"
                )
                sizing_adjustment = min(sizing_adjustment, 0.8)

            # Log dynamics for transparency
            logger.info(
                f"[MACRO] {ticker} {direction}: funding={rate:.6f} "
                f"dyn={dyn_signal} p{pctile:.0f} accel={accel:.6f} "
                f"div={div:.2f} sizing={sizing_adjustment}"
            )
    except Exception as dyn_exc:
        logger.warning(f"[MACRO] Funding dynamics computation failed: {dyn_exc}")

    return {
        "blocked": blocked,
        "caution": ctx["recommendation"] == "caution" and not blocked,
        "warnings": warnings,
        "sizing_adjustment": sizing_adjustment,
        "context": ctx,
    }
