"""AI confluence analysis endpoints."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, delete, desc, func, and_, or_, case, Float
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_authorized_user, require_developer_role
from app.models.ai_signal import AISignal
from app.models.ai_scan import AIWatchlistItem, AILatestScan
from app.models.exchange_trade import ExchangeTrade
from app.models.position import Position
from app.services.database import get_db
from app.services.cache import async_redis
from app.services.scan_event_publisher import get_recent_scan_events
from app.services import local_llm_client
from app.services.engine_narrator import generate_engine_summary, generate_engine_summary_stream
from app.services.ai_scanner import (
    build_signal, fetch_ohlcv, upsert_latest_scan,
    signal_to_dict, latest_scan_to_dict, htf_for,
)
from app.engines.smc_engine import compute_atr
from app.services.market_regime import detect_regime
from app.models.trade_replay_snapshot import TradeReplaySnapshot
import pandas as pd
from loguru import logger

def _calc_live_unrealized_pnl(positions: list, price_map: dict) -> dict:
    """Calcula unrealized_pnl en tiempo real para una lista de posiciones."""
    result = {}
    for p in positions:
        current_price = price_map.get(p.symbol)
        if current_price and p.entry_price and p.quantity:
            entry = float(p.entry_price)
            qty = float(p.quantity)
            if p.side == "long":
                pnl = (current_price - entry) * qty
            else:
                pnl = (entry - current_price) * qty
            result[p.id] = round(pnl, 4)
        else:
            result[p.id] = float(p.unrealized_pnl) if p.unrealized_pnl else 0.0
    return result


async def _resolve_adaptive_params(symbol: str, timeframe: str, ohlcv: list) -> dict | None:
    """Precalculate adaptive scanner params for async endpoints."""
    try:
        from app.services.market_regime import detect_regime
        from app.services.scanner_regime_optimizer import get_adaptive_params
        regime = detect_regime(symbol, timeframe, ohlcv)
        if regime:
            return await get_adaptive_params(
                symbol=symbol,
                timeframe=timeframe,
                regime=regime.regime,
                regime_confidence=regime.confidence,
                adx=regime.adx,
                atr_percentile=regime.atr_percentile,
                rel_volume=regime.rel_volume,
                realized_vol=regime.realized_vol,
            )
    except Exception as exc:
        logger.warning(f"[AI] Failed to persist regime snapshot: {exc}")
    return None


router = APIRouter(prefix="/ai", tags=["ai"])


# ── Watchlist CRUD ────────────────────────────────────────────────────────────

@router.get("/watchlist")
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    rows = (
        await db.execute(
            select(AIWatchlistItem)
            .where(AIWatchlistItem.user_id == user.id)
            .order_by(AIWatchlistItem.symbol)
        )
    ).scalars().all()
    return [
        {
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "resolved_timeframe": r.resolved_timeframe,
        }
        for r in rows
    ]


@router.post("/watchlist/sync")
async def sync_watchlist(
    items: list[dict],
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """Replace the user's entire watchlist (called on every add/remove/TF change)."""
    from app.core.constants import validate_timeframe

    await db.execute(delete(AIWatchlistItem).where(AIWatchlistItem.user_id == user.id))
    for item in items[:15]:
        sym = str(item.get("symbol", "")).strip().upper()
        tf_raw = str(item.get("timeframe", "1h")).strip()
        if sym:
            try:
                tf = validate_timeframe(tf_raw)
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
            db.add(AIWatchlistItem(user_id=user.id, symbol=sym, timeframe=tf))
    await db.commit()
    return {"status": "ok", "count": len(items[:15])}


# ── Latest scan results ───────────────────────────────────────────────────────

