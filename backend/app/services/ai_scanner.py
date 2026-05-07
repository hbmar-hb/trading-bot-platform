"""Core ICT/confluence scan logic — shared by API routes and background Celery task."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import ccxt.async_support as ccxt
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ict_engine import analyze as ict_analyze
from app.engines.confluence_engine import analyze_confluence
from app.engines.signal_quality_engine import assess_quality
from app.models.ai_signal import AISignal
from app.models.ai_scan import AILatestScan

# NOTE: semaphore is NOT module-level — Celery fork workers would bind it to the
# parent event loop. Each caller creates its own and passes it in via _sem.
_DEFAULT_CONCURRENCY = 6

# Maps each LTF to its confirmation HTF (x4 or nearest liquid TF)
_HTF_MAP: dict[str, str] = {
    "1m":  "5m",  "3m":  "15m", "5m":  "30m",
    "15m": "1h",  "30m": "2h",  "1h":  "4h",
    "2h":  "8h",  "4h":  "1d",  "8h":  "1d",
    "12h": "3d",  "1d":  "1w",  "1w":  "1M",
}


def htf_for(timeframe: str) -> str | None:
    """Return the confirmation HTF for a given LTF, or None if not mapped."""
    return _HTF_MAP.get(timeframe)


def _get_htf_bias(htf_ohlcv: list) -> str | None:
    """Return 'bull'/'bear' when HTF has a confirmed structural break, else None."""
    if not htf_ohlcv or len(htf_ohlcv) < 50:
        return None
    closed = [
        {"open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in htf_ohlcv[:-1]
    ]
    ict = ict_analyze(closed)
    # Only return a bias when structure is confirmed; default "bull" is not reliable
    return ict.bias if ict.last_break is not None else None


# ── Symbol helpers ────────────────────────────────────────────────────────────

def to_ccxt(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    s = symbol.replace(".P", "").replace(".p", "")
    for q in ["USDT", "USDC", "BTC", "ETH", "USD"]:
        if s.endswith(q):
            return f"{s[:-len(q)]}/{q}:{q}"
    return symbol


# ── ICT context builder ───────────────────────────────────────────────────────

def _reason_no_signal(ict) -> str:
    if ict.last_break is None:
        return "Sin rotura de estructura — pivots insuficientes o mercado en rango estrecho"
    if ict.active_ob is None:
        return (
            f"Rotura {ict.last_break.kind} {ict.last_break.direction} detectada — "
            f"sin Order Block válido para zona de entrada"
        )
    return (
        f"OB {ict.active_ob.kind} activo "
        f"({ict.active_ob.bottom:.4f}–{ict.active_ob.top:.4f}) — "
        f"precio aún no en zona de pullback"
    )


def build_context(ict, last_close: float) -> dict:
    ob_zone = None
    if ict.active_ob:
        ob_zone = {
            "kind":   ict.active_ob.kind,
            "top":    round(ict.active_ob.top, 8),
            "bottom": round(ict.active_ob.bottom, 8),
        }
    fvg_zones = [
        {"kind": f.kind, "top": round(f.top, 8), "bottom": round(f.bottom, 8)}
        for f in ict.active_fvgs[:4]
    ]
    return {
        "bias":        ict.bias,
        "last_break":  ict.last_break.kind if ict.last_break else None,
        "break_level": round(ict.last_break.level, 8) if ict.last_break else None,
        "trigger":     ict.trigger or None,
        "active_ob":   ob_zone,
        "active_fvgs": len(ict.active_fvgs),
        "fvg_zones":   fvg_zones,
        "eq_highs":    [round(p, 8) for p in ict.eq_highs[:5]],
        "eq_lows":     [round(p, 8) for p in ict.eq_lows[:5]],
        "last_close":  last_close,
        "reason":      _reason_no_signal(ict),
    }


# ── Core analysis ─────────────────────────────────────────────────────────────

def build_signal(
    symbol: str,
    timeframe: str,
    ohlcv: list,
    htf_ohlcv: list | None = None,
) -> tuple[dict, AISignal | None]:
    """Run ICT + confluence. Returns (result_dict, signal_orm | None).

    htf_ohlcv: pre-fetched candles for the confirmation timeframe.
    When provided and the HTF has a confirmed structural bias that
    contradicts the LTF signal direction, the signal is suppressed.
    """
    closed = [
        {"open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in ohlcv[:-1]
    ]
    last_close  = float(ohlcv[-1][4])
    signal_time = datetime.fromtimestamp(ohlcv[-2][0] / 1000, tz=timezone.utc)

    ict     = ict_analyze(closed)
    context = build_context(ict, last_close)
    result  = analyze_confluence(closed, symbol, timeframe)

    if not result:
        return {"symbol": symbol, "status": "NO_SIGNAL", "context": context}, None

    # HTF confirmation gate
    htf_bias: str | None = _get_htf_bias(htf_ohlcv) if htf_ohlcv is not None else None
    if htf_bias is not None:
        aligned = (
            (result.direction == "long"  and htf_bias == "bull") or
            (result.direction == "short" and htf_bias == "bear")
        )
        if not aligned:
            return {
                "symbol":  symbol,
                "status":  "NO_SIGNAL",
                "context": {**context, "htf_conflict": htf_bias},
            }, None

    result.features["htf_bias"]    = htf_bias
    result.features["htf_aligned"] = htf_bias is not None

    quality = assess_quality(result)
    sig = AISignal(
        ticker            = symbol,
        ccxt_symbol       = to_ccxt(symbol),
        timeframe         = timeframe,
        direction         = result.direction,
        score             = result.score,
        confidence        = result.confidence,
        entry_price       = result.entry_price,
        entry_zone_low    = result.entry_zone[0],
        entry_zone_high   = result.entry_zone[1],
        stop_loss         = result.stop_loss,
        take_profit_1     = result.take_profit_1,
        take_profit_2     = result.take_profit_2,
        features          = result.features,
        components        = result.components,
        warnings          = result.warnings,
        explanation       = result.explanation,
        quality_score     = quality.quality_score,
        quality_tier      = quality.quality_tier,
        anti_fake_status  = quality.anti_fake_status,
        red_flags         = quality.red_flags,
        green_flags       = quality.green_flags,
        signal_time       = signal_time,
        created_at        = datetime.now(timezone.utc),
    )
    return {"symbol": symbol, "status": "SIGNAL", "context": context}, sig


async def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    _sem: asyncio.Semaphore | None = None,
) -> tuple[str, list | None]:
    sem = _sem or asyncio.Semaphore(_DEFAULT_CONCURRENCY)
    ccxt_sym = to_ccxt(symbol)
    async with sem:
        exchange = ccxt.binance({"options": {"defaultType": "swap"}})
        try:
            ohlcv = await exchange.fetch_ohlcv(ccxt_sym, timeframe, limit=200)
            return symbol, ohlcv
        except Exception:
            return symbol, None
        finally:
            await exchange.close()


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def upsert_latest_scan(
    db: AsyncSession,
    symbol: str,
    timeframe: str,
    result_dict: dict,
    sig: AISignal | None = None,
) -> None:
    """Upsert into ai_latest_scans (one row per symbol+timeframe)."""
    signal_data = signal_to_dict(sig) if sig else None
    values = {
        "symbol":      symbol,
        "timeframe":   timeframe,
        "status":      result_dict.get("status", "NO_SIGNAL"),
        "context":     result_dict.get("context"),
        "signal_data": signal_data,
        "signal_id":   sig.id if sig else None,
        "scanned_at":  datetime.now(timezone.utc),
    }
    stmt = (
        pg_insert(AILatestScan)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["symbol", "timeframe"],
            set_={k: values[k] for k in ("status", "context", "signal_data", "signal_id", "scanned_at")},
        )
    )
    await db.execute(stmt)


# ── Serializer ────────────────────────────────────────────────────────────────

def signal_to_dict(s: AISignal) -> dict:
    recommendation = (
        "AVOID" if s.anti_fake_status == "BLOCK" else
        "WAIT"  if s.anti_fake_status == "CAUTION" else
        "ENTER" if s.quality_tier == "STRONG" else "WAIT"
    )
    return {
        "id":               str(s.id),
        "ticker":           s.ticker,
        "timeframe":        s.timeframe,
        "direction":        s.direction,
        "score":            s.score,
        "confidence":       s.confidence,
        "entry_price":      s.entry_price,
        "entry_zone":       [s.entry_zone_low, s.entry_zone_high],
        "stop_loss":        s.stop_loss,
        "take_profit_1":    s.take_profit_1,
        "take_profit_2":    s.take_profit_2,
        "components":       s.components,
        "warnings":         s.warnings,
        "explanation":      s.explanation,
        "quality_score":    s.quality_score,
        "quality_tier":     s.quality_tier,
        "anti_fake_status": s.anti_fake_status,
        "red_flags":        s.red_flags or [],
        "green_flags":      s.green_flags or [],
        "recommendation":   recommendation,
        "features":         s.features or {},
        "outcome":          s.outcome,
        "pnl_pct":          s.pnl_pct,
        "outcome_bars":     s.outcome_bars,
        "resolved_at":      s.resolved_at.isoformat() if s.resolved_at else None,
        "signal_time":      s.signal_time.isoformat(),
        "created_at":       s.created_at.isoformat(),
    }


def latest_scan_to_dict(row: AILatestScan) -> dict:
    base = {
        "symbol":     row.symbol,
        "timeframe":  row.timeframe,
        "status":     row.status,
        "context":    row.context,
        "scanned_at": row.scanned_at.isoformat(),
    }
    if row.signal_data:
        base.update(row.signal_data)
    return base
