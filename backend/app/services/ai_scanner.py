"""Core ICT/confluence scan logic — shared by API routes and background Celery task."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import ccxt.async_support as ccxt
from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ict_engine import analyze as ict_analyze
from app.engines.confluence_engine import analyze_confluence
from app.engines.signal_quality_engine import assess_quality
from app.models.ai_signal import AISignal
from app.models.ai_scan import AILatestScan
from ai import registry as anti_fake_registry
from ai import ensemble_registry

# NOTE: semaphore is NOT module-level — Celery fork workers would bind it to the
# parent event loop. Each caller creates its own and passes it in via _sem.
_DEFAULT_CONCURRENCY = 3

from app.core.constants import htf_for


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


def _components_from_ict(ict, htf_bias: str | None = None) -> dict:
    """Build a minimal components dict for NO_SIGNAL results so the UI can still
    show which structural pillars are present."""
    components: dict = {}
    if htf_bias:
        components["htf_bias"] = f"Sesgo HTF {htf_bias}"
    # Structure
    if ict.last_break:
        components["structure"] = f"{ict.last_break.kind} — {ict.last_break.direction}"
    # POI / trigger
    if ict.active_ob:
        components["trigger"] = "Order Block activo"
    elif ict.active_fvgs:
        components["trigger"] = "Fair Value Gap activo"
    return components


# ── Core analysis ─────────────────────────────────────────────────────────────

def build_signal(
    symbol: str,
    timeframe: str,
    ohlcv: list,
    htf_ohlcv: list | None = None,
    adaptive_params: dict | None = None,
    candles_1d: list | None = None,
    candles_1w: list | None = None,
) -> tuple[dict, AISignal | None]:
    """Run ICT + confluence. Returns (result_dict, signal_orm | None).

    Circuit breaker: if OPEN, skip signal generation entirely.
    

    htf_ohlcv: pre-fetched candles for the confirmation timeframe.
    When provided and the HTF has a confirmed structural bias that
    contradicts the LTF signal direction, the signal is suppressed.
    """
    # Circuit breaker check
    try:
        from risk.circuit_breaker import circuit_allows_trading
        if not circuit_allows_trading():
            return {
                "symbol": symbol,
                "status": "NO_SIGNAL",
                "context": {"circuit_breaker": "OPEN"},
            }, None
    except Exception:
        pass  # Never block because circuit breaker failed

    # Market quality filter — first gate after data fetch
    try:
        from ai.services.market_quality_filter import MarketQualityFilter
        mq = MarketQualityFilter.allow_scan(symbol, ohlcv)
        if not mq.allows_scan:
            return {
                "symbol": symbol,
                "status": "NO_SIGNAL",
                "context": {"market_quality": mq.reason, "market_quality_detail": mq.detail},
            }, None
    except Exception:
        pass  # Never block because market quality filter failed

    closed = [
        {"open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in ohlcv[:-1]
    ]
    last_close  = float(ohlcv[-1][4])
    signal_time = datetime.fromtimestamp(ohlcv[-2][0] / 1000, tz=timezone.utc)

    # Fase A: reuse current candles as HTF macro data when timeframe itself is daily/weekly
    if candles_1d is None and timeframe == "1d":
        candles_1d = ohlcv[:-1]
    if candles_1w is None and timeframe == "1w":
        candles_1w = ohlcv[:-1]

    ict     = ict_analyze(closed)
    context = build_context(ict, last_close)

    # ── Detect regime and resolve adaptive parameters ──
    regime_info = None
    try:
        from app.services.market_regime import detect_regime
        regime_info = detect_regime(symbol, timeframe, ohlcv)
    except Exception:
        pass

    if adaptive_params is None and regime_info:
        try:
            from app.services.scanner_regime_optimizer import get_adaptive_params_sync
            adaptive_params = get_adaptive_params_sync(
                symbol=symbol,
                timeframe=timeframe,
                regime=regime_info.regime,
                regime_confidence=regime_info.confidence,
                adx=regime_info.adx,
                atr_percentile=regime_info.atr_percentile,
                rel_volume=regime_info.rel_volume,
                realized_vol=regime_info.realized_vol,
            )
        except Exception:
            pass  # Never block signal because optimizer failed

    result = analyze_confluence(
        closed,
        symbol,
        timeframe,
        adaptive_params=adaptive_params,
        candles_1d=candles_1d,
        candles_1w=candles_1w,
    )

    if not result:
        components = _components_from_ict(ict, htf_bias=None)
        return {
            "symbol": symbol,
            "status": "NO_SIGNAL",
            "context": context,
            "components": components,
            "features": {"htf_bias": None, "htf_aligned": False},
        }, None

    # Evaluación 1: Regime is NOT a model feature — save for post-processing only
    regime = regime_info.regime if regime_info else "unknown"
    # Do NOT add regime_* to result.features — model sees only structural features

    # HTF confirmation gate
    htf_bias: str | None = _get_htf_bias(htf_ohlcv) if htf_ohlcv is not None else None
    if htf_bias is not None:
        aligned = (
            (result.direction == "long"  and htf_bias == "bull") or
            (result.direction == "short" and htf_bias == "bear")
        )
        if not aligned:
            return {
                "symbol":     symbol,
                "status":     "NO_SIGNAL",
                "context":    {**context, "htf_conflict": htf_bias},
                "components": result.components,
                "features":   {**result.features, "htf_bias": htf_bias, "htf_aligned": False},
            }, None

    result.features["htf_bias"]    = htf_bias
    result.features["htf_aligned"] = htf_bias is not None

    # Macro context gate
    try:
        from app.services.macro_context import macro_gate_for_signal
        macro = macro_gate_for_signal(symbol, result.direction)
        if macro["blocked"]:
            return {
                "symbol":     symbol,
                "status":     "NO_SIGNAL",
                "context":    {**context, "macro_blocked": True, "macro_warnings": macro["warnings"]},
                "components": result.components,
                "features":   {**result.features, "htf_bias": htf_bias, "htf_aligned": htf_bias is not None},
            }, None
        if macro["caution"]:
            result.warnings = list(result.warnings or []) + macro["warnings"]
        # Keep the SMC macro_context computed by the confluence engine; store
        # the macro gate (funding/news) context under a separate key.
        result.features["macro_gate_context"] = macro.get("context", {})
        result.features["macro_gate_blocked"] = macro["blocked"]
        result.features["macro_gate_caution"] = macro["caution"]
        result.features["macro_gate_warnings"] = macro["warnings"]
    except Exception:
        pass  # Never block signal because macro service failed

    quality = assess_quality(result)

    # Causal execution-quality features — optional, never block signal
    try:
        from ai.services.causal_feature_builder import CausalFeatureBuilder
        causal = CausalFeatureBuilder().build(symbol, signal_time)
        if causal.is_complete:
            result.features["avg_entry_slippage"] = causal.avg_slippage_30d
            result.features["gap_frequency"] = causal.gap_frequency_90d
            result.features["fee_rate"] = causal.fee_rate
            result.features["tp_fill_rate"] = causal.tp_fill_rate_30d
        else:
            logger.debug(f"[AI SCANNER] {symbol}: causal features incomplete, continuing without them")
    except Exception as exc:
        logger.debug(f"[AI SCANNER] {symbol}: causal builder failed ({exc}), continuing without causal features")

    # Ensemble / XGBoost success probability (0-1, higher = more likely success)
    success_prob = None
    shadow_success_prob = None
    candidate_prob = None
    try:
        # Prefer hybrid ensemble if available
        if ensemble_registry.model_ready():
            ens_probs = ensemble_registry.predict_ensemble_probability(result.features)
            if ens_probs:
                success_prob = ens_probs["ensemble"]
                result.features["ensemble_success_prob"] = ens_probs["ensemble"]
                result.features["xgb_success_prob"] = ens_probs["xgb"]
                result.features["rf_success_prob"] = ens_probs["rf"]
                result.features["nb_success_prob"] = ens_probs.get("nb")
        # Fallback to standalone XGBoost
        elif anti_fake_registry.model_ready():
            calibrated = anti_fake_registry.predict_calibrated_success_probability(result.features)
            raw = anti_fake_registry.predict_success_probability(result.features)
            if calibrated is not None:
                success_prob = calibrated
            elif raw is not None:
                success_prob = raw
            else:
                success_prob = None
            if raw is not None and calibrated is not None:
                result.features["success_probability_raw"] = float(raw)
                result.features["success_probability_calibrated"] = float(calibrated)

        # Pre-compute probabilities for shadow mode (recorded after DB commit)
        if anti_fake_registry.model_ready():
            shadow_success_prob = anti_fake_registry.predict_calibrated_success_probability(result.features)
        from ai.services import candidate_model
        if candidate_model.model_ready():
            candidate_prob = candidate_model.predict_success_probability(result.features)
    except Exception:
        pass  # Model not ready or prediction failed — fall back to heuristic only

    # Evaluación 1: Apply regime-adjusted thresholds AFTER ensemble prediction
    try:
        from ai.services.regime_adapter import RegimeAdapter
        passes_regime, regime_reason = RegimeAdapter.apply_to_signal(
            score=result.score,
            success_prob=success_prob,
            regime=regime,
        )
        if not passes_regime:
            return {
                "symbol": symbol,
                "status": "NO_SIGNAL",
                "context": {**context, "regime_blocked": True, "regime_reason": regime_reason},
            }, None
        result.features["regime_adjustment"] = regime_reason
    except Exception:
        pass  # Never block because regime adapter failed

    # Evaluación 1+2: Risk engine sizing (3 multipliers, calibrated confidence)
    try:
        from risk.risk_engine import quick_size
        calibrated_conf = success_prob if success_prob is not None else 0.5
        suggested_size = quick_size(
            quality=quality.quality_tier or "WEAK",
            calibrated_conf=calibrated_conf,
            risk_status="GREEN",  # System risk assessed at execution time
        )
        result.features["risk_suggested_size"] = suggested_size
        result.features["risk_calibrated_conf"] = round(calibrated_conf, 4)
    except Exception:
        pass

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
        success_probability  = success_prob,
        red_flags         = quality.red_flags,
        green_flags       = quality.green_flags,
        signal_time       = signal_time,
        created_at        = datetime.now(timezone.utc),
    )
    # Probabilities are pre-computed above; the caller must record shadow mode
    # predictions AFTER the AISignal is committed and refreshed so that the
    # real signal_id is available (recording here with sig.id produces "None").
    return {
        "symbol": symbol,
        "status": "SIGNAL",
        "context": context,
        "_shadow_probs": {
            "live": success_prob,
            "shadow": shadow_success_prob,
            "candidate": candidate_prob,
        },
    }, sig


def record_shadow_for_signal(signal_id: str, result_dict: dict) -> None:
    """Record live/shadow/candidate predictions after the signal has a real DB id.

    Must be called by the caller AFTER the AISignal has been committed and
    refreshed, otherwise signal_id will be "None" and shadow resolution will
    never match.
    """
    if not signal_id or signal_id == "None":
        return
    probs = result_dict.get("_shadow_probs") or {}
    live = probs.get("live")
    shadow = probs.get("shadow")
    candidate = probs.get("candidate")

    if live is not None and shadow is not None:
        try:
            from ai.services.shadow_mode import record_shadow
            record_shadow(signal_id=signal_id, live_prob=live, shadow_prob=shadow)
        except Exception:
            pass

    if live is not None and candidate is not None:
        try:
            from ai.services.candidate_shadow_mode import record_candidate_shadow
            record_candidate_shadow(signal_id=signal_id, live_prob=live, candidate_prob=candidate)
        except Exception:
            pass


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
            for attempt in range(3):
                try:
                    ohlcv = await exchange.fetch_ohlcv(ccxt_sym, timeframe, limit=200)
                    if ohlcv and len(ohlcv) >= 50:
                        return symbol, ohlcv
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
                except Exception as exc:
                    logger.debug(f"[fetch_ohlcv] {symbol}/{timeframe} attempt {attempt + 1} failed: {exc}")
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
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
    # Blend heuristic + ML for recommendation
    ml_status = s.anti_fake_status
    if s.success_probability is not None:
        if s.success_probability <= 0.30:
            ml_status = "BLOCK"
        elif s.success_probability <= 0.50:
            ml_status = "CAUTION"
        else:
            ml_status = "CLEAR"

    recommendation = (
        "AVOID" if ml_status == "BLOCK" else
        "WAIT"  if ml_status == "CAUTION" else
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
        "success_probability": s.success_probability,
        "ml_status":        ml_status,
        "red_flags":        s.red_flags or [],
        "green_flags":      s.green_flags or [],
        "recommendation":   recommendation,
        "features":         s.features or {},
        "outcome":          s.outcome,
        "pnl_pct":          s.pnl_pct,
        "realistic_outcome": s.realistic_outcome,
        "realistic_pnl_pct": s.realistic_pnl_pct,
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