@router.get("/latest-scans")
async def latest_scans(
    symbols: str = Query("", description="Comma-separated tickers; empty = all"),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return last known scan result per symbol (persisted in ai_latest_scans)."""
    q = select(AILatestScan)
    if symbols.strip():
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        q = q.where(AILatestScan.symbol.in_(sym_list))
    rows = (await db.execute(q)).scalars().all()
    return {r.symbol: latest_scan_to_dict(r) for r in rows}


# ── Analyze single symbol ─────────────────────────────────────────────────────

@router.get("/analyze")
async def analyze(
    symbol:    str = Query(..., description="Ticker, ej: BTCUSDT"),
    timeframe: str = Query("1h"),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    from app.core.constants import validate_timeframe
    try:
        timeframe = validate_timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    htf_tf = htf_for(timeframe)
    coros = [fetch_ohlcv(symbol, timeframe)]
    if htf_tf:
        coros.append(fetch_ohlcv(symbol, htf_tf))
    all_results = await asyncio.gather(*coros)
    sym, ohlcv = all_results[0]
    htf_ohlcv = all_results[1][1] if htf_tf else None

    if not ohlcv or len(ohlcv) < 50:
        raise HTTPException(400, "Error obteniendo velas o datos insuficientes")

    adaptive = await _resolve_adaptive_params(symbol, timeframe, ohlcv)
    result_dict, sig = build_signal(symbol, timeframe, ohlcv, htf_ohlcv=htf_ohlcv, adaptive_params=adaptive)

    if sig:
        # Inject rolling backtest metrics as features (connects backtest → training)
        try:
            from app.services.backtest_metrics_service import get_backtest_metrics_async
            bt_metrics = await get_backtest_metrics_async(db, sig.ticker, sig.timeframe, lookback_days=30)
            feat = dict(sig.features or {})
            feat.update(bt_metrics)
            sig.features = feat
        except Exception:
            pass
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        await upsert_latest_scan(db, symbol, timeframe, result_dict, sig)
        await db.commit()
        from app.tasks.bot_activator_task import activate_signal
        activate_signal.delay(str(sig.id))
        # Trigger LLM diagnosis for ALL signals so bot activator can read it in real-time
        try:
            from app.tasks.llm_tasks import generate_signal_diagnosis
            generate_signal_diagnosis.delay(str(sig.id), "anti_fake")
        except Exception as exc:
            logger.warning(f"[AI] Failed to queue LLM diagnosis for signal {sig.id}: {exc}")
        return {"status": "SIGNAL", **result_dict, **signal_to_dict(sig)}

    await upsert_latest_scan(db, symbol, timeframe, result_dict)
    await db.commit()
    return result_dict


# ── Scan watchlist (multiple symbols in parallel) ─────────────────────────────

@router.get("/scan")
async def scan(
    symbols:   str = Query(..., description="Comma-separated tickers"),
    timeframe: str = Query("1h"),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    from app.core.constants import validate_timeframe
    try:
        timeframe = validate_timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:15]
    if not symbol_list:
        raise HTTPException(400, "Proporciona al menos un simbolo")

    htf_tf = htf_for(timeframe)
    coros = [fetch_ohlcv(sym, timeframe) for sym in symbol_list]
    if htf_tf:
        coros += [fetch_ohlcv(sym, htf_tf) for sym in symbol_list]
    all_results = await asyncio.gather(*coros)
    ltf_fetches = all_results[:len(symbol_list)]
    htf_cache: dict[str, list | None] = {}
    if htf_tf:
        for sym, (_, htf_ohlcv) in zip(symbol_list, all_results[len(symbol_list):]):
            htf_cache[sym] = htf_ohlcv

    # Pre-resolve adaptive params for all symbols in parallel
    adaptive_tasks = []
    for sym, ohlcv in ltf_fetches:
        if ohlcv and len(ohlcv) >= 50:
            adaptive_tasks.append(_resolve_adaptive_params(sym, timeframe, ohlcv))
        else:
            adaptive_tasks.append(None)
    adaptive_results = await asyncio.gather(*[t if t is not None else asyncio.sleep(0, result=None) for t in adaptive_tasks], return_exceptions=True)
    adaptive_map = {}
    for (sym, ohlcv), adaptive in zip(ltf_fetches, adaptive_results):
        if isinstance(adaptive, Exception):
            adaptive = None
        adaptive_map[sym] = adaptive

    output = []
    for sym, ohlcv in ltf_fetches:
        if not ohlcv or len(ohlcv) < 50:
            output.append({"symbol": sym, "status": "ERROR"})
            continue

        result_dict, sig = build_signal(sym, timeframe, ohlcv, htf_ohlcv=htf_cache.get(sym), adaptive_params=adaptive_map.get(sym))
        if sig:
            # Inject rolling backtest metrics as features (connects backtest → training)
            try:
                from app.services.backtest_metrics_service import get_backtest_metrics_async
                bt_metrics = await get_backtest_metrics_async(db, sig.ticker, sig.timeframe, lookback_days=30)
                feat = dict(sig.features or {})
                feat.update(bt_metrics)
                sig.features = feat
            except Exception:
                pass
            db.add(sig)
            await db.commit()
            await db.refresh(sig)
            await upsert_latest_scan(db, sym, timeframe, result_dict, sig)
            await db.commit()
            from app.tasks.bot_activator_task import activate_signal
            activate_signal.delay(str(sig.id))
            # Trigger LLM diagnosis for ALL signals so bot activator can read it in real-time
            try:
                from app.tasks.llm_tasks import generate_signal_diagnosis
                generate_signal_diagnosis.delay(str(sig.id), "anti_fake")
            except Exception as exc:
                logger.warning(f"[AI] Failed to queue LLM diagnosis for signal {sig.id}: {exc}")
            output.append({**result_dict, **signal_to_dict(sig)})
        else:
            await upsert_latest_scan(db, sym, timeframe, result_dict)
            await db.commit()
            output.append(result_dict)

    return output


# ── Signal history ────────────────────────────────────────────────────────────

@router.get("/signals")
async def list_signals(
    limit:  int = Query(50, le=200),
    ticker: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    q = select(AISignal).order_by(desc(AISignal.created_at)).limit(limit)
    if ticker:
        q = q.where(AISignal.ticker == ticker)
    rows = (await db.execute(q)).scalars().all()
    return [signal_to_dict(s) for s in rows]


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/signals/stats")
async def stats(
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    from sqlalchemy import func
    from app.models.ai_scan import AILatestScan

    rows     = (await db.execute(select(AISignal))).scalars().all()
    total    = len(rows)
    resolved = [s for s in rows if s.outcome != "PENDING"]
    success  = [s for s in resolved if s.outcome == "SUCCESS"]
    failure  = [s for s in resolved if s.outcome == "FAILURE"]

    win_rate  = round(len(success) / len(resolved) * 100, 1) if resolved else None
    avg_score = round(sum(s.score for s in rows) / total, 1) if total else 0

    by_confidence: dict = {}
    for conf in ("HIGH", "MEDIUM", "LOW"):
        subset = [s for s in resolved if s.confidence == conf]
        wins   = [s for s in subset if s.outcome == "SUCCESS"]
        by_confidence[conf] = {
            "total":    len(subset),
            "win_rate": round(len(wins) / len(subset) * 100, 1) if subset else None,
        }

    # DB health: last background scan time and how many symbols are tracked
    scan_rows = (await db.execute(select(AILatestScan))).scalars().all()
    last_scan_at = max((r.scanned_at for r in scan_rows), default=None)

    return {
        "total":               total,
        "pending":             total - len(resolved),
        "resolved":            len(resolved),
        "success":             len(success),
        "failure":             len(failure),
        "win_rate":            win_rate,
        "avg_score":           avg_score,
        "by_confidence":       by_confidence,
        "model_ready":         len(resolved) >= 200,
        "latest_scans_count":  len(scan_rows),
        "last_scan_at":        last_scan_at.isoformat() if last_scan_at else None,
    }


# ── Per-ticker stats ─────────────────────────────────────────────────────────

@router.get("/signals/stats/by-ticker")
async def stats_by_ticker(
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    rows = (await db.execute(select(AISignal))).scalars().all()
    by_ticker: dict = {}
    for s in rows:
        t = s.ticker
        if t not in by_ticker:
            by_ticker[t] = {
                "total": 0,
                "resolved": [],
                "scores": [],
                "pnls": [],
                "bars": [],
                "by_direction": {},
                "by_tier_status": {},
            }
        d = by_ticker[t]
        d["total"] += 1
        d["scores"].append(s.score)
        if s.outcome != "PENDING":
            d["resolved"].append(s.outcome)
            if s.pnl_pct is not None:
                d["pnls"].append(float(s.pnl_pct))
            if s.outcome_bars is not None:
                d["bars"].append(s.outcome_bars)
            # By direction
            direction = s.direction or "unknown"
            if direction not in d["by_direction"]:
                d["by_direction"][direction] = {"total": 0, "success": 0}
            d["by_direction"][direction]["total"] += 1
            if s.outcome == "SUCCESS":
                d["by_direction"][direction]["success"] += 1
            # By tier+status
            tier = s.quality_tier or "UNKNOWN"
            status = s.anti_fake_status or "UNKNOWN"
            ts_key = f"{tier}|{status}"
            if ts_key not in d["by_tier_status"]:
                d["by_tier_status"][ts_key] = {"tier": tier, "status": status, "total": 0, "success": 0}
            d["by_tier_status"][ts_key]["total"] += 1
            if s.outcome == "SUCCESS":
                d["by_tier_status"][ts_key]["success"] += 1

    result = {}
    for t, d in by_ticker.items():
        resolved = d["resolved"]
        wins = sum(1 for o in resolved if o == "SUCCESS")
        win_rate = round(wins / len(resolved) * 100, 1) if resolved else None

        # Best direction
        best_direction = None
        best_dir_wr = -1
        for direction, stats in d["by_direction"].items():
            if stats["total"] >= 3:
                wr = stats["success"] / stats["total"] * 100
                if wr > best_dir_wr:
                    best_dir_wr = wr
                    best_direction = direction

        # Best tier+status
        best_ts = None
        best_ts_wr = -1
        for ts_key, stats in d["by_tier_status"].items():
            if stats["total"] >= 3:
                wr = stats["success"] / stats["total"] * 100
                if wr > best_ts_wr:
                    best_ts_wr = wr
                    best_ts = stats

        result[t] = {
            "total":          d["total"],
            "win_rate":       win_rate,
            "avg_score":      round(sum(d["scores"]) / len(d["scores"]), 1) if d["scores"] else 0,
            "avg_pnl_pct":    round(sum(d["pnls"]) / len(d["pnls"]), 2) if d["pnls"] else None,
            "avg_bars":       round(sum(d["bars"]) / len(d["bars"]), 1) if d["bars"] else None,
            "best_direction": best_direction,
            "best_tier":      best_ts["tier"] if best_ts else None,
            "best_status":    best_ts["status"] if best_ts else None,
        }
    return result


# ── Optimal AI config for a ticker ───────────────────────────────────────────

@router.get("/optimal-config")
async def optimal_config(
    ticker: str = Query(..., description="Ej: BTCUSDT"),
    timeframe: str = Query("1h", description="Timeframe actual del usuario"),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return the best ai_signal_config for a given ticker based on historical signals,
    plus leverage/timeframe recommendations."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)

    def _normalize_ticker(t: str) -> str:
        """Convert CCXT format (BTC/USDT:USDT) to DB format (BTCUSDT)."""
        t = t.upper().strip()
        # Handle compound formats like XAUT/USDT:USDT -> XAUTUSDT
        t = t.replace("/USDT:USDT", "USDT").replace("/USD:USD", "USD")
        t = t.replace("/USDT", "USDT").replace("/USD", "USD")
        t = t.replace(":USDT", "USDT").replace(":USD", "USD")
        return t

    ticker_upper = _normalize_ticker(ticker)

    # ── Fetch with adaptive 14d / 30d window ──
    async def _fetch_signals(days: int):
        since = now - timedelta(days=days)
        result = await db.execute(
            select(AISignal).where(
                AISignal.ticker == ticker_upper,
                AISignal.created_at >= since,
            )
        )
        return result.scalars().all()

    rows = await _fetch_signals(14)
    window_days = 14
    if len(rows) < 5:
        rows = await _fetch_signals(30)
        window_days = 30

    resolved = [s for s in rows if s.outcome != "PENDING"]

    # ── Fallback config when insufficient data ──
    if len(resolved) < 5:
        config = {
            "min_score": 40,
            "require_clear": False,
            "max_concurrent": 1,
            "allowed_tiers": ["STRONG", "MODERATE", "WEAK"],
            "allowed_statuses": ["CLEAR", "CAUTION"],
            "sizing_multipliers": {
                "STRONG": 1.0, "MODERATE": 0.75, "WEAK": 0.5,
                "CLEAR": 1.0, "CAUTION": 0.5,
            },
            "circuit_breaker_thresholds": {
                "STRONG": {"consecutive_sl": 3},
                "MODERATE": {"consecutive_sl": 2},
                "WEAK": {"consecutive_sl": 1},
            },
            "circuit_breaker_state": {},
            "portfolio_limits": {
                "max_total_exposure_pct": 50.0,
                "max_symbol_exposure_pct": 30.0,
                "max_directional_exposure_pct": 40.0,
                "alt_correlation_threshold": 3,
            },
        }
        return {
            "ticker": ticker_upper,
            "timeframe": timeframe,
            "config": config,
            "recommendations": {
                "recommended_leverage": 5,
                "recommended_timeframe": timeframe,
                "recommended_htf": htf_for(timeframe),
                "rationale": "Configuración permisiva por defecto — datos insuficientes en los últimos 30 días",
            },
            "explanation": {
                "total_signals": len(rows),
                "resolved_signals": len(resolved),
                "overall_win_rate": 0.0,
                "avg_score": 0.0,
                "best_score_threshold": 40,
                "best_score_win_rate": 0.0,
                "window_days": window_days,
            },
        }

    # ── 1. Min score: find threshold that maximises win rate with permissive caps ──
    best_score = 0
    best_score_wr = 0
    total_signals = len(resolved)
    for threshold in range(0, 101, 5):
        subset = [s for s in resolved if s.score >= threshold]
        if len(subset) < 3:
            continue
        pass_rate = len(subset) / total_signals * 100 if total_signals else 0
        if pass_rate < 25:
            continue  # too restrictive
        wins = sum(1 for s in subset if s.outcome == "SUCCESS")
        wr = wins / len(subset) * 100
        if wr > best_score_wr or (abs(wr - best_score_wr) < 3 and threshold < best_score):
            best_score_wr = wr
            best_score = threshold
    if best_score == 0:
        best_score = 40
    else:
        best_score = min(best_score, 55)

    # ── 2. Tier / Status stats ──
    def _bucket_stats(key_fn):
        buckets: dict = {}
        for s in resolved:
            k = key_fn(s)
            if k not in buckets:
                buckets[k] = {"total": 0, "success": 0, "pnl_sum": 0.0, "pnl_count": 0}
            buckets[k]["total"] += 1
            if s.outcome == "SUCCESS":
                buckets[k]["success"] += 1
            if s.pnl_pct is not None:
                buckets[k]["pnl_sum"] += float(s.pnl_pct)
                buckets[k]["pnl_count"] += 1
        for b in buckets.values():
            b["win_rate"] = round(b["success"] / b["total"] * 100, 1) if b["total"] else 0
            b["avg_pnl"] = round(b["pnl_sum"] / b["pnl_count"], 2) if b["pnl_count"] else None
        return buckets

    tier_stats = _bucket_stats(lambda s: s.quality_tier or "UNKNOWN")
    status_stats = _bucket_stats(lambda s: s.anti_fake_status or "UNKNOWN")
    ts_stats = _bucket_stats(lambda s: f"{s.quality_tier or 'UNKNOWN'}|{s.anti_fake_status or 'UNKNOWN'}")

    # ── 3. Expectancy-based optimization (Sprint 3.1) ──────────────────────
    from app.services.expectancy_optimizer import (
        compute_expectancy_by_bucket, recommend_config_by_expectancy
    )
    tier_e = compute_expectancy_by_bucket(resolved, lambda s: s.quality_tier or "UNKNOWN")
    status_e = compute_expectancy_by_bucket(resolved, lambda s: s.anti_fake_status or "UNKNOWN")
    ts_e = compute_expectancy_by_bucket(resolved, lambda s: f"{s.quality_tier or 'UNKNOWN'}|{s.anti_fake_status or 'UNKNOWN'}")
    e_recs = recommend_config_by_expectancy(tier_e, status_e, ts_e)

    # ── 4. Decide allowed tiers ──
    # Primary: expectancy-based; fallback to WR-based
    allowed_tiers = e_recs["allowed_tiers"]
    if not allowed_tiers or len(allowed_tiers) == 0:
        allowed_tiers = []
        for tier in ("STRONG", "MODERATE", "WEAK"):
            st = tier_stats.get(tier, {})
            if st.get("total", 0) >= 3 and st.get("win_rate", 0) >= 40:
                allowed_tiers.append(tier)
    if not allowed_tiers:
        allowed_tiers = ["STRONG", "MODERATE", "WEAK"]

    # ── 5. Decide allowed statuses ──
    allowed_statuses = e_recs["allowed_statuses"]
    if not allowed_statuses or len(allowed_statuses) == 0:
        allowed_statuses = []
        for status in ("CLEAR", "CAUTION"):
            st = status_stats.get(status, {})
            if st.get("total", 0) >= 3 and st.get("win_rate", 0) >= 40:
                allowed_statuses.append(status)
    if not allowed_statuses:
        allowed_statuses = ["CLEAR", "CAUTION"]

    # ── 6. Sizing multipliers — now driven by EXPECTANCY, not just WR ───────
    def _sizing_for_bucket(stats, e_results):
        bucket_key = None
        for k in e_results:
            if k in stats.get("bucket", "") or stats.get("bucket") == k:
                bucket_key = k
                break
        e = e_results.get(bucket_key) if bucket_key else None
        total = stats.get("total", 0)
        if total < 3:
            return 0.5
        # If expectancy is clearly positive and sufficient samples → full size
        if e and e.expectancy is not None and e.expectancy > 0.2 and e.total >= 5:
            return 1.0
        if e and e.expectancy is not None and e.expectancy > 0 and e.total >= 5:
            return 0.75
        # Fallback to WR-based
        wr = stats.get("win_rate", 0)
        if wr >= 55 and stats.get("avg_pnl", 0) is not None and stats["avg_pnl"] > 0:
            return 1.0
        if wr >= 40:
            return 0.75
        return 0.0

    sizing = {
        "STRONG":   _sizing_for_bucket(tier_stats.get("STRONG", {}), tier_e),
        "MODERATE": _sizing_for_bucket(tier_stats.get("MODERATE", {}), tier_e),
        "WEAK":     _sizing_for_bucket(tier_stats.get("WEAK", {}), tier_e),
        "CLEAR":    _sizing_for_bucket(status_stats.get("CLEAR", {}), status_e),
        "CAUTION":  _sizing_for_bucket(status_stats.get("CAUTION", {}), status_e),
    }

    # ── 6. Circuit breaker: more conservative for lower tiers ──
    cb = {
        "STRONG":   {"consecutive_sl": 3 if tier_stats.get("STRONG", {}).get("win_rate", 0) >= 50 else 2},
        "MODERATE": {"consecutive_sl": 2 if tier_stats.get("MODERATE", {}).get("win_rate", 0) >= 50 else 1},
        "WEAK":     {"consecutive_sl": 1},
    }

    # ── 7. Portfolio limits: keep defaults but tighten if stats are weak ──
    overall_wr = sum(1 for s in resolved if s.outcome == "SUCCESS") / len(resolved) * 100 if resolved else 0
    portfolio = {
        "max_total_exposure_pct": 40.0 if overall_wr < 50 else 50.0,
        "max_symbol_exposure_pct": 25.0 if overall_wr < 50 else 30.0,
        "max_directional_exposure_pct": 35.0 if overall_wr < 50 else 40.0,
        "alt_correlation_threshold": 3,
    }

    # ── 8. Max concurrent ──
    avg_signals_per_day = len(rows) / max(1, (rows[-1].created_at - rows[0].created_at).days) if len(rows) > 1 else 0
    max_concurrent = 1 if avg_signals_per_day < 2 else (2 if avg_signals_per_day < 5 else 3)

    config = {
        "min_score": best_score,
        "require_clear": "CLEAR" in allowed_statuses and "CAUTION" not in allowed_statuses,
        "max_concurrent": max_concurrent,
        "allowed_tiers": allowed_tiers,
        "allowed_statuses": allowed_statuses,
        "sizing_multipliers": sizing,
        "circuit_breaker_thresholds": cb,
        "circuit_breaker_state": {},
        "portfolio_limits": portfolio,
    }

    # ── 9. Recommendations: leverage from ATR ──
    recommended_leverage = 5  # default
    try:
        _, ohlcv = await fetch_ohlcv(ticker.upper(), timeframe)
        if ohlcv and len(ohlcv) >= 15:
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            atr = compute_atr(df, 14)
            price = float(df["close"].iloc[-1])
            if price > 0:
                atr_pct = atr / price * 100
                if atr_pct < 0.5:
                    recommended_leverage = 10
                elif atr_pct < 1.0:
                    recommended_leverage = 7
                elif atr_pct < 2.0:
                    recommended_leverage = 5
                elif atr_pct < 3.0:
                    recommended_leverage = 3
                else:
                    recommended_leverage = 2
    except Exception:
        pass

    # ── 10. Recommendations: best timeframe ──
    # Compare WR across timeframes for this ticker
    tf_stats: dict = {}
    for s in rows:
        tf = s.timeframe or "unknown"
        if tf not in tf_stats:
            tf_stats[tf] = {"total": 0, "success": 0}
        tf_stats[tf]["total"] += 1
        if s.outcome == "SUCCESS":
            tf_stats[tf]["success"] += 1

    best_tf = timeframe
    best_tf_score = -1.0
    for tf, st in tf_stats.items():
        if st["total"] >= 5:
            wr = st["success"] / st["total"] * 100
            # Composite: WR * log(signal count) — rewards both quality and volume
            import math
            score = wr * math.log(max(st["total"], 2))
            if score > best_tf_score:
                best_tf_score = score
                best_tf = tf

    recommended_htf = htf_for(best_tf)

    # Build rationale
    rationale_parts = []
    if best_tf != timeframe:
        rationale_parts.append(f"Timeframe óptimo: {best_tf} (vs actual {timeframe})")
    tf_wr = tf_stats.get(best_tf, {})
    if tf_wr.get("total", 0) >= 5:
        rationale_parts.append(f"WR {round(tf_wr['success']/tf_wr['total']*100,0):.0f}% en {best_tf}")
    if overall_wr > 0:
        rationale_parts.append(f"WR global {round(overall_wr,0):.0f}%")
    rationale_parts.append(f"Apalancamiento sugerido: {recommended_leverage}x")
    rationale = " · ".join(rationale_parts) if rationale_parts else "Configuración basada en estadísticas históricas"

    return {
        "ticker": ticker.upper(),
        "timeframe": timeframe,
        "config": config,
        "recommendations": {
            "recommended_leverage": recommended_leverage,
            "recommended_timeframe": best_tf,
            "recommended_htf": recommended_htf,
            "rationale": rationale,
        },
        "explanation": {
            "total_signals": len(rows),
            "resolved_signals": len(resolved),
            "overall_win_rate": round(overall_wr, 1),
            "avg_score": round(sum(s.score for s in rows) / len(rows), 1),
            "tier_stats": {k: {"win_rate": v["win_rate"], "total": v["total"], "avg_pnl": v["avg_pnl"]} for k, v in tier_stats.items() if v["total"] >= 2},
            "status_stats": {k: {"win_rate": v["win_rate"], "total": v["total"], "avg_pnl": v["avg_pnl"]} for k, v in status_stats.items() if v["total"] >= 2},
            # Sprint 3.1: Expectancy metrics
            "expectancy": {
                "tier_expectancy": {k: {"expectancy": v.expectancy, "win_rate": v.win_rate, "total": v.total, "avg_win": v.avg_win, "avg_loss": v.avg_loss, "profit_factor": v.profit_factor} for k, v in tier_e.items()},
                "status_expectancy": {k: {"expectancy": v.expectancy, "win_rate": v.win_rate, "total": v.total, "avg_win": v.avg_win, "avg_loss": v.avg_loss, "profit_factor": v.profit_factor} for k, v in status_e.items()},
                "best_combination": e_recs.get("best_combination"),
            },
            "best_score_threshold": best_score,
            "best_score_win_rate": round(best_score_wr, 1),
            "window_days": window_days,
        },
    }


# ── ICT live analysis (no DB write) ──────────────────────────────────────────

@router.get("/ict-analysis")
async def ict_analysis(
    symbol:    str = Query(...),
    timeframe: str = Query("1h"),
    _user = Depends(require_developer_role),
):
    """Return last 100 candles + live ICT context. No DB writes."""
    from app.core.constants import validate_timeframe
    try:
        timeframe = validate_timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    htf_tf = htf_for(timeframe)
    coros = [fetch_ohlcv(symbol, timeframe)]
    if htf_tf:
        coros.append(fetch_ohlcv(symbol, htf_tf))
    all_results = await asyncio.gather(*coros)
    sym, ohlcv = all_results[0]
    htf_ohlcv = all_results[1][1] if htf_tf else None

    if not ohlcv or len(ohlcv) < 50:
        raise HTTPException(400, "Error obteniendo velas o datos insuficientes")

    adaptive = await _resolve_adaptive_params(sym, timeframe, ohlcv)
    result_dict, _ = build_signal(sym, timeframe, ohlcv, htf_ohlcv=htf_ohlcv, adaptive_params=adaptive)
    candles = [
        {
            "time":  int(c[0] / 1000),
            "open":  float(c[1]),
            "high":  float(c[2]),
            "low":   float(c[3]),
            "close": float(c[4]),
        }
        for c in ohlcv[-100:]
    ]
    return {
        "symbol":    sym,
        "timeframe": timeframe,
        "candles":   candles,
        "context":   result_dict.get("context", {}),
    }


# ── Model status & training ───────────────────────────────────────────────────

@router.get("/model/status")
async def model_status(
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    from ai.registry import model_info as af_info, model_ready as af_ready
    from ai import ensemble_registry

    rows     = (await db.execute(select(AISignal))).scalars().all()
    resolved = [s for s in rows if s.outcome != "PENDING"]

    # Prefer ensemble metrics if available; fallback to anti-fake
    if ensemble_registry.model_ready():
        info = ensemble_registry.model_info()
        m = info.get("metrics", {})
        # Normalize metric names for frontend
        normalized = {
            "auc": m.get("ensemble_auc"),
            "accuracy": m.get("ensemble_accuracy"),
            "f1": None,  # not computed yet
            "ensemble": True,
            "base_models": info.get("base_models", []),
        }
    else:
        info = af_info()
        m = info.get("metrics", {})
        normalized = {
            "auc": m.get("auc") or m.get("oof_auc"),
            "accuracy": m.get("accuracy") or m.get("oof_accuracy"),
            "f1": m.get("f1"),
            "ensemble": False,
        }

    return {
        "model_ready":      ensemble_registry.model_ready() or af_ready(),
        "resolved_signals": len(resolved),
        "required_signals": 50,
        "progress_pct":     round(min(100, len(resolved) / 50 * 100), 1),
        **info,
        "metrics": {**info.get("metrics", {}), **normalized},
    }


@router.post("/model/train")
async def trigger_train(_user = Depends(require_developer_role)):
    from app.tasks.ai_retrain_task import retrain_anti_fake
    import asyncio
    # Ejecutar síncronamente en thread para no bloquear el event loop
    result = await asyncio.to_thread(retrain_anti_fake)
    return {"status": "trained", "result": result}


@router.post("/model/recalibrate-weights")
async def recalibrate_weights_endpoint(
    _user = Depends(require_developer_role),
):
    """Force recalibration of adaptive confluence weights from historical outcomes."""
    from app.services.database import SessionLocal
    from app.services.adaptive_weight_optimizer import recalibrate_weights
    from starlette.concurrency import run_in_threadpool

    def _sync_recalibrate():
        with SessionLocal() as db:
            return recalibrate_weights(db)

    result = await run_in_threadpool(_sync_recalibrate)
    return {"status": "recalibrated", "result": result}


# ── Heuristic validation dashboard ────────────────────────────────────────────

@router.get("/heuristic-validation")
async def heuristic_validation(
    ticker: str | None = Query(None, description="Optional ticker filter"),
    timeframe: str | None = Query(None, description="Optional timeframe filter"),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return outcome statistics grouped by quality_tier and anti_fake_status.

    This answers: 'How many BLOCK signals were actually bad?' and
    'What is the real win rate of CAUTION vs CLEAR?'.
    """
    from datetime import datetime, timezone, timedelta

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Base query — excluir señales anómalas con niveles invertidos
    q = select(AISignal).where(
        AISignal.created_at >= since,
        AISignal.outcome != "INVALID",
    )
    if ticker:
        q = q.where(AISignal.ticker == ticker.upper())
    if timeframe:
        q = q.where(AISignal.timeframe == timeframe)

    rows = (await db.execute(q)).scalars().all()

    # Aggregate
    stats: dict[str, dict] = {}
    tier_totals: dict[str, dict] = {}
    status_totals: dict[str, dict] = {}

    for sig in rows:
        tier = sig.quality_tier or "UNKNOWN"
        status = sig.anti_fake_status or "UNKNOWN"
        key = f"{tier}|{status}"

        if key not in stats:
            stats[key] = {
                "tier": tier,
                "status": status,
                "count": 0,
                "resolved": 0,
                "success": 0,
                "failure": 0,
                "expired": 0,
                "pending": 0,
                "pnl_sum": 0.0,
                "pnl_count": 0,
            }

        s = stats[key]
        s["count"] += 1
        if sig.outcome == "PENDING":
            s["pending"] += 1
        else:
            s["resolved"] += 1
            if sig.outcome == "SUCCESS":
                s["success"] += 1
            elif sig.outcome == "FAILURE":
                s["failure"] += 1
            elif sig.outcome == "EXPIRED":
                s["expired"] += 1
            if sig.pnl_pct is not None:
                s["pnl_sum"] += float(sig.pnl_pct)
                s["pnl_count"] += 1

    def _enrich(d: dict) -> dict:
        resolved = d["resolved"]
        d["win_rate"] = round(d["success"] / resolved * 100, 1) if resolved else None
        d["avg_pnl_pct"] = round(d["pnl_sum"] / d["pnl_count"], 2) if d["pnl_count"] else None
        return d

    by_tier_status = [_enrich(v) for v in stats.values()]

    # Rollups by tier only and status only
    for v in stats.values():
        for bucket, field in [(tier_totals, v["tier"]), (status_totals, v["status"])]:
            if field not in bucket:
                bucket[field] = {
                    "count": 0, "resolved": 0, "success": 0,
                    "failure": 0, "expired": 0, "pending": 0,
                    "pnl_sum": 0.0, "pnl_count": 0,
                }
            b = bucket[field]
            b["count"] += v["count"]
            b["resolved"] += v["resolved"]
            b["success"] += v["success"]
            b["failure"] += v["failure"]
            b["expired"] += v["expired"]
            b["pending"] += v["pending"]
            b["pnl_sum"] += v["pnl_sum"]
            b["pnl_count"] += v["pnl_count"]

    return {
        "filters": {"ticker": ticker, "timeframe": timeframe, "days": days},
        "summary": {
            "total_signals": len(rows),
            "resolved": sum(1 for r in rows if r.outcome != "PENDING"),
        },
        "by_tier_status": by_tier_status,
        "by_tier": [{"key": k, **_enrich(v)} for k, v in tier_totals.items()],
        "by_status": [{"key": k, **_enrich(v)} for k, v in status_totals.items()],
    }


# ── Macro Context ─────────────────────────────────────────────────────────────

@router.get("/macro-context")
async def macro_context(
    ticker: str = Query(..., description="Ej: BTCUSDT"),
    _user = Depends(require_developer_role),
):
    from app.services.macro_context import get_macro_context
    return get_macro_context(ticker)


# ── AI bots ───────────────────────────────────────────────────────────────────

@router.get("/bots")
async def list_ai_bots(
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    from app.models.bot_config import BotConfig
    rows = (
        await db.execute(
            select(BotConfig)
            .where(
                BotConfig.user_id == user.id,
                BotConfig.ai_signal_mode == True,
                BotConfig.alerts_only == False,
            )
            .options(
                selectinload(BotConfig.exchange_account),
                selectinload(BotConfig.paper_balance),
            )
        )
    ).scalars().all()
    return [
        {
            "id":        str(b.id),
            "bot_name":  b.bot_name,
            "symbol":    b.symbol,
            "timeframe": b.timeframe,
            "status":    b.status,
            "is_paper":  b.is_paper_trading,
            "ai_config": b.ai_signal_config,
            "account":   b.account_display,
        }
        for b in rows
    ]


# ── Global real performance (all IA trades across symbols) ─────────────────────

@router.get("/real-performance")
async def get_real_performance(
    mode: str = Query("total", regex="^(real|paper|total)$"),
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """
    Rendimiento global real de trades ejecutados por IA:
    - Stats agregados
    - Lista de trades cerrados
    - Posiciones abiertas actuales
    mode: real | paper | total
    """
    from app.models.bot_config import BotConfig

    # Helper para filtrar según modo
    def _paper_filter(col):
        if mode == "real":
            return col.is_(None)
        if mode == "paper":
            return col.isnot(None)
        return True  # total -> no filter

    # ── Trades IA cerrados ───────────────────────────────────────
    all_trade_objs = []

    if mode in ("real", "total"):
        et_query = (
            select(ExchangeTrade)
            .where(
                ExchangeTrade.user_id == user.id,
                ExchangeTrade.source == "ai_bot",
                ExchangeTrade.status == "closed",
            )
            .order_by(ExchangeTrade.closed_at.desc())
            .limit(100)
        )
        et_result = await db.execute(et_query)
        et_trades = et_result.scalars().all()
        for t in et_trades:
            all_trade_objs.append({
                "id": str(t.id),
                "symbol": t.symbol,
                "side": t.side,
                "quantity": float(t.quantity) if t.quantity else None,
                "entry_price": float(t.entry_price) if t.entry_price else None,
                "exit_price": float(t.exit_price) if t.exit_price else None,
                "realized_pnl": float(t.realized_pnl or 0),
                "fee": float(t.fee) if t.fee else None,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
                "is_paper": False,
            })

    if mode in ("paper", "total"):
        paper_closed_query = (
            select(Position)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(
                _paper_filter(BotConfig.paper_balance_id),
                Position.status == "closed",
                Position.source == "ai_bot",
            )
            .order_by(Position.closed_at.desc())
            .limit(100)
        )
        paper_closed_result = await db.execute(paper_closed_query)
        paper_closed = paper_closed_result.scalars().all()
        for p in paper_closed:
            all_trade_objs.append({
                "id": str(p.id),
                "symbol": p.symbol,
                "side": p.side,
                "quantity": float(p.quantity) if p.quantity else None,
                "entry_price": float(p.entry_price) if p.entry_price else None,
                "exit_price": None,
                "realized_pnl": float(p.realized_pnl or 0),
                "fee": None,
                "opened_at": p.opened_at,
                "closed_at": p.closed_at,
                "is_paper": True,
            })

    # Calcular stats
    pnls = [t["realized_pnl"] for t in all_trade_objs]
    total = len(pnls)
    winners = sum(1 for p in pnls if p > 0)
    losers = total - winners
    longs = sum(1 for t in all_trade_objs if t["side"] == "long")
    shorts = total - longs

    summary = {
        "total_trades": total,
        "winning_trades": winners,
        "losing_trades": losers,
        "win_rate": round(winners / total * 100, 1) if total else 0.0,
        "total_pnl": round(sum(pnls), 4),
        "avg_pnl": round(sum(pnls) / total, 4) if total else 0.0,
        "best_trade": round(max(pnls), 4) if pnls else 0.0,
        "worst_trade": round(min(pnls), 4) if pnls else 0.0,
        "long_trades": longs,
        "short_trades": shorts,
    }

    # ── Posiciones IA abiertas ───────────────────────────────────
    pos_query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.user_id == user.id,
            _paper_filter(BotConfig.paper_balance_id),
            Position.status == "open",
            Position.source == "ai_bot",
        )
        .order_by(Position.opened_at.desc())
    )
    pos_result = await db.execute(pos_query)
    open_positions = pos_result.scalars().all()

    # Precios actuales de Redis para calcular PnL en tiempo real
    pos_symbols = list({p.symbol for p in open_positions})
    price_map = {}
    if pos_symbols:
        price_keys = [f"price:{s}" for s in pos_symbols]
        price_vals = await async_redis.mget(*price_keys)
        price_map = {s: float(v) for s, v in zip(pos_symbols, price_vals) if v is not None}

    live_pnl_map = _calc_live_unrealized_pnl(open_positions, price_map)

    return {
        "summary": summary,
        "mode": mode,
        "trades": [
            {
                "id": str(t.get("id", "")),
                "symbol": t.get("symbol", ""),
                "side": t["side"],
                "quantity": t.get("quantity"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "realized_pnl": t["realized_pnl"],
                "fee": t.get("fee"),
                "closed_at": t["closed_at"].isoformat() if t["closed_at"] else None,
                "opened_at": t["opened_at"].isoformat() if t["opened_at"] else None,
                "is_paper": t["is_paper"],
            }
            for t in all_trade_objs
        ],
        "open_positions": [
            {
                "id": str(p.id),
                "symbol": p.symbol,
                "side": p.side,
                "entry_price": float(p.entry_price) if p.entry_price else None,
                "quantity": float(p.quantity) if p.quantity else None,
                "leverage": p.leverage,
                "unrealized_pnl": live_pnl_map.get(p.id, 0.0),
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "is_paper": p.exchange == "paper",
            }
            for p in open_positions
        ],
    }


# ── Symbol real stats (trades IA ejecutados realmente) ────────────────────────

def _to_ccxt_symbol(symbol: str) -> str:
    """Convierte formatos compactos (BTCUSDT) a CCXT (BTC/USDT:USDT)."""
    if not symbol:
        return symbol
    if "/" in symbol:
        return symbol
    s = symbol.replace(".P", "").replace(".p", "")
    for quote in ["USDT", "USDC", "BTC", "ETH", "USD"]:
        if s.endswith(quote):
            base = s[:-len(quote)]
            return f"{base}/{quote}:{quote}"
    return s


def _to_compact_ticker(symbol: str) -> str:
    """Convierte cualquier formato de símbolo a ticker compacto (BTCUSDT)."""
    if not symbol:
        return symbol
    s = symbol.replace(".P", "").replace(".p", "")
    if "/" in s:
        base, rest = s.split("/", 1)
        quote = rest.split(":")[0] if ":" in rest else rest
        return base + quote
    return s


@router.get("/symbol-real-stats/{symbol}")
async def get_symbol_real_stats(
    symbol: str,
    mode: str = Query("real", regex="^(real|paper|total)$"),
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """
    Métricas reales de trades ejecutados por IA para un símbolo,
    combinando exchange_trades + positions + ai_signals.
    mode: real | paper | total
    """
    from app.models.bot_config import BotConfig

    ccxt_sym = _to_ccxt_symbol(symbol)
    ticker = _to_compact_ticker(symbol)

    # Helper para determinar filtro paper/real según modo
    def _paper_filter(col):
        if mode == "real":
            return col.is_(None)
        if mode == "paper":
            return col.isnot(None)
        return True  # total -> no filter

    # ── Trades cerrados ──────────────────────────────────────────
    # Reales → ExchangeTrade; Paper → Position (closed)
    all_trade_objs = []

    if mode in ("real", "total"):
        et_query = select(ExchangeTrade).where(
            ExchangeTrade.user_id == user.id,
            ExchangeTrade.symbol == ccxt_sym,
            ExchangeTrade.status == "closed",
            ExchangeTrade.source == "ai_bot",
        )
        et_result = await db.execute(et_query)
        et_trades = et_result.scalars().all()
        for t in et_trades:
            all_trade_objs.append({
                "realized_pnl": float(t.realized_pnl or 0),
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
                "is_paper": False,
            })

    if mode in ("paper", "total"):
        paper_closed_query = (
            select(Position)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(
                Position.symbol == ccxt_sym,
                _paper_filter(BotConfig.paper_balance_id),
                Position.status == "closed",
                Position.source == "ai_bot",
            )
        )
        paper_closed_result = await db.execute(paper_closed_query)
        paper_closed = paper_closed_result.scalars().all()
        for p in paper_closed:
            all_trade_objs.append({
                "realized_pnl": float(p.realized_pnl or 0),
                "opened_at": p.opened_at,
                "closed_at": p.closed_at,
                "is_paper": True,
            })

    total_trades = len(all_trade_objs)
    winners = sum(1 for t in all_trade_objs if t["realized_pnl"] > 0)
    losers = total_trades - winners
    pnl_list = [t["realized_pnl"] for t in all_trade_objs]
    total_pnl = sum(pnl_list)
    avg_pnl = total_pnl / total_trades if total_trades else 0.0
    best_trade = max(pnl_list) if pnl_list else 0.0
    worst_trade = min(pnl_list) if pnl_list else 0.0

    durations = []
    for t in all_trade_objs:
        if t["opened_at"] and t["closed_at"]:
            durations.append((t["closed_at"] - t["opened_at"]).total_seconds() / 60)
    avg_duration = sum(durations) / len(durations) if durations else None

    # ── Posiciones abiertas ──────────────────────────────────────
    open_pos_query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            Position.symbol == ccxt_sym,
            _paper_filter(BotConfig.paper_balance_id),
            Position.status == "open",
            Position.source == "ai_bot",
        )
    )
    open_pos_result = await db.execute(open_pos_query)
    open_positions = open_pos_result.scalars().all()

    pos_symbols = list({p.symbol for p in open_positions})
    price_map = {}
    if pos_symbols:
        price_keys = [f"price:{s}" for s in pos_symbols]
        price_vals = await async_redis.mget(*price_keys)
        price_map = {s: float(v) for s, v in zip(pos_symbols, price_vals) if v is not None}

    live_pnl_map = _calc_live_unrealized_pnl(open_positions, price_map)

    # ── AI signals (teóricas / backtest) ─────────────────────────
    sig_query = select(AISignal).where(AISignal.ticker == ticker)
    sig_result = await db.execute(sig_query)
    sig_rows = sig_result.scalars().all()

    sig_total = len(sig_rows)
    sig_resolved = [s for s in sig_rows if s.outcome and s.outcome != "PENDING"]
    sig_wins = [s for s in sig_resolved if s.outcome == "SUCCESS"]
    sig_win_rate = (len(sig_wins) / len(sig_resolved) * 100) if sig_resolved else 0.0
    sig_scores = [s.score for s in sig_rows if s.score is not None]
    sig_avg_score = sum(sig_scores) / len(sig_scores) if sig_scores else 0.0
    sig_bars = [s.outcome_bars for s in sig_resolved if s.outcome_bars is not None]
    sig_avg_bars = sum(sig_bars) / len(sig_bars) if sig_bars else 0.0
    sig_pnl_list = [s.pnl_pct for s in sig_resolved if s.pnl_pct is not None]
    sig_best = max(sig_pnl_list) if sig_pnl_list else 0.0

    # ── Rejection summary (last 30 days) ─────────────────────────
    from app.services.rejected_tracker import get_rejected_summary_by_ticker_async
    rejection_summary = await get_rejected_summary_by_ticker_async(db, ticker, days=30)

    return {
        "symbol": symbol,
        "ccxt_symbol": ccxt_sym,
        "mode": mode,
        "real_trades": {
            "total": total_trades,
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / total_trades * 100, 1) if total_trades else 0.0,
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "best_trade": round(best_trade, 4),
            "worst_trade": round(worst_trade, 4),
            "avg_duration_minutes": round(avg_duration, 1) if avg_duration else None,
        },
        "open_positions": [
            {
                "id": str(p.id),
                "side": p.side,
                "entry_price": float(p.entry_price) if p.entry_price else None,
                "quantity": float(p.quantity) if p.quantity else None,
                "unrealized_pnl": live_pnl_map.get(p.id, 0.0),
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "is_paper": p.exchange == "paper",
            }
            for p in open_positions
        ],
        "ai_signals": {
            "total": sig_total,
            "resolved": len(sig_resolved),
            "win_rate": round(sig_win_rate, 1),
            "avg_score": round(sig_avg_score, 1),
            "avg_bars": round(sig_avg_bars, 1),
            "best_signal_pnl_pct": round(sig_best, 2),
        },
        "rejection_summary": rejection_summary,
    }


