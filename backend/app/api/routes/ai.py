"""AI confluence analysis endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.models.ai_signal import AISignal
from app.models.ai_scan import AIWatchlistItem, AILatestScan
from app.services.database import get_db
from app.services.ai_scanner import (
    build_signal, fetch_ohlcv, upsert_latest_scan,
    signal_to_dict, latest_scan_to_dict, htf_for,
)

router = APIRouter(prefix="/ai", tags=["ai"])


# ── Watchlist CRUD ────────────────────────────────────────────────────────────

@router.get("/watchlist")
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(AIWatchlistItem)
            .where(AIWatchlistItem.user_id == user.id)
            .order_by(AIWatchlistItem.symbol)
        )
    ).scalars().all()
    return [{"symbol": r.symbol, "timeframe": r.timeframe} for r in rows]


@router.post("/watchlist/sync")
async def sync_watchlist(
    items: list[dict],
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    """Replace the user's entire watchlist (called on every add/remove/TF change)."""
    await db.execute(delete(AIWatchlistItem).where(AIWatchlistItem.user_id == user.id))
    for item in items[:15]:
        sym = str(item.get("symbol", "")).strip().upper()
        tf  = str(item.get("timeframe", "1h")).strip()
        if sym:
            db.add(AIWatchlistItem(user_id=user.id, symbol=sym, timeframe=tf))
    await db.commit()
    return {"status": "ok", "count": len(items[:15])}


# ── Latest scan results ───────────────────────────────────────────────────────

@router.get("/latest-scans")
async def latest_scans(
    symbols: str = Query("", description="Comma-separated tickers; empty = all"),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
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
    _user = Depends(get_current_user),
):
    htf_tf = htf_for(timeframe)
    coros = [fetch_ohlcv(symbol, timeframe)]
    if htf_tf:
        coros.append(fetch_ohlcv(symbol, htf_tf))
    all_results = await asyncio.gather(*coros)
    sym, ohlcv = all_results[0]
    htf_ohlcv = all_results[1][1] if htf_tf else None

    if not ohlcv or len(ohlcv) < 50:
        raise HTTPException(400, "Error obteniendo velas o datos insuficientes")

    result_dict, sig = build_signal(symbol, timeframe, ohlcv, htf_ohlcv=htf_ohlcv)

    if sig:
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        await upsert_latest_scan(db, symbol, timeframe, result_dict, sig)
        await db.commit()
        from app.tasks.bot_activator_task import activate_signal
        activate_signal.delay(str(sig.id))
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
    _user = Depends(get_current_user),
):
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

    output = []
    for sym, ohlcv in ltf_fetches:
        if not ohlcv or len(ohlcv) < 50:
            output.append({"symbol": sym, "status": "ERROR"})
            continue

        result_dict, sig = build_signal(sym, timeframe, ohlcv, htf_ohlcv=htf_cache.get(sym))
        if sig:
            db.add(sig)
            await db.commit()
            await db.refresh(sig)
            await upsert_latest_scan(db, sym, timeframe, result_dict, sig)
            await db.commit()
            from app.tasks.bot_activator_task import activate_signal
            activate_signal.delay(str(sig.id))
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
    _user = Depends(get_current_user),
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
    _user = Depends(get_current_user),
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
    _user = Depends(get_current_user),
):
    rows = (await db.execute(select(AISignal))).scalars().all()
    by_ticker: dict = {}
    for s in rows:
        t = s.ticker
        if t not in by_ticker:
            by_ticker[t] = {"total": 0, "resolved": [], "scores": []}
        by_ticker[t]["total"] += 1
        by_ticker[t]["scores"].append(s.score)
        if s.outcome != "PENDING":
            by_ticker[t]["resolved"].append(s.outcome)
    result = {}
    for t, d in by_ticker.items():
        resolved = d["resolved"]
        wins = sum(1 for o in resolved if o == "SUCCESS")
        result[t] = {
            "total":     d["total"],
            "win_rate":  round(wins / len(resolved) * 100, 1) if resolved else None,
            "avg_score": round(sum(d["scores"]) / len(d["scores"]), 1) if d["scores"] else 0,
        }
    return result


# ── ICT live analysis (no DB write) ──────────────────────────────────────────

@router.get("/ict-analysis")
async def ict_analysis(
    symbol:    str = Query(...),
    timeframe: str = Query("1h"),
    _user = Depends(get_current_user),
):
    """Return last 100 candles + live ICT context. No DB writes."""
    htf_tf = htf_for(timeframe)
    coros = [fetch_ohlcv(symbol, timeframe)]
    if htf_tf:
        coros.append(fetch_ohlcv(symbol, htf_tf))
    all_results = await asyncio.gather(*coros)
    sym, ohlcv = all_results[0]
    htf_ohlcv = all_results[1][1] if htf_tf else None

    if not ohlcv or len(ohlcv) < 50:
        raise HTTPException(400, "Error obteniendo velas o datos insuficientes")

    result_dict, _ = build_signal(sym, timeframe, ohlcv, htf_ohlcv=htf_ohlcv)
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
    _user = Depends(get_current_user),
):
    from ai.registry import model_info, model_ready
    rows     = (await db.execute(select(AISignal))).scalars().all()
    resolved = [s for s in rows if s.outcome != "PENDING"]
    return {
        "model_ready":      model_ready(),
        "resolved_signals": len(resolved),
        "required_signals": 200,
        "progress_pct":     round(min(100, len(resolved) / 200 * 100), 1),
        **model_info(),
    }


@router.post("/model/train")
async def trigger_train(_user = Depends(get_current_user)):
    from app.tasks.ai_retrain_task import retrain_anti_fake
    task = retrain_anti_fake.delay()
    return {"status": "queued", "task_id": task.id}


# ── AI bots ───────────────────────────────────────────────────────────────────

@router.get("/bots")
async def list_ai_bots(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.bot_config import BotConfig
    rows = (
        await db.execute(
            select(BotConfig)
            .where(
                BotConfig.user_id == user.id,
                BotConfig.ai_signal_mode == True,
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
