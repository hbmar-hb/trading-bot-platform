"""SMC macro context: NWOG, ORG, BISI, SIBI, IFVG.

These concepts are computed from higher-timeframe candles and the current
ICT+SMC structure.  They are exposed as soft features/score bonuses — never
as hard rejection gates — so the engine can learn their real edge without
killing signal frequency.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger


def _to_dt(ts_ms: int | float) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def _candle_dict(c: list) -> dict[str, float]:
    """Normalize ccxt OHLCV candle to dict."""
    return {
        "timestamp": int(c[0]),
        "open": float(c[1]),
        "high": float(c[2]),
        "low": float(c[3]),
        "close": float(c[4]),
        "volume": float(c[5]) if len(c) > 5 else 0.0,
    }


def detect_weekly_gap(candles_1d: list[list], current_price: float | None = None) -> dict[str, Any]:
    """Detect the most recent New Week Opening Gap (NWOG).

    The NWOG is the gap between the previous week's close (Saturday) and the
    current week's open (Sunday).  It is considered:
      - bullish if the market gapped up on Sunday open
      - bearish if the market gapped down
      - mitigated if current price has returned inside the gap range
    """
    if not candles_1d or len(candles_1d) < 8:
        return {"present": False}

    days = [_candle_dict(c) for c in candles_1d]
    # Group candles by week starting on Sunday
    weeks: dict[tuple[int, int], list[dict]] = {}
    for d in days:
        dt = _to_dt(d["timestamp"])
        # days since Sunday (Sunday=0)
        days_since_sun = (dt.weekday() + 1) % 7
        sun = dt.date() - __import__("datetime").timedelta(days=days_since_sun)
        key = (sun.year, sun.isocalendar().week)
        weeks.setdefault(key, []).append(d)

    if len(weeks) < 2:
        return {"present": False}

    sorted_week_keys = sorted(weeks.keys())
    prev_week = weeks[sorted_week_keys[-2]]
    curr_week = weeks[sorted_week_keys[-1]]

    prev_close = prev_week[-1]["close"]
    curr_open = curr_week[0]["open"]

    gap_high = max(prev_close, curr_open)
    gap_low = min(prev_close, curr_open)
    mid = (gap_high + gap_low) / 2.0
    bias = "bull" if curr_open > prev_close else "bear" if curr_open < prev_close else "neutral"

    price = current_price if current_price is not None else days[-1]["close"]
    mitigated = gap_low <= price <= gap_high

    distance_pct = (abs(price - mid) / mid * 100) if mid > 0 else 0.0

    return {
        "present": True,
        "high": gap_high,
        "low": gap_low,
        "mid": mid,
        "bias": bias,
        "mitigated": mitigated,
        "distance_pct": round(distance_pct, 4),
    }


def detect_daily_gaps(
    candles_1d: list[list],
    current_price: float | None = None,
    lookback: int = 5,
) -> dict[str, Any]:
    """Detect the most recent unmitigated Opening Range Gap (ORG).

    The ORG is the gap between yesterday's close and today's open.  We scan
    the last `lookback` days and return the most recent one that has not been
    revisited by the current price.
    """
    if not candles_1d or len(candles_1d) < lookback + 1:
        return {"present": False}

    days = [_candle_dict(c) for c in candles_1d]
    price = current_price if current_price is not None else days[-1]["close"]

    for i in range(len(days) - 1, 0, -1):
        if len(days) - 1 - i >= lookback:
            break
        today = days[i]
        yesterday = days[i - 1]
        gap_high = max(today["open"], yesterday["close"])
        gap_low = min(today["open"], yesterday["close"])

        if gap_high == gap_low:
            continue

        mitigated = gap_low <= price <= gap_high
        if mitigated:
            continue

        bias = "bull" if today["open"] > yesterday["close"] else "bear"
        mid = (gap_high + gap_low) / 2.0
        distance_pct = (abs(price - mid) / mid * 100) if mid > 0 else 0.0

        return {
            "present": True,
            "high": gap_high,
            "low": gap_low,
            "mid": mid,
            "bias": bias,
            "mitigated": False,
            "distance_pct": round(distance_pct, 4),
            "age_days": len(days) - 1 - i,
        }

    return {"present": False}


def detect_bisi_sibi(
    ict,
    pd_position: float,
) -> dict[str, Any]:
    """Detect BISI/SIBI zones from the current ICT structure and PD position.

    BISI (buy-side imbalance / sell-side inefficiency) = bullish zone in discount.
    SIBI (sell-side imbalance / buy-side inefficiency) = bearish zone in premium.
    """
    result: dict[str, Any] = {
        "bisi_present": False,
        "bisi_price": None,
        "sibi_present": False,
        "sibi_price": None,
    }

    if ict is None:
        return result

    # BISI: bullish OB in discount
    if ict.active_ob and ict.active_ob.kind == "bull" and pd_position < 0.40:
        has_bull_fvg = any(f.kind == "bull" and not f.filled for f in ict.active_fvgs)
        if has_bull_fvg:
            result["bisi_present"] = True
            result["bisi_price"] = round(ict.active_ob.bottom, 8)

    # SIBI: bearish OB in premium
    if ict.active_ob and ict.active_ob.kind == "bear" and pd_position > 0.60:
        has_bear_fvg = any(f.kind == "bear" and not f.filled for f in ict.active_fvgs)
        if has_bear_fvg:
            result["sibi_present"] = True
            result["sibi_price"] = round(ict.active_ob.top, 8)

    return result


def detect_inverse_fvg(
    candles_ltf: list[dict],
    ict,
) -> dict[str, Any]:
    """Detect an inverse FVG (IFVG) recently mitigated and rejected.

    For a bullish bias, an IFVG is a bearish FVG above price that was touched
    by the wick but the candle closed back below it.  For bearish bias, the
    opposite.
    """
    result = {"present": False, "price": None, "kind": None}
    if not candles_ltf or not ict or not ict.bias:
        return result

    last = candles_ltf[-1]
    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    bias = ict.bias

    for fvg in ict.active_fvgs:
        if bias == "bull" and fvg.kind == "bear":
            # Wick touched the bearish FVG but price rejected back down
            if high >= fvg.bottom and close < fvg.bottom:
                result = {"present": True, "price": round(fvg.bottom, 8), "kind": "bear"}
                return result
        elif bias == "bear" and fvg.kind == "bull":
            # Wick touched the bullish FVG but price rejected back up
            if low <= fvg.top and close > fvg.top:
                result = {"present": True, "price": round(fvg.top, 8), "kind": "bull"}
                return result

    return result


def build_macro_features(
    candles_1d: list[list] | None,
    candles_1w: list[list] | None,
    ict_ltf,
    entry_mid: float,
    direction: str,
    pd_position: float = 0.5,
    candles_ltf: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a flat feature dict with all SMC macro concepts."""
    if not candles_1d:
        return {
            "nwog_present": False,
            "nwog_aligned": False,
            "nwog_mitigated": False,
            "nwog_distance_pct": 0.0,
            "nwog_bias": "neutral",
            "org_present": False,
            "org_aligned": False,
            "org_mitigated": False,
            "org_distance_pct": 0.0,
            "org_bias": "neutral",
            "bisi_present": False,
            "sibi_present": False,
            "ifvg_present": False,
        }

    nwog = detect_weekly_gap(candles_1d, current_price=entry_mid)
    org = detect_daily_gaps(candles_1d, current_price=entry_mid)
    bisi_sibi = detect_bisi_sibi(ict_ltf, pd_position)
    if candles_ltf is None and candles_1d:
        candles_ltf = [
            {"open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in candles_1d
        ]
    ifvg = detect_inverse_fvg(candles_ltf, ict_ltf)

    is_long = direction == "long"

    nwog_aligned = False
    if nwog.get("present") and not nwog.get("mitigated"):
        if is_long and nwog["bias"] == "bull" and entry_mid > nwog["high"]:
            nwog_aligned = True
        elif not is_long and nwog["bias"] == "bear" and entry_mid < nwog["low"]:
            nwog_aligned = True

    org_aligned = False
    if org.get("present") and not org.get("mitigated"):
        if is_long and org["bias"] == "bull" and entry_mid > org["high"]:
            org_aligned = True
        elif not is_long and org["bias"] == "bear" and entry_mid < org["low"]:
            org_aligned = True

    features: dict[str, Any] = {
        "nwog_present": nwog.get("present", False),
        "nwog_aligned": nwog_aligned,
        "nwog_mitigated": nwog.get("mitigated", False),
        "nwog_distance_pct": nwog.get("distance_pct", 0.0),
        "nwog_bias": nwog.get("bias", "neutral"),
        "org_present": org.get("present", False),
        "org_aligned": org_aligned,
        "org_mitigated": org.get("mitigated", False),
        "org_distance_pct": org.get("distance_pct", 0.0),
        "org_bias": org.get("bias", "neutral"),
        "bisi_present": bisi_sibi["bisi_present"],
        "sibi_present": bisi_sibi["sibi_present"],
        "ifvg_present": ifvg["present"],
        "ifvg_kind": ifvg["kind"],
    }

    logger.debug(f"[SMC_MACRO] {direction} entry={entry_mid:.6f} features={features}")
    return features