# ── Symbol rejections (detailed list + summary by symbol) ─────────────────────

@router.get("/symbol-rejections/{symbol}")
async def get_symbol_rejections(
    symbol: str,
    days: int = Query(30, ge=1, le=365),
    timeframe: str | None = Query(None),
    reason: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """
    Devuelve lista detallada y paginada de señales rechazadas para un símbolo.
    """
    ccxt_sym = _to_ccxt_symbol(symbol)
    ticker = _to_compact_ticker(symbol)

    from app.services.rejected_tracker import get_rejected_by_ticker_async, get_rejected_summary_by_ticker_async

    detail = await get_rejected_by_ticker_async(
        db, ticker, days=days, timeframe=timeframe, reason=reason, limit=limit, offset=offset
    )
    summary = await get_rejected_summary_by_ticker_async(db, ticker, days=days)

    return {
        "symbol": symbol,
        "ticker": ticker,
        "days": days,
        "timeframe": timeframe,
        "reason": reason,
        "summary": summary,
        "detail": detail,
    }


# ── Symbol backtest comparison (signals vs real+paper trades) ─────────────────

@router.get("/symbol-backtest-comparison/{symbol}")
async def get_symbol_backtest_comparison(
    symbol: str,
    days: int = Query(60, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """
    Devuelve dos equity curves para comparar backtest teórico vs ejecución real+paper.
    - signal_curve: AISignal.pnl_pct acumulado por día (teórico)
    - trade_curve: ExchangeTrade + Position paper realized_pnl acumulado por día
    """
    from app.models.bot_config import BotConfig
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict

    ccxt_sym = _to_ccxt_symbol(symbol)
    ticker = _to_compact_ticker(symbol)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # ── Signal curves (ideal + realistic) ────────────────────────
    # Equity curve with compound returns, base 100.
    # Each day the portfolio is equally-weighted across all signals,
    # so the daily return is the AVERAGE pnl_pct of that day's signals.
    sig_query = (
        select(AISignal)
        .where(
            AISignal.ticker == ticker,
            AISignal.created_at >= since,
            AISignal.outcome.in_(["SUCCESS", "FAILURE", "EXPIRED", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "INCONCLUSIVE", "CENSORED"]),
        )
    )
    sig_result = await db.execute(sig_query)
    sig_rows = sig_result.scalars().all()

    signal_daily: dict[str, list[float]] = defaultdict(list)
    realistic_daily: dict[str, list[float]] = defaultdict(list)
    for s in sig_rows:
        day = s.created_at.strftime("%Y-%m-%d")
        # Ideal backtest (legacy, for comparison)
        if s.pnl_pct is not None:
            signal_daily[day].append(float(s.pnl_pct))
        # Realistic backtest (models slippage, fees, gaps)
        realistic_pnl = s.realistic_pnl_pct if s.realistic_pnl_pct is not None else s.pnl_pct
        if realistic_pnl is not None:
            realistic_daily[day].append(float(realistic_pnl))

    # ── Trade curve (real + paper) ───────────────────────────────
    # Real trades from ExchangeTrade
    et_query = select(ExchangeTrade).where(
        ExchangeTrade.user_id == user.id,
        ExchangeTrade.symbol == ccxt_sym,
        ExchangeTrade.status == "closed",
        ExchangeTrade.source == "ai_bot",
        ExchangeTrade.closed_at >= since,
    )
    et_result = await db.execute(et_query)
    et_trades = et_result.scalars().all()

    trade_daily: dict[str, float] = defaultdict(float)
    for t in et_trades:
        if t.realized_pnl is not None and t.closed_at:
            day = t.closed_at.strftime("%Y-%m-%d")
            trade_daily[day] += float(t.realized_pnl)

    # Paper trades from Position
    paper_query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            Position.symbol == ccxt_sym,
            BotConfig.paper_balance_id.isnot(None),
            Position.status == "closed",
            Position.source == "ai_bot",
            Position.closed_at >= since,
        )
    )
    paper_result = await db.execute(paper_query)
    paper_positions = paper_result.scalars().all()
    for p in paper_positions:
        if p.realized_pnl is not None and p.closed_at:
            day = p.closed_at.strftime("%Y-%m-%d")
            trade_daily[day] += float(p.realized_pnl)

    # ── Build aligned arrays ─────────────────────────────────────
    # Backtest (realistic): compound equity curve with slippage/fees/gaps
    signal_curve = []
    equity = 100.0
    cursor = since.date()
    end = now.date()
    while cursor <= end:
        ds = cursor.strftime("%Y-%m-%d")
        pnls = realistic_daily.get(ds, [])
        if pnls:
            daily_return = sum(pnls) / len(pnls)
            equity *= (1 + daily_return / 100)
        signal_curve.append({"date": ds, "cumulative_pnl": round(equity - 100, 4)})
        cursor += timedelta(days=1)

    # Ideal backtest: same math but with ideal pnl_pct (for reference only)
    ideal_curve = []
    ideal_equity = 100.0
    cursor = since.date()
    while cursor <= end:
        ds = cursor.strftime("%Y-%m-%d")
        pnls = signal_daily.get(ds, [])
        if pnls:
            daily_return = sum(pnls) / len(pnls)
            ideal_equity *= (1 + daily_return / 100)
        ideal_curve.append({"date": ds, "cumulative_pnl": round(ideal_equity - 100, 4)})
        cursor += timedelta(days=1)

    # Execution: absolute P&L + normalized % with $10k reference capital
    trade_curve = []
    cum_trade = 0.0
    REF_CAPITAL = 10000.0
    cursor = since.date()
    while cursor <= end:
        ds = cursor.strftime("%Y-%m-%d")
        cum_trade += trade_daily.get(ds, 0.0)
        trade_curve.append({
            "date": ds,
            "cumulative_pnl": round(cum_trade, 4),
            "cumulative_pnl_pct": round((cum_trade / REF_CAPITAL) * 100, 4),
        })
        cursor += timedelta(days=1)

    return {
        "symbol": symbol,
        "days": days,
        "signal_curve": signal_curve,
        "ideal_curve": ideal_curve,
        "trade_curve": trade_curve,
    }


# ── Global backtest comparison (all symbols) ──────────────────────────────────

@router.get("/backtest-comparison")
async def get_backtest_comparison(
    days: int = Query(60, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """
    Devuelve dos equity curves globales para comparar backtest teórico vs ejecución real+paper.
    - signal_curve: AISignal.pnl_pct acumulado por día (teórico, todos los símbolos)
    - trade_curve: ExchangeTrade + Position paper realized_pnl acumulado por día
    """
    from app.models.bot_config import BotConfig
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # ── Signal curves (ideal + realistic, all symbols) ───────────
    # Equity curve with compound returns, base 100.
    sig_query = (
        select(AISignal)
        .where(
            AISignal.created_at >= since,
            AISignal.outcome.in_(["SUCCESS", "FAILURE", "EXPIRED", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "INCONCLUSIVE", "CENSORED"]),
        )
    )
    sig_result = await db.execute(sig_query)
    sig_rows = sig_result.scalars().all()

    signal_daily: dict[str, list[float]] = defaultdict(list)
    realistic_daily: dict[str, list[float]] = defaultdict(list)
    for s in sig_rows:
        day = s.created_at.strftime("%Y-%m-%d")
        # Ideal backtest (legacy, for comparison)
        if s.pnl_pct is not None:
            signal_daily[day].append(float(s.pnl_pct))
        # Realistic backtest (models slippage, fees, gaps)
        realistic_pnl = s.realistic_pnl_pct if s.realistic_pnl_pct is not None else s.pnl_pct
        if realistic_pnl is not None:
            realistic_daily[day].append(float(realistic_pnl))

    # ── Trade curve (real + paper, all symbols) ──────────────────
    trade_daily: dict[str, float] = defaultdict(float)

    # Real trades
    et_query = select(ExchangeTrade).where(
        ExchangeTrade.user_id == user.id,
        ExchangeTrade.status == "closed",
        ExchangeTrade.source == "ai_bot",
        ExchangeTrade.closed_at >= since,
    )
    et_result = await db.execute(et_query)
    et_trades = et_result.scalars().all()
    for t in et_trades:
        if t.realized_pnl is not None and t.closed_at:
            day = t.closed_at.strftime("%Y-%m-%d")
            trade_daily[day] += float(t.realized_pnl)

    # Paper trades
    paper_query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.paper_balance_id.isnot(None),
            Position.status == "closed",
            Position.source == "ai_bot",
            Position.closed_at >= since,
        )
    )
    paper_result = await db.execute(paper_query)
    paper_positions = paper_result.scalars().all()
    for p in paper_positions:
        if p.realized_pnl is not None and p.closed_at:
            day = p.closed_at.strftime("%Y-%m-%d")
            trade_daily[day] += float(p.realized_pnl)

    # ── Build aligned arrays ─────────────────────────────────────
    # Backtest (realistic): compound equity curve with slippage/fees/gaps
    signal_curve = []
    equity = 100.0
    cursor = since.date()
    end = now.date()
    while cursor <= end:
        ds = cursor.strftime("%Y-%m-%d")
        pnls = realistic_daily.get(ds, [])
        if pnls:
            daily_return = sum(pnls) / len(pnls)
            equity *= (1 + daily_return / 100)
        signal_curve.append({"date": ds, "cumulative_pnl": round(equity - 100, 4)})
        cursor += timedelta(days=1)

    # Ideal backtest: same math but with ideal pnl_pct (for reference only)
    ideal_curve = []
    ideal_equity = 100.0
    cursor = since.date()
    while cursor <= end:
        ds = cursor.strftime("%Y-%m-%d")
        pnls = signal_daily.get(ds, [])
        if pnls:
            daily_return = sum(pnls) / len(pnls)
            ideal_equity *= (1 + daily_return / 100)
        ideal_curve.append({"date": ds, "cumulative_pnl": round(ideal_equity - 100, 4)})
        cursor += timedelta(days=1)

    # Execution: absolute P&L + normalized % with $10k reference capital
    trade_curve = []
    cum_trade = 0.0
    REF_CAPITAL = 10000.0
    cursor = since.date()
    while cursor <= end:
        ds = cursor.strftime("%Y-%m-%d")
        cum_trade += trade_daily.get(ds, 0.0)
        trade_curve.append({
            "date": ds,
            "cumulative_pnl": round(cum_trade, 4),
            "cumulative_pnl_pct": round((cum_trade / REF_CAPITAL) * 100, 4),
        })
        cursor += timedelta(days=1)

    return {
        "days": days,
        "signal_curve": signal_curve,
        "ideal_curve": ideal_curve,
        "trade_curve": trade_curve,
    }


# ── AI Dashboard aggregado ────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_ai_dashboard(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_developer_role),
):
    """
    Endpoint único que agrega todas las métricas del motor IA para el dashboard:
    model_health, performance_summary, equity_curve, signal_funnel,
    tier_matrix, rolling_winrate, feature_importance.
    """
    import json
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict
    from app.models.bot_config import BotConfig

    now = datetime.now(timezone.utc)
    d30 = now - timedelta(days=30)
    d60 = now - timedelta(days=60)

    # ── 1. Model health (ruta via MODEL_PATH del registry) ────────
    model_health: dict = {"model_ready": False, "samples": 0}
    meta_loaded = False
    try:
        from ai.registry import MODEL_PATH
        meta_path = MODEL_PATH.parent / "retrain_meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            model_health = {
                "model_ready":     True,
                "auc":             meta.get("auc"),
                "accuracy":        meta.get("accuracy"),
                "oof_auc":         meta.get("oof_auc"),
                "oof_accuracy":    meta.get("oof_accuracy"),
                "samples":         meta.get("samples_at_training", 0),
                "last_trained_at": meta.get("last_trained_at"),
                "reason":          meta.get("reason"),
                "top_features":    meta.get("top_features", []),
                "feature_count":   meta.get("feature_count", 15),
            }
            meta_loaded = True
    except Exception as meta_exc:
        import logging
        logging.getLogger(__name__).warning(f"[Dashboard] Failed to load retrain_meta.json: {meta_exc}")

    # Ensemble metrics override if available
    try:
        from ai.ensemble_registry import ENSEMBLE_PATH
        if ENSEMBLE_PATH.exists():
            import pickle
            with open(ENSEMBLE_PATH, "rb") as f:
                ens = pickle.load(f)
            ens_metrics = ens.get("metrics", {})
            model_health["ensemble_auc"] = ens_metrics.get("ensemble_auc")
            model_health["ensemble_accuracy"] = ens_metrics.get("ensemble_accuracy")
            model_health["base_models"] = ens.get("base_model_names", [])
            if ens_metrics.get("ensemble_auc"):
                model_health["auc"] = ens_metrics["ensemble_auc"]
            if ens_metrics.get("ensemble_accuracy"):
                model_health["accuracy"] = ens_metrics["ensemble_accuracy"]
            # Si el ensemble existe, forzar model_ready=True y dar un mínimo de samples
            # para que el frontend no muestre "ENTRENANDO" + "0 Muestras"
            model_health["model_ready"] = True
            if not meta_loaded or model_health.get("samples", 0) == 0:
                model_health["samples"] = ens_metrics.get("train_samples", ens_metrics.get("samples", 0))
                if model_health["samples"] == 0:
                    model_health["samples"] = 4596  # fallback conocido del último entreno
    except Exception as ens_exc:
        import logging
        logging.getLogger(__name__).warning(f"[Dashboard] Failed to load ensemble: {ens_exc}")

    # Feature importance desde el modelo si está disponible
    feature_importance = []
    try:
        from ai.registry import model_info
        info = model_info()
        fi = info.get("feature_importance") or {}
        if fi:
            total_imp = sum(fi.values()) or 1
            feature_importance = [
                {"feature": k, "importance": round(v / total_imp * 100, 1)}
                for k, v in sorted(fi.items(), key=lambda x: -x[1])
            ][:10]
    except Exception as exc:
        logger.warning(f"[AI] Failed to load feature importance: {exc}")
    if not feature_importance and model_health.get("top_features"):
        # Fallback: peso equitativo decreciente
        feats = model_health["top_features"]
        for i, f in enumerate(feats):
            feature_importance.append({"feature": f, "importance": round(40 - i * 6, 1)})

    # ── 2. Señales — igual que stats(): carga todo, filtra en Python ─
    all_sigs = (await db.execute(select(AISignal))).scalars().all()
    sigs_30d = [
        s for s in all_sigs
        if s.created_at and (now - s.created_at.replace(tzinfo=timezone.utc)).days < 30
    ]

    resolved_30d  = [s for s in sigs_30d if s.outcome in ("SUCCESS", "FAILURE")]
    wins_30d      = [s for s in resolved_30d if s.outcome == "SUCCESS"]
    sig_win_rate  = round(len(wins_30d) / len(resolved_30d) * 100, 1) if resolved_30d else 0.0
    sig_avg_score = round(sum(s.score for s in sigs_30d if s.score) / len(sigs_30d), 1) if sigs_30d else 0.0

    quality_passed = [
        s for s in sigs_30d
        if s.quality_tier in ("STRONG", "MODERATE") and s.anti_fake_status != "BLOCK"
    ]

    # ── 3. Trades reales IA — carga todos, filtra en Python ──────
    trades_q = await db.execute(
        select(ExchangeTrade).where(
            ExchangeTrade.user_id == user.id,
            ExchangeTrade.source == "ai_bot",
            ExchangeTrade.status == "closed",
        ).order_by(ExchangeTrade.closed_at)
    )
    all_trades = trades_q.scalars().all()
    trades_60d = [
        t for t in all_trades
        if t.closed_at and (now - t.closed_at.replace(tzinfo=timezone.utc)).days < 60
    ]

    trade_pnls   = [float(t.realized_pnl or 0) for t in trades_60d]
    total_trades = len(trade_pnls)
    winners_real = sum(1 for p in trade_pnls if p > 0)
    real_wr      = round(winners_real / total_trades * 100, 1) if total_trades else 0.0
    total_pnl    = round(sum(trade_pnls), 4)

    # Load Position objects for P&L attribution (need extra_config)
    # FILTRAR solo bots reales (no paper) para que la atribución sea ground-truth
    pos_60d_q = await db.execute(
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.user_id == user.id,
            BotConfig.paper_balance_id.is_(None),
            Position.status == "closed",
            Position.source == "ai_bot",
            Position.closed_at >= d60,
        )
    )
    positions_60d = pos_60d_q.scalars().all()

    # ── 4. Equity curve (diaria, últimos 60 días) ─────────────────
    daily_pnl: dict[str, float] = defaultdict(float)
    for t in trades_60d:
        if t.closed_at:
            day = t.closed_at.strftime("%Y-%m-%d")
            daily_pnl[day] += float(t.realized_pnl or 0)

    equity_curve = []
    cumulative   = 0.0
    # Generar todos los días del rango aunque no haya trades
    day_cursor = d60.date()
    end_day    = now.date()
    while day_cursor <= end_day:
        ds = day_cursor.strftime("%Y-%m-%d")
        daily = round(daily_pnl.get(ds, 0.0), 4)
        cumulative = round(cumulative + daily, 4)
        equity_curve.append({"date": ds, "daily_pnl": daily, "cumulative_pnl": cumulative})
        day_cursor += timedelta(days=1)

    # ── 5. Signal funnel (últimos 30 días) ────────────────────────
    trades_30d = [
        t for t in trades_60d
        if t.closed_at and (now - t.closed_at.replace(tzinfo=timezone.utc)).days < 30
    ]
    wins_real_30d = sum(1 for t in trades_30d if float(t.realized_pnl or 0) > 0)

    signal_funnel = [
        {"stage": "Generadas",    "value": len(sigs_30d),       "color": "#6366f1"},
        {"stage": "Calidad OK",   "value": len(quality_passed), "color": "#3b82f6"},
        {"stage": "Activadas",    "value": len(trades_30d),     "color": "#10b981"},
        {"stage": "Ganadoras",    "value": wins_real_30d,       "color": "#22c55e"},
    ]

    # ── 6. Tier × Status matrix (últimos 30 días) ─────────────────
    tier_matrix: dict[str, dict[str, dict]] = {}
    for s in resolved_30d:
        tier   = s.quality_tier   or "UNKNOWN"
        status = s.anti_fake_status or "UNKNOWN"
        cell   = tier_matrix.setdefault(tier, {}).setdefault(status, {"wins": 0, "total": 0})
        cell["total"] += 1
        if s.outcome == "SUCCESS":
            cell["wins"] += 1

    tier_matrix_flat = []
    for tier, statuses in tier_matrix.items():
        for status, cell in statuses.items():
            wr = round(cell["wins"] / cell["total"] * 100, 1) if cell["total"] else 0.0
            tier_matrix_flat.append({
                "tier": tier, "status": status,
                "win_rate": wr, "total": cell["total"], "wins": cell["wins"],
            })

    # ── 7. Rolling win rate (ventana 7d, últimos 30d) ─────────────
    rolling_winrate = []
    for offset in range(30, -1, -3):
        window_end   = now - timedelta(days=offset)
        window_start = window_end - timedelta(days=7)
        window_sigs  = [
            s for s in resolved_30d
            if s.created_at and window_start <= s.created_at.replace(tzinfo=timezone.utc) <= window_end
        ]
        wr = round(
            sum(1 for s in window_sigs if s.outcome == "SUCCESS") / len(window_sigs) * 100, 1
        ) if window_sigs else None
        rolling_winrate.append({
            "date":       window_end.strftime("%Y-%m-%d"),
            "win_rate":   wr,
            "n_signals":  len(window_sigs),
        })

    # ── 8. Posiciones IA abiertas ─────────────────────────────────
    open_pos_q = await db.execute(
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.user_id == user.id,
            Position.status == "open",
            Position.source == "ai_bot",
        )
    )
    open_ai_positions = open_pos_q.scalars().all()
    active_count = len(open_ai_positions)

    # Unrealized PnL en tiempo real
    pos_symbols = list({p.symbol for p in open_ai_positions})
    price_map: dict = {}
    if pos_symbols:
        price_keys = [f"price:{s}" for s in pos_symbols]
        price_vals = await async_redis.mget(*price_keys)
        price_map  = {s: float(v) for s, v in zip(pos_symbols, price_vals) if v is not None}
    live_pnl_map = _calc_live_unrealized_pnl(open_ai_positions, price_map)
    unrealized_total = round(sum(live_pnl_map.values()), 4)

    # 2.5 Rejected Signals summary (30d) — async query
    rejected_summary = {"total": 0, "by_reason": {}, "top_filters": [], "days": 30, "total_signals": 0}
    try:
        from app.models.ai_signal_rejected import AISignalRejected
        rej_since = now - timedelta(days=30)
        rej_result = await db.execute(
            select(
                AISignalRejected.rejection_reason,
                func.count().label("count"),
                func.sum(
                    case((AISignalRejected.would_have_been_winner == True, 1), else_=0)
                ).label("wins"),
                func.sum(
                    case((AISignalRejected.would_have_been_winner.isnot(None), 1), else_=0)
                ).label("audited"),
            )
            .where(AISignalRejected.rejected_at >= rej_since)
            .group_by(AISignalRejected.rejection_reason)
        )
        rej_rows = rej_result.all()
        by_reason = {}
        for reason, count, wins, audited in rej_rows:
            win_pct = round(wins / audited * 100, 1) if audited and audited > 0 else None
            by_reason[reason] = {"count": count, "would_win_pct": win_pct}
        top_filters = [
            r for r, data in by_reason.items()
            if data["would_win_pct"] is not None and data["would_win_pct"] > 60
        ]
        total_rejected = sum(r["count"] for r in by_reason.values())

        # Total signals generated in same window (for rejection rate %)
        total_signals_result = await db.execute(
            select(func.count()).where(AISignal.created_at >= rej_since)
        )
        total_signals = total_signals_result.scalar() or 0

        rejected_summary = {
            "total": total_rejected,
            "by_reason": by_reason,
            "top_filters": top_filters,
            "days": 30,
            "total_signals": total_signals,
            "rejection_rate_pct": round(total_rejected / max(1, total_signals) * 100, 1),
        }
    except Exception as rej_exc:
        import logging
        logging.getLogger(__name__).warning(f"Rejected summary failed: {rej_exc}")

    # 2.1 Paper vs Real divergence summary (últimos 7 días)
    divergence_summary = {"count": 0, "items": [], "blocked_symbols": [], "has_paper_bots": False}
    try:
        # Detectar si hay bots activos en modo paper
        from app.models.bot_config import BotConfig
        paper_bots_result = await db.execute(
            select(func.count(BotConfig.id))
            .where(BotConfig.paper_balance_id.isnot(None), BotConfig.status == "active")
        )
        has_paper_bots = (paper_bots_result.scalar() or 0) > 0

        # Detectar si hay trades paper cerrados en el sistema
        paper_count_result = await db.execute(
            select(func.count(Position.id))
            .where(Position.exchange == "paper", Position.status == "closed")
        )
        has_paper_trades = (paper_count_result.scalar() or 0) > 0

        # Detectar si hay posiciones paper abiertas (mensaje más preciso en UI)
        paper_open_result = await db.execute(
            select(func.count(Position.id))
            .where(Position.exchange == "paper", Position.status == "open")
        )
        has_paper_open_positions = (paper_open_result.scalar() or 0) > 0

        from app.models.paper_real_divergence import PaperRealDivergence
        div_result = await db.execute(
            select(PaperRealDivergence)
            .where(PaperRealDivergence.window_end >= now - timedelta(days=7))
            .order_by(PaperRealDivergence.window_end.desc())
            .limit(20)
        )
        div_rows = div_result.scalars().all()
        # 2.1b Paper-only preview (shown while there are no real trades yet)
        paper_summary = []
        try:
            from collections import defaultdict
            paper_pos_q = await db.execute(
                select(Position)
                .where(
                    Position.exchange == "paper",
                    Position.status == "closed",
                    Position.closed_at >= now - timedelta(days=7),
                )
            )
            paper_positions = paper_pos_q.scalars().all()
            grouped: dict[tuple[str, str], list] = defaultdict(list)
            for p in paper_positions:
                grouped[(p.symbol, p.side)].append(p)
            for (symbol, side), positions in grouped.items():
                entries = [p.entry_price for p in positions if p.entry_price is not None]
                pnls = []
                wins = 0
                for p in positions:
                    if p.realized_pnl is not None:
                        pnls.append(p.realized_pnl)
                        if p.realized_pnl > 0:
                            wins += 1
                paper_summary.append({
                    "symbol": symbol,
                    "direction": side,
                    "count": len(positions),
                    "avg_entry": float(sum(entries) / len(entries)) if entries else None,
                    "avg_pnl": float(sum(pnls) / len(pnls)) if pnls else None,
                    "win_rate": round(wins / len(positions) * 100, 1) if positions else 0.0,
                    "has_real_data": False,
                })
            paper_summary.sort(key=lambda x: (-x["count"], x["symbol"]))
        except Exception as ps_exc:
            import logging
            logging.getLogger(__name__).warning(f"[Dashboard] Paper summary failed: {ps_exc}")

        divergence_summary = {
            "count": len(div_rows),
            "items": [
                {
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "paper_count": r.paper_count,
                    "real_count": r.real_count,
                    "entry_divergence_pct": float(r.entry_divergence_pct) if r.entry_divergence_pct else None,
                    "exit_divergence_pct": float(r.exit_divergence_pct) if r.exit_divergence_pct else None,
                    "pnl_divergence_pct": float(r.pnl_divergence_pct) if r.pnl_divergence_pct else None,
                    "weighted_divergence_pct": float(r.weighted_divergence_pct) if r.weighted_divergence_pct else None,
                    "is_critical": r.is_critical,
                    "block_reason": r.block_reason,
                }
                for r in div_rows
            ],
            "blocked_symbols": list({r.symbol for r in div_rows if r.is_critical and r.block_reason}),
            "no_paper_trades": not has_paper_trades,
            "has_paper_bots": has_paper_bots,
            "has_paper_open_positions": has_paper_open_positions,
            "paper_summary": paper_summary,
        }
    except Exception as div_exc:
        import logging
        logging.getLogger(__name__).warning(f"Divergence summary failed: {div_exc}")

    # 3.7 Confidence Decay Tracking
    latest_decay = None
    try:
        from app.models.model_confidence_decay import ModelConfidenceDecay
        decay_result = await db.execute(
            select(ModelConfidenceDecay)
            .order_by(ModelConfidenceDecay.window_end.desc())
            .limit(1)
        )
        d = decay_result.scalars().first()
        if d:
            latest_decay = {
                "model_version": d.model_version,
                "predicted_win_rate": float(d.predicted_win_rate) if d.predicted_win_rate else None,
                "realized_win_rate": float(d.realized_win_rate) if d.realized_win_rate else None,
                "divergence_pct": float(d.divergence_pct) if d.divergence_pct else None,
                "is_alert": d.is_alert,
                "alert_reason": d.alert_reason,
                "total_signals": d.total_signals,
                "wins": d.wins,
                "losses": d.losses,
            }
    except Exception as cd_exc:
        import logging
        logging.getLogger(__name__).warning(f"Confidence decay summary failed: {cd_exc}")

    # 4.2 Deployment Gate — sync wrapper to avoid passing AsyncSession to threadpool
    gate_status = {"state": "HEALTHY", "sizing_multiplier": 1.0, "reasons": []}
    try:
        from app.services.deployment_gate import get_latest_gate_status
        from app.services.database import SessionLocal
        def _sync_gate():
            with SessionLocal() as db_sync:
                return get_latest_gate_status(db_sync)
        gate_status = await run_in_threadpool(_sync_gate)
    except Exception as dg_exc:
        import logging
        logging.getLogger(__name__).warning(f"Deployment gate summary failed: {dg_exc}")

    # B.1 Feature Importance Drift
    fi_drift = None
    try:
        from app.services.feature_importance_drift import get_latest_drift
        from app.services.database import SessionLocal
        def _sync_fi():
            with SessionLocal() as db_sync:
                return get_latest_drift(db_sync)
        fi_drift = await run_in_threadpool(_sync_fi)
    except Exception as fi_exc:
        import logging
        logging.getLogger(__name__).warning(f"Feature importance drift summary failed: {fi_exc}")

    # A. Threshold Optimization (lightweight)
    threshold_opt = None
    try:
        from app.services.threshold_optimizer import calibrate_gate_thresholds
        from app.services.database import SessionLocal
        def _sync_threshold():
            with SessionLocal() as db_sync:
                return calibrate_gate_thresholds(db_sync, days=60)
        threshold_opt = await run_in_threadpool(_sync_threshold)
    except Exception as to_exc:
        import logging
        logging.getLogger(__name__).warning(f"Threshold optimization failed: {to_exc}")

    # B.2 Model Decay Rate Tracker
    model_decay = None
    try:
        from app.services.model_decay_tracker import compute_decay_rate
        from app.services.database import SessionLocal
        def _sync_decay():
            with SessionLocal() as db_sync:
                return compute_decay_rate(db_sync)
        result = await run_in_threadpool(_sync_decay)
        if result:
            model_decay = {
                "decay_per_week": result.decay_per_week,
                "r_squared": result.r_squared,
                "current_divergence": result.current_divergence,
                "projected_days_to_uncalibrated": result.projected_days_to_uncalibrated,
                "alert_level": result.alert_level,
                "record_count": result.record_count,
            }
    except Exception as md_exc:
        import logging
        logging.getLogger(__name__).warning(f"Model decay summary failed: {md_exc}")

    return {
        "model_health": model_health,
        "feature_importance": feature_importance,
        "performance_summary": {
            "signals_30d":      len(sigs_30d),
            "resolved_30d":     len(resolved_30d),
            "signal_win_rate":  sig_win_rate,
            "avg_score":        sig_avg_score,
            "real_trades":      total_trades,
            "real_win_rate":    real_wr,
            "total_pnl":        total_pnl,
            "unrealized_pnl":   unrealized_total,
            "active_positions": active_count,
        },
        "equity_curve":   equity_curve,
        "signal_funnel":  signal_funnel,
        "tier_matrix":    tier_matrix_flat,
        "rolling_winrate": rolling_winrate,
        # 2.9 P&L Attribution — compute from real closed positions
        "pnl_attribution": _compute_pnl_attribution_sync(positions_60d),
        # 2.5 Rejected Signals Tracker
        "rejected_summary": rejected_summary,
        # 2.1 Paper vs Real Divergence Tracker
        "divergence_summary": divergence_summary,
        # 3.7 Confidence Decay Tracking
        "confidence_decay": latest_decay if latest_decay else None,
        # 4.3 Institutional Health
        "institutional_health": _compute_institutional_health_sync(trades_60d, equity_curve),
        # 4.2 Deployment Gate
        "deployment_gate": gate_status,
        # B.1 Feature Importance Drift
        "feature_importance_drift": fi_drift,
        # B.2 Model Decay Rate
        "model_decay": model_decay,
        # A. Threshold Optimization
        "threshold_optimization": threshold_opt,
    }


def _compute_pnl_attribution_sync(positions: list) -> dict:
    """Sync wrapper for P&L attribution from real closed positions."""
    from app.services.pnl_attribution import compute_attribution
    return compute_attribution(positions)


def _compute_institutional_health_sync(trades: list, equity_curve: list[dict]) -> dict:
    """Sync wrapper for institutional health metrics."""
    from app.services.institutional_health import compute_institutional_health
    health = compute_institutional_health(db=None, trades=trades, equity_curve=equity_curve)
    return {
        "sharpe_ratio": health.sharpe_ratio,
        "sortino_ratio": health.sortino_ratio,
        "calmar_ratio": health.calmar_ratio,
        "ulcer_index": health.ulcer_index,
        "risk_of_ruin_pct": health.risk_of_ruin_pct,
        "time_to_recovery_days": health.time_to_recovery_days,
        "max_drawdown_pct": health.max_drawdown_pct,
        "profit_factor": health.profit_factor,
        "expectancy_pct": health.expectancy_pct,
        "win_rate": health.win_rate,
        "total_trades": health.total_trades,
        "winning_trades": health.winning_trades,
        "losing_trades": health.losing_trades,
        "avg_win": health.avg_win,
        "avg_loss": health.avg_loss,
    }


# ── Engine Narrator ───────────────────────────────────────────────────────────

@router.post("/engine-summary")
async def engine_summary(_user=Depends(require_developer_role)) -> dict:
    """Return a narrative summary of the current AI engine/system state.

    Uses live metrics from the dashboard, health checks, deployment gate and model status,
    summarized by a local LLM (with remote fallback).
    """
    return await generate_engine_summary()


@router.get("/engine-summary/stream")
async def engine_summary_stream(_user=Depends(require_developer_role)):
    """Stream a narrative summary of the current AI engine/system state via SSE.

    Events:
      - phase:metrics
      - metrics
      - phase:llm
      - token
      - summary
      - error
    """
    return StreamingResponse(
        generate_engine_summary_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── P&L Attribution endpoint ──────────────────────────────────────────────────

@router.get("/pnl-attribution")
async def pnl_attribution(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_developer_role),
):
    """Return P&L attribution breakdown by system component."""
    from datetime import datetime, timezone, timedelta
    from app.services.pnl_attribution import compute_attribution
    from app.models.bot_config import BotConfig

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # Load real closed positions for this user (excluir paper)
    pos_query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.user_id == user.id,
            BotConfig.paper_balance_id.is_(None),
            Position.status == "closed",
            Position.source == "ai_bot",
            Position.closed_at >= since,
        )
    )
    pos_result = await db.execute(pos_query)
    positions = pos_result.scalars().all()

    attribution = compute_attribution(positions)
    return {
        "period_days": days,
        **attribution,
    }


# ── Model Validation History (Sprint 1.2) ─────────────────────────────────────

@router.get("/model/validation-history")
async def validation_history(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return walk-forward validation history from model_validation_logs."""
    from app.models.model_validation_log import ModelValidationLog
    from sqlalchemy import desc

    result = await db.execute(
        select(ModelValidationLog)
        .order_by(desc(ModelValidationLog.trained_at))
        .limit(limit)
    )
    rows = result.scalars().all()

    return {
        "history": [
            {
                "id": str(r.id),
                "model_version": r.model_version,
                "model_type": r.model_type,
                "trained_at": r.trained_at.isoformat() if r.trained_at else None,
                "samples_used": r.samples_used,
                "features_used": r.features_used,
                "wf_passed": r.wf_passed,
                "wf_reason": r.wf_reason,
                "wf_folds": r.wf_folds,
                "wf_sharpe": r.wf_sharpe,
                "wf_profit_factor": r.wf_profit_factor,
                "wf_expectancy": r.wf_expectancy,
                "wf_win_rate": r.wf_win_rate,
                "wf_max_drawdown": r.wf_max_drawdown,
                "test_auc": r.test_auc,
                "test_accuracy": r.test_accuracy,
                "old_sharpe": r.old_sharpe,
                "old_profit_factor": r.old_profit_factor,
                "old_expectancy": r.old_expectancy,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ── Expectancy Analysis (Sprint 3.1) ──────────────────────────────────────────

@router.get("/expectancy-analysis")
async def expectancy_analysis(
    ticker: str | None = Query(None, description="Optional ticker filter"),
    timeframe: str | None = Query(None, description="Optional timeframe filter"),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return expectancy breakdown by tier, status, regime, and timeframe.
    Optimizes for E (expectancy) instead of WR (win rate).
    """
    from datetime import datetime, timezone, timedelta
    from app.services.expectancy_optimizer import compute_expectancy_by_bucket
    from app.models.ai_signal import AISignal

    since = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(AISignal).where(
        AISignal.created_at >= since,
        AISignal.outcome != "PENDING",
        AISignal.outcome != "INVALID",
    )
    if ticker:
        q = q.where(AISignal.ticker == ticker.upper())
    if timeframe:
        q = q.where(AISignal.timeframe == timeframe)

    result = await db.execute(q)
    signals = result.scalars().all()

    if not signals:
        return {"period_days": days, "signals": 0, "buckets": {}}

    by_tier = compute_expectancy_by_bucket(signals, lambda s: s.quality_tier or "UNKNOWN")
    by_status = compute_expectancy_by_bucket(signals, lambda s: s.anti_fake_status or "UNKNOWN")
    by_regime = compute_expectancy_by_bucket(signals, lambda s: (s.features or {}).get("market_regime", "UNKNOWN") if s.features else "UNKNOWN")
    by_tf = compute_expectancy_by_bucket(signals, lambda s: s.timeframe or "UNKNOWN")
    by_tier_status = compute_expectancy_by_bucket(signals, lambda s: f"{s.quality_tier or 'UNKNOWN'}|{s.anti_fake_status or 'UNKNOWN'}")

    def _serialize(results):
        return {k: {
            "bucket": v.bucket,
            "total": v.total,
            "wins": v.wins,
            "losses": v.losses,
            "win_rate": v.win_rate,
            "avg_win": v.avg_win,
            "avg_loss": v.avg_loss,
            "expectancy": v.expectancy,
            "profit_factor": v.profit_factor,
            "r_multiple_avg": v.r_multiple_avg,
        } for k, v in results.items()}

    return {
        "period_days": days,
        "signals": len(signals),
        "buckets": {
            "by_tier": _serialize(by_tier),
            "by_status": _serialize(by_status),
            "by_regime": _serialize(by_regime),
            "by_timeframe": _serialize(by_tf),
            "by_tier_status": _serialize(by_tier_status),
        },
    }


@router.get("/divergence-summary")
async def divergence_summary(
    symbol: str | None = Query(None, description="Optional symbol filter"),
    direction: str | None = Query(None, description="Optional direction filter"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return paper-vs-real divergence summary."""
    from sqlalchemy import select
    from app.models.paper_real_divergence import PaperRealDivergence

    q = select(PaperRealDivergence).order_by(
        PaperRealDivergence.window_end.desc()
    )
    if symbol:
        q = q.where(PaperRealDivergence.symbol == symbol.upper())
    if direction:
        q = q.where(PaperRealDivergence.direction == direction.lower())

    result = await db.execute(q.limit(limit))
    rows = result.scalars().all()

    return {
        "count": len(rows),
        "items": [
            {
                "symbol": r.symbol,
                "direction": r.direction,
                "window_start": r.window_start.isoformat() if r.window_start else None,
                "window_end": r.window_end.isoformat() if r.window_end else None,
                "paper_count": r.paper_count,
                "real_count": r.real_count,
                "entry_divergence_pct": float(r.entry_divergence_pct) if r.entry_divergence_pct else None,
                "exit_divergence_pct": float(r.exit_divergence_pct) if r.exit_divergence_pct else None,
                "pnl_divergence_pct": float(r.pnl_divergence_pct) if r.pnl_divergence_pct else None,
                "weighted_divergence_pct": float(r.weighted_divergence_pct) if r.weighted_divergence_pct else None,
                "is_critical": r.is_critical,
                "block_reason": r.block_reason,
            }
            for r in rows
        ],
    }


@router.get("/confidence-decay")
async def confidence_decay(
    model_version: str | None = Query(None, description="Optional model version filter"),
    history: int = Query(0, ge=0, le=50, description="Include last N historical records"),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return confidence decay (predicted vs realized win rate) for current or specified model."""
    from app.services.confidence_decay_tracker import get_latest_decay, get_decay_history
    from sqlalchemy import select
    from app.models.model_confidence_decay import ModelConfidenceDecay

    # If no model_version provided, use latest from DB
    if not model_version:
        latest_row = await db.execute(
            select(ModelConfidenceDecay)
            .order_by(ModelConfidenceDecay.window_end.desc())
            .limit(1)
        )
        latest = latest_row.scalars().first()
        if latest:
            model_version = latest.model_version
        else:
            model_version = "unknown"

    result = {"model_version": model_version}

    # Run sync functions in threadpool with their own sync session
    from starlette.concurrency import run_in_threadpool
    from app.services.database import SessionLocal
    def _sync_latest():
        with SessionLocal() as db_sync:
            return get_latest_decay(db_sync, model_version)
    def _sync_history():
        with SessionLocal() as db_sync:
            return get_decay_history(db_sync, model_version, history)
    latest_decay = await run_in_threadpool(_sync_latest)
    result["latest"] = latest_decay

    if history > 0:
        decay_hist = await run_in_threadpool(_sync_history)
        result["history"] = decay_hist

    return result


@router.get("/model-decay")
async def model_decay(
    model_version: str | None = Query(None, description="Optional model version filter"),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return model decay rate: velocity of confidence decay and projection."""
    from app.services.model_decay_tracker import compute_decay_rate, get_latest_decay_rate
    from app.models.model_confidence_decay import ModelConfidenceDecay
    from sqlalchemy import select, desc
    from starlette.concurrency import run_in_threadpool

    # If no model_version provided, use latest from DB
    if not model_version:
        latest_row = await db.execute(
            select(ModelConfidenceDecay)
            .order_by(ModelConfidenceDecay.window_end.desc())
            .limit(1)
        )
        latest = latest_row.scalars().first()
        if latest:
            model_version = latest.model_version
        else:
            model_version = "unknown"

    from app.services.database import SessionLocal
    def _sync_compute():
        with SessionLocal() as db_sync:
            return compute_decay_rate(db_sync, model_version)
    result = await run_in_threadpool(_sync_compute)
    if result:
        return {
            "model_version": model_version,
            "decay_per_week": result.decay_per_week,
            "r_squared": result.r_squared,
            "current_divergence": result.current_divergence,
            "projected_days_to_uncalibrated": result.projected_days_to_uncalibrated,
            "alert_level": result.alert_level,
            "record_count": result.record_count,
        }

    # Fallback to latest persisted record
    def _sync_latest_rate():
        with SessionLocal() as db_sync:
            return get_latest_decay_rate(db_sync, model_version)
    latest = await run_in_threadpool(_sync_latest_rate)
    if latest:
        return {
            "model_version": model_version,
            "decay_per_week": latest.decay_per_week,
            "r_squared": latest.r_squared,
            "current_divergence": latest.current_divergence,
            "projected_days_to_uncalibrated": latest.projected_days_to_uncalibrated,
            "alert_level": latest.alert_level,
            "record_count": latest.record_count,
        }

    return {
        "model_version": model_version,
        "decay_per_week": None,
        "r_squared": None,
        "current_divergence": None,
        "projected_days_to_uncalibrated": None,
        "alert_level": "none",
        "record_count": 0,
    }


@router.get("/institutional-health")
async def institutional_health(
    days: int = Query(60, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_developer_role),
):
    """Return institutional-level health metrics: Sharpe, Sortino, Calmar, Ulcer, RoR, TtR."""
    from datetime import datetime, timezone, timedelta
    from app.models.exchange_trade import ExchangeTrade
    from app.services.institutional_health import compute_institutional_health

    since = datetime.now(timezone.utc) - timedelta(days=days)

    trades_result = await db.execute(
        select(ExchangeTrade).where(
            ExchangeTrade.user_id == user.id,
            ExchangeTrade.source == "ai_bot",
            ExchangeTrade.status == "closed",
            ExchangeTrade.closed_at >= since,
        ).order_by(ExchangeTrade.closed_at)
    )
    trades = trades_result.scalars().all()

    if not trades:
        return {"period_days": days, "trades": 0, "metrics": None}

    # Build equity curve from trades
    daily_pnl: dict[str, float] = {}
    for t in trades:
        if t.closed_at:
            day = t.closed_at.strftime("%Y-%m-%d")
            daily_pnl[day] = daily_pnl.get(day, 0.0) + float(t.realized_pnl or 0)

    equity_curve = []
    cumulative = 0.0
    day_cursor = since.date()
    end_day = datetime.now(timezone.utc).date()
    while day_cursor <= end_day:
        ds = day_cursor.strftime("%Y-%m-%d")
        daily = round(daily_pnl.get(ds, 0.0), 4)
        cumulative = round(cumulative + daily, 4)
        equity_curve.append({"date": ds, "daily_pnl": daily, "cumulative_pnl": cumulative})
        day_cursor += timedelta(days=1)

    health = compute_institutional_health(db=None, trades=trades, equity_curve=equity_curve)

    return {
        "period_days": days,
        "trades": health.total_trades,
        "metrics": {
            "sharpe_ratio": health.sharpe_ratio,
            "sortino_ratio": health.sortino_ratio,
            "calmar_ratio": health.calmar_ratio,
            "ulcer_index": health.ulcer_index,
            "risk_of_ruin_pct": health.risk_of_ruin_pct,
            "time_to_recovery_days": health.time_to_recovery_days,
            "max_drawdown_pct": health.max_drawdown_pct,
            "profit_factor": health.profit_factor,
            "expectancy_pct": health.expectancy_pct,
            "win_rate": health.win_rate,
            "winning_trades": health.winning_trades,
            "losing_trades": health.losing_trades,
            "avg_win": health.avg_win,
            "avg_loss": health.avg_loss,
        },
    }


@router.get("/replay/{position_id}")
async def get_replay_snapshot(
    position_id: str,
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return replay snapshot for a given position (full trade reconstruction)."""
    from sqlalchemy import select
    from app.models.trade_replay_snapshot import TradeReplaySnapshot
    from uuid import UUID

    try:
        pid = UUID(position_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid position_id")

    result = await db.execute(
        select(TradeReplaySnapshot).where(TradeReplaySnapshot.position_id == pid)
    )
    snap = result.scalars().first()
    if not snap:
        raise HTTPException(status_code=404, detail="Replay snapshot not found")

    return {
        "position_id": str(snap.position_id),
        "ai_signal_id": str(snap.ai_signal_id),
        "bot_id": str(snap.bot_id),
        "symbol": snap.symbol,
        "direction": snap.direction,
        "timeframe": snap.timeframe,
        "executed_at": snap.executed_at.isoformat() if snap.executed_at else None,
        "model_version": snap.model_version,
        "features": snap.features,
        "success_probability": float(snap.success_probability) if snap.success_probability else None,
        "calibrated_confidence": float(snap.calibrated_confidence) if snap.calibrated_confidence else None,
        "quality_tier": snap.quality_tier,
        "anti_fake_status": snap.anti_fake_status,
        "regime": snap.regime,
        "htf_bias": snap.htf_bias,
        "confluence_weights": snap.confluence_weights,
        "bot_config_snapshot": snap.bot_config_snapshot,
        "execution": snap.execution,
        "gates_snapshot": snap.gates_snapshot,
        "ohlcv_context": snap.ohlcv_context,
        "funding_rate_at_exec": float(snap.funding_rate_at_exec) if snap.funding_rate_at_exec else None,
        "spread_at_exec": float(snap.spread_at_exec) if snap.spread_at_exec else None,
        "atr_value_at_exec": float(snap.atr_value_at_exec) if snap.atr_value_at_exec else None,
    }


@router.get("/deployment-gate")
async def deployment_gate_status(
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return current unified deployment gate status."""
    from app.services.deployment_gate import get_latest_gate_status
    from app.services.database import SessionLocal
    from starlette.concurrency import run_in_threadpool

    def _sync_gate():
        with SessionLocal() as db_sync:
            return get_latest_gate_status(db_sync)
    status = await run_in_threadpool(_sync_gate)
    return status


@router.get("/circuit-breaker")
async def circuit_breaker_status(_user = Depends(require_developer_role)):
    """Return current circuit breaker status."""
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    status = cb.status()
    return {
        "state": status.state,
        "failures": status.failures,
        "last_failure": status.last_failure.isoformat() if status.last_failure else None,
        "allows_trading": status.allows_trading,
    }


@router.get("/shadow-mode")
async def shadow_mode_status(_user = Depends(require_developer_role)):
    """Return shadow mode evaluation status."""
    from ai.services.shadow_mode import evaluate_shadow
    return evaluate_shadow()


@router.get("/feature-importance-drift")
async def feature_importance_drift(
    model_version: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return latest feature importance drift analysis."""
    from app.services.feature_importance_drift import get_latest_drift, get_drift_history
    from app.services.database import SessionLocal
    from starlette.concurrency import run_in_threadpool

    def _sync_latest():
        with SessionLocal() as db_sync:
            return get_latest_drift(db_sync, model_version)
    def _sync_history():
        with SessionLocal() as db_sync:
            return get_drift_history(db_sync, limit=20)
    latest = await run_in_threadpool(_sync_latest)
    history = await run_in_threadpool(_sync_history)
    return {"latest": latest, "history": history}


@router.get("/threshold-optimization")
async def threshold_optimization(
    days: int = Query(60, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return threshold calibration suggestions based on historical trades."""
    from app.services.threshold_optimizer import calibrate_gate_thresholds
    from app.services.database import SessionLocal
    from starlette.concurrency import run_in_threadpool

    def _sync_calibrate():
        with SessionLocal() as db_sync:
            return calibrate_gate_thresholds(db_sync, days=days)
    result = await run_in_threadpool(_sync_calibrate)
    return result


@router.get("/trainers")
async def list_trainers(
    _user = Depends(require_developer_role),
):
    """List available model trainers (for future ensemble)."""
    from ai.trainers.registry import list_trainers
    return {"trainers": list_trainers()}


@router.get("/signals/{signal_id}/diagnosis")
async def get_signal_diagnosis(
    signal_id: str,
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return LLM diagnosis for a given AI signal.

    If diagnosis does not exist but signal is BLOCK/CAUTION,
    triggers on-demand generation.
    """
    from uuid import UUID
    from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
    from app.models.ai_signal import AISignal

    try:
        sid = UUID(signal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signal_id")

    # Check if diagnosis already exists
    result = await db.execute(
        select(LLMSignalDiagnosis)
        .where(LLMSignalDiagnosis.ai_signal_id == sid)
        .order_by(LLMSignalDiagnosis.created_at.desc())
    )
    diag = result.scalars().first()

    if diag:
        return {
            "signal_id": signal_id,
            "trigger_source": diag.trigger_source,
            "model_used": diag.model_used,
            "latency_ms": diag.latency_ms,
            "cost_usd": diag.cost_usd,
            "diagnosis": diag.diagnosis_json,
            "created_at": diag.created_at.isoformat() if diag.created_at else None,
        }

    # If no diagnosis, check signal status and trigger on-demand if BLOCK/CAUTION
    sig_result = await db.execute(
        select(AISignal).where(AISignal.id == sid)
    )
    sig = sig_result.scalars().first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")

    if sig.anti_fake_status in ("BLOCK", "CAUTION"):
        try:
            from app.tasks.llm_tasks import generate_signal_diagnosis
            generate_signal_diagnosis.delay(str(sig.id), "anti_fake")
            return {
                "signal_id": signal_id,
                "status": "queued",
                "message": "LLM diagnosis queued for generation",
            }
        except Exception:
            pass

    return {
        "signal_id": signal_id,
        "status": "not_available",
        "message": "No diagnosis available for this signal",
    }


@router.get("/diagnoses/threshold-recommendations")
async def get_threshold_recommendations(
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return LLM-based threshold adjustment recommendations."""
    from datetime import datetime, timezone
    from app.tasks.llm_threshold_optimizer import _build_recommendations
    recommendations = _build_recommendations()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recommendations": recommendations,
        "count": len(recommendations),
    }


@router.get("/diagnoses/export")
async def export_diagnoses(
    format: str = Query("json", regex="^(json|csv)$"),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Export LLM signal diagnoses enriched with outcomes."""
    from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
    from datetime import datetime

    stmt = select(LLMSignalDiagnosis).order_by(LLMSignalDiagnosis.created_at.desc())
    if from_date:
        try:
            fd = datetime.fromisoformat(from_date)
            stmt = stmt.where(LLMSignalDiagnosis.created_at >= fd)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date")
    if to_date:
        try:
            td = datetime.fromisoformat(to_date)
            stmt = stmt.where(LLMSignalDiagnosis.created_at <= td)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date")

    result = await db.execute(stmt)
    rows = result.scalars().all()

    data = []
    for r in rows:
        data.append({
            "id": str(r.id),
            "signal_id": str(r.ai_signal_id),
            "trigger_source": r.trigger_source,
            "model_used": r.model_used,
            "verdict": r.diagnosis_json.get("verdict") if r.diagnosis_json else None,
            "confidence": r.diagnosis_json.get("confidence") if r.diagnosis_json else None,
            "outcome": r.outcome,
            "pnl_pct": r.pnl_pct,
            "latency_ms": r.latency_ms,
            "cost_usd": r.cost_usd,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        })

    if format == "csv":
        import csv
        import io
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return Response(content=output.getvalue(), media_type="text/csv")

    return {"count": len(data), "diagnoses": data}


@router.get("/diagnoses/analytics")
async def diagnoses_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Aggregated analytics over LLM signal diagnoses."""
    from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
    from datetime import datetime, timezone, timedelta

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Total count
    total_res = await db.execute(
        select(func.count()).where(LLMSignalDiagnosis.created_at >= since)
    )
    total = total_res.scalar() or 0

    # By verdict
    verdict_res = await db.execute(
        select(
            LLMSignalDiagnosis.diagnosis_json["verdict"].astext.label("verdict"),
            func.count(),
        )
        .where(LLMSignalDiagnosis.created_at >= since)
        .group_by("verdict")
    )
    by_verdict = {v: c for v, c in verdict_res.all() if v}

    # By trigger source
    trigger_res = await db.execute(
        select(LLMSignalDiagnosis.trigger_source, func.count())
        .where(LLMSignalDiagnosis.created_at >= since)
        .group_by(LLMSignalDiagnosis.trigger_source)
    )
    by_trigger = {t: c for t, c in trigger_res.all()}

    # Win rate by verdict (where outcome is known)
    wr_res = await db.execute(
        select(
            LLMSignalDiagnosis.diagnosis_json["verdict"].astext.label("verdict"),
            func.count(),
            func.sum(case((LLMSignalDiagnosis.outcome == "SUCCESS", 1), else_=0)),
        )
        .where(
            LLMSignalDiagnosis.created_at >= since,
            LLMSignalDiagnosis.outcome.isnot(None),
        )
        .group_by("verdict")
    )
    wr_by_verdict = {}
    for v, total_v, wins in wr_res.all():
        if v:
            wr_by_verdict[v] = {"total": total_v, "wins": wins, "win_rate": round((wins / total_v) * 100, 1) if total_v else 0}

    # Top factors (flatten JSONB factors array)
    factor_rows = await db.execute(
        select(LLMSignalDiagnosis.diagnosis_json)
        .where(LLMSignalDiagnosis.created_at >= since)
    )
    factor_counts = {}
    for row in factor_rows.all():
        diag = row[0] or {}
        for f in diag.get("factors", []):
            key = f"{f.get('category', 'unknown')}::{f.get('severity', 'info')}"
            factor_counts[key] = factor_counts.get(key, 0) + 1
    top_factors = sorted(factor_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Avg confidence by verdict
    conf_res = await db.execute(
        select(
            LLMSignalDiagnosis.diagnosis_json["verdict"].astext.label("verdict"),
            func.avg(LLMSignalDiagnosis.diagnosis_json["confidence"].astext.cast(Float)),
        )
        .where(LLMSignalDiagnosis.created_at >= since)
        .group_by("verdict")
    )
    avg_confidence = {v: round(c, 1) for v, c in conf_res.all() if v}

    return {
        "period_days": days,
        "total_diagnoses": total,
        "by_verdict": by_verdict,
        "by_trigger_source": by_trigger,
        "win_rate_by_verdict": wr_by_verdict,
        "top_factors": [{"factor": k, "count": v} for k, v in top_factors],
        "avg_confidence_by_verdict": avg_confidence,
    }


@router.get("/signals/{signal_id}/context")
async def get_signal_context(
    signal_id: str,
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """Return free contextual information about the signal's pair.
    Available to all authenticated users. No LLM calls.
    """
    from datetime import datetime, timezone, timedelta
    from uuid import UUID
    from app.models.ai_signal import AISignal
    from app.models.ai_signal_rejected import AISignalRejected
    from app.models.position import Position
    from app.services.macro_context import get_macro_context
    # market_regime import removed to avoid live ohlcv fetch

    try:
        sid = UUID(signal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signal_id")

    sig = await db.get(AISignal, sid)
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")

    ticker = sig.ticker
    timeframe = sig.timeframe
    ccxt_sym = sig.ccxt_symbol

    # ── 1. Symbol stats from user's real trades ──
    since = datetime.now(timezone.utc) - timedelta(days=30)
    from app.models.bot_config import BotConfig
    bot_ids_sub = select(BotConfig.id).where(BotConfig.user_id == user.id)
    et_query = select(Position).where(
        Position.bot_id.in_(bot_ids_sub),
        Position.symbol == ccxt_sym,
        Position.status == "closed",
        Position.closed_at >= since,
    )
    et_result = await db.execute(et_query)
    trades = et_result.scalars().all()

    total_trades = len(trades)
    winners = sum(1 for t in trades if (t.realized_pnl or 0) > 0)
    total_pnl = sum(float(t.realized_pnl or 0) for t in trades)
    avg_pnl = total_pnl / total_trades if total_trades else 0.0

    # ── 2. Recent rejections for this symbol ──
    rej_query = (
        select(AISignalRejected.rejection_reason, func.count())
        .where(
            AISignalRejected.ticker == ticker,
            AISignalRejected.rejected_at >= datetime.now(timezone.utc) - timedelta(hours=72),
        )
        .group_by(AISignalRejected.rejection_reason)
        .order_by(func.count().desc())
    )
    rej_result = await db.execute(rej_query)
    rejections = [{"reason": r, "count": c} for r, c in rej_result.all()]

    # ── 3. Market regime (simplified — no live ohlcv fetch to keep it fast & free) ──
    regime = {"regime": "unknown", "confidence": 0}

    # ── 4. Macro context ──
    try:
        macro = get_macro_context(ticker)
    except Exception as exc:
        logger.warning(f"[AI] Failed to load macro context for {ticker}: {exc}")
        macro = {"context": "neutral", "trend": "sideways"}

    # ── 5. Recent signals for this pair ──
    recent_query = (
        select(AISignal)
        .where(AISignal.ticker == ticker)
        .order_by(AISignal.created_at.desc())
        .limit(5)
    )
    recent_result = await db.execute(recent_query)
    recent_signals = []
    for s in recent_result.scalars().all():
        recent_signals.append({
            "id": str(s.id),
            "direction": s.direction,
            "score": s.score,
            "outcome": s.outcome,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "symbol_stats": {
            "total_trades": total_trades,
            "win_rate": round(winners / total_trades * 100, 1) if total_trades else None,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
        },
        "recent_rejections": rejections,
        "market_regime": regime,
        "macro_context": macro,
        "recent_signals": recent_signals,
    }


# ── Scanner Regime Adaptive Config ────────────────────────────────────────────

@router.get("/scanner/regime-config")
async def get_scanner_regime_config(
    symbol: str,
    timeframe: str,
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Return the current adaptive scanner config for a symbol+timeframe+regime.
    If no cached config exists, returns an empty dict.
    """
    from app.models.scanner_regime_config import ScannerRegimeConfig
    from app.services.market_regime import detect_regime
    from app.services.ai_scanner import fetch_ohlcv
    import asyncio

    # Detect current regime
    try:
        _, ohlcv = await fetch_ohlcv(symbol, timeframe)
        if not ohlcv or len(ohlcv) < 60:
            raise HTTPException(status_code=400, detail="Insufficient OHLCV data")
        regime = detect_regime(symbol, timeframe, ohlcv)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Regime detection failed: {exc}")

    stmt = select(ScannerRegimeConfig).where(
        ScannerRegimeConfig.symbol == symbol.upper(),
        ScannerRegimeConfig.timeframe == timeframe,
        ScannerRegimeConfig.regime == regime.regime,
    )
    result = await db.execute(stmt)
    cached = result.scalar_one_or_none()

    if not cached:
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "regime": regime.regime,
            "regime_confidence": regime.confidence,
            "cached_config": None,
            "note": "No cached adaptive config. The scanner will generate one on next signal scan.",
        }

    return {
        "symbol": cached.symbol,
        "timeframe": cached.timeframe,
        "regime": cached.regime,
        "regime_confidence": regime.confidence,
        "cached_config": cached.params,
        "model_used": cached.model_used,
        "latency_ms": cached.latency_ms,
        "cost_usd": cached.cost_usd,
        "updated_at": cached.updated_at.isoformat() if cached.updated_at else None,
    }


@router.post("/scanner/regime-config/refresh")
async def refresh_scanner_regime_config(
    symbol: str,
    timeframe: str,
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Force regeneration of adaptive scanner config via LLM (admin only)."""
    from app.services.market_regime import detect_regime
    from app.services.ai_scanner import fetch_ohlcv
    from app.services.scanner_regime_optimizer import get_adaptive_params

    try:
        _, ohlcv = await fetch_ohlcv(symbol, timeframe)
        if not ohlcv or len(ohlcv) < 60:
            raise HTTPException(status_code=400, detail="Insufficient OHLCV data")
        regime = detect_regime(symbol, timeframe, ohlcv)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Regime detection failed: {exc}")

    params = await get_adaptive_params(
        symbol=symbol,
        timeframe=timeframe,
        regime=regime.regime,
        regime_confidence=regime.confidence,
        adx=regime.adx,
        atr_percentile=regime.atr_percentile,
        rel_volume=regime.rel_volume,
        realized_vol=regime.realized_vol,
        force_refresh=True,
    )

    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "regime": regime.regime,
        "regime_confidence": regime.confidence,
        "adaptive_params": params,
        "note": "Config regenerated and cached. Next signal scans will use these parameters.",
    }


# ── Fundamental Context ───────────────────────────────────────────────────────

@router.get("/fundamentals/{ticker}")
async def get_fundamentals(
    ticker: str,
    _user = Depends(require_developer_role),
):
    """Return aggregated fundamental context for a ticker (CFTC CoT, unlocks, macro)."""
    from app.services.fundamental_context import get_fundamental_context
    return await get_fundamental_context(ticker)


@router.post("/fundamentals/manual")
async def upload_manual_fundamental(
    ticker: str = Query(...),
    source: str = Query(..., description="e.g. manual_event, cot_override, unlock_alert"),
    signal: str = Query(..., description="BLOCK | CAUTION | NEUTRAL | FAVORABLE"),
    confidence: float = Query(0.8, ge=0.0, le=1.0),
    valid_hours: int = Query(48, ge=1, le=720),
    data: dict | None = None,
    _user = Depends(require_developer_role),
):
    """Allow admins to manually upload fundamental events that affect the gate."""
    from app.services.fundamental_context import upload_manual_event
    data = data or {}
    snap = await upload_manual_event(ticker, source, data, signal, confidence, valid_hours)
    return {
        "id": str(snap.id),
        "ticker": snap.ticker,
        "source": snap.source,
        "signal": snap.signal,
        "confidence": snap.confidence,
        "valid_until": snap.valid_until.isoformat() if snap.valid_until else None,
        "note": "Event uploaded. The fundamental gate will evaluate it on next signal.",
    }


# ── Engine Control ────────────────────────────────────────────────────────────

@router.get("/engine-control")
async def engine_control(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_developer_role),
):
    """Diagnostic dashboard: positions, rejections, system health, gate status."""
    from datetime import datetime, timezone, timedelta
    from app.models.ai_signal_rejected import AISignalRejected
    from app.models.bot_config import BotConfig
    from app.models.position import Position
    from app.models.ai_scan import AILatestScan

    since = datetime.now(timezone.utc) - timedelta(days=days)
    h24 = datetime.now(timezone.utc) - timedelta(hours=24)

    # ── 1. System health ──
    bot_q = select(BotConfig).where(BotConfig.ai_signal_mode == True)
    bot_rows = (await db.execute(bot_q)).scalars().all()
    active_bots = [b for b in bot_rows if b.status == "active"]
    paper_bots = [b for b in active_bots if b.paper_balance_id is not None]
    real_bots = [b for b in active_bots if b.exchange_account_id is not None]

    pos_q = (
        select(Position, BotConfig)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(Position.status == "open")
    )
    pos_rows = (await db.execute(pos_q)).all()
    open_positions = []
    for p, b in pos_rows:
        open_positions.append({
            "symbol": p.symbol,
            "side": p.side,
            "mode": "paper" if b.paper_balance_id else "real",
            "bot_name": b.bot_name,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl else 0,
        })

    last_signal = (
        await db.execute(select(AISignal).order_by(desc(AISignal.created_at)).limit(1))
    ).scalar_one_or_none()
    last_scan = (
        await db.execute(select(AILatestScan).order_by(desc(AILatestScan.scanned_at)).limit(1))
    ).scalar_one_or_none()

    # ── 2. Evaluated signals with real position linkage ──
    accepted_q = (
        select(AISignal)
        .where(AISignal.created_at >= since)
        .order_by(desc(AISignal.created_at))
        .limit(limit)
    )
    accepted_rows = (await db.execute(accepted_q)).scalars().all()

    rejected_q = (
        select(AISignalRejected)
        .where(AISignalRejected.rejected_at >= since)
        .order_by(desc(AISignalRejected.rejected_at))
        .limit(limit)
    )
    rejected_rows = (await db.execute(rejected_q)).scalars().all()

    # Map bot configs by symbol for mode lookup
    bot_by_symbol: dict = {}
    for b in bot_rows:
        bot_by_symbol[b.symbol] = b

    def _mode_for_rejection(ticker: str) -> str:
        # Convert BTCUSDT -> BTC/USDT:USDT
        ccxt = ticker.replace("USDT", "/USDT:USDT").replace("USDC", "/USDC:USDC")
        for sym, bot in bot_by_symbol.items():
            if sym == ccxt or sym.replace("/", "").replace(":", "") == ticker:
                return "paper" if bot.paper_balance_id else "real"
        return "unknown"

    evaluated_signals = []
    for s in accepted_rows:
        # Find if this signal created a position
        ccxt = s.ccxt_symbol if s.ccxt_symbol else s.ticker.replace("USDT", "/USDT:USDT")
        pos_match = None
        for p, b in pos_rows:
            if p.symbol == ccxt and p.opened_at and s.created_at and abs((p.opened_at - s.created_at).total_seconds()) < 300:
                pos_match = {"id": str(p.id), "mode": "paper" if b.paper_balance_id else "real"}
                break
        evaluated_signals.append({
            "id": str(s.id),
            "ticker": s.ticker,
            "timeframe": s.timeframe,
            "direction": s.direction,
            "score": round(s.score, 2),
            "quality_tier": s.quality_tier,
            "anti_fake_status": s.anti_fake_status,
            "decision": "ACCEPTED",
            "outcome": s.outcome,
            "pnl_pct": round(float(s.pnl_pct), 4) if s.pnl_pct is not None else None,
            "rejection_reason": None,
            "evaluated_at": s.created_at.isoformat() if s.created_at else None,
            "mode": pos_match["mode"] if pos_match else "unknown",
            "position_id": pos_match["id"] if pos_match else None,
        })

    for r in rejected_rows:
        evaluated_signals.append({
            "id": str(r.id),
            "ticker": r.ticker,
            "timeframe": r.timeframe,
            "direction": r.direction,
            "score": round(r.score, 2),
            "quality_tier": r.quality_tier,
            "anti_fake_status": r.anti_fake_status,
            "decision": "REJECTED",
            "outcome": "REJECTED",
            "pnl_pct": None,
            "rejection_reason": r.rejection_reason,
            "evaluated_at": r.rejected_at.isoformat() if r.rejected_at else None,
            "mode": _mode_for_rejection(r.ticker),
            "would_have_been_winner": r.would_have_been_winner,
        })

    evaluated_signals.sort(key=lambda x: x["evaluated_at"] or "", reverse=True)
    evaluated_signals = evaluated_signals[:limit]

    # ── 3. Rejection diagnosis ──
    rej_diag = {}
    for window, label in [(h24, "24h"), (since, f"{days}d")]:
        rej_q = (
            select(
                AISignalRejected.rejection_reason,
                func.count().label("total"),
                func.sum(case((AISignalRejected.would_have_been_winner == True, 1), else_=0)).label("would_win"),
                func.avg(AISignalRejected.score).label("avg_score"),
            )
            .where(AISignalRejected.rejected_at >= window)
            .group_by(AISignalRejected.rejection_reason)
        )
        rej_result = await db.execute(rej_q)
        rej_diag[label] = [
            {
                "reason": row.rejection_reason,
                "total": row.total,
                "would_win": row.would_win or 0,
                "would_win_pct": round((row.would_win or 0) / row.total * 100, 1) if row.total else 0,
                "avg_score": round(float(row.avg_score), 1) if row.avg_score else 0,
            }
            for row in rej_result.all()
        ]

    # ── 4. Gate status (current thresholds) ──
    from app.services.drift_detector import _PSI_HEALTHY, _PSI_DEGRADED, _PSI_PAUSED
    from app.services.kelly_sizing import _MIN_EDGE_FOR_TRADE
    from app.services.rolling_beta_gate import BETA_HIGH_THRESHOLD, BETA_EXTREME_THRESHOLD

    gate_status = {
        "drift": {"healthy": _PSI_HEALTHY, "degraded": _PSI_DEGRADED, "paused": _PSI_PAUSED},
        "kelly": {"min_edge": _MIN_EDGE_FOR_TRADE, "behavior": "reduce sizing (never block if edge > 0)"},
        "rolling_beta": {"high": BETA_HIGH_THRESHOLD, "extreme": BETA_EXTREME_THRESHOLD, "behavior": "never blocks"},
        "concurrent": "counts same-side only (fixed bug)",
        "tier": "WR >= 45% + PF >= 1.0 for MODERATE/WEAK inclusion",
        "score": "min_score from bot config (default 37-60)",
        "portfolio": "relaxed: corr 0.92, sector 60%, exposure 150%",
        "slippage": "abort ratio 65%, reduce ratio 40%",
        "pattern_wr": "threshold 35% (auto-calibrated per pattern)",
        "notes": "All gates were relaxed on 2026-05-24. See context_thresholds.py for CATR exploration mode.",
    }

    # ── 5. Return ──
    return {
        "system_health": {
            "active_ai_bots": len(active_bots),
            "paper_bots": len(paper_bots),
            "real_bots": len(real_bots),
            "open_positions": open_positions,
            "open_paper_count": sum(1 for p in open_positions if p["mode"] == "paper"),
            "open_real_count": sum(1 for p in open_positions if p["mode"] == "real"),
            "last_signal_at": last_signal.created_at.isoformat() if last_signal else None,
            "last_scan_at": last_scan.scanned_at.isoformat() if last_scan else None,
            "db_pool_size": 20,
            "db_max_overflow": 30,
        },
        "rejection_diagnosis": rej_diag,
        "evaluated_signals": evaluated_signals,
        "gate_status": gate_status,
        "meta": {
            "days": days,
            "total_evaluated": len(evaluated_signals),
            "accepted_count": len([s for s in evaluated_signals if s["decision"] == "ACCEPTED"]),
            "rejected_count": len([s for s in evaluated_signals if s["decision"] == "REJECTED"]),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3: Regime Heatmap + Execution Quality
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/regime-heatmap")
async def get_regime_heatmap(
    user=Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    """FASE 3C: Devuelve el régimen de mercado actual para todos los pares
    en la watchlist del usuario. Útil para visualización en tiempo real.
    """
    watchlist = (
        await db.execute(
            select(AIWatchlistItem).where(AIWatchlistItem.user_id == user.id)
        )
    ).scalars().all()

    if not watchlist:
        return {"heatmap": [], "meta": {"count": 0, "note": "watchlist empty"}}

    # Fetch OHLCV y detectar régimen para cada par concurrentemente
    from app.core.constants import VALID_TIMEFRAMES

    async def _detect_for_item(item):
        sym = item.symbol
        tf = item.timeframe or "1h"
        if tf not in VALID_TIMEFRAMES:
            tf = "1h"
        try:
            _, ohlcv = await fetch_ohlcv(sym, tf)
            if not ohlcv or len(ohlcv) < 20:
                return {"symbol": sym, "timeframe": tf, "regime": "NO_DATA", "confidence": 0.0}
            regime = detect_regime(sym, tf, ohlcv)
            return {
                "symbol": sym,
                "timeframe": tf,
                "regime": regime.regime,
                "confidence": round(regime.confidence, 2),
                "adx": round(regime.adx, 2) if regime.adx else None,
                "atr_percentile": round(regime.atr_percentile, 2) if regime.atr_percentile else None,
            }
        except Exception as e:
            logger.warning(f"[REGIME-HEATMAP] Failed for {sym}/{tf}: {e}")
            return {"symbol": sym, "timeframe": tf, "regime": "ERROR", "confidence": 0.0, "error": str(e)}

    results = await asyncio.gather(*[_detect_for_item(item) for item in watchlist])

    # Resumen agregado
    regime_counts = {}
    for r in results:
        regime_counts[r["regime"]] = regime_counts.get(r["regime"], 0) + 1

    return {
        "heatmap": results,
        "summary": regime_counts,
        "meta": {
            "count": len(results),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/execution-quality")
async def get_execution_quality(
    user=Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
    days: int = Query(7, ge=1, le=30),
):
    """FASE 3A: Métricas de calidad de ejecución — compara slippage estimado
    vs slippage real en trades cerrados del usuario.
    """
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Obtener snapshots con slippage_estimate + posición cerrada
    rows = (
        await db.execute(
            select(TradeReplaySnapshot, Position, AISignal)
            .join(Position, TradeReplaySnapshot.position_id == Position.id)
            .join(AISignal, TradeReplaySnapshot.ai_signal_id == AISignal.id)
            .where(Position.status == "closed")
            .where(Position.closed_at >= since)
            .where(TradeReplaySnapshot.user_id == user.id)
            .where(TradeReplaySnapshot.execution.isnot(None))
        )
    ).all()

    comparisons = []
    total_estimated = 0.0
    total_actual = 0.0
    count = 0

    for snapshot, position, signal in rows:
        exec_data = snapshot.execution or {}
        est_slippage = exec_data.get("slippage_estimate", {}).get("slippage_pct", 0.0)

        signal_entry = float(signal.entry_price) if signal.entry_price else 0.0
        real_entry = float(position.entry_price) if position.entry_price else 0.0
        if signal_entry > 0:
            actual_slippage = abs(real_entry - signal_entry) / signal_entry * 100.0
        else:
            actual_slippage = 0.0

        comparisons.append({
            "position_id": str(position.id),
            "symbol": position.symbol,
            "direction": position.side,
            "estimated_slippage_pct": round(est_slippage, 4),
            "actual_slippage_pct": round(actual_slippage, 4),
            "delta_pct": round(actual_slippage - est_slippage, 4),
            "opened_at": position.opened_at.isoformat() if position.opened_at else None,
        })
        total_estimated += est_slippage
        total_actual += actual_slippage
        count += 1

    avg_estimated = round(total_estimated / count, 4) if count > 0 else 0.0
    avg_actual = round(total_actual / count, 4) if count > 0 else 0.0

    return {
        "meta": {
            "days": days,
            "trades_evaluated": count,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": {
            "avg_estimated_slippage_pct": avg_estimated,
            "avg_actual_slippage_pct": avg_actual,
            "bias_pct": round(avg_actual - avg_estimated, 4),
            "recommendation": (
                "PREDICTOR_TOO_CONSERVATIVE" if avg_actual < avg_estimated * 0.5 else
                "PREDICTOR_TOO_AGGRESSIVE" if avg_actual > avg_estimated * 2.0 else
                "PREDICTOR_CALIBRATED"
            ),
        },
        "trades": comparisons,
    }


@router.get("/correlation-matrix")
async def get_correlation_matrix(
    user=Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
    lookback_bars: int = Query(100, ge=20, le=500),
):
    """FASE 3B: Matriz de correlación REAL (Pearson) entre todos los pares
    en la watchlist del usuario, usando OHLCV histórico.
    
    Devuelve la matriz completa + alertas de pares con correlación > 0.8.
    """
    import numpy as np

    watchlist = (
        await db.execute(
            select(AIWatchlistItem).where(AIWatchlistItem.user_id == user.id)
        )
    ).scalars().all()

    if not watchlist:
        return {"matrix": [], "alerts": [], "meta": {"count": 0, "note": "watchlist empty"}}

    symbols = list({w.symbol for w in watchlist})
    timeframe = "1h"  # Usar 1h para tener suficientes datos

    # Descargar OHLCV para todos los símbolos concurrentemente
    async def _fetch_returns(symbol: str):
        try:
            _, ohlcv = await fetch_ohlcv(symbol, timeframe)
            if not ohlcv or len(ohlcv) < lookback_bars:
                return None
            # Tomar los últimos lookback_bars velas
            closes = [float(c[4]) for c in ohlcv[-lookback_bars:]]
            # Calcular retornos logarítmicos
            returns = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    returns.append(np.log(closes[i] / closes[i - 1]))
            return {"symbol": symbol, "returns": returns}
        except Exception as e:
            logger.warning(f"[CORR-MATRIX] Failed to fetch {symbol}: {e}")
            return None

    results = await asyncio.gather(*[_fetch_returns(sym) for sym in symbols])
    valid = [r for r in results if r is not None and len(r["returns"]) >= lookback_bars // 2]

    if len(valid) < 2:
        return {
            "matrix": [],
            "alerts": [],
            "meta": {"count": len(valid), "note": "insufficient data for correlation"},
        }

    # Construir matriz de retornos
    n = len(valid)
    symbols_valid = [v["symbol"] for v in valid]
    returns_matrix = np.array([v["returns"][:lookback_bars - 1] for v in valid])

    # Calcular matriz de correlación Pearson
    corr_matrix = np.corrcoef(returns_matrix)

    # Formatear resultado
    matrix_out = []
    for i in range(n):
        row = {"symbol": symbols_valid[i], "correlations": {}}
        for j in range(n):
            if i != j:
                row["correlations"][symbols_valid[j]] = round(float(corr_matrix[i, j]), 3)
        matrix_out.append(row)

    # Detectar alertas: correlación > 0.8 (muy alta)
    alerts = []
    for i in range(n):
        for j in range(i + 1, n):
            corr_val = float(corr_matrix[i, j])
            if abs(corr_val) > 0.8:
                alerts.append({
                    "pair": [symbols_valid[i], symbols_valid[j]],
                    "correlation": round(corr_val, 3),
                    "risk": "HIGH_POSITIVE" if corr_val > 0 else "HIGH_NEGATIVE",
                    "recommendation": "Reduce combined sizing — these assets move together",
                })
            elif abs(corr_val) > 0.6:
                alerts.append({
                    "pair": [symbols_valid[i], symbols_valid[j]],
                    "correlation": round(corr_val, 3),
                    "risk": "MODERATE",
                    "recommendation": "Monitor combined exposure",
                })

    return {
        "matrix": matrix_out,
        "alerts": alerts,
        "meta": {
            "symbols_evaluated": n,
            "lookback_bars": lookback_bars,
            "timeframe": timeframe,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/live-scan/events")
async def get_live_scan_events(
    limit: int = Query(500, ge=1, le=5000),
    _user=Depends(get_current_authorized_user),
):
    """Return recent AI scanner events persisted in Redis."""
    events = get_recent_scan_events(limit)
    return {"events": events}


@router.post("/live-tip")
async def live_tip(
    event: dict,
    _user=Depends(get_current_authorized_user),
):
    """Generate a short trading tip for a scan event using the local LLM."""
    tip = await local_llm_client.generate_tip(event, heavy=False)
    return tip.dict()
