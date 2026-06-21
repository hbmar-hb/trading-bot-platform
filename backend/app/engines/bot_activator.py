"""Bot Activator — bridges AI Confluence signals to real exchange orders.

Finds BotConfigs with ai_signal_mode=True matching the signal's ticker,
places market orders with the AI signal's pre-computed SL/TP levels.

Per-bot filters (configurable via ai_signal_config):
  1. Tier filter    — allowed_tiers   ["STRONG"] by default
  2. Status filter  — allowed_statuses ["CLEAR"] by default
  3. Score filter   — min_score threshold (default 60)
  4. Concurrency cap — max_concurrent open positions (default 1)
  5. Set leverage   — from bot.leverage
  6. Size position  — bot.position_value (% equity or fixed USDT)
  7. Open position  — market order via exchange factory
  8. Place SL       — ai signal's stop_loss price
  9. Record Position + BotLog
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN

from loguru import logger

from app.models.ai_signal import AISignal
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.models.position import Position
from app.services.database import SessionLocal
from app.services.context_thresholds import ContextThresholdRegistry
from ai import registry as anti_fake_registry
from ai import ensemble_registry
from ai import bot_registry
from app.core.ict_engine import _POI_STRENGTH as _ICT_POI_STRENGTH
from app.engines.confluence_engine import _compute_confluence_score, _load_adaptive_weights

# Max age in candle-multiples before a signal is considered stale
_STALE_CANDLES = 5

# Minimum notional in USDT — auto-adjusted if calculated sizing is below exchange minimums
_MIN_NOTIONAL_BASE = 10.0  # raised from 2.0 to make trades economically viable after fees


def _to_ccxt_symbol(symbol: str) -> str:
    """Normalize any symbol format to compact form (e.g. BTCUSDT)."""
    if not symbol:
        return symbol
    # Handle BTC/USDT:USDT → BTCUSDT
    normalized = re.sub(r'/([^:]+):[^:]+$', r'\1', symbol)
    return normalized.replace('/', '').replace(':', '').upper()


def _get_min_viable_notional(symbol: str, entry_price: float) -> float:
    """Calculate minimum viable notional for a symbol based on price and exchange precision.
    
    A trade must be large enough that a typical TP move (0.5-1%) produces meaningful
    profit after fees (0.1% round-trip) and slippage.
    """
    if not entry_price or entry_price <= 0:
        return _MIN_NOTIONAL_BASE
    
    # Estimate exchange min quantity precision based on price tier
    # These are conservative estimates for BingX perpetual futures
    if entry_price > 50000:       # BTC
        min_qty = 0.0001
    elif entry_price > 1000:      # ETH, BNB, SOL
        min_qty = 0.001
    elif entry_price > 100:       # LINK, LPT, AAVE
        min_qty = 0.01
    elif entry_price > 10:        # UNI, ARB, ONDO
        min_qty = 0.1
    elif entry_price > 1:         # PENGU, XRP
        min_qty = 1.0
    else:                         # 1000PEPE, SHIB-like
        min_qty = 1000.0
    
    precision_min = min_qty * entry_price
    return max(_MIN_NOTIONAL_BASE, precision_min)

# Evaluación 2: PortfolioManager replaces hardcoded correlation gate
from app.services.portfolio_manager import PortfolioManager


def _check_portfolio_gate(db, bot: BotConfig, sig: AISignal, notional: float) -> tuple[bool, str]:
    """Return (allowed, reason). Blocks if correlated asset already open or sector over-exposed.
    
    Only counts REAL open positions — paper positions do not affect real bot exposure.
    """
    open_positions = (
        db.query(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .filter(
            BotConfig.user_id == bot.user_id,
            BotConfig.paper_balance_id.is_(None),
            Position.status == "open",
        )
        .all()
    )
    # Fetch total equity from exchange for exposure calculation
    total_equity = 0.0
    try:
        exchange = get_exchange_for_bot(bot)
        bal = _arun(exchange.fetch_balance())
        total_equity = float(bal.get("total", {}).get("USDT", 0)) if bal else 0.0
    except Exception:
        pass

    result = PortfolioManager.check_new_position(
        new_symbol=bot.symbol,
        new_direction=sig.direction,
        new_notional=notional,
        open_positions=open_positions,
        total_equity=max(total_equity, 1.0),
    )
    return result.allowed, result.reason

from app.core.constants import TF_MINUTES as _TF_MINUTES


def _merge_structural_levels(
    features: dict,
    ltf_key: str,
    htf_key: str,
    ltf_name: str,
) -> list[dict]:
    """Merge LTF and HTF structural levels, sorting HTF first due to higher
    structural strength, then by POI strength and distance."""
    ltf_levels = features.get(ltf_key, [])
    htf_levels = features.get(htf_key, [])
    htf_tf = features.get("htf_timeframe", "htf")

    merged = []
    for l in ltf_levels:
        merged.append({**l, "tf_source": ltf_name})
    for l in htf_levels:
        merged.append({**l, "tf_source": htf_tf, "htf_bonus": True})

    merged.sort(key=lambda x: (
        -1 if x.get("htf_bonus") else 0,
        -_ICT_POI_STRENGTH.get(x.get("kind", ""), 0.5),
        x.get("distance_pct", 999),
    ))
    return merged


def _resolve_structural_tps_from_fill(
    fill_price: float,
    direction: str,
    forward_levels: list[dict],
    min_distance_pct: float = 0.5,
) -> tuple[float | None, str | None, float | None, str | None]:
    """Recalculate valid structural TP levels from the real fill price.

    The signal's forward_levels were computed from the ICT entry_zone mid,
    which can differ significantly from the actual fill_price (slippage,
    fast moves). This function:

      1. Filters levels that are already "behind" the fill price
         (e.g. for SHORT, levels ABOVE fill are already passed).
      2. Recomputes real distance from fill_price.
      3. Discards levels too close (< min_distance_pct) to avoid
         breakeven-only TPs like AAVE (TP1 0.01 away from entry).
      4. Returns up to 2 valid levels with their kind sources.

    Returns: (tp1_price, tp1_kind, tp2_price, tp2_kind)
             Any can be None if no valid level exists.
    """
    if not forward_levels:
        return None, None, None, None

    is_long = direction == "long"
    valid_levels: list[dict] = []

    for lvl in forward_levels:
        price = float(lvl.get("price", 0))
        kind = lvl.get("kind", "unknown")
        if price <= 0:
            continue

        # For LONG: TP must be ABOVE fill_price
        # For SHORT: TP must be BELOW fill_price
        if is_long:
            if price <= fill_price:
                continue  # already passed or equal
        else:
            if price >= fill_price:
                continue  # already passed or equal

        # Real distance from fill_price
        dist_pct = abs(price - fill_price) / fill_price * 100
        if dist_pct < min_distance_pct:
            logger.info(
                f"[STRUCTURAL TP] Discarded {kind} @ {price} — too close "
                f"({dist_pct:.3f}% < {min_distance_pct}% min) to fill {fill_price}"
            )
            continue

        valid_levels.append({"price": price, "kind": kind, "distance_pct": dist_pct})

    if not valid_levels:
        return None, None, None, None

    # Sort by distance ASC (closest first) — same logic as confluence engine
    valid_levels.sort(key=lambda x: x["distance_pct"])

    tp1 = valid_levels[0]
    tp1_price, tp1_kind = tp1["price"], tp1["kind"]

    tp2_price, tp2_kind = None, None
    if len(valid_levels) >= 2:
        tp2 = valid_levels[1]
        tp2_price, tp2_kind = tp2["price"], tp2["kind"]

    logger.info(
        f"[STRUCTURAL TP] Resolved from fill {fill_price}: "
        f"TP1={tp1_price} ({tp1_kind}, {tp1['distance_pct']:.3f}%) "
        f"TP2={tp2_price or 'NONE'} ({tp2_kind or 'NONE'})"
    )
    return tp1_price, tp1_kind, tp2_price, tp2_kind


def _compute_mechanical_tps(
    fill_price: float,
    sl_price: float,
    direction: str,
    tp1_r: float = 1.5,
    tp2_r: float = 2.5,
) -> tuple[float, float]:
    """Compute mechanical TP levels from fill_price using R-multiples.

    Used as fallback when no valid structural levels exist from the fill price.
    Ensures TPs are always in the correct direction (above entry for LONG,
    below entry for SHORT).
    """
    risk = abs(fill_price - sl_price)
    if risk <= 0:
        risk = fill_price * 0.01  # 1% default risk

    if direction == "long":
        tp1 = fill_price + risk * tp1_r
        tp2 = fill_price + risk * tp2_r
    else:
        tp1 = fill_price - risk * tp1_r
        tp2 = fill_price - risk * tp2_r

    return tp1, tp2


def _evaluate_trade_longevity(
    fill_price: float,
    sl_price: float,
    direction: str,
    forward_levels: list[dict],
    atr_value: float,
    timeframe: str,
) -> tuple[bool, list[str], float | None, str | None, float | None, str | None]:
    """Evaluate whether a trade has sufficient structural longevity from fill_price.

    A trade should ONLY be opened when ICT+SMC forward levels provide real,
    profitable targets from the actual fill price. This is autonomous — no
    fixed thresholds. The minimum viable distance adapts to:
      - Risk distance (R-multiple): TP1 must be at least 1.0R away
      - ATR: TP1 must be at least 1.5× ATR (avoids noise in volatile markets)
      - Fees: minimum 0.2% to cover round-trip costs
      - Timeframe: tighter for LTF (15m), wider for HTF (4h+)

    Returns:
        (ok, reasons, tp1_price, tp1_kind, tp2_price, tp2_kind)
        If ok=False, tp1/tp2 will be None — the signal should be REJECTED.
    """
    reasons: list[str] = []
    is_long = direction == "long"
    risk = abs(fill_price - sl_price)
    risk_pct = (risk / fill_price * 100) if fill_price > 0 else 0.0
    atr_pct = (atr_value / fill_price * 100) if fill_price > 0 else 0.0

    # Adaptive minimum distance based on market context
    # 1. Minimum 1.0R: if SL is 2% away, TP1 must be at least 2% away
    # 2. Minimum 1.5× ATR: avoids noise-driven false breakouts
    # 3. Minimum 0.2% absolute: covers fees + slippage
    # 4. Timeframe multiplier: HTF needs bigger moves
    tf_mult = {
        "15m": 1.0, "30m": 1.0, "1h": 1.1, "2h": 1.2,
        "4h": 1.3, "6h": 1.3, "8h": 1.4, "12h": 1.5,
        "1d": 1.5, "3d": 1.8, "1w": 2.0,
    }.get(timeframe, 1.0)

    min_distance_pct = max(
        risk_pct * 1.0,           # At least 1.0R
        atr_pct * 1.5,            # At least 1.5× ATR
        0.2,                      # Minimum fee coverage
    ) * tf_mult

    valid_levels: list[dict] = []
    for lvl in forward_levels:
        price = float(lvl.get("price", 0))
        kind = lvl.get("kind", "unknown")
        if price <= 0:
            continue
        if is_long and price <= fill_price:
            reasons.append(f"{kind}@{price} below fill for LONG")
            continue
        if not is_long and price >= fill_price:
            reasons.append(f"{kind}@{price} above fill for SHORT")
            continue
        dist_pct = abs(price - fill_price) / fill_price * 100
        if dist_pct < min_distance_pct:
            reasons.append(
                f"{kind}@{price} too close ({dist_pct:.3f}% < {min_distance_pct:.3f}% "
                f"min: 1.0R={risk_pct:.3f}% | 1.5ATR={atr_pct*1.5:.3f}% | tf_mult={tf_mult})"
            )
            continue
        valid_levels.append({"price": price, "kind": kind, "distance_pct": dist_pct})

    if not valid_levels:
        reasons.append(
            f"No valid structural levels from fill={fill_price} "
            f"(min_distance={min_distance_pct:.3f}%)"
        )
        return False, reasons, None, None, None, None

    valid_levels.sort(key=lambda x: x["distance_pct"])
    tp1 = valid_levels[0]
    tp1_price, tp1_kind = tp1["price"], tp1["kind"]

    tp2_price, tp2_kind = None, None
    if len(valid_levels) >= 2:
        tp2 = valid_levels[1]
        tp2_price, tp2_kind = tp2["price"], tp2["kind"]
    else:
        reasons.append("Only 1 structural level available")

    rr = abs(tp1_price - fill_price) / risk if risk > 0 else 0.0
    reasons.append(
        f"LONGEVITY OK: TP1={tp1_price} ({tp1_kind}, {tp1['distance_pct']:.3f}%, "
        f"{rr:.2f}R) min={min_distance_pct:.3f}%"
    )
    return True, reasons, tp1_price, tp1_kind, tp2_price, tp2_kind


def _signal_is_stale(sig: AISignal) -> bool:
    """Return True when signal is older than 3 candles of its timeframe."""
    tf_min   = _TF_MINUTES.get(sig.timeframe, 60)
    max_age  = tf_min * _STALE_CANDLES
    st = sig.signal_time
    if st.tzinfo is None:
        st = st.replace(tzinfo=timezone.utc)
    age_min = (datetime.now(timezone.utc) - st).total_seconds() / 60
    return age_min > max_age


def _arun(coro):
    """Run an async coroutine safely in a Celery worker (sync) context.

    Reuses the thread-local event loop if available so that aiohttp
    sessions (used by ccxt.async_support) stay alive across calls.
    The loop is closed automatically when the Celery worker thread dies.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _pattern_win_rate(db, ticker: str, tier: str, status: str, direction: str, min_samples: int = 10) -> float | None:
    """Return historical win rate for exact pattern (ticker+tier+status+direction).
    Returns None if fewer than min_samples exist.

    Counts BOTH real and paper executed positions to align with the optimal-config
    weighting scheme (real=1.0, paper_same_tf=0.5).
    """
    from app.models.ai_signal import AISignal
    from app.models.position import Position
    from sqlalchemy import func, case, String, desc

    result = db.query(
        func.count().label("total"),
        func.sum(case((AISignal.outcome == "SUCCESS", 1), else_=0)).label("wins")
    ).join(
        Position, Position.extra_config["ai_signal_id"].astext == func.cast(AISignal.id, String)
    ).filter(
        AISignal.ticker == ticker,
        AISignal.quality_tier == tier,
        AISignal.anti_fake_status == status,
        AISignal.direction == direction,
        AISignal.outcome.in_(["SUCCESS", "FAILURE"])
    ).first()
    if not result or result.total < min_samples:
        return None
    return result.wins / result.total


def _effective_status(sig: AISignal, cfg: dict | None = None, bot_id: str | None = None) -> str:
    """Return the effective anti-fake status blending heuristic + XGBoost.

    If the anti-fake model is trained and success_probability is available,
    it overrides the heuristic status with ML-driven thresholds.
    Thresholds are auto-calibrated from cfg['ml_status_thresholds'] with
    safe defaults: block=0.30, caution=0.50.

    Falls back to the heuristic anti_fake_status when ML is unavailable.
    """
    thresholds = (cfg or {}).get("ml_status_thresholds", {})
    block_thr = thresholds.get("block", 0.30)
    caution_thr = thresholds.get("caution", 0.50)

    sp = getattr(sig, "success_probability", None)
    ml_ready = (
        anti_fake_registry.model_ready()
        or ensemble_registry.model_ready()
        or (bot_id is not None and bot_registry.model_ready_for_bot(bot_id))
    )
    if sp is not None and ml_ready:
        if sp <= block_thr:
            return "BLOCK"
        elif sp <= caution_thr:
            return "CAUTION"
        else:
            return "CLEAR"
    return sig.anti_fake_status or "CLEAR"


# ── Public entry point ────────────────────────────────────────────────────────

def _compute_optimal_config_sync(db, ticker: str, target_timeframe: str | None = None, current_cfg: dict | None = None) -> dict | None:
    """Sync version of /optimal-config/{ticker} logic. Returns optimal ai_signal_config or None.

    DATA SOURCES (in priority order):
      1. Real trades: Position + ExchangeTrade (ground truth)
      2. Realistic simulation: AISignal.realistic_outcome (calibrated model)
      3. CONSERVATIVE fallback when insufficient data

    This ensures the bot never operates on optimistic assumptions.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text
    from app.models.ai_signal import AISignal
    from app.models.position import Position
    from app.models.exchange_trade import ExchangeTrade

    now = datetime.now(timezone.utc)
    ticker_upper = ticker.upper()
    ticker_normalized = ticker_upper
    since_30d = now - timedelta(days=30)
    since_14d = now - timedelta(days=14)

    # ═══════════════════════════════════════════════════════════
    # SOURCE 1: Real closed AI positions + exchange trades (timeframe-aware)
    # ═══════════════════════════════════════════════════════════
    # If target_timeframe is provided, we ALSO count paper positions from the
    # SAME timeframe (with lower weight) to supplement thin real data.
    if target_timeframe:
        real_sql = text("""
            SELECT
                p.id AS position_id,
                p.realized_pnl,
                p.extra_config,
                s.score,
                s.quality_tier,
                s.anti_fake_status,
                s.direction,
                s.timeframe,
                s.entry_price AS signal_entry,
                s.stop_loss AS signal_sl,
                s.take_profit_1 AS signal_tp1,
                COALESCE(et.fee, 0) AS fee,
                et.exit_price,
                CASE WHEN bc.paper_balance_id IS NULL THEN 'real' ELSE 'paper' END AS execution_type
            FROM positions p
            JOIN bot_configs bc ON bc.id = p.bot_id
            LEFT JOIN ai_signals s ON s.id = (p.extra_config->>'ai_signal_id')::uuid
            LEFT JOIN exchange_trades et ON et.position_id = p.id
            WHERE p.source = 'ai_bot'
              AND p.status = 'closed'
              AND s.ticker = :ticker
              AND p.closed_at >= :since
            ORDER BY p.closed_at DESC
            LIMIT 500
        """)
    else:
        real_sql = text("""
            SELECT
                p.id AS position_id,
                p.realized_pnl,
                p.extra_config,
                s.score,
                s.quality_tier,
                s.anti_fake_status,
                s.direction,
                s.timeframe,
                s.entry_price AS signal_entry,
                s.stop_loss AS signal_sl,
                s.take_profit_1 AS signal_tp1,
                COALESCE(et.fee, 0) AS fee,
                et.exit_price,
                'real' AS execution_type
            FROM positions p
            JOIN bot_configs bc ON bc.id = p.bot_id AND bc.paper_balance_id IS NULL
            LEFT JOIN ai_signals s ON s.id = (p.extra_config->>'ai_signal_id')::uuid
            LEFT JOIN exchange_trades et ON et.position_id = p.id
            WHERE p.source = 'ai_bot'
              AND p.status = 'closed'
              AND s.ticker = :ticker
              AND p.closed_at >= :since
            ORDER BY p.closed_at DESC
            LIMIT 500
        """)

    real_rows = db.execute(real_sql, {"ticker": ticker_normalized, "since": since_30d}).mappings().all()

    # Bucket rows by (tier, status, direction, timeframe, execution_type)
    # with WEIGHTS: real_same_tf=1.0, paper_same_tf=0.5, real_diff_tf=0.2, paper_diff_tf=0.0
    def _bucket_real_rows(rows, target_tf):
        buckets = {}
        total_real_weight = 0.0
        total_paper_same_weight = 0.0
        for r in rows:
            row_tf = r["timeframe"] or "1h"
            is_same_tf = (row_tf == target_tf) if target_tf else True
            exec_type = r["execution_type"] or "real"
            is_real = (exec_type == "real")

            if is_real and is_same_tf:
                weight = 1.0
                total_real_weight += 1.0
            elif not is_real and is_same_tf:
                weight = 0.5
                total_paper_same_weight += 1.0
            elif is_real and not is_same_tf:
                weight = 0.2
            else:
                continue  # paper + diff_tf = excluded

            key = (r["quality_tier"] or "UNKNOWN", r["anti_fake_status"] or "UNKNOWN", r["direction"] or "long")
            buckets.setdefault(key, {"trades": [], "pnls": [], "weights": []})
            pnl = float(r["realized_pnl"]) if r["realized_pnl"] is not None else 0.0
            buckets[key]["trades"].append(r)
            buckets[key]["pnls"].append(pnl * weight)
            buckets[key]["weights"].append(weight)
        return buckets, total_real_weight, total_paper_same_weight

    real_buckets, total_real, total_paper_same = _bucket_real_rows(real_rows, target_timeframe)

    # ═══════════════════════════════════════════════════════════
    # SOURCE 2: Realistic simulated outcomes (fallback, same timeframe only)
    # ═══════════════════════════════════════════════════════════
    def _fetch_realistic(days: int, tf: str | None):
        since = now - timedelta(days=days)
        q = (
            db.query(AISignal)
            .filter(
                AISignal.ticker == ticker_normalized,
                AISignal.created_at >= since,
                AISignal.realistic_outcome.isnot(None),
            )
        )
        if tf:
            q = q.filter(AISignal.timeframe == tf)
        return q.all()

    realistic_signals = _fetch_realistic(14, target_timeframe)
    if len(realistic_signals) < 5:
        realistic_signals = _fetch_realistic(30, target_timeframe)

    # ═══════════════════════════════════════════════════════════
    # HELPER: Compute stats for a bucket
    # ═══════════════════════════════════════════════════════════
    def _compute_bucket_stats(pnls: list[float]) -> dict:
        if not pnls:
            return {"count": 0, "wr": 0.0, "avg_pnl": 0.0, "profit_factor": 0.0, "max_dd": 0.0}
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        wr = len(wins) / len(pnls) * 100
        avg_pnl = sum(pnls) / len(pnls)
        profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (999.0 if wins else 0.0)
        # Simple max drawdown: worst consecutive loss streak
        max_dd = min(pnls) if pnls else 0.0
        return {
            "count": len(pnls),
            "wr": wr,
            "avg_pnl": avg_pnl,
            "profit_factor": profit_factor,
            "max_dd": max_dd,
        }

    # Merge real + realistic data into unified tier/status buckets
    unified_tier = {"STRONG": [], "MODERATE": [], "WEAK": []}
    unified_status = {"CLEAR": [], "CAUTION": []}

    # Add weighted real P&L (includes paper_same_tf at 0.5 weight)
    for key, data in real_buckets.items():
        tier, status, _ = key
        if tier in unified_tier:
            unified_tier[tier].extend(data["pnls"])
        if status in unified_status:
            unified_status[status].extend(data["pnls"])

    # Add realistic P&L (only for buckets with < 5 weighted real samples)
    for sig in realistic_signals:
        tier = sig.quality_tier or "UNKNOWN"
        status = sig.anti_fake_status or "UNKNOWN"
        pnl = sig.realistic_pnl_pct or 0.0
        weighted_count = sum(real_buckets.get((tier, status, sig.direction), {}).get("weights", []))
        if weighted_count < 5:
            if tier in unified_tier:
                unified_tier[tier].append(pnl * 0.3)  # realistic sim gets low weight
            if status in unified_status:
                unified_status[status].append(pnl * 0.3)

    # Compute stats
    tier_stats = {k: _compute_bucket_stats(v) for k, v in unified_tier.items()}
    status_stats = {k: _compute_bucket_stats(v) for k, v in unified_status.items()}

    # Total weighted samples
    total_weighted_real = total_real + total_paper_same * 0.5
    total_realistic = len(realistic_signals)

    # ═══════════════════════════════════════════════════════════
    # CONSERVATIVE FALLBACK when insufficient real data for this timeframe
    # ═══════════════════════════════════════════════════════════
    # Need ≥ 20 weighted real trades OR ≥ 10 real + ≥ 10 paper_same
    if total_weighted_real < 20 and total_real < 10:
        logger.warning(
            f"[OPTIMAL CONFIG] {ticker_upper}/{target_timeframe or 'global'}: "
            f"only {total_real} real + {total_paper_same} paper_same trades. "
            f"Using timeframe-aware CONSERVATIVE fallback."
        )
        return _conservative_fallback_config(target_timeframe)

    # ═══════════════════════════════════════════════════════════
    # THRESHOLDS based on REAL performance only
    # ═══════════════════════════════════════════════════════════
    # Tier inclusion: WR >= 50% AND profit_factor >= 1.2 AND >= 5 samples
    allowed_tiers = []
    for tier in ("STRONG", "MODERATE", "WEAK"):
        st = tier_stats.get(tier, {})
        count = st.get("count", 0)
        wr = st.get("wr", 0)
        pf = st.get("profit_factor", 0)
        # Include tier if we have enough data and it shows marginal profitability,
        # OR if data is sparse but it's a stronger tier (avoid over-restricting).
        if count >= 5 and wr >= 45 and pf >= 1.0:
            allowed_tiers.append(tier)
        elif count < 5 and tier in ("STRONG", "MODERATE"):
            allowed_tiers.append(tier)

    # Never allow weaker tiers without stronger ones IF stronger ones are available,
    # but don't force STRONG if we have no evidence for it.
    if "WEAK" in allowed_tiers and "MODERATE" not in allowed_tiers:
        allowed_tiers.remove("WEAK")

    if not allowed_tiers:
        allowed_tiers = ["STRONG", "MODERATE"]  # Less restrictive default

    # Status inclusion: CAUTION only if its WR is within 5 pts of CLEAR
    clear_wr = status_stats.get("CLEAR", {}).get("wr", 0)
    allowed_statuses = ["CLEAR"]
    caution_wr = status_stats.get("CAUTION", {}).get("wr", 0)
    if caution_wr >= clear_wr - 5 and status_stats.get("CAUTION", {}).get("count", 0) >= 5:
        allowed_statuses.append("CAUTION")

    # Min score: search for threshold that maximizes profit_factor with >=25% pass rate
    # Use realistic signals for score optimization
    best_score = 65  # conservative default
    best_pf = 0.0
    all_scores = [s.score for s in realistic_signals if s.score is not None]
    if all_scores:
        for threshold in range(40, 81, 5):
            subset = [s for s in realistic_signals if s.score >= threshold]
            if len(subset) < 5:
                continue
            pass_rate = len(subset) / len(realistic_signals) * 100
            if pass_rate < 25:
                continue
            pnls = [s.realistic_pnl_pct or 0.0 for s in subset]
            stats = _compute_bucket_stats(pnls)
            if stats["profit_factor"] > best_pf:
                best_pf = stats["profit_factor"]
                best_score = threshold

    # Sizing multipliers based on real avg P&L and WR
    def _sizing_from_real(stats: dict) -> float:
        count = stats.get("count", 0)
        wr = stats.get("wr", 0)
        avg_pnl = stats.get("avg_pnl", 0)
        pf = stats.get("profit_factor", 0)
        if count < 3:
            return 1.0  # Insufficient data — trust the model, use full sizing
        if wr > 55 and avg_pnl > 0 and pf >= 1.5:
            return 1.0
        if wr > 50 and avg_pnl > 0 and pf >= 1.2:
            return 0.75
        if wr > 45 and avg_pnl > 0:
            return 0.5
        return 0.25  # Poor data but still allow reduced sizing

    sizing = {
        "STRONG":   _sizing_from_real(tier_stats.get("STRONG", {})),
        "MODERATE": _sizing_from_real(tier_stats.get("MODERATE", {})),
        "WEAK":     _sizing_from_real(tier_stats.get("WEAK", {})),
        "CLEAR":    _sizing_from_real(status_stats.get("CLEAR", {})),
        "CAUTION":  _sizing_from_real(status_stats.get("CAUTION", {})),
    }

    # Circuit breaker: more restrictive if drawdown is high
    max_dd = min(
        tier_stats.get("STRONG", {}).get("max_dd", 0),
        tier_stats.get("MODERATE", {}).get("max_dd", 0),
    )
    cb = {
        "STRONG":   {"consecutive_sl": 2 if max_dd < -10 else 3},
        "MODERATE": {"consecutive_sl": 1 if max_dd < -10 else 2},
        "WEAK":     {"consecutive_sl": 2},
    }

    # Portfolio limits: tighten if overall performance is weak
    overall_pnls = []
    for data in real_buckets.values():
        overall_pnls.extend(data["pnls"])
    if not overall_pnls:
        overall_pnls = [s.realistic_pnl_pct or 0.0 for s in realistic_signals]

    overall_stats = _compute_bucket_stats(overall_pnls)
    overall_wr = overall_stats.get("wr", 0)
    overall_pf = overall_stats.get("profit_factor", 0)

    if overall_wr < 50 or overall_pf < 1.2:
        portfolio = {
            "max_total_exposure_pct": 30.0,
            "max_symbol_exposure_pct": 20.0,
            "max_directional_exposure_pct": 25.0,
            "alt_correlation_threshold": 2,
        }
    else:
        portfolio = {
            "max_total_exposure_pct": 40.0,
            "max_symbol_exposure_pct": 25.0,
            "max_directional_exposure_pct": 35.0,
            "alt_correlation_threshold": 3,
        }

    config = {
        "min_score": best_score,
        "require_clear": "CLEAR" in allowed_statuses and "CAUTION" not in allowed_statuses,
        "allowed_tiers": allowed_tiers,
        "allowed_statuses": allowed_statuses,
        "sizing_multipliers": sizing,
        "circuit_breaker_thresholds": cb,
        "circuit_breaker_state": {},
        "portfolio_limits": portfolio,
    }

    logger.info(
        f"[OPTIMAL CONFIG] {ticker_upper} (real={total_real}, sim={total_realistic}): "
        f"score≥{best_score}, tiers={allowed_tiers}, statuses={allowed_statuses}, "
        f"real_wr={overall_wr:.1f}%, real_pf={overall_pf:.2f}, max_dd={max_dd:.2f}%"
    )

    # ── Merge rejection-feedback adjustments (survival-bias calibration) ──
    try:
        from app.services.rejection_feedback_optimizer import (
            compute_rejection_adjustments,
            apply_rejection_adjustments_to_config,
        )
        adjustments = compute_rejection_adjustments(
            db, ticker_upper, None, config, days=30
        )
        if adjustments:
            config = apply_rejection_adjustments_to_config(db, None, config, adjustments)
            logger.info(
                f"[OPTIMAL CONFIG] {ticker_upper} merged rejection feedback: "
                f"{adjustments.get('_reasons', [])}"
            )
    except Exception:
        pass  # Non-critical; base config is safe

    # ── Respect recent manual/auto calibrations ──
    if current_cfg:
        meta = current_cfg.get("rejection_calibration_meta", {})
        last_cal = meta.get("last_calibration_at")
        if last_cal:
            try:
                from datetime import datetime, timezone, timedelta
                cal_dt = datetime.fromisoformat(last_cal)
                if cal_dt.tzinfo is None:
                    cal_dt = cal_dt.replace(tzinfo=timezone.utc)
                hours_since = (datetime.now(timezone.utc) - cal_dt).total_seconds() / 3600
                if hours_since < 24:
                    # Preserve calibrated keys; optimal config should not override recent learning
                    preserved_keys = [
                        "allowed_tiers", "allowed_statuses", "min_score",
                        "max_concurrent", "portfolio_limits",
                    ]
                    for key in preserved_keys:
                        if key in current_cfg:
                            old_val = config.get(key)
                            new_val = current_cfg[key]
                            if old_val != new_val:
                                logger.info(
                                    f"[OPTIMAL CONFIG] {ticker_upper}: preserving calibrated {key}="
                                    f"{new_val} (optimal suggested {old_val}, cal age={hours_since:.1f}h)"
                                )
                            config[key] = new_val
            except Exception:
                pass

    return config


def _conservative_fallback_config(timeframe: str | None = None) -> dict:
    """Return a strictly conservative configuration when no reliable data exists.
    
    Timeframe-aware: shorter TF = higher min_score (tighter), longer TF = lower min_score.
    With insufficient real trades, we still need the bot to operate so it can
    accumulate ground-truth data.
    """
    defaults = {
        "15m": {"min_score": 50, "allowed_tiers": ["STRONG", "MODERATE"], "leverage": 20},
        "30m": {"min_score": 48, "allowed_tiers": ["STRONG", "MODERATE"], "leverage": 15},
        "1h":  {"min_score": 45, "allowed_tiers": ["STRONG", "MODERATE"], "leverage": 10},
        "2h":  {"min_score": 45, "allowed_tiers": ["STRONG", "MODERATE"], "leverage": 8},
        "4h":  {"min_score": 42, "allowed_tiers": ["STRONG", "MODERATE"], "leverage": 5},
        "1d":  {"min_score": 40, "allowed_tiers": ["STRONG", "MODERATE"], "leverage": 3},
    }
    tf_cfg = defaults.get(timeframe, defaults["1h"])
    return {
        "min_score": tf_cfg["min_score"],
        "require_clear": False,
        "allowed_tiers": tf_cfg["allowed_tiers"],
        "allowed_statuses": ["CLEAR", "CAUTION"],
        "leverage": tf_cfg["leverage"],
        "sizing_multipliers": {
            "STRONG": 1.0, "MODERATE": 1.0, "WEAK": 0.0,
            "CLEAR": 1.0, "CAUTION": 0.5,
        },
        "circuit_breaker_thresholds": {
            "STRONG": {"consecutive_sl": 2},
            "MODERATE": {"consecutive_sl": 1},
            "WEAK": {"consecutive_sl": 2},
        },
        "circuit_breaker_state": {},
        "portfolio_limits": {
            "max_total_exposure_pct": 30.0,
            "max_symbol_exposure_pct": 20.0,
            "max_directional_exposure_pct": 25.0,
            "alt_correlation_threshold": 2,
        },
    }


def activate(ai_signal_id: str) -> dict:
    """Dispatch orders for all AI bots matching the given signal."""
    with SessionLocal() as db:
        sig = db.query(AISignal).filter(
            AISignal.id == uuid.UUID(ai_signal_id)
        ).first()

        if not sig:
            return {"activated": 0, "reason": "signal_not_found"}

        # Staleness gate — reject if price likely moved past entry zone
        if _signal_is_stale(sig):
            tf_min  = _TF_MINUTES.get(sig.timeframe, 60)
            max_age = tf_min * _STALE_CANDLES
            logger.info(
                f"[ACTIVATOR] {sig.ticker} signal stale — "
                f"signal_time={sig.signal_time.isoformat()} "
                f"max_age={max_age}min tf={sig.timeframe}"
            )
            try:
                from app.services.rejected_tracker import record_rejection
                record_rejection(db, sig, "stale", trigger_diagnosis=True)
            except Exception:
                pass
            return {"activated": 0, "reason": "stale_signal"}

        bots = (
            db.query(BotConfig)
            .filter(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
                BotConfig.alerts_only == False,
            )
            .all()
        )

        # Normalize symbol comparison: bot.symbol may be compact (BTCUSDT)
        # while sig.ccxt_symbol is always CCXT format (BTC/USDT:USDT)
        from app.services.ai_scanner import to_ccxt
        bots = [b for b in bots if to_ccxt(b.symbol) == sig.ccxt_symbol and b.timeframe == sig.timeframe]

        # Filtrar bots sin cuenta válida (real o paper)
        valid_bots = []
        for bot in bots:
            if bot.is_paper_trading:
                if bot.paper_balance_id:
                    valid_bots.append(bot)
                else:
                    logger.warning(f"[ACTIVATOR] {bot.bot_name}: paper_balance_id vacío, saltando")
            else:
                if bot.exchange_account_id:
                    valid_bots.append(bot)
                else:
                    logger.warning(f"[ACTIVATOR] {bot.bot_name}: sin exchange_account, saltando")
        bots = valid_bots

        if not bots:
            logger.debug(f"[ACTIVATOR] No AI bots configured for {sig.ccxt_symbol}")
            return {"activated": 0, "reason": "no_matching_bots"}

        activated, results = 0, []
        alert_fired = False

        # Save original signal state to prevent cross-bot mutation (C2)
        _original_score = sig.score
        _original_prob = sig.success_probability
        _original_features = dict(sig.features) if sig.features else {}

        for bot in bots:
            # Restore signal state at start of each iteration (C2 fix)
            # Use object.__setattr__ to bypass SQLAlchemy dirty-tracking so
            # subsequent db.commit() calls inside the loop do not revert
            # the persisted state of a bot that already entered.
            object.__setattr__(sig, "score", _original_score)
            object.__setattr__(sig, "success_probability", _original_prob)
            # features is a plain dict (JSONB without MutableDict), so in-place
            # mutations are invisible to the ORM dirty tracker.
            if sig.features:
                sig.features.clear()
                sig.features.update(_original_features)

            # ── Bot-specific ML model override ──
            # If the bot has its own trained model, recompute success_probability
            # using that model instead of the global one pre-calculated by the scanner.
            if bot.ai_signal_mode and bot_registry.model_ready_for_bot(str(bot.id)):
                try:
                    bot_prob = bot_registry.predict_success_probability_for_bot(sig.features or {}, str(bot.id))
                    if bot_prob is not None:
                        old_prob = sig.success_probability
                        sig.success_probability = bot_prob
                        logger.info(
                            f"[ACTIVATOR] {bot.bot_name}: using bot-specific model "
                            f"(global_sp={old_prob:.3f} → bot_sp={bot_prob:.3f})"
                        )
                except Exception as ml_exc:
                    logger.debug(f"[ACTIVATOR] {bot.bot_name}: bot-specific ML failed: {ml_exc}")

            # ── Bot-specific confluence weight re-score ──
            # If the bot has its own adaptive weights, recompute the confluence score
            # using those weights. The signal's structural features are unchanged;
            # only the weighting of each component differs.
            try:
                bot_weights = _load_adaptive_weights(sig.ticker, sig.timeframe, str(bot.id))
                if bot_weights:
                    entry_mid = (float(sig.entry_zone_low) + float(sig.entry_zone_high)) / 2
                    new_score, _, _ = _compute_confluence_score(
                        sig.features or {},
                        sig.direction,
                        bot_weights,
                        at_bonus=sig.features.get("at_bonus", 0.0) if sig.features else 0.0,
                        mc_bonus=sig.features.get("mc_bonus", 0.0) if sig.features else 0.0,
                        entry_mid=entry_mid,
                        apply_hard_gates=False,  # signal already passed gates in scanner
                    )
                    if new_score is not None:
                        old_score = sig.score
                        sig.score = round(new_score, 1)
                        if sig.features:
                            sig.features["score"] = sig.score
                        logger.info(
                            f"[ACTIVATOR] {bot.bot_name}: re-scored with bot weights "
                            f"(global_score={old_score:.1f} → bot_score={sig.score:.1f})"
                        )
            except Exception as cw_exc:
                logger.debug(f"[ACTIVATOR] {bot.bot_name}: bot weight re-score failed: {cw_exc}")

            # ── Asegurar defaults de risk management para bots IA ──
            if bot.ai_signal_mode:
                _ensure_ia_risk_configs(bot)

            # ── Auto-timeframe: skip if signal TF != best historical TF ──
            # FASE 2D: Solo activar auto-timeframe si hay >100 trades históricos
            if getattr(bot, "auto_timeframe", False):
                from app.services.auto_timeframe import resolve_best_timeframe_sync, _DEFAULT_TF
                best_tf = resolve_best_timeframe_sync(sig.ticker, db)
                # Count historical trades for this ticker
                trade_count = db.query(Position).filter(
                    Position.symbol == sig.ticker,
                    Position.status == "closed",
                    Position.source == "ai_bot",
                ).count()
                if trade_count < 100:
                    logger.info(
                        f"[ACTIVATOR] {bot.bot_name}: auto-timeframe DISABLED — "
                        f"only {trade_count} trades for {sig.ticker} (<100 minimum). "
                        f"Accepting signal timeframe {sig.timeframe}"
                    )
                elif sig.timeframe != best_tf and best_tf != _DEFAULT_TF:
                    logger.info(
                        f"[ACTIVATOR] {bot.bot_name}: auto-timeframe skip — "
                        f"signal is {sig.timeframe}, best TF for {sig.ticker} is {best_tf}"
                    )
                    continue
                elif sig.timeframe != best_tf and best_tf == _DEFAULT_TF:
                    logger.info(
                        f"[ACTIVATOR] {bot.bot_name}: auto-timeframe fallback — "
                        f"no data for {sig.ticker}, accepting signal timeframe {sig.timeframe}"
                    )

            # ── Timeframe fallback: accept signals from higher TFs ──
            tf_match = (sig.timeframe == bot.timeframe)
            if not tf_match and (bot.ai_signal_config or {}).get("timeframe_fallback_enabled", False):
                from app.core.constants import VALID_TIMEFRAMES
                try:
                    sig_idx = VALID_TIMEFRAMES.index(sig.timeframe)
                    bot_idx = VALID_TIMEFRAMES.index(bot.timeframe)
                    if sig_idx > bot_idx:  # signal TF is higher/coarser
                        logger.info(
                            f"[ACTIVATOR] {bot.bot_name}: timeframe fallback accepted — "
                            f"bot TF={bot.timeframe}, signal TF={sig.timeframe}"
                        )
                        tf_match = True
                except ValueError:
                    pass

            if not tf_match:
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: timeframe mismatch — "
                    f"bot={bot.timeframe} signal={sig.timeframe}"
                )
                continue

            cfg = bot.ai_signal_config or {}

            # Execution blocked by system safety (drawdown, drift, deployment gate, etc.)
            if cfg.get("execution_blocked"):
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: execution blocked — "
                    f"reason={cfg.get('execution_blocked_reason', 'unknown')}"
                )
                continue

            # Cooldown guard: prevent immediate re-entry after a closed trade
            if _is_in_cooldown(bot, db):
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: in cooldown ({_cooldown_minutes_for_tf(bot.timeframe)}min) — skipping"
                )
                continue

            # Respect autonomy_state pauses from high-precedence systems
            autonomy = cfg.get("autonomy_state", {})
            paused_by = autonomy.get("paused_by")
            if paused_by in ("kill_switch", "emergency_stop"):
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: autonomy paused by {paused_by} — skipping"
                )
                continue

            # Auto-apply optimal config if ai_optimal_config_enabled is set
            if getattr(bot, "ai_optimal_config_enabled", False):
                optimal_cfg = cfg.get("optimal_config", {})
                computed_at = optimal_cfg.get("computed_at")
                stale = True
                if computed_at:
                    try:
                        computed_dt = datetime.fromisoformat(computed_at)
                        if computed_dt.tzinfo is None:
                            computed_dt = computed_dt.replace(tzinfo=timezone.utc)
                        stale = (datetime.now(timezone.utc) - computed_dt) > timedelta(hours=1)
                    except Exception:
                        stale = True
                if stale:
                    optimal = _compute_optimal_config_sync(db, sig.ticker, sig.timeframe, current_cfg=cfg)
                    if optimal:
                        cfg["optimal_config"] = {
                            "config": optimal,
                            "computed_at": datetime.now(timezone.utc).isoformat(),
                        }
                        bot.ai_signal_config = cfg
                else:
                    optimal = optimal_cfg.get("config")
                if optimal:
                    # Merge: optimal overrides existing keys
                    merged = {**cfg, **optimal}
                    if merged != cfg:
                        logger.info(
                            f"[ACTIVATOR] {bot.bot_name}: applied optimal config for {sig.ticker} "
                            f"→ tiers={merged.get('allowed_tiers')} statuses={merged.get('allowed_statuses')} "
                            f"score≥{merged.get('min_score')}"
                        )
                    cfg = merged

            # ── L2 Regime: Apply market regime adjustments ────────────────────
            try:
                from app.services.market_regime import regime_gate_for_signal
                regime_name = sig.features.get("market_regime", "RANGING") if sig.features else "RANGING"
                # Build a minimal RegimeResult from stored features for gate logic
                from app.services.market_regime import RegimeResult
                regime = RegimeResult(
                    regime=regime_name,
                    adx=sig.features.get("regime_adx", 0) if sig.features else 0,
                    atr_percentile=sig.features.get("regime_atr_p", 50) if sig.features else 50,
                    rel_volume=1.0,
                    realized_vol=0.0,
                    btc_corr=None,
                    funding_accel=None,
                    confidence=sig.features.get("regime_confidence", 0.5) if sig.features else 0.5,
                )
                rg = regime_gate_for_signal(bot.symbol, sig.direction, regime)
                if rg["blocked"]:
                    logger.info(
                        f"[ACTIVATOR] {bot.bot_name}: regime BLOCKED — {rg['reason']}"
                    )
                    try:
                        from app.services.rejected_tracker import record_rejection
                        record_rejection(db, sig, "regime", str(bot.id),
                                         extra_context={"regime_reason": rg.get("reason")},
                                         trigger_diagnosis=True)
                    except Exception:
                        pass
                    continue
                if rg["min_score_adjust"]:
                    min_score = cfg.get("min_score", 60) + rg["min_score_adjust"]
                    cfg = {**cfg, "min_score": min_score}
                if rg["allowed_tiers"] is not None:
                    cfg = {**cfg, "allowed_tiers": rg["allowed_tiers"]}
                if rg["sizing_multiplier"] != 1.0:
                    # Store regime sizing multiplier for later application
                    cfg = {**cfg, "regime_sizing_multiplier": rg["sizing_multiplier"]}
                if rg["leverage_max"] is not None:
                    cfg = {**cfg, "leverage_max": rg["leverage_max"]}
                if rg["reason"]:
                    logger.info(
                        f"[ACTIVATOR] {bot.bot_name}: regime adjusted — {rg['reason']}"
                    )
            except Exception as regime_exc:
                logger.warning(f"[ACTIVATOR] Regime gate failed: {regime_exc}")

            min_score        = cfg.get("min_score", 60)
            max_conc         = cfg.get("max_concurrent", 1)

            # ── CATR: Context-Aware Thresholds ─────────────────────────────
            # Ajusta umbrales por (ticker, timeframe, regime) basado en
            # historial reciente de trades. Fallback a globales si no hay datos.
            try:
                regime = (
                    sig.features.get("market_regime", "unknown")
                    if sig.features
                    else "unknown"
                )
                catr = ContextThresholdRegistry()
                context_th = catr.get(sig.ticker, sig.timeframe, regime)

                if context_th.get("confidence", 0) > 0.5:
                    catr_score_th = context_th["score_threshold"]
                    # Cap CATR escalation so it never exceeds a reasonable bound
                    # (prevents overly aggressive gating during transient drawdowns)
                    max_allowed_th = min(80, min_score + 20)
                    effective_min_score = max(min_score, min(catr_score_th, max_allowed_th))
                    effective_prob_th = context_th["prob_threshold"]

                    if effective_min_score != min_score:
                        logger.info(
                            f"[ACTIVATOR] {bot.bot_name}: CATR raised score threshold "
                            f"{min_score} → {effective_min_score} for "
                            f"{sig.ticker}/{sig.timeframe}/{regime} "
                            f"(wr={context_th['recent_winrate']}, "
                            f"n={context_th['n_trades']})"
                        )

                    min_score = effective_min_score
                    # Guardar prob_threshold efectivo para filtro posterior
                    if effective_prob_th > 0:
                        cfg = {**cfg, "_catr_prob_threshold": effective_prob_th}
            except Exception as catr_exc:
                logger.debug(f"[ACTIVATOR] CATR error (using defaults): {catr_exc}")
            # Backward compat: if allowed_* not present but require_clear=False,
            # default to allowing CAUTION as well.
            _legacy_require_clear = cfg.get("require_clear", True)
            allowed_tiers    = cfg.get("allowed_tiers", ["STRONG"])
            allowed_statuses = cfg.get("allowed_statuses",
                                       ["CLEAR"] if _legacy_require_clear else ["CLEAR", "CAUTION"])

            # Tier / status filter (heuristic + XGBoost blended)
            effective_status = _effective_status(sig, cfg, str(bot.id))
            if sig.quality_tier not in allowed_tiers:
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: tier {sig.quality_tier} "
                    f"not in {allowed_tiers}"
                )
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "tier", str(bot.id), trigger_diagnosis=True)
                except Exception:
                    pass
                continue

            if effective_status not in allowed_statuses:
                reason = f"status {effective_status}"
                if sig.success_probability is not None and effective_status != sig.anti_fake_status:
                    reason += f" (ML override: sp={sig.success_probability:.2f}, heuristic={sig.anti_fake_status})"
                logger.info(f"[ACTIVATOR] {bot.bot_name}: {reason} not in {allowed_statuses}")
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "status", str(bot.id),
                                     extra_context={"effective_status": effective_status},
                                     trigger_diagnosis=True)
                except Exception:
                    pass
                continue

            # Historical win-rate filter for exact pattern (auto-calibrated threshold)
            wr = _pattern_win_rate(db, sig.ticker, sig.quality_tier, sig.anti_fake_status, sig.direction)
            pattern_wr_threshold = cfg.get("pattern_wr_threshold", 0.35)
            if wr is not None and wr < pattern_wr_threshold:
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: pattern win rate {wr:.1%} < {pattern_wr_threshold:.0%} "
                    f"({sig.ticker} {sig.quality_tier} {sig.anti_fake_status} {sig.direction})"
                )
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "score", str(bot.id),
                                     extra_context={"pattern_wr": round(wr, 3),
                                                    "threshold": pattern_wr_threshold},
                                     trigger_diagnosis=True)
                except Exception:
                    pass
                continue

            # Circuit breaker by tier — sizing penalty instead of hard block
            cb_state = cfg.get("circuit_breaker_state", {})
            tier_cb = cb_state.get(sig.quality_tier, {})
            if tier_cb.get("tripped_at"):
                consecutive = tier_cb.get("consecutive_sl", 1)
                # Escalated sizing penalty: 1 SL → 0.5x, 2 → 0.35x, 3+ → 0.25x
                if consecutive == 1:
                    cb_mult = 0.50
                elif consecutive == 2:
                    cb_mult = 0.35
                else:
                    cb_mult = 0.25
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: circuit breaker OPEN for "
                    f"tier {sig.quality_tier} ({consecutive} SL) — sizing reduced to {cb_mult:.0%}"
                )
                cfg["cb_sizing_multiplier"] = cb_mult
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "circuit_breaker", str(bot.id),
                                     extra_context={"circuit_breaker_tier": sig.quality_tier,
                                                    "consecutive_sl": consecutive,
                                                    "sizing_multiplier": cb_mult},
                                     trigger_diagnosis=True)
                except Exception:
                    pass

            # Macro context gate
            try:
                from app.services.macro_context import macro_gate_for_signal
                macro = macro_gate_for_signal(sig.ticker, sig.direction)
                if macro["blocked"]:
                    logger.info(
                        f"[ACTIVATOR] {bot.bot_name}: macro context BLOCKED — "
                        f"{macro['warnings']}"
                    )
                    try:
                        from app.services.rejected_tracker import record_rejection
                        record_rejection(db, sig, "macro", str(bot.id),
                                         extra_context={"macro_warnings": macro.get("warnings", [])},
                                         trigger_diagnosis=True)
                    except Exception:
                        pass
                    continue
                if macro["caution"]:
                    logger.info(
                        f"[ACTIVATOR] {bot.bot_name}: macro context CAUTION — "
                        f"{macro['warnings']}"
                    )
            except Exception:
                pass

            # ── Monte Carlo Setup Base Gate (híbrido por confianza) ─────────
            mc_cfg = getattr(bot, "montecarlo_config", None) or {}
            if mc_cfg.get("enabled") and mc_cfg.get("mode") == "setup_base":
                try:
                    from app.engines.mc_setup_engine import MCSetupEngine, MCSetupContext

                    # 1. Cargar setup cache
                    setup_cache = mc_cfg.get("setup_cache", {})
                    context = None
                    if setup_cache:
                        context = MCSetupEngine.get_cached(bot)

                    # 2. Si no hay cache o está stale, recalcular
                    if context is None:
                        strategy_id = mc_cfg.get("strategy_id")
                        if strategy_id:
                            context = MCSetupEngine.run(
                                strategy_id=strategy_id,
                                symbol=bot.symbol,
                                timeframe=bot.timeframe,
                                params=mc_cfg.get("optimized_params"),
                                lookback_days=90,
                            )
                            MCSetupEngine.set_cached(bot, context)
                            # Persistir inmediatamente el cache actualizado
                            db.commit()

                    if context:
                        # 3. Calcular joint_score
                        ai_score = sig.score
                        mc_score = context.mc_validation.get("score", 0)
                        joint_score = (ai_score * 0.5) + (mc_score * 0.5)

                        # 4. Decisión basada en confianza del setup
                        confidence_tier = context.confidence_tier
                        min_joint = mc_cfg.get("min_score", 70.0)

                        if confidence_tier == "high":
                            # Filtro duro: joint_score debe superar umbral
                            if joint_score < min_joint:
                                logger.info(
                                    f"[ACTIVATOR] {bot.bot_name}: MC Setup BLOCK (high confidence) — "
                                    f"joint={joint_score:.1f} < {min_joint}, "
                                    f"ai={ai_score:.1f}, mc={mc_score:.1f}, "
                                    f"bias={context.direction_bias}"
                                )
                                try:
                                    from app.services.rejected_tracker import record_rejection
                                    record_rejection(
                                        db, sig, "montecarlo", str(bot.id),
                                        extra_context={
                                            "joint_score": round(joint_score, 1),
                                            "ai_score": ai_score,
                                            "mc_score": mc_score,
                                            "mc_min_score": min_joint,
                                            "confidence_tier": confidence_tier,
                                            "direction_bias": context.direction_bias,
                                        },
                                        trigger_diagnosis=True,
                                    )
                                except Exception:
                                    pass
                                continue
                            else:
                                logger.info(
                                    f"[ACTIVATOR] {bot.bot_name}: MC Setup PASS (high confidence) — "
                                    f"joint={joint_score:.1f}, ai={ai_score:.1f}, mc={mc_score:.1f}"
                                )
                        elif confidence_tier == "medium":
                            # Ponderación suave: reduce sizing si joint_score bajo
                            sizing_mult = max(0.3, joint_score / 100)
                            cfg["mc_sizing_multiplier"] = sizing_mult
                            logger.info(
                                f"[ACTIVATOR] {bot.bot_name}: MC Setup CAUTION (medium confidence) — "
                                f"joint={joint_score:.1f}, sizing_mult={sizing_mult:.2f}"
                            )
                        else:
                            # Baja confianza: solo log, no afecta ejecución
                            logger.info(
                                f"[ACTIVATOR] {bot.bot_name}: MC Setup LOW confidence — "
                                f"joint={joint_score:.1f}, letting signal through"
                            )

                        # 5. Guardar joint_score en features para tracking
                        sig.features["joint_score"] = round(joint_score, 2)
                        sig.features["mc_score"] = round(mc_score, 2)
                        sig.features["mc_direction_bias"] = context.direction_bias
                        sig.features["mc_confidence_tier"] = confidence_tier
                        db.add(sig)
                        db.commit()

                        # 6. Actualizar historial de joint scores
                        history = mc_cfg.get("joint_score_history", [])
                        history.append({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "ai": round(ai_score, 2),
                            "mc": round(mc_score, 2),
                            "joint": round(joint_score, 2),
                        })
                        mc_cfg["joint_score_history"] = history[-50:]  # últimos 50
                        bot.montecarlo_config = mc_cfg

                except Exception as mc_exc:
                    logger.warning(f"[ACTIVATOR] {bot.bot_name}: MC Setup gate error: {mc_exc}")

            # ── Legacy Monte Carlo Validation Gate (histórico del bot) ───────
            # Este gate sigue activo como capa adicional de seguridad cuando
            # no hay setup_base o como complemento.
            elif mc_cfg.get("enabled"):
                try:
                    from app.engines.montecarlo_engine import TradingValidator
                    from app.models.exchange_trade import ExchangeTrade

                    lookback = mc_cfg.get("n_trades_lookback", 50)
                    min_score = mc_cfg.get("min_score", 70.0)

                    recent_trades = (
                        db.query(ExchangeTrade)
                        .filter(
                            ExchangeTrade.bot_id == bot.id,
                            ExchangeTrade.closed_at.is_not(None),
                            ExchangeTrade.realized_pnl.is_not(None),
                        )
                        .order_by(ExchangeTrade.closed_at.desc())
                        .limit(lookback)
                        .all()
                    )

                    if len(recent_trades) >= 10:
                        mc_trades = []
                        for t in recent_trades:
                            entry_price = float(t.entry_price) if t.entry_price else 0.0
                            exit_price = float(t.exit_price) if t.exit_price else entry_price
                            pnl_abs = float(t.realized_pnl) if t.realized_pnl else 0.0
                            # FASE 3B FIX: pnl_pct debe ser % del capital comprometido (margen), no por unidad.
                            # notional = entry_price * quantity / leverage
                            trade_leverage = float(t.leverage) if t.leverage else 1.0
                            trade_notional = entry_price * float(t.quantity or 0)
                            margin = trade_notional / trade_leverage if trade_leverage > 0 else trade_notional
                            pnl_pct = (pnl_abs / margin * 100.0) if margin > 0 else 0.0
                            mc_trades.append({
                                "entry_time": t.opened_at or t.closed_at,
                                "exit_time": t.closed_at,
                                "direction": 1 if t.side == "long" else -1,
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl_pct": pnl_pct,
                                "pnl_abs": pnl_abs,
                                "duration_bars": 0,
                                "max_drawdown_pct": 0.0,
                            })

                        validator = TradingValidator(initial_capital=10000.0)
                        result = validator.validate_live_from_dicts(mc_trades)
                        should_trade = validator.should_trade(min_score=min_score)

                        if not should_trade:
                            logger.info(
                                f"[ACTIVATOR] {bot.bot_name}: Monte Carlo BLOCK — "
                                f"score={result['validation']['score']:.1f} < {min_score}, "
                                f"failures={result['validation']['failures']}"
                            )
                            try:
                                from app.services.rejected_tracker import record_rejection
                                record_rejection(
                                    db, sig, "montecarlo", str(bot.id),
                                    extra_context={
                                        "mc_score": result["validation"]["score"],
                                        "mc_failures": result["validation"]["failures"],
                                        "mc_min_score": min_score,
                                    },
                                    trigger_diagnosis=True,
                                )
                            except Exception:
                                pass
                            continue
                        else:
                            logger.info(
                                f"[ACTIVATOR] {bot.bot_name}: Monte Carlo PASS — "
                                f"score={result['validation']['score']:.1f}"
                            )
                except Exception as mc_exc:
                    logger.warning(f"[ACTIVATOR] {bot.bot_name}: Monte Carlo gate error: {mc_exc}")

            if sig.score < min_score:
                logger.info(f"[ACTIVATOR] {bot.bot_name}: score {sig.score} < min {min_score}")
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "score", str(bot.id),
                                     extra_context={"min_score": min_score},
                                     trigger_diagnosis=True)
                except Exception:
                    pass
                continue

            # CATR prob threshold filter (solo si CATR ajustó el umbral)
            prob_th = cfg.get("_catr_prob_threshold")
            if (
                prob_th is not None
                and sig.success_probability is not None
                and sig.success_probability < prob_th
            ):
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: prob {sig.success_probability:.3f} < "
                    f"CATR threshold {prob_th}"
                )
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(
                        db, sig, "prob_threshold", str(bot.id),
                        extra_context={"prob_threshold": prob_th, "source": "catr"},
                        trigger_diagnosis=True,
                    )
                except Exception:
                    pass
                continue

            # 0. Bloquear si ya existe posición del MISMO lado en ESTE bot
            same_side_pos = (
                db.query(Position)
                .filter(
                    Position.bot_id == bot.id,
                    Position.symbol == bot.symbol,
                    Position.side == sig.direction,
                    Position.status == "open",
                )
                .first()
            )
            if same_side_pos:
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: ya tiene posición {sig.direction} "
                    f"abierta en {bot.symbol} (id={same_side_pos.id}) — señal rechazada"
                )
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "same_side", str(bot.id),
                                     extra_context={"position_id": str(same_side_pos.id)},
                                     trigger_diagnosis=True)
                except Exception:
                    pass
                continue

            # Only count same-side positions; opposite-side positions are closed
            # by conflict resolution later, so they shouldn't block concurrency.
            open_count = (
                db.query(Position)
                .filter(
                    Position.bot_id == bot.id,
                    Position.symbol == bot.symbol,
                    Position.status == "open",
                    Position.side == sig.direction,
                )
                .count()
            )
            if open_count >= max_conc:
                logger.info(f"[ACTIVATOR] {bot.bot_name}: max_concurrent={max_conc} reached en {bot.symbol}")
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "concurrent", str(bot.id),
                                     extra_context={"open_count": open_count, "max_concurrent": max_conc},
                                     trigger_diagnosis=True)
                except Exception:
                    pass
                continue

            # Fundamental gate
            if bot.fundamental_gate_enabled:
                try:
                    from app.services.fundamental_context import check_fundamental_gate
                    fund_allowed, fund_reason, fund_signal, fund_conf = _arun(
                        check_fundamental_gate(bot.symbol, bot.fundamental_sensitivity)
                    )
                    if not fund_allowed:
                        logger.info(f"[ACTIVATOR] {bot.bot_name}: fundamental gate blocked — {fund_reason}")
                        try:
                            from app.services.rejected_tracker import record_rejection
                            record_rejection(db, sig, "fundamental", str(bot.id),
                                             extra_context={"fundamental_reason": fund_reason, "signal": fund_signal, "confidence": fund_conf},
                                             trigger_diagnosis=True)
                        except Exception:
                            pass
                        continue
                    if fund_reason:
                        logger.info(f"[ACTIVATOR] {bot.bot_name}: fundamental warning — {fund_reason}")
                except Exception as exc:
                    logger.warning("[ACTIVATOR] {}: fundamental gate error — {}", bot.bot_name, exc)

            # ── 2.6 Signal Stacking Policy ────────────────────────────────────────
            try:
                from app.services.stacking_policy import check_stacking_policy
                effective_status = _effective_status(sig, cfg, str(bot.id))
                stack = check_stacking_policy(
                    db=db,
                    bot_id=str(bot.id),
                    symbol=bot.symbol,
                    side=sig.direction,
                    quality_tier=sig.quality_tier,
                    anti_fake_status=effective_status,
                    entry_price=float(sig.entry_price),
                    timeframe=sig.timeframe,
                )
                if not stack["allowed"]:
                    logger.info(f"[ACTIVATOR] {bot.bot_name}: stacking BLOCKED — {stack['reason']}")
                    try:
                        from app.services.rejected_tracker import record_rejection
                        record_rejection(db, sig, "stacking", str(bot.id),
                                         extra_context={"stacking_reason": stack["reason"],
                                                        "stack_count": stack["stack_count"]},
                                         trigger_diagnosis=True)
                    except Exception:
                        pass
                    continue
            except Exception as stack_exc:
                logger.warning(f"[ACTIVATOR] Stacking policy check failed: {stack_exc}")

            try:
                res = _execute_for_bot(db, bot, sig)
                results.append(res)
                activated += 1

                # Telegram/Discord alert — fires once AFTER first successful execution
                if not alert_fired:
                    try:
                        from app.tasks.notification_tasks import ai_signal_alert
                        htf_bias = (sig.features or {}).get("htf_bias")
                        ai_signal_alert.delay(
                            ticker      = sig.ticker,
                            timeframe   = sig.timeframe,
                            direction   = sig.direction,
                            score       = float(sig.score),
                            quality_score = float(sig.quality_score),
                            confidence  = sig.confidence,
                            entry       = float(sig.entry_price),
                            sl          = float(sig.stop_loss),
                            tp1         = float(sig.take_profit_1),
                            tp2         = float(sig.take_profit_2),
                            components  = sig.components or {},
                            warnings    = (sig.warnings or [])[:3],
                            htf_bias    = htf_bias,
                        )
                        alert_fired = True
                    except Exception as _alert_exc:
                        logger.warning("[ACTIVATOR] Alert dispatch failed: {}", _alert_exc)

            except Exception as exc:
                logger.error(
                    "[ACTIVATOR] Error on bot {}: {}",
                    bot.bot_name,
                    exc,
                    exc_info=True,
                )
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="ai_activation_error",
                    message=str(exc)[:500],
                    metadata={"error": str(exc)[:500], "ai_signal_id": str(sig.id)},
                ))
                db.commit()
                # Notificar error al usuario por Telegram
                try:
                    from app.models.user import User
                    from app.tasks.notification_tasks import error_alert
                    user = db.query(User).filter(User.id == bot.user_id).first()
                    if user and user.telegram_chat_id:
                        error_alert.delay(
                            bot_name=bot.bot_name,
                            error=f"IA no pudo abrir posición: {str(exc)[:200]}",
                            chat_id=user.telegram_chat_id,
                        )
                except Exception:
                    pass

        return {"activated": activated, "results": results}


# ── Per-bot execution ─────────────────────────────────────────────────────────

def _execute_for_bot(db, bot: BotConfig, sig: AISignal) -> dict:
    from app.exchanges.factory import create_exchange, create_paper_exchange
    from app.models.paper_balance import PaperBalance

    # Guard: reject signals missing critical price fields BEFORE touching the exchange
    if sig.entry_price is None or sig.stop_loss is None:
        missing = [f for f, v in [("entry_price", sig.entry_price), ("stop_loss", sig.stop_loss)] if v is None]
        logger.warning(f"[ACTIVATOR] {bot.bot_name}: signal {sig.id} missing {missing} — rejecting to prevent orphan")
        return {"status": "rejected", "reason": "missing_price_fields", "detail": f"None fields: {missing}"}

    # Variables para replay snapshot (inicializar antes de cualquier gate)
    _slip_estimate = None
    _route_strategy = None
    _kelly_meta = None
    _horizon_meta = None
    _gates = {}

    cfg = bot.ai_signal_config or {}

    if bot.is_paper_trading:
        paper = db.query(PaperBalance).filter(
            PaperBalance.id == bot.paper_balance_id
        ).first()
        if not paper:
            raise ValueError("PaperBalance not found")
        exchange = create_paper_exchange(paper, bot_id=str(bot.id))
    else:
        if not bot.exchange_account:
            raise ValueError("No exchange_account on bot")
        exchange = create_exchange(bot.exchange_account)

    # ── 4.2 Deployment Gate por par (per-symbol/TF) ──
    # El gate global fue eliminado — solo el per-symbol/TF gate controla ejecución.
    # Cada par se evalúa independientemente; un par malo no envenena a los demás.
    is_paper = bool(getattr(bot, "is_paper_trading", False) or bot.paper_balance_id)
    try:
        from app.services.deployment_gate import get_symbol_gate_status

        if not is_paper:
            sym_gate = get_symbol_gate_status(db, bot.symbol, bot.timeframe)
            if sym_gate.get("state") == "PAUSED":
                from app.services.rejected_tracker import record_rejection
                record_rejection(
                    db, sig, "symbol_deployment_gate", str(bot.id),
                    extra_context={
                        "reason": sym_gate.get("reasons"),
                        "symbol": bot.symbol,
                        "timeframe": bot.timeframe,
                    },
                    trigger_diagnosis=True,
                )
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name}: REJECTED by symbol gate (PAUSED) "
                    f"for {bot.symbol}/{bot.timeframe} — {sym_gate.get('reasons')}"
                )
                return {
                    "status": "rejected",
                    "reason": "symbol_deployment_gate_paused",
                    "detail": sym_gate.get("reasons"),
                }
            elif sym_gate.get("state") == "DEGRADED":
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: Symbol gate DEGRADED for "
                    f"{bot.symbol}/{bot.timeframe} — sizing reduced to {sym_gate.get('sizing_multiplier')}"
                )
    except Exception as dg_exc:
        logger.debug(f"[ACTIVATOR] Symbol gate check skipped: {dg_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # ── Direction-flip gate: FASE 1G FIX — convertido a scoring ──
    # Antes: bloqueaba la dirección por 4h tras 2+ pérdidas consecutivas.
    # Ahora: reduce sizing 50% pero NO bloquea — en tendencia fuerte,
    # bloquear dirección te hace perder el move completo.
    direction_flip_mult = 1.0
    try:
        from sqlalchemy import desc
        loss_outcomes = ["FAILURE_MAX_ADVERSE", "FAILURE", "FAILURE_BEHAVIORAL"]
        recent_signals = (
            db.query(AISignal)
            .filter(
                AISignal.ticker == sig.ticker,
                AISignal.timeframe == sig.timeframe,
                AISignal.outcome.in_(loss_outcomes + ["SUCCESS"]),
                AISignal.resolved_at.isnot(None),
            )
            .order_by(desc(AISignal.resolved_at))
            .limit(10)
            .all()
        )
        consecutive_losses_same_dir = 0
        for s in recent_signals:
            if s.direction and s.direction.upper() == sig.direction.upper():
                if s.outcome in loss_outcomes:
                    consecutive_losses_same_dir += 1
                else:
                    break
            else:
                continue

        if consecutive_losses_same_dir >= 2:
            direction_flip_mult = 0.50
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: DIRECTION FLIP SCORING — "
                f"{consecutive_losses_same_dir} consecutive {sig.direction} losses "
                f"→ sizing will be reduced 50% (NOT blocking)"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="direction_flip_scoring",
                message=f"{consecutive_losses_same_dir} consecutive {sig.direction} losses → sizing 50%",
                metadata={"ai_signal_id": str(sig.id), "loss_outcomes": loss_outcomes},
            ))
            db.commit()
    except Exception as dir_exc:
        logger.debug(f"[ACTIVATOR] Direction-flip gate skipped: {dir_exc}")

    # ── Divergence gate: FASE 1F FIX — deshabilitado temporalmente ──
    # Motivo: paper trading tiene bugs (ignora leverage) por lo que la divergencia
    # es artefacto del bug, no del mercado. Reactivar tras fix completo de paper.
    # if not bot.is_paper_trading:
    #     try:
    #         from app.services.divergence_tracker import is_symbol_blocked
    #         blocked, block_reason = is_symbol_blocked(...)
    #         ...
    #     except Exception:
    #         pass

    # Dynamic leverage adjustment
    from app.services.dynamic_leverage import compute_dynamic_leverage, fetch_funding_rate

    atr_value = float(sig.features.get("atr_value", 0)) if sig.features else 0
    atr_history = sig.features.get("atr_history", []) if sig.features else []

    funding_rate = _arun(fetch_funding_rate(bot.symbol, exchange))

    macro = {"blocked": False, "caution": False, "sizing_adjustment": 1.0}
    try:
        from app.services.macro_context import macro_gate_for_signal
        macro = macro_gate_for_signal(sig.ticker, sig.direction)
    except Exception:
        pass

    # Accumulate pre-notional sizing multipliers from gates that run before notional is computed
    pre_notional_mult = 1.0

    # ── 3.5 Session / Funding gate ──
    session_funding = {"blocked": False, "caution": False, "reason": None}
    try:
        from app.services.session_funding_filter import session_funding_gate
        session_funding = session_funding_gate(bot.symbol, funding_rate, sig.direction)
        if session_funding.get("blocked"):
            # FASE 1G FIX: convertido de bloqueo a scoring
            pre_notional_mult *= 0.70
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: SESSION/FUNDING SCORING — "
                f"{session_funding.get('reason')} → sizing reduced 30% (NOT blocking)"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="session_funding_scoring",
                message=f"Funding adverse: {session_funding.get('reason')} → sizing 70%",
                metadata={"ai_signal_id": str(sig.id), "reason": session_funding.get("reason")},
            ))
        elif session_funding.get("caution"):
            pre_notional_mult *= 0.85
            logger.info(
                f"[ACTIVATOR] {bot.bot_name}: Session/funding caution — "
                f"{session_funding.get('reason')} → sizing reduced 15%"
            )
    except Exception as sf_exc:
        logger.debug(f"[ACTIVATOR] Session/funding evaluation skipped: {sf_exc}")

    # ── 3.4 Open Interest / CVD Rate of Change gate ──
    oi_cvd = {"blocked": False, "caution": False, "reason": None}
    try:
        from app.services.oi_cvd_tracker import evaluate_oi_cvd
        oi_cvd = _arun(evaluate_oi_cvd(exchange, bot.symbol, sig.direction))
        if oi_cvd.get("blocked"):
            # FASE 1G FIX: convertido de bloqueo a scoring
            pre_notional_mult *= 0.70
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: OI/CVD SCORING — "
                f"{oi_cvd.get('reason')} → sizing reduced 30% (NOT blocking)"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="oi_cvd_scoring",
                message=f"OI/CVD anomaly: {oi_cvd.get('reason')} → sizing 70%",
                metadata={"ai_signal_id": str(sig.id), "reason": oi_cvd.get("reason")},
            ))
        elif oi_cvd.get("caution"):
            pre_notional_mult *= 0.85
            logger.info(
                f"[ACTIVATOR] {bot.bot_name}: OI/CVD caution — "
                f"{oi_cvd.get('reason')} → sizing reduced 15%"
            )
    except Exception as oi_exc:
        logger.debug(f"[ACTIVATOR] OI/CVD evaluation skipped: {oi_exc}")

    # ── 2.7 Rolling Beta Gate ──
    beta_gate = {"blocked": False, "caution": False, "sizing_multiplier": 1.0, "reason": None}
    try:
        from app.services.rolling_beta_gate import rolling_beta_gate
        # Fetch last 60 closes for symbol and BTC
        ohlcv_sym = _arun(exchange._client.fetch_ohlcv(bot.symbol, timeframe="1h", limit=61))
        ohlcv_btc = _arun(exchange._client.fetch_ohlcv("BTC/USDT:USDT", timeframe="1h", limit=61))
        sym_prices = [float(c[4]) for c in ohlcv_sym] if ohlcv_sym else []
        btc_prices = [float(c[4]) for c in ohlcv_btc] if ohlcv_btc else []
        beta_gate = rolling_beta_gate(
            db, bot.user_id, bot.symbol, sig.direction, sym_prices, btc_prices,
            user_cfg=cfg,
        )
        if beta_gate.get("blocked"):
            # FASE 1G FIX: convertido de bloqueo a scoring
            mult = beta_gate.get("sizing_multiplier", 0.70)
            pre_notional_mult *= mult
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: ROLLING BETA SCORING — "
                f"{beta_gate.get('reason')} → sizing reduced to {mult:.0%} (NOT blocking)"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="rolling_beta_scoring",
                message=f"Rolling beta: {beta_gate.get('reason')} → sizing {mult:.0%}",
                metadata={"ai_signal_id": str(sig.id), "reason": beta_gate.get("reason"), "mult": mult},
            ))
        elif beta_gate.get("caution"):
            mult = beta_gate.get("sizing_multiplier", 0.85)
            pre_notional_mult *= mult
            logger.info(
                f"[ACTIVATOR] {bot.bot_name}: Rolling beta caution — "
                f"{beta_gate.get('reason')} → sizing reduced to {mult:.0%}"
            )
    except Exception as beta_exc:
        logger.debug(f"[ACTIVATOR] Rolling beta evaluation skipped: {beta_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # FASE 2A: Apalancamiento por score + timeframe + ATR
    # Tabla score+TF determina el CAP máximo. El ATR puede reducirlo
    # aún más si la volatilidad es extrema, pero NUNCA supera el cap.
    # Mínimo 3x para que fees+slippage no coman toda la ganancia.
    confluence_score = float(sig.score) if sig.score else 0.0
    score_tf_cap = _get_leverage_cap(confluence_score, bot.timeframe)
    if score_tf_cap == 0:
        logger.info(
            f"[ACTIVATOR] {bot.bot_name}: score={confluence_score:.1f} tf={bot.timeframe} "
            f"— por debajo del mínimo (55), no opera"
        )
        return {"status": "rejected", "reason": "score_below_minimum", "detail": f"score={confluence_score:.1f} < 55"}

    entry_price_for_lev = float(sig.entry_price) if sig.entry_price else 0.0
    if atr_value > 0 and entry_price_for_lev > 0:
        atr_pct = atr_value / entry_price_for_lev
        target_atr_pct = 0.10  # 10% target for crypto futures
        atr_based_lev = int(target_atr_pct / atr_pct)
        base_leverage = min(score_tf_cap, max(3, atr_based_lev))
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} leverage score+TF — "
            f"score={confluence_score:.1f} tf_cap={score_tf_cap}x "
            f"atr_based={atr_based_lev}x → base_leverage={base_leverage}x "
            f"(atr={atr_value:.4f} atr_pct={atr_pct:.4%})"
        )
    else:
        # Fallback al cap por score+TF si no hay datos de ATR
        base_leverage = score_tf_cap
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} leverage score+TF (no ATR) — "
            f"score={confluence_score:.1f} tf_cap={score_tf_cap}x → base_leverage={base_leverage}x"
        )

    dyn_leverage = compute_dynamic_leverage(
        base_leverage=base_leverage,
        current_atr=atr_value,
        atr_history=atr_history,
        funding_rate=funding_rate,
        macro_blocked=macro.get("blocked", False),
        macro_caution=macro.get("caution", False),
    )

    effective_leverage = dyn_leverage

    # Apply regime leverage cap if set
    cfg = bot.ai_signal_config or {}
    regime_leverage_max = cfg.get("leverage_max")
    if regime_leverage_max is not None and effective_leverage > regime_leverage_max:
        effective_leverage = regime_leverage_max
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} regime leverage capped — "
            f"max={regime_leverage_max:.1f}x"
        )

    # Set leverage — must succeed before opening. If the exchange rejects it
    # (e.g. leverage already locked by an existing position) we log a loud
    # warning and continue, because the position may still open with the
    # exchange's current leverage.
    try:
        _arun(exchange.set_leverage(bot.symbol, effective_leverage, sig.direction))
    except Exception as lev_exc:
        logger.warning(
            f"[ACTIVATOR] {bot.bot_name} set_leverage({effective_leverage}x) failed: {lev_exc}. "
            f"The exchange may open the position with a different leverage."
        )

    # Size position
    balance_info = _arun(exchange.get_equity())
    equity = float(balance_info.total_equity)

    # FASE 2B: Position sizing por riesgo ($)
    if bot.position_sizing_type == "risk_based":
        # position_value = % del equity a arriesgar (ej. 1.0 = 1%)
        risk_pct = float(bot.position_value) / 100.0
        risk_amount = equity * risk_pct
        entry_p = float(sig.entry_price) if sig.entry_price else 0.0
        sl_p = float(sig.stop_loss) if sig.stop_loss else 0.0
        risk_distance = abs(entry_p - sl_p)
        if risk_distance > 0 and entry_p > 0:
            # notional = cantidad de margen necesaria para que el riesgo ($) sea correcto
            # risk_amount = notional * leverage * (risk_distance / entry_p)
            # → notional = risk_amount / (leverage * risk_distance / entry_p)
            notional = risk_amount / (effective_leverage * risk_distance / entry_p)
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} RISK-BASED sizing — "
                f"equity={equity:.2f} risk_pct={risk_pct:.2%} risk_amount={risk_amount:.2f} "
                f"entry={entry_p:.4f} sl={sl_p:.4f} dist={risk_distance:.4f} "
                f"leverage={effective_leverage}x → notional={notional:.2f}"
            )
        else:
            notional = 0.0
            logger.error(
                f"[ACTIVATOR] {bot.bot_name} RISK-BASED sizing FAILED — "
                f"invalid entry/sl (entry={entry_p}, sl={sl_p})"
            )
    elif bot.position_sizing_type == "percentage":
        notional = equity * float(bot.position_value) / 100.0
    else:
        notional = float(bot.position_value)

    # Apply pre-notional gate multipliers (session/funding, OI/CVD, rolling beta)
    if pre_notional_mult != 1.0:
        notional = notional * pre_notional_mult
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} pre-notional gate multiplier applied — "
            f"mult={pre_notional_mult:.2f} notional={notional:.2f}"
        )

    # Dynamic sizing by quality tier / anti-fake status
    cfg = bot.ai_signal_config or {}
    sizing_cfg = cfg.get("sizing_multipliers", {})
    tier_mult    = sizing_cfg.get(sig.quality_tier, 1.0)
    status_mult  = sizing_cfg.get(sig.anti_fake_status, 1.0)
    cb_mult      = cfg.pop("cb_sizing_multiplier", 1.0)
    mc_mult      = cfg.pop("mc_sizing_multiplier", 1.0)

    # Gate-health sizing: boost winners, cut losers
    gate_mult = 1.0
    try:
        from app.services.deployment_gate import get_symbol_gate_status
        gst = get_symbol_gate_status(db, bot.symbol, bot.timeframe)
        if gst.get("state") == "HEALTHY":
            sharpe = gst.get("sharpe_20")
            pf = gst.get("profit_factor")
            if sharpe is not None and pf is not None:
                if sharpe > 5 and pf > 3:
                    gate_mult = 1.25
                elif sharpe > 2 and pf > 1.5:
                    gate_mult = 1.10
                elif sharpe < -3 or pf < 0.5:
                    gate_mult = 0.50
                elif sharpe < 0 or pf < 1.0:
                    gate_mult = 0.75
    except Exception as gate_exc:
        logger.debug(f"[ACTIVATOR] Gate-health sizing skipped: {gate_exc}")

    # Entry-type sizing: Risk Entry (no CDC) gets reduced exposure while model learns
    entry_type = (sig.features or {}).get("entry_type", "CE")
    entry_type_mult = 0.60 if entry_type == "RE" else 1.0
    if entry_type == "RE":
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} Risk Entry sizing — "
            f"reduced to {entry_type_mult:.0%} (no CDC confirmation)"
        )

    combined_mult = tier_mult * status_mult * cb_mult * gate_mult * mc_mult * entry_type_mult * direction_flip_mult
    if combined_mult != 1.0:
        notional = notional * combined_mult
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} sizing adjusted — "
            f"tier_mult={tier_mult} status_mult={status_mult} cb_mult={cb_mult} "
            f"gate_mult={gate_mult:.2f} mc_mult={mc_mult:.2f} entry_type_mult={entry_type_mult:.2f} "
            f"direction_flip_mult={direction_flip_mult:.2f} notional={notional:.2f}"
        )

    # Apply regime sizing multiplier if set
    regime_sizing = cfg.get("regime_sizing_multiplier", 1.0)
    if regime_sizing != 1.0:
        notional = notional * regime_sizing
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} regime sizing adjusted — "
            f"mult={regime_sizing:.2f} notional={notional:.2f}"
        )

    # ── L1 Risk: Kelly Criterion Sizing ────────────────────────────────────────
    try:
        from app.services.kelly_sizing import compute_kelly_sizing

        # Compute ATR percentile from history
        atr_percentile = None
        if atr_history and len(atr_history) >= 10:
            sorted_atr = sorted(atr_history)
            rank = sum(1 for a in sorted_atr if a < atr_value)
            atr_percentile = (rank / len(sorted_atr)) * 100

        # Pass regime for regime-specific Kelly caps (Sprint 1.4)
        regime_name = sig.features.get("market_regime", "RANGING") if sig.features else "RANGING"

        kelly = compute_kelly_sizing(
            db=db,
            bot_id=str(bot.id),
            ticker=sig.ticker,
            timeframe=sig.timeframe,
            base_notional=notional,
            equity=equity,
            atr_percentile=atr_percentile,
            regime=regime_name,
            user_cfg=cfg,
        )
        _kelly_meta = {
            "edge": kelly.edge,
            "kelly_fraction": kelly.kelly_fraction,
            "half_kelly": kelly.half_kelly,
            "sizing_multiplier": kelly.sizing_multiplier,
            "capped_reason": kelly.capped_reason,
        }

        if kelly.sizing_multiplier <= 0:
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: Kelly BLOCKED — "
                f"edge={kelly.edge:.4f} reason={kelly.capped_reason}"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="kelly_blocked",
                message=f"Kelly criterion blocked: {kelly.capped_reason}",
                metadata={
                    "ai_signal_id": str(sig.id),
                    "edge": kelly.edge,
                    "kelly_fraction": kelly.kelly_fraction,
                    "half_kelly": kelly.half_kelly,
                    "reason": kelly.capped_reason,
                },
            ))
            try:
                from app.services.rejected_tracker import record_rejection
                record_rejection(db, sig, "kelly", str(bot.id),
                                 extra_context={"kelly_reason": kelly.capped_reason, "edge": kelly.edge},
                                 trigger_diagnosis=True)
            except Exception:
                pass
            db.commit()
            return {
                "bot_id": str(bot.id),
                "bot_name": bot.bot_name,
                "blocked": True,
                "reason": "kelly_criterion",
            }

        if kelly.sizing_multiplier != 1.0:
            notional = notional * kelly.sizing_multiplier
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} Kelly sizing adjusted — "
                f"mult={kelly.sizing_multiplier:.2f} edge={kelly.edge:.4f} "
                f"half_kelly={kelly.half_kelly:.4f} notional={notional:.2f}"
                + (f" cap={kelly.capped_reason}" if kelly.capped_reason else "")
            )
    except Exception as kelly_exc:
        logger.warning(f"[ACTIVATOR] Kelly sizing check failed: {kelly_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # ── L1 Risk: Feature Drift Detector (PSI) ────────────────────────────────
    try:
        from app.services.drift_detector import get_drift_status_for_signal
        model_id = f"xgb_{sig.ticker}_{sig.timeframe}"
        drift = get_drift_status_for_signal(db, sig.ticker, sig.timeframe, model_id, user_cfg=cfg)

        if drift["blocked"]:
            # FASE 1G FIX: convertido de bloqueo a scoring agresivo
            mult = 0.50  # Reduce 50% cuando drift es severo
            notional = notional * mult
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: DRIFT SCORING — "
                f"status={drift['reason']} max_psi={drift['max_psi']} → sizing reduced to {mult:.0%} ({notional:.2f})"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="drift_scoring",
                message=f"Feature drift severe: {drift['reason']} → sizing {mult:.0%}",
                metadata={
                    "ai_signal_id": str(sig.id),
                    "max_psi": drift["max_psi"],
                    "action": drift["action"],
                    "mult": mult,
                },
            ))
            db.commit()
        elif drift["degraded"]:
            notional = notional * drift["sizing_multiplier"]
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} drift sizing adjusted — "
                f"mult={drift['sizing_multiplier']:.2f} max_psi={drift['max_psi']:.4f} "
                f"notional={notional:.2f}"
            )
    except Exception as drift_exc:
        logger.warning(f"[ACTIVATOR] Drift check failed: {drift_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # ── L2 Regime: Macro funding dynamics sizing adjustment ──────────────────
    macro_sizing = macro.get("sizing_adjustment", 1.0)
    if macro_sizing < 1.0:
        notional = notional * macro_sizing
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} macro sizing adjusted — "
            f"mult={macro_sizing:.2f} notional={notional:.2f}"
        )

    # ── L3 Execution: Slippage + Transaction Cost Gate ───────────────────────
    # Block trades where expected profit is eaten by fees + slippage
    try:
        from app.services.slippage_predictor import estimate_slippage
        from app.services.execution_analytics import get_profile_for_signal

        entry_price = float(sig.entry_price) if sig.entry_price else 0.0
        sl_price = float(sig.stop_loss) if sig.stop_loss else 0.0
        tp_price = float(sig.take_profit_1) if sig.take_profit_1 else 0.0

        # 1. Slippage estimate
        slip = estimate_slippage(
            symbol=bot.symbol,
            direction=sig.direction,
            notional=notional,
            entry_price=entry_price,
            stop_loss=sl_price,
            atr_value=atr_value if atr_value > 0 else None,
            user_cfg=cfg,
        )
        _slip_estimate = {
            "slippage_pct": slip.slippage_pct,
            "risk_distance_pct": slip.risk_distance_pct,
            "ratio": slip.slippage_vs_risk_ratio,
            "action": slip.action,
            "reason": slip.reason,
        }
        if slip.action == "abort":
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: SLIPPAGE ABORT — {slip.reason}"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="slippage_abort",
                message=f"Slippage abort: {slip.reason}",
                metadata={"notional": notional, "slippage_pct": slip.slippage_pct, "risk_pct": slip.risk_distance_pct},
            ))
            try:
                from app.services.rejected_tracker import record_rejection
                record_rejection(db, sig, "slippage", str(bot.id),
                                 extra_context={"slippage_reason": slip.reason, "ratio": slip.slippage_vs_risk_ratio})
            except Exception:
                pass
            db.commit()
            return {
                "bot_id": str(bot.id),
                "bot_name": bot.bot_name,
                "blocked": True,
                "reason": "slippage_abort",
            }
        elif slip.action == "reduce_70":
            notional = notional * 0.30
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} slippage sizing reduced — "
                f"mult=0.30 reason={slip.reason} notional={notional:.2f}"
            )

        # 2. Transaction cost viability gate
        profile = get_profile_for_signal(sig.ticker, sig.timeframe)
        fee_cost_pct = profile.fee_rate * 100.0 * 2.0  # entry + exit
        slippage_cost_pct = profile.avg_entry_slippage_pct + abs(profile.avg_tp_slippage_pct)
        total_cost_pct = fee_cost_pct + slippage_cost_pct

        if entry_price > 0 and tp_price > 0:
            expected_pnl_pct = abs(tp_price - entry_price) / entry_price * 100.0
            # Require expected PnL to be at least 1.5x total costs to be viable
            if expected_pnl_pct <= total_cost_pct * 1.5:
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name}: COST GATE — expected PnL {expected_pnl_pct:.3f}% "
                    f"<= costs {total_cost_pct:.3f}%*1.5 (fee={fee_cost_pct:.3f}% slippage={slippage_cost_pct:.3f}%)"
                )
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="cost_gate_blocked",
                    message=f"Cost gate: TP distance too small to cover fees+slippage",
                    metadata={
                        "expected_pnl_pct": expected_pnl_pct,
                        "fee_cost_pct": fee_cost_pct,
                        "slippage_cost_pct": slippage_cost_pct,
                        "total_cost_pct": total_cost_pct,
                        "notional": notional,
                    },
                ))
                try:
                    from app.services.rejected_tracker import record_rejection
                    record_rejection(db, sig, "cost_gate", str(bot.id),
                                     extra_context={"expected_pnl_pct": expected_pnl_pct, "total_cost_pct": total_cost_pct})
                except Exception:
                    pass
                db.commit()
                return {
                    "bot_id": str(bot.id),
                    "bot_name": bot.bot_name,
                    "blocked": True,
                    "reason": "cost_gate",
                }
            else:
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name} cost gate passed — "
                    f"expected PnL {expected_pnl_pct:.3f}% > costs {total_cost_pct:.3f}%*1.5"
                )
    except Exception as cost_exc:
        logger.warning(f"[ACTIVATOR] Slippage/cost gate check failed: {cost_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # ─── Minimum notional guard — BEFORE portfolio so risk is evaluated on final size
    min_notional = _get_min_viable_notional(bot.symbol, float(sig.entry_price) if sig.entry_price else 0)
    if notional < min_notional:
        logger.warning(
            f"[ACTIVATOR] {bot.bot_name} notional {notional:.2f} < min {min_notional:.2f} — "
            f"auto-adjusting to {min_notional:.2f} USDT"
        )
        notional = min_notional

    # Portfolio risk guard
    try:
        from app.services.portfolio_manager import evaluate_portfolio_risk
        risk = evaluate_portfolio_risk(
            db, bot, notional, sig.direction, equity
        )
        if risk["blocked"]:
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: portfolio BLOCKED — "
                f"{risk['warnings']}"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="portfolio_blocked",
                message=f"Portfolio blocked: {', '.join(risk['warnings'])}",
                metadata={
                    "ai_signal_id": str(sig.id),
                    "warnings": risk["warnings"],
                    "exposure_pct": risk["total_exposure_pct"],
                },
            ))
            try:
                from app.services.rejected_tracker import record_rejection
                record_rejection(db, sig, "portfolio", str(bot.id),
                                 extra_context={"portfolio_warnings": risk.get("warnings", [])})
            except Exception:
                pass
            db.commit()
            return {
                "bot_id": str(bot.id),
                "bot_name": bot.bot_name,
                "blocked": True,
                "reason": "portfolio_risk",
            }
        if risk["sizing_multiplier"] < 1.0:
            notional = notional * risk["sizing_multiplier"]
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} portfolio sizing adjusted — "
                f"mult={risk['sizing_multiplier']} notional={notional:.2f} "
                f"reason={risk['warnings']}"
            )
    except Exception as pm_exc:
        logger.warning(f"[ACTIVATOR] Portfolio risk check failed: {pm_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # ── L2.5 Dynamic Risk: Exposure Cap by Symbol ──────────────────────────
    try:
        from app.services.dynamic_risk_manager import ExposureCapBySymbol, _dynamic_risk_config

        # Gather user's open positions for this symbol
        # Only count positions of the SAME type (real or paper) to avoid
        # paper positions blocking real trades and vice versa.
        op_q = (
            db.query(Position)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .filter(
                BotConfig.user_id == bot.user_id,
                Position.status == "open",
            )
        )
        if bot.is_paper_trading:
            op_q = op_q.filter(BotConfig.paper_balance_id.isnot(None))
        else:
            op_q = op_q.filter(BotConfig.paper_balance_id.is_(None))
        open_positions = op_q.all()

        # Compute proposed risk % for this new trade
        entry_p = float(sig.entry_price)
        sl_p = float(sig.stop_loss)
        risk_distance = abs(entry_p - sl_p)
        proposed_risk_pct = risk_distance / entry_p if entry_p > 0 else 0

        dr_cfg = _dynamic_risk_config(bot)
        ecs_cfg = dr_cfg.get("exposure_caps", {}) if dr_cfg else {}
        ecs_slippage = dr_cfg.get("slippage_multipliers", {}) if dr_cfg else {}

        cap_result = ExposureCapBySymbol.check(
            symbol=bot.symbol,
            proposed_risk_pct=proposed_risk_pct,
            open_positions=open_positions,
            user_cfg={"exposure_caps": ecs_cfg, "slippage_multipliers": ecs_slippage} if dr_cfg else None,
        )

        if not cap_result["allowed"]:
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name}: EXPOSURE CAP BLOCKED — "
                f"{cap_result['reason']}"
            )
            db.add(BotLog(
                bot_id=bot.id,
                event_type="exposure_cap_blocked",
                message=f"Exposure cap blocked: {cap_result['reason']}",
                metadata={
                    "ai_signal_id": str(sig.id),
                    "symbol": bot.symbol,
                    "proposed_risk_pct": proposed_risk_pct,
                    "reason": cap_result["reason"],
                },
            ))
            try:
                from app.services.rejected_tracker import record_rejection
                record_rejection(db, sig, "exposure_cap", str(bot.id),
                                 extra_context={"exposure_cap_reason": cap_result["reason"]})
            except Exception:
                pass
            db.commit()
            return {
                "bot_id": str(bot.id),
                "bot_name": bot.bot_name,
                "blocked": True,
                "reason": "exposure_cap",
            }

        # Apply slippage multiplier to sizing (increases effective risk estimate)
        slippage_mult = cap_result.get("slippage_multiplier", 1.0)
        if slippage_mult > 1.0:
            # Reduce notional to account for expected worse slippage on this symbol
            notional = notional / slippage_mult
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} slippage multiplier adjusted — "
                f"mult={slippage_mult:.1f} notional={notional:.2f}"
            )
    except Exception as ecs_exc:
        logger.warning(f"[ACTIVATOR] Exposure cap check failed: {ecs_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # ── Real-time LLM diagnosis gate ─────────────────────────────────────────
    # FASE 1F FIX: Convertido de bloqueo letal a scoring.
    # Antes: BLOCK rechazaba, CAUTION podía rechazar si score bajaba.
    # Ahora: BLOCK reduce notional 50%, CAUTION reduce notional 15%.
    # Nunca rechaza — el LLM gate era un punto de fallo innecesario.
    # Missing → proceed (diagnosis may not be ready yet).
    try:
        from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
        diag = (
            db.query(LLMSignalDiagnosis)
            .filter(
                LLMSignalDiagnosis.ai_signal_id == sig.id,
                LLMSignalDiagnosis.trigger_source == "anti_fake",
            )
            .order_by(LLMSignalDiagnosis.created_at.desc())
            .first()
        )
        if diag and diag.diagnosis_json:
            verdict = (diag.diagnosis_json.get("verdict") or "CLEAR").upper()
            confidence = float(diag.diagnosis_json.get("confidence") or 50)
            if verdict == "BLOCK":
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name}: LLM diagnosis BLOCK "
                    f"(conf={confidence:.0f}) → reducing notional 50% (NOT rejecting)"
                )
                notional = notional * 0.50
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="llm_block_scoring",
                    message=f"LLM BLOCK reduced notional 50%",
                    metadata={"ai_signal_id": str(sig.id), "llm_confidence": confidence},
                ))
            elif verdict == "CAUTION":
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name}: LLM diagnosis CAUTION "
                    f"(conf={confidence:.0f}) → reducing notional 15%"
                )
                notional = notional * 0.85
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="llm_caution_scoring",
                    message=f"LLM CAUTION reduced notional 15%",
                    metadata={"ai_signal_id": str(sig.id), "llm_confidence": confidence},
                ))
            else:
                logger.debug(
                    f"[ACTIVATOR] {bot.bot_name}: LLM diagnosis CLEAR (conf={confidence:.0f}) → proceeding"
                )
    except Exception as diag_exc:
        logger.debug(f"[ACTIVATOR] LLM diagnosis query failed: {diag_exc}")

    # ─── Calcular cantidad usando el exchange (respeta min_amount / precision) ─
    # notional = margen en USDT ya ajustado por tier/status/portfolio
    quantity = _arun(exchange.calculate_quantity(
        symbol=bot.symbol,
        equity=Decimal(str(equity)),
        sizing_type="fixed",
        sizing_value=Decimal(str(notional)),
        leverage=effective_leverage,
    ))

    logger.info(
        f"[ACTIVATOR] {bot.bot_name} | {sig.direction.upper()} {sig.ticker} | "
        f"qty={quantity} sl={sig.stop_loss} tp1={sig.take_profit_1}"
    )

    # ─── Resolver conflictos antes de abrir ─────────────────────
    from app.core.conflict_resolver import get_conflicting_positions, resolve_conflict
    from app.core.engine import close_position_for_bot
    from app.models.user import User

    # 1. Cerrar posición contraria del PROPIO bot si existe
    own_opposite = db.query(Position).filter(
        Position.bot_id == bot.id,
        Position.symbol == bot.symbol,
        Position.status == "open",
        Position.side != sig.direction,
    ).first()

    if own_opposite:
        logger.info(
            f"[ACTIVATOR] Cerrando posición contraria {own_opposite.side} "
            f"del propio bot {bot.bot_name}"
        )
        try:
            closed_pos = close_position_for_bot(db, bot, position_to_close=own_opposite)
            db.add(BotLog(
                bot_id=bot.id,
                event_type="position_closed_by_ia_own_opposite",
                message=f"Closed own {own_opposite.side} position to open {sig.direction}",
                metadata={
                    "ai_signal_id": str(sig.id),
                    "closed_side": own_opposite.side,
                    "opened_side": sig.direction,
                    "realized_pnl": float(closed_pos.realized_pnl) if closed_pos.realized_pnl else 0,
                },
            ))
            db.commit()
        except Exception as close_exc:
            logger.error(
                "[ACTIVATOR] Error cerrando posición propia contraria: {}", close_exc
            )
            return {
                "bot_id": str(bot.id),
                "bot_name": bot.bot_name,
                "blocked": True,
                "reason": f"No se pudo cerrar posición propia contraria: {close_exc}",
            }

    # 1.5 Verificar posiciones HUÉRFANAS en la exchange (no trackeadas en DB)
    # Esto previene abrir long+short simultáneos cuando una posición se quedó
    # fuera de sync por un error previo (orphan position).
    try:
        live_positions = _arun(exchange.get_open_positions())
        for live_pos in live_positions:
            if _to_ccxt_symbol(live_pos.symbol) != _to_ccxt_symbol(bot.symbol):
                continue
            # ¿Está esta posición viva trackeada en DB?
            live_in_db = db.query(Position).filter(
                Position.symbol == _to_ccxt_symbol(live_pos.symbol),
                Position.status == "open",
                Position.side == live_pos.side,
            ).first()
            if live_in_db:
                continue  # Ya la conocemos, el flujo normal la maneja

            # Huérfana detectada en la exchange
            if live_pos.side != sig.direction:
                # Posición contraria huérfana → cerrarla para no tener ambas direcciones
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name}: Cerrando posición HUÉRFANA "
                    f"{live_pos.side} en {live_pos.symbol} (qty={live_pos.quantity}) "
                    f"antes de abrir {sig.direction}"
                )
                try:
                    _arun(exchange.close_position(
                        live_pos.symbol,
                        side=live_pos.side,
                        quantity=float(live_pos.quantity),
                    ))
                    db.add(BotLog(
                        bot_id=bot.id,
                        event_type="orphan_position_closed",
                        message=f"Closed orphan {live_pos.side} position before opening {sig.direction}",
                        metadata={
                            "symbol": live_pos.symbol,
                            "side": live_pos.side,
                            "quantity": float(live_pos.quantity),
                            "entry_price": float(live_pos.entry_price) if hasattr(live_pos, "entry_price") else None,
                        },
                    ))
                    db.commit()
                except Exception as orphan_close_exc:
                    logger.error(
                        f"[ACTIVATOR] {bot.bot_name}: No se pudo cerrar posición huérfana "
                        f"{live_pos.side}: {orphan_close_exc}"
                    )
                    return {
                        "bot_id": str(bot.id),
                        "bot_name": bot.bot_name,
                        "blocked": True,
                        "reason": f"Orphan {live_pos.side} position exists and could not be closed: {orphan_close_exc}",
                    }
            else:
                # Posición en MISMA dirección huérfana → bloquear para no duplicar
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name}: BLOQUEADO — existe posición HUÉRFANA "
                    f"{live_pos.side} en {live_pos.symbol} (qty={live_pos.quantity}) "
                    f"no trackeada en DB. Reconciler debe sync primero."
                )
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="orphan_position_blocked",
                    message=f"Blocked: orphan {live_pos.side} position exists on exchange",
                    metadata={
                        "symbol": live_pos.symbol,
                        "side": live_pos.side,
                        "quantity": float(live_pos.quantity),
                    },
                ))
                db.commit()
                return {
                    "bot_id": str(bot.id),
                    "bot_name": bot.bot_name,
                    "blocked": True,
                    "reason": f"Orphan {live_pos.side} position exists on exchange (not tracked in DB). Close manually or wait for reconciler.",
                }
    except Exception as live_exc:
        logger.warning(
            f"[ACTIVATOR] {bot.bot_name}: No se pudieron verificar posiciones "
            f"huérfanas en exchange: {live_exc}"
        )

    # 2. Resolver conflictos con OTROS bots
    conflicting = get_conflicting_positions(db, bot)
    conflict_result = resolve_conflict(db, bot, sig.direction, "ia", conflicting)

    if conflict_result["action"] == "reject":
        msg = conflict_result["reason"]
        logger.warning(f"[ACTIVATOR] {bot.bot_name} rechazado: {msg}")
        db.add(BotLog(
            bot_id=bot.id,
            event_type="ai_conflict_rejected",
            message=msg,
            metadata={
                "ai_signal_id": str(sig.id),
                "direction": sig.direction,
                "reason": msg,
            },
        ))
        db.commit()
        # Notificar Telegram
        try:
            from app.services.rejected_tracker import record_rejection
            record_rejection(db, sig, "stacking", str(bot.id),
                             extra_context={"stacking_reason": msg},
                             trigger_diagnosis=True)
        except Exception:
            pass
        user = db.query(User).filter(User.id == bot.user_id).first()
        if user and user.telegram_chat_id:
            from app.tasks.notification_tasks import trade_rejected
            trade_rejected.delay(
                bot_name=bot.bot_name,
                symbol=bot.symbol,
                side=sig.direction,
                reason=msg,
                chat_id=user.telegram_chat_id,
            )
        return {
            "bot_id": str(bot.id),
            "bot_name": bot.bot_name,
            "blocked": True,
            "reason": msg,
        }

    # Cerrar posiciones contrarias de OTROS bots si la config lo indica
    from app.models.bot_config import BotConfig as _BotConfig
    for pos_to_close in conflict_result.get("close_positions", []):
        other_bot = db.query(_BotConfig).filter(_BotConfig.id == pos_to_close.bot_id).first()
        other_name = other_bot.bot_name if other_bot else f"bot_{pos_to_close.bot_id}"
        logger.info(
            f"[ACTIVATOR] Cerrando posición de {other_name} "
            f"para dar paso a IA {bot.bot_name}"
        )
        try:
            closed_pos = close_position_for_bot(
                db, other_bot or bot, position_to_close=pos_to_close
            )
            if other_bot:
                db.add(BotLog(
                    bot_id=other_bot.id,
                    event_type="position_closed_by_ia_priority",
                    message=f"Position closed by IA priority from {bot.bot_name}",
                    metadata={
                        "closed_by_bot_id": str(bot.id),
                        "closed_by_bot_name": bot.bot_name,
                        "ai_signal_id": str(sig.id),
                        "realized_pnl": float(closed_pos.realized_pnl) if closed_pos.realized_pnl else 0,
                    },
                ))
                db.commit()
                user = db.query(User).filter(User.id == bot.user_id).first()
                if user and user.telegram_chat_id:
                    from app.tasks.notification_tasks import position_override
                    position_override.delay(
                        closed_bot_name=other_name,
                        opened_bot_name=bot.bot_name,
                        symbol=bot.symbol,
                        side=sig.direction,
                        chat_id=user.telegram_chat_id,
                    )
        except Exception as close_exc:
            logger.error(
                f"[ACTIVATOR] Error cerrando posición de {other_name}: {close_exc}"
            )
            return {
                "bot_id": str(bot.id),
                "bot_name": bot.bot_name,
                "blocked": True,
                "reason": f"No se pudo cerrar posición de {other_name}: {close_exc}",
            }

    # ── 2.2 Smart Order Routing (SOR) ───────────────────────────────────────
    signal_age = (datetime.now(timezone.utc) - sig.signal_time).total_seconds()
    try:
        from app.services.smart_order_router import route_order, get_current_bid_ask
        best_bid, best_ask = _arun(get_current_bid_ask(exchange, bot.symbol))
        route = route_order(
            symbol=bot.symbol,
            direction=sig.direction,
            quantity=quantity,
            notional=float(notional),
            entry_price=float(sig.entry_price),
            best_bid=best_bid,
            best_ask=best_ask,
            atr_value=atr_value,
            signal_age_seconds=signal_age,
        )
        _route_strategy = {
            "strategy": route.strategy,
            "reason": route.reason,
            "price": float(route.price) if route.price else None,
            "slices": route.slices,
        }
        logger.info(
            f"[SOR] {bot.bot_name}: {route.strategy} — {route.reason} "
            f"price={route.price} slices={route.slices}"
        )
    except Exception as sor_exc:
        logger.warning("[SOR] {}: routing failed, falling back to MARKET: {}", bot.bot_name, sor_exc)
        route = None

    # Evaluación 2: Regime-aware order type override
    # If existing router says LIMIT but confidence is very high → prefer MARKET for speed
    # If existing router says MARKET but regime is volatile → prefer LIMIT for control
    try:
        from execution.smart_router import SmartOrderRouter
        regime_name = sig.features.get("market_regime", "ranging") if sig.features else "ranging"
        success_prob = getattr(sig, "success_probability", None) or 0.5
        spread_pct = 0.0
        if best_bid and best_ask and sig.entry_price:
            spread_pct = (best_ask - best_bid) / float(sig.entry_price)

        regime_route = SmartOrderRouter.route(
            entry_price=float(sig.entry_price),
            direction=sig.direction,
            confidence=success_prob,
            regime=regime_name,
            spread_pct=spread_pct,
        )
        # Override only if regime router disagrees and existing router is not TWAP/stale-MARKET
        if route and route.strategy not in ("TWAP",):
            if regime_route.type == "MARKET" and route.strategy == "LIMIT_MAKER":
                route = type("Route", (), {
                    "strategy": "MARKET",
                    "price": None,
                    "slices": 1,
                    "reason": f"regime_override: {regime_route.detail}",
                })()
                _route_strategy["strategy"] = "MARKET"
                _route_strategy["reason"] = route.reason
                _route_strategy["price"] = None
                logger.info(f"[SOR-REGIME] {bot.bot_name}: LIMIT → MARKET ({regime_route.detail})")
            elif regime_route.type == "LIMIT" and route.strategy == "MARKET":
                route = type("Route", (), {
                    "strategy": "LIMIT_MAKER",
                    "price": Decimal(str(regime_route.price)) if regime_route.price else None,
                    "slices": 1,
                    "reason": f"regime_override: {regime_route.detail}",
                })()
                _route_strategy["strategy"] = "LIMIT_MAKER"
                _route_strategy["reason"] = route.reason
                _route_strategy["price"] = float(route.price) if route.price else None
                logger.info(f"[SOR-REGIME] {bot.bot_name}: MARKET → LIMIT ({regime_route.detail})")
    except Exception as regime_sor_exc:
        logger.warning("[SOR-REGIME] {}: override failed, keeping original route: {}", bot.bot_name, regime_sor_exc)

    # TWAP advisory — log warning but execute as single market for now
    if route and route.strategy == "TWAP":
        logger.warning(
            f"[SOR] {bot.bot_name}: TWAP advised ({route.slices} slices) "
            f"but executing single market order — full TWAP not yet implemented"
        )

    # Open position with retry on amount-precision errors
    order = None
    current_notional = notional
    for attempt in range(1, 4):
        try:
            limit_price = route.price if route and route.strategy == "LIMIT_MAKER" else None
            if sig.direction == "long":
                order = _arun(exchange.open_long(bot.symbol, quantity, limit_price))
            else:
                order = _arun(exchange.open_short(bot.symbol, quantity, limit_price))
            break
        except Exception as open_exc:
            err_msg = str(open_exc).lower()
            if "amount" in err_msg or "precision" in err_msg or "minimum" in err_msg:
                current_notional = current_notional * 1.5
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name} open failed (amount/precision), "
                    f"retrying with notional {current_notional:.2f} (attempt {attempt}/3)"
                )
                quantity = _arun(exchange.calculate_quantity(
                    symbol=bot.symbol,
                    equity=Decimal(str(equity)),
                    sizing_type="fixed",
                    sizing_value=Decimal(str(current_notional)),
                    leverage=effective_leverage,
                ))
                if attempt == 3:
                    raise RuntimeError(
                        f"Failed to open position after 3 attempts: {open_exc}"
                    ) from open_exc
            else:
                raise

    fill_price = order.fill_price or Decimal(str(sig.entry_price))

    # ═══════════════════════════════════════════════════════════════════════
    # ATOMIC POSITION PERSISTENCE
    # Create and commit position IMMEDIATELY after exchange order succeeds.
    # This prevents orphan positions if anything fails later (SL, TP, snapshot,
    # notifications, longevity evaluation, etc.).
    # ═══════════════════════════════════════════════════════════════════════
    _emergency_sl = Decimal(str(sig.stop_loss)) if sig.stop_loss else fill_price
    _emergency_tp1 = Decimal(str(sig.take_profit_1)) if sig.take_profit_1 else None
    _emergency_tp2 = Decimal(str(sig.take_profit_2)) if sig.take_profit_2 else None
    _emergency_exchange = bot.exchange_account.exchange if bot.exchange_account else "paper"

    # Pre-calculate TP splits for atomic persistence consistency
    _effective_status_val = _effective_status(sig)
    _tp1_pct_atomic = 40
    _tp2_pct_atomic = 30
    _tp3_pct_atomic = 30
    if sig.quality_tier == "STRONG" and _effective_status_val == "CLEAR":
        _tp1_pct_atomic, _tp2_pct_atomic, _tp3_pct_atomic = 35, 35, 30
    elif sig.quality_tier == "WEAK" or _effective_status_val in ("CAUTION", "BLOCK"):
        _tp1_pct_atomic, _tp2_pct_atomic, _tp3_pct_atomic = 50, 25, 25

    _atomic_tp_records = [
        {"level": 1, "price": float(_emergency_tp1), "close_percent": _tp1_pct_atomic, "hit": False, "order_id": None},
    ] if _emergency_tp1 else []
    if _emergency_tp2:
        _atomic_tp_records.append(
            {"level": 2, "price": float(_emergency_tp2), "close_percent": _tp2_pct_atomic, "hit": False, "order_id": None}
        )

    position = Position(
        bot_id=bot.id,
        exchange=_emergency_exchange,
        symbol=bot.symbol,
        side=sig.direction,
        entry_price=fill_price,
        quantity=quantity,
        leverage=effective_leverage,
        current_sl_price=_emergency_sl,
        current_tp_prices=_atomic_tp_records,
        exchange_order_id=order.order_id,
        exchange_sl_order_id=None,
        source="ai_bot",
        status="open",
        extra_config={
            "source": "ai_signal",
            "ai_signal_id": str(sig.id),
            "score": sig.score,
            "confidence": sig.confidence,
            "quality_tier": sig.quality_tier,
            "anti_fake_status": _effective_status_val,
            "market_regime": sig.features.get("market_regime", "RANGING") if sig.features else "RANGING",
            "timeframe": sig.timeframe,
            "initial_sl_price": float(sig.stop_loss) if sig.stop_loss else float(fill_price),
            "initial_risk_pct": 0,
            "signal_atr": float(sig.features.get("atr_value", 0)) if sig.features else 0.0,
            "original_quantity": float(quantity),
            "tp_strategy": "3stage_40_30_30",
            "breakeven_after_tp1": True,
            "atomic_persisted_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(position)
    db.add(BotLog(
        bot_id=bot.id,
        event_type="ai_signal_activated",
        message=f"AI signal activated: {sig.direction.upper()} {bot.symbol} @ {float(fill_price)}",
        metadata={"ai_signal_id": str(sig.id), "direction": sig.direction, "score": sig.score},
    ))
    db.commit()
    logger.info(f"[ACTIVATOR] Position {position.id} persisted atomically after exchange order")
    # ═══════════════════════════════════════════════════════════════════════

    # Verify real leverage on exchange after open — critical risk check
    try:
        live_positions = _arun(exchange.get_open_positions())
        live_pos = next(
            (p for p in live_positions if p.symbol == bot.symbol and p.side == sig.direction),
            None,
        )
        if live_pos and live_pos.leverage and live_pos.leverage != effective_leverage:
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name} leverage MISMATCH: expected={effective_leverage}x, "
                f"exchange={live_pos.leverage}x. Using exchange value for DB record."
            )
            effective_leverage = live_pos.leverage
    except Exception as lev_verify_exc:
        logger.debug(
            f"[ACTIVATOR] Could not verify real leverage after open: {lev_verify_exc}"
        )

    # Log SOR result
    if route:
        db.add(BotLog(
            bot_id=bot.id,
            event_type="sor_execution",
            message=f"SOR {route.strategy} executed",
            metadata={
                "strategy": route.strategy,
                "reason": route.reason,
                "limit_price": str(route.price) if route.price else None,
                "fill_price": float(fill_price),
                "signal_age_sec": signal_age,
            },
        ))

    # Distancia de riesgo real desde el fill hasta el SL (en % del precio)
    fill_f = float(fill_price)
    sl_f   = float(sig.stop_loss) if sig.stop_loss is not None else fill_f
    initial_risk_distance = abs(fill_f - sl_f)
    initial_risk_pct = (initial_risk_distance / fill_f * 100) if fill_f > 0 else 0.0
    signal_atr = float(sig.features.get("atr_value", 0)) if sig.features else 0.0

    # FIX FASE 1B: Actualizar initial_risk_pct real en la posición ya persistida
    if position and initial_risk_pct > 0:
        position.extra_config["initial_risk_pct"] = initial_risk_pct
        db.add(position)
        db.commit()
        logger.info(
            f"[ACTIVATOR] {bot.bot_name}: initial_risk_pct updated to {initial_risk_pct:.4f}% "
            f"for position {position.id}"
        )

    # Pre-compute signal metadata for position record
    effective_status = _effective_status(sig)
    regime_name = sig.features.get("market_regime", "RANGING") if sig.features else "RANGING"

    # ── EVALUATE trade longevity from REAL fill price ──
    # FASE 1F FIX: Convertido de bloqueo letal a scoring/warning.
    # Antes: si longevity era insuficiente, cerraba la posición inmediatamente
    # (matando trades con fees pagados y generando pérdidas forzadas).
    # Ahora: reduce sizing y loguea warning, pero mantiene la posición.
    feats = sig.features or {}
    forward_levels_merged = _merge_structural_levels(
        feats, "forward_levels", "htf_forward_levels", sig.timeframe
    )
    longevity_ok, longevity_reasons, struct_tp1, struct_tp1_kind, struct_tp2, struct_tp2_kind = (
        _evaluate_trade_longevity(
            fill_f, sl_f, sig.direction, forward_levels_merged, signal_atr, sig.timeframe
        )
    )

    if not longevity_ok:
        reasons_str = "; ".join(longevity_reasons)
        logger.warning(
            f"[ACTIVATOR] {bot.bot_name} STRUCTURAL LONGEVITY WARNING (not blocking): "
            f"{reasons_str} — reducing notional 30% instead of closing"
        )
        # Reduce sizing en lugar de cerrar — el trade sigue vivo
        notional = notional * 0.70
        db.add(BotLog(
            bot_id=bot.id,
            event_type="longevity_warning",
            message=f"Structural longevity weak: {reasons_str}",
            metadata={"ai_signal_id": str(sig.id), "reasons": longevity_reasons, "notional_adjusted": notional},
        ))
        db.commit()
    else:
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} structural longevity OK: "
            f"TP1={struct_tp1:.4f}({struct_tp1_kind}) TP2={struct_tp2:.4f}({struct_tp2_kind})"
        )

    # Use resolved structural TPs only when longevity is OK; otherwise fallback to signal TPs
    if longevity_ok and struct_tp1 is not None:
        tp1_price = struct_tp1
        tp2_price = struct_tp2
        tp1_source_final = f"structural_{struct_tp1_kind}"
        tp2_source_final = f"structural_{struct_tp2_kind}" if struct_tp2 else "structural_single"
        use_structural_tps = True
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} LONGEVITY CONFIRMED from fill {fill_f}: "
            f"TP1={tp1_price:.4f} ({tp1_source_final}) "
            f"TP2={tp2_price or 'NONE'} ({tp2_source_final})"
        )
    else:
        # Fallback to original signal TPs to avoid None → Decimal crash
        tp1_price = float(sig.take_profit_1) if sig.take_profit_1 else None
        tp2_price = float(sig.take_profit_2) if sig.take_profit_2 else None
        tp1_source_final = "signal_fallback"
        tp2_source_final = "signal_fallback" if tp2_price else "none"
        use_structural_tps = False
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} LONGEVITY WEAK — using signal TPs: "
            f"TP1={tp1_price} TP2={tp2_price or 'NONE'}"
        )

    # ── SAPP: Signal-Aware Position Plan ─────────────────────────────────
    sapp_plan = None
    sapp_tp_records = []
    try:
        from app.services.signal_risk_plan import SignalRiskPlanner, calculate_tp_prices
        planner = SignalRiskPlanner()
        # Equity aproximado para sizing (no usado aún, pero el plan lo requiere)
        account_equity = 10000.0  # placeholder; se mejorará con balance real
        sapp_plan = planner.generate_plan(
            sig,
            account_equity=account_equity,
            market_context={
                "regime": regime_name,
                "atr_14": signal_atr,
            },
            forward_levels=forward_levels_merged,
        )
        sapp_tp_records = calculate_tp_prices(
            Decimal(str(fill_f)), sig.direction, Decimal(str(sl_f)), sapp_plan.tp_levels
        )
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} SAPP plan generated: "
            f"{len(sapp_plan.tp_levels)} TP levels, time_limit={sapp_plan.time_limit_bars}, "
            f"eb_r={sapp_plan.emergency_brake_at_r}"
        )
    except Exception as sapp_exc:
        logger.warning(f"[ACTIVATOR] SAPP plan generation failed, using legacy: {sapp_exc}")

    # ── 3.3 Horizonte Temporal Dinámico (ATR + volatilidad) ──
    # CRITICAL FIX: If we have valid structural TPs, we ONLY adjust the SL with
    # dynamic horizon. We NEVER recalculate structural TPs mechanically — that
    # destroys the ICT+SMC levels (e.g. DOGE: FVG bull @ 0.09774 became 0.095455).
    atr_percentile = float(feats.get("regime_atr_p", 50)) if feats else 50.0
    sl_price = float(sig.stop_loss)

    # FIX: Slippage favorable — maintain original risk % from fill price
    # to prevent SL distance inflation when fill is much better than signal entry
    if sig.entry_price and sig.stop_loss and fill_f > 0:
        entry_f = float(sig.entry_price)
        base_sl_raw = float(sig.stop_loss)
        if sig.direction == "long":
            original_risk_pct = abs(entry_f - base_sl_raw) / entry_f
            adjusted_base_sl = fill_f * (1 - original_risk_pct)
        else:
            original_risk_pct = abs(base_sl_raw - entry_f) / entry_f
            adjusted_base_sl = fill_f * (1 + original_risk_pct)

        # Clamp: don't let SL get wider than 1.3x or narrower than 0.8x
        original_dist = abs(base_sl_raw - entry_f)
        new_dist = abs(adjusted_base_sl - fill_f)
        if new_dist > original_dist * 1.3:
            if sig.direction == "long":
                adjusted_base_sl = fill_f - original_dist * 1.3
            else:
                adjusted_base_sl = fill_f + original_dist * 1.3
        elif new_dist < original_dist * 0.8:
            if sig.direction == "long":
                adjusted_base_sl = fill_f - original_dist * 0.8
            else:
                adjusted_base_sl = fill_f + original_dist * 0.8

        if abs(adjusted_base_sl - base_sl_raw) > 0.0001:
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} SL slippage-adjusted: "
                f"{base_sl_raw:.4f}→{adjusted_base_sl:.4f} "
                f"(risk_pct={original_risk_pct:.4%} fill={fill_f:.4f})"
            )
        sl_price = adjusted_base_sl

    try:
        from app.services.dynamic_horizon import compute_dynamic_tp_sl
        if use_structural_tps:
            # Structural TPs: adjust ONLY SL, keep TPs intact
            sl_price, _, _, horizon_meta = compute_dynamic_tp_sl(
                entry_price=fill_f,
                direction=sig.direction,
                atr_value=signal_atr,
                atr_percentile=atr_percentile,
                base_sl=sl_price,
                base_tp1=tp1_price,
                base_tp2=tp2_price,
                regime=regime_name,
            )
            _horizon_meta = horizon_meta
            if horizon_meta.get("applied"):
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name} Dynamic horizon applied to SL only "
                    f"(structural TPs preserved): "
                    f"mult={horizon_meta['final_multiplier']} "
                    f"SL {horizon_meta['original_sl']:.4f}→{horizon_meta['adjusted_sl']:.4f} "
                    f"TP1 {tp1_price:.4f} (UNCHANGED) TP2 {tp2_price or 'NONE'} (UNCHANGED)"
                )
        else:
            # Mechanical TPs: standard dynamic horizon (SL + TPs)
            sl_price, tp1_price, tp2_price, horizon_meta = compute_dynamic_tp_sl(
                entry_price=fill_f,
                direction=sig.direction,
                atr_value=signal_atr,
                atr_percentile=atr_percentile,
                base_sl=sl_price,
                base_tp1=tp1_price,
                base_tp2=tp2_price,
                regime=regime_name,
            )
            _horizon_meta = horizon_meta
            if horizon_meta.get("applied"):
                logger.info(
                    f"[ACTIVATOR] {bot.bot_name} Dynamic horizon applied: "
                    f"mult={horizon_meta['final_multiplier']} "
                    f"SL {horizon_meta['original_sl']:.4f}→{horizon_meta['adjusted_sl']:.4f} "
                    f"TP1 {horizon_meta['original_tp1']:.4f}→{horizon_meta['adjusted_tp1']:.4f}"
                )
    except Exception as dh_exc:
        logger.warning(f"[ACTIVATOR] Dynamic horizon failed, using signal defaults: {dh_exc}")

    # ── EMA 50 SL Guard ───────────────────────────────────────────────────────
    ema50 = feats.get("ema50") if feats else None
    if ema50 and sl_price and sl_price > 0:
        ema_f = float(ema50)
        old_sl = sl_price
        adjusted = False
        if sig.direction == "long":
            # For long: SL should be BELOW EMA50 (or very close)
            if sl_price > ema_f * 1.005:
                sl_price = ema_f * 0.995
                adjusted = True
        else:
            # For short: SL should be ABOVE EMA50 (or very close)
            if sl_price < ema_f * 0.995:
                sl_price = ema_f * 1.005
                adjusted = True

        if adjusted:
            logger.info(
                f"[ACTIVATOR] {bot.bot_name} EMA50 guard adjusted SL: "
                f"{old_sl:.4f}→{sl_price:.4f} (EMA50={ema_f:.4f})"
            )

    # Place stop loss — si falla, cerrar posición para evitar riesgo desnudo
    sl_order_id: str | None = None
    try:
        sl_order_id = _arun(
            exchange.place_stop_loss(
                bot.symbol, sig.direction, quantity, Decimal(str(sl_price))
            )
        )
    except Exception as sl_exc:
        logger.error(
            f"[ACTIVATOR] SL placement FAILED — closing position to avoid naked risk: {sl_exc}"
        )
        try:
            _arun(exchange.close_position(bot.symbol, sig.direction, quantity))
            logger.info(f"[ACTIVATOR] Position closed after SL failure — no naked risk")
        except Exception as close_exc:
            logger.critical(
                f"[ACTIVATOR] CRITICAL: Could not close position after SL failure: {close_exc}"
            )
        # Mark position as closed in DB to avoid orphan state
        position.status = "closed"
        position.closed_at = datetime.now(timezone.utc)
        position.quantity = Decimal("0")
        db.commit()
        raise RuntimeError(
            f"SL placement failed and position was closed to avoid naked risk: {sl_exc}"
        ) from sl_exc

    # ── 3-Stage TP Strategy with IRL/ERL (SMC) ───────────────────────────────
    # TP1 (40%): first IRL (Internal Range Liquidity) — intraday target.
    # TP2 (30%): second IRL or +2% momentum — continuation target.
    # TP3 (30%): first ERL (External Range Liquidity) — swing target.
    # After TP1 hit → SL moves to breakeven.
    # After TP2 hit → trailing stop activates to let TP3 run.
    effective_status = _effective_status(sig)
    feats = sig.features or {}

    # Fixed 40/30/30 split (can be overridden by signal features if needed)
    tp1_pct = Decimal("0.40")
    tp2_pct = Decimal("0.30")
    tp3_pct = Decimal("0.30")
    tp1_source = "3stage_irl_erl"

    # Quality overlay: adjust TP1 slightly for signal strength
    if sig.quality_tier == "STRONG" and effective_status == "CLEAR":
        tp1_pct = Decimal("0.35")
        tp2_pct = Decimal("0.35")
        tp3_pct = Decimal("0.30")
    elif sig.quality_tier == "WEAK" or effective_status in ("CAUTION", "BLOCK"):
        tp1_pct = Decimal("0.50")
        tp2_pct = Decimal("0.25")
        tp3_pct = Decimal("0.25")

    logger.info(
        f"[ACTIVATOR] {bot.bot_name} 3-stage TP split: "
        f"TP1={float(tp1_pct)*100:.0f}% TP2={float(tp2_pct)*100:.0f}% TP3={float(tp3_pct)*100:.0f}%"
    )

    qty_tp1 = (quantity * tp1_pct).quantize(Decimal("0.000001"))
    qty_tp2 = (quantity * tp2_pct).quantize(Decimal("0.000001"))
    qty_tp3 = quantity - qty_tp1 - qty_tp2
    # Guard against negative qty_tp3 due to rounding
    if qty_tp3 < Decimal("0"):
        logger.warning(
            f"[ACTIVATOR] {bot.bot_name} qty_tp3 negative ({qty_tp3}) due to rounding — "
            f"redistributing to TP1/TP2"
        )
        qty_tp3 = Decimal("0")
        qty_tp1 = quantity * Decimal("0.70")
        qty_tp2 = quantity * Decimal("0.30")
        tp1_pct = Decimal("0.70")
        tp2_pct = Decimal("0.30")
        tp3_pct = Decimal("0")

    # ── IRL / ERL extraction from forward levels ────────────────────────────
    fill_f = float(fill_price)
    irl_levels = [l for l in forward_levels_merged if l.get("liquidity_type") == "IRL"]
    erl_levels = [l for l in forward_levels_merged if l.get("liquidity_type") == "ERL"]
    irl_levels.sort(key=lambda x: x.get("distance_pct", 999))
    erl_levels.sort(key=lambda x: x.get("distance_pct", 999))

    # Compute fallback % moves
    if sig.direction == "long":
        tp2_price_pct = fill_f * 1.02
        tp3_price_pct = fill_f * 1.04
    else:
        tp2_price_pct = fill_f * 0.98
        tp3_price_pct = fill_f * 0.96

    # TP1 (40%): first IRL, or struct_tp1 if it's the best available, or signal TP1
    if irl_levels:
        tp1_price = irl_levels[0]["price"]
        tp1_source_final = f"IRL_{irl_levels[0].get('kind', 'unknown')}"
    elif tp1_price is None:
        tp1_price = float(sig.take_profit_1) if sig.take_profit_1 else None
        tp1_source_final = "signal_fallback"

    # TP2 (30%): second IRL, or +2% fallback
    if len(irl_levels) >= 2:
        tp2_price = irl_levels[1]["price"]
        tp2_source_final = f"IRL_{irl_levels[1].get('kind', 'unknown')}"
    else:
        # Fallback: use structural TP2 if it exists and is conservative, else % move
        if tp2_price is not None:
            if sig.direction == "long":
                tp2_price = min(tp2_price, tp2_price_pct)
            else:
                tp2_price = max(tp2_price, tp2_price_pct)
        else:
            tp2_price = tp2_price_pct
        tp2_source_final = "fallback_pct"

    # TP3 (30%): first ERL, or +4% fallback
    if erl_levels:
        tp3_price = erl_levels[0]["price"]
        tp3_source_final = f"ERL_{erl_levels[0].get('kind', 'unknown')}"
    else:
        tp3_price = tp3_price_pct
        tp3_source_final = "fallback_pct"

    # Validate TP prices against current market price to avoid "TP below current price" errors.
    # Protect structural IRL/ERL levels: if price already beyond TP by >0.3%, signal is stale.
    original_tp1 = tp1_price
    original_tp2 = tp2_price
    original_tp3 = tp3_price
    try:
        current_price = float(_arun(exchange.get_price(bot.symbol)))
        _stale_threshold = 0.003
        if sig.direction == "long":
            if tp1_price <= current_price * (1 + _stale_threshold):
                if tp1_source_final != "fallback_pct":
                    raise RuntimeError(
                        f"TP1 IRL {tp1_price:.4f} already behind current price {current_price:.4f} — "
                        f"signal stale, rejecting to protect SMC edge"
                    )
                tp1_price = current_price * 1.005
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name} TP1 adjusted {original_tp1:.4f} → {tp1_price:.4f} "
                    f"(below current price {current_price:.4f})"
                )
            if tp2_price is not None and tp2_price <= tp1_price:
                tp2_price = tp1_price * 1.01
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name} TP2 adjusted {original_tp2:.4f} → {tp2_price:.4f} "
                    f"(below TP1 {tp1_price:.4f})"
                )
            if tp3_price is not None and tp3_price <= tp2_price:
                tp3_price = tp2_price * 1.01
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name} TP3 adjusted {original_tp3:.4f} → {tp3_price:.4f} "
                    f"(below TP2 {tp2_price:.4f})"
                )
        else:  # short
            if tp1_price >= current_price * (1 - _stale_threshold):
                if tp1_source_final != "fallback_pct":
                    raise RuntimeError(
                        f"TP1 IRL {tp1_price:.4f} already behind current price {current_price:.4f} — "
                        f"signal stale, rejecting to protect SMC edge"
                    )
                tp1_price = current_price * 0.995
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name} TP1 adjusted {original_tp1:.4f} → {tp1_price:.4f} "
                    f"(above current price {current_price:.4f})"
                )
            if tp2_price is not None and tp2_price >= tp1_price:
                tp2_price = tp1_price * 0.99
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name} TP2 adjusted {original_tp2:.4f} → {tp2_price:.4f} "
                    f"(above TP1 {tp1_price:.4f})"
                )
            if tp3_price is not None and tp3_price >= tp2_price:
                tp3_price = tp2_price * 0.99
                logger.warning(
                    f"[ACTIVATOR] {bot.bot_name} TP3 adjusted {original_tp3:.4f} → {tp3_price:.4f} "
                    f"(above TP2 {tp2_price:.4f})"
                )
    except RuntimeError as stale_exc:
        # Stale signal with structural TP — close position in exchange AND DB to avoid orphan
        logger.error(f"[ACTIVATOR] Stale signal detected for {bot.symbol} — closing atomic position")
        closed_on_exchange = False
        try:
            # 1. Close on exchange first
            _arun(exchange.close_position(bot.symbol, side=sig.direction, quantity=quantity))
            closed_on_exchange = True
            logger.info(f"[ACTIVATOR] Stale position closed on exchange: {bot.symbol} {sig.direction} qty={quantity}")
        except Exception as close_exc:
            logger.critical(
                f"[ACTIVATOR] CRITICAL: Failed to close stale position on exchange {bot.symbol}: {close_exc}. "
                f"Position may become orphan."
            )
        try:
            # 2. Mark closed in DB
            position.status = "closed"
            position.closed_at = datetime.now(timezone.utc)
            position.quantity = Decimal("0")
            db.add(BotLog(
                bot_id=bot.id,
                event_type="ai_activation_error",
                message=f"Stale signal after atomic open — position closed: {stale_exc}",
                metadata={"ai_signal_id": str(sig.id), "error": str(stale_exc)[:500], "exchange_closed": closed_on_exchange},
            ))
            db.commit()
        except Exception as cleanup_exc:
            logger.critical(
                f"[ACTIVATOR] CRITICAL: Failed to close orphan position after stale signal: {cleanup_exc}"
            )
        raise
    except Exception as price_exc:
        logger.warning(f"[ACTIVATOR] Could not fetch current price for TP validation: {price_exc}")

    # Ensure qty_tp2 and qty_tp3 meet exchange minimum
    try:
        if not exchange._client.markets:
            _arun(exchange._client.load_markets())
        market = exchange._client.market(bot.symbol)
        min_amount = float((market.get("limits") or {}).get("amount", {}).get("min") or 0)
        if min_amount and float(qty_tp2) < min_amount:
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name} qty_tp2={qty_tp2} < min_amount={min_amount}, "
                f"moving qty_tp2 to TP1"
            )
            qty_tp1 += qty_tp2
            qty_tp2 = Decimal("0")
        if min_amount and float(qty_tp3) < min_amount:
            logger.warning(
                f"[ACTIVATOR] {bot.bot_name} qty_tp3={qty_tp3} < min_amount={min_amount}, "
                f"moving qty_tp3 to TP2"
            )
            if qty_tp2 > Decimal("0"):
                qty_tp2 += qty_tp3
            else:
                qty_tp1 += qty_tp3
            qty_tp3 = Decimal("0")
        # Re-quantize after adjustments
        qty_tp1 = qty_tp1.quantize(Decimal("0.000001"))
        qty_tp2 = qty_tp2.quantize(Decimal("0.000001"))
        qty_tp3 = qty_tp3.quantize(Decimal("0.000001"))
        # Recalculate close_percent to match actual quantities
        if quantity > Decimal("0"):
            tp1_pct = qty_tp1 / quantity
            tp2_pct = qty_tp2 / quantity
            tp3_pct = qty_tp3 / quantity
        logger.info(
            f"[ACTIVATOR] {bot.bot_name} post-min_amount splits: "
            f"tp1={qty_tp1}({tp1_pct:.0%}) tp2={qty_tp2}({tp2_pct:.0%}) tp3={qty_tp3}({tp3_pct:.0%})"
        )
    except Exception as min_exc:
        logger.warning(f"[ACTIVATOR] Could not validate min_amount for TP split: {min_exc}")

    tp1_order_id: str | None = None
    tp2_order_id: str | None = None
    tp_placed = False
    try:
        tp1_order_id = _arun(
            exchange.place_take_profit(
                bot.symbol, sig.direction, qty_tp1, Decimal(str(tp1_price))
            )
        )
        if qty_tp2 > Decimal("0"):
            tp2_order_id = _arun(
                exchange.place_take_profit(
                    bot.symbol, sig.direction, qty_tp2, Decimal(str(tp2_price))
                )
            )
        tp_placed = True
        logger.info(
            f"[ACTIVATOR] TP orders placed — TP1={tp1_order_id} TP2={tp2_order_id} "
            f"(TP3={float(tp3_price):.4f} logical, qty={qty_tp3})"
        )
    except Exception as tp_exc:
        logger.error(
            f"[ACTIVATOR] TP order placement FAILED — closing position to avoid naked risk: {tp_exc}"
        )
        try:
            _arun(exchange.close_position(bot.symbol, sig.direction, quantity))
            logger.info(f"[ACTIVATOR] Position closed after TP failure — no naked risk")
        except Exception as close_exc:
            logger.critical(
                f"[ACTIVATOR] CRITICAL: Could not close position after TP failure: {close_exc}"
            )
        # Mark position as closed in DB to avoid orphan state
        position.status = "closed"
        position.closed_at = datetime.now(timezone.utc)
        position.quantity = Decimal("0")
        db.commit()
        raise RuntimeError(
            f"TP placement failed and position was closed to avoid naked risk: {tp_exc}"
        ) from tp_exc

    # Determine exchange name
    exchange_name = (
        bot.exchange_account.exchange if bot.exchange_account else "paper"
    )

    # ── Score + Timeframe based risk config adjustment ──
    # Breakeven activates by R-multiple (not only after TP1).
    # Trailing activates at score+TF specific R level.
    tf = bot.timeframe or "15m"
    score = float(sig.score) if sig.score else 0.0

    # Use score+TF based configs directly for AI bots.
    # Bot-level trailing/breakeven configs are ignored for AI bots because
    # they were auto-generated by _ensure_ia_risk_configs with old defaults.
    # Manual/legacy bots still use their configured values.
    score_tf_trailing = _get_trailing_by_score_tf(score, tf)
    score_tf_breakeven = _get_breakeven_by_score_tf(score, tf)

    if bot.ai_signal_mode:
        default_trailing = score_tf_trailing
        default_breakeven = score_tf_breakeven
    else:
        default_trailing = bot.trailing_config or score_tf_trailing
        default_breakeven = bot.breakeven_config or score_tf_breakeven

    forward_levels = (sig.features or {}).get("forward_levels", [])
    risk_pct_value = float(initial_risk_pct) if initial_risk_pct > 0 else 0.0
    adjusted_trailing, adjusted_breakeven = _adjust_risk_configs_by_structure(
        default_trailing,
        default_breakeven,
        forward_levels,
        risk_pct_value,
        score_tf_trailing["activation_r"],
        score_tf_breakeven["activation_r"],
    )
    logger.info(
        f"[ACTIVATOR] {bot.bot_name} risk configs (score={score:.1f} {tf}): "
        f"trailing@{adjusted_trailing['activation_r']}R, "
        f"BE@{adjusted_breakeven['activation_r']}R lock={adjusted_breakeven.get('lock_profit', 0.2)}%"
    )

    # ── Build gates snapshot for replay ──
    _gates = {
        "deployment_gate": gate_status if 'gate_status' in locals() else {},
        "macro": macro if 'macro' in locals() else {},
        "session_funding": session_funding if 'session_funding' in locals() else {},
        "oi_cvd": oi_cvd if 'oi_cvd' in locals() else {},
        "rolling_beta": beta_gate if 'beta_gate' in locals() else {},
        "divergence": {"blocked": False} if bot.is_paper_trading else {},
    }

    # Update atomically-persisted position with real SL/TP/order IDs
    position.current_sl_price      = Decimal(str(sl_price))
    _tp_records = [
        {"level": 1, "price": float(tp1_price), "close_percent": int(float(tp1_pct) * 100), "hit": False, "order_id": tp1_order_id},
    ]
    if tp2_price is not None and qty_tp2 > Decimal("0"):
        _tp_records.append(
            {"level": 2, "price": float(tp2_price), "close_percent": int(float(tp2_pct) * 100), "hit": False, "order_id": tp2_order_id}
        )
    if qty_tp3 > Decimal("0"):
        _tp_records.append(
            {"level": 3, "price": float(tp3_price), "close_percent": int(float(tp3_pct) * 100), "hit": False, "order_id": None}  # Logical TP
        )
    position.current_tp_prices     = _tp_records
    position.exchange_sl_order_id  = sl_order_id
    position.extra_config          = {
            "source":               "ai_signal",
            "ai_signal_id":         str(sig.id),
            "score":                sig.score,
            "confidence":           sig.confidence,
            "quality_tier":         sig.quality_tier,
            "anti_fake_status":     effective_status,
            "market_regime":        regime_name,
            "timeframe":            sig.timeframe,
            # Datos de riesgo para gestión autónoma basada en R-múltiplos
            "initial_sl_price":     sl_f,
            "initial_risk_pct":     round(initial_risk_pct, 6),
            "initial_risk_distance": round(initial_risk_distance, 8),
            "signal_atr":           round(signal_atr, 8),
            "original_quantity":    float(quantity),
            # 3.4 OI/CVD
            "oi_cvd":               oi_cvd if oi_cvd else {},
            # 3.5 Session / Funding
            "session_funding":      session_funding if session_funding else {},
            # 2.7 Rolling Beta
            "rolling_beta":         beta_gate if beta_gate else {},
            # Forward structural levels for structural TP/SL management
            # Merge LTF + HTF levels, sorting HTF first due to higher structural strength
            "forward_levels":       _merge_structural_levels(
                sig.features or {}, "forward_levels", "htf_forward_levels", sig.timeframe
            ),
            "support_levels":       _merge_structural_levels(
                sig.features or {}, "support_levels", "htf_support_levels", sig.timeframe
            ),
            "ltf_forward_levels":   (sig.features or {}).get("forward_levels", []),
            "ltf_support_levels":   (sig.features or {}).get("support_levels", []),
            "htf_forward_levels":   (sig.features or {}).get("htf_forward_levels", []),
            "htf_support_levels":   (sig.features or {}).get("htf_support_levels", []),
            "htf_timeframe":        (sig.features or {}).get("htf_timeframe"),
            "tp1_source":           tp1_source_final,
            "tp2_source":           tp2_source_final,
            # For debugging: original signal levels vs resolved from fill
            "original_signal_levels": {
                "entry_price_signal": float(sig.entry_price),
                "take_profit_1_signal": float(sig.take_profit_1),
                "take_profit_2_signal": float(sig.take_profit_2),
                "stop_loss_signal": float(sig.stop_loss),
                "fill_price": fill_f,
                "structural_tp1_resolved": struct_tp1,
                "structural_tp2_resolved": struct_tp2,
                "use_structural_tps": use_structural_tps,
            },
            # Risk strategy flags
            "breakeven_after_tp1": False,  # BE activates by R-multiple, not only after TP1
            "tp_strategy": "3stage_40_30_30",
            "tp2_move_pct": 0.02,
            "tp3_move_pct": 0.04,
            # Structural risk configs (overrides bot defaults per signal)
            "adjusted_trailing_config": adjusted_trailing,
            "adjusted_breakeven_config": adjusted_breakeven,
            # SAPP: Signal-Aware Position Plan
            "dynamic_plan":         {
                "size_usd": sapp_plan.size_usd if sapp_plan else None,
                "sl_distance": sapp_plan.sl_distance if sapp_plan else None,
                "tp_levels": [
                    {"level": tp.level, "close_pct": tp.close_pct, "r_multiple": tp.r_multiple, "action_after_hit": tp.action_after_hit}
                    for tp in (sapp_plan.tp_levels if sapp_plan else [])
                ],
                "time_limit_bars": sapp_plan.time_limit_bars if sapp_plan else 50,
                "emergency_brake_at_r": sapp_plan.emergency_brake_at_r if sapp_plan else -1.0,
                "execution_mode": sapp_plan.execution_mode if sapp_plan else "standard",
            } if sapp_plan else None,
            "sapp_tp_prices":       sapp_tp_records if sapp_tp_records else [],
        }
    db.commit()

    # BotLog was already created during atomic persistence; skip duplicate

    # ── 3.6 Replay Snapshot ──
    try:
        from app.services.replay_snapshot import capture_replay_snapshot
        capture_replay_snapshot(
            db=db,
            position=position,
            sig=sig,
            bot=bot,
            fill_price=fill_price,
            quantity=quantity,
            effective_leverage=effective_leverage,
            slippage_estimate=_slip_estimate,
            sor_strategy=_route_strategy,
            dynamic_horizon_meta=_horizon_meta,
            kelly_meta=_kelly_meta,
            gates=_gates,
            exchange=exchange,
        )
    except Exception as snap_exc:
        logger.warning(f"[ACTIVATOR] Replay snapshot failed (non-critical): {snap_exc}")

    # Notify user of AI trade opened
    try:
        from app.models.user import User
        user = db.query(User).filter(User.id == bot.user_id).first()
        if user and user.telegram_chat_id and user.notify_on_open:
            from app.tasks.notification_tasks import trade_opened
            trade_opened.delay(
                bot_name=bot.bot_name,
                symbol=bot.symbol,
                side=sig.direction,
                entry=float(fill_price),
                sl=float(sl_price),
                chat_id=user.telegram_chat_id,
                source="ai_bot",
                tp1=float(tp1_price) if tp1_price else None,
                tp2=float(tp2_price) if tp2_price else None,
                tp3=float(tp3_price) if tp3_price else None,
                trailing_config=adjusted_trailing,
                breakeven_config=adjusted_breakeven,
                dynamic_sl_config=bot.dynamic_sl_config,
                leverage=int(effective_leverage),
                risk_pct=float(initial_risk_pct) if initial_risk_pct > 0 else None,
                quantity=float(quantity) if quantity else None,
                order_id=str(order.order_id) if order and order.order_id else None,
                signal_id=str(sig.id),
                explanation=sig.explanation,
                autopilot_status="Aprobado",
                timeframe=sig.timeframe,
            )
    except Exception as notif_exc:
        logger.warning(f"[ACTIVATOR] Failed to send trade opened notification: {notif_exc}")

    return {
        "bot_id":     str(bot.id),
        "bot_name":   bot.bot_name,
        "order_id":   order.order_id,
        "fill_price": float(fill_price),
    }


# ── Cooldown helpers ─────────────────────────────────────────────────────────

def _cooldown_minutes_for_tf(timeframe: str) -> int:
    """Minimum minutes between trades for a given timeframe.
    Prevents overtrading / re-entry on the same swing."""
    tf = (timeframe or "15m").lower()
    return {
        "1m": 10, "3m": 15, "5m": 20, "15m": 60,
        "30m": 60, "1h": 120, "2h": 180, "4h": 240,
        "6h": 360, "8h": 480, "12h": 720, "1d": 1440,
    }.get(tf, 60)


def _is_in_cooldown(bot: BotConfig, db) -> bool:
    """Check if bot had a closed trade too recently."""
    from sqlalchemy import desc
    last_pos = (
        db.query(Position)
        .filter(Position.bot_id == bot.id, Position.status == "closed")
        .order_by(desc(Position.closed_at))
        .first()
    )
    if not last_pos or not last_pos.closed_at:
        return False
    cooldown = timedelta(minutes=_cooldown_minutes_for_tf(bot.timeframe))
    return datetime.now(timezone.utc) - last_pos.closed_at < cooldown


# ── Structural Risk Config Overrides ─────────────────────────────────────────

def _adjust_risk_configs_by_structure(
    trailing_cfg: dict,
    breakeven_cfg: dict,
    forward_levels: list[dict],
    risk_pct: float,
    tf_default_trailing_r: float,
    tf_default_breakeven_r: float,
) -> tuple[dict, dict]:
    """
    Adjust trailing/breakeven activation based on structural forward levels.
    
    Trailing: activates at min(90% of distance to 1st forward level, TF default).
    This prevents trailing from kicking in BEFORE the price reaches the 
    first structural target (e.g. EQ high).
    
    Breakeven: if TP1 is very close (<1.0R), delay breakeven until AFTER TP1
    or until profit exceeds TP1 by 10%. Avoids moving SL to breakeven before
    the structural TP1 has a chance to fill.
    """
    adjusted_trailing = dict(trailing_cfg)
    adjusted_breakeven = dict(breakeven_cfg)

    if forward_levels and risk_pct > 0:
        first_dist_r = forward_levels[0]["distance_pct"] / risk_pct
        
        # Trailing: 90% of way to 1st structural level, capped by TF default
        structural_trailing_r = first_dist_r * 0.9
        adjusted_trailing["activation_r"] = round(
            min(structural_trailing_r, tf_default_trailing_r), 2
        )
        
        # Breakeven: conditional on TP1 distance
        if first_dist_r <= 1.0:
            # TP1 very close — delay breakeven until past TP1
            adjusted_breakeven["activation_r"] = round(first_dist_r * 1.1, 2)
        elif first_dist_r <= 1.5:
            # TP1 moderately close — use TF default but ensure it's not too early
            adjusted_breakeven["activation_r"] = round(
                max(tf_default_breakeven_r, first_dist_r * 0.8), 2
            )
        else:
            # TP1 far — normal TF default
            adjusted_breakeven["activation_r"] = round(tf_default_breakeven_r, 2)

    return adjusted_trailing, adjusted_breakeven


# ── IA Risk Management Defaults (timeframe-aware) ───────────────────────────

def _default_ia_trailing(timeframe: str = "15m") -> dict:
    """Trailing stop defaults: higher TF = earlier activation, tighter callback."""
    tf = (timeframe or "15m").lower()
    if tf in ("1d",):
        return {"enabled": True, "activation_r": 0.8, "callback_rate": 0.8}
    elif tf in ("4h",):
        return {"enabled": True, "activation_r": 1.0, "callback_rate": 0.9}
    elif tf in ("1h",):
        return {"enabled": True, "activation_r": 1.2, "callback_rate": 1.0}
    else:
        return {"enabled": True, "activation_r": 1.5, "callback_rate": 1.0}

def _default_ia_breakeven(timeframe: str = "15m") -> dict:
    """Breakeven defaults: higher TF = earlier lock, more profit locked."""
    tf = (timeframe or "15m").lower()
    if tf in ("1d", "4h"):
        return {"enabled": True, "activation_r": 0.5, "lock_profit": 0.3}
    elif tf in ("1h",):
        return {"enabled": True, "activation_r": 0.8, "lock_profit": 0.25}
    else:
        return {"enabled": True, "activation_r": 1.0, "lock_profit": 0.2}

def _default_ia_dynamic_sl(timeframe: str = "15m") -> dict:
    """Dynamic SL defaults: higher TF = more steps to let winners run."""
    tf = (timeframe or "15m").lower()
    if tf in ("1d",):
        return {"enabled": True, "step_r": 0.5, "max_steps": 10}  # up to 5R
    elif tf in ("4h",):
        return {"enabled": True, "step_r": 0.5, "max_steps": 8}   # up to 4R
    elif tf in ("1h",):
        return {"enabled": True, "step_r": 0.5, "max_steps": 7}   # up to 3.5R
    else:
        return {"enabled": True, "step_r": 0.5, "max_steps": 6}   # up to 3R


# ── Score + Timeframe based risk tables ─────────────────────────────────────

_LEVERAGE_TABLE = {
    "15m": {"<55": 0, "55-60": 5, "60-65": 7, "65-70": 10, "70-75": 12, "75-80": 15, "80-85": 17, ">85": 20},
    "1h":  {"<55": 0, "55-60": 5, "60-65": 5, "65-70":  7, "70-75":  9, "75-80": 10, "80-85": 12, ">85": 15},
    "4h":  {"<55": 0, "55-60": 3, "60-65": 5, "65-70":  5, "70-75":  5, "75-80":  7, "80-85":  7, ">85":  9},
}

_TRAILING_TABLE = {
    "15m": {"<70": 0.5, "70-80": 0.8, ">=80": 1.0},
    "1h":  {"<70": 0.8, "70-80": 1.0, ">=80": 1.2},
    "4h":  {"<70": 1.0, "70-80": 1.2, ">=80": 1.5},
}

_BREAKEVEN_TABLE = {
    "15m": {"<70": {"activation_r": 0.5, "lock_profit": 0.2}, ">=70": {"activation_r": 1.0, "lock_profit": 0.2}},
    "1h":  {"<70": {"activation_r": 0.8, "lock_profit": 0.25}, ">=70": {"activation_r": 1.0, "lock_profit": 0.25}},
    "4h":  {"<70": {"activation_r": 0.5, "lock_profit": 0.3},  ">=70": {"activation_r": 0.8, "lock_profit": 0.3}},
}


def _get_leverage_cap(score: float, timeframe: str) -> int:
    """Devuelve el máximo de apalancamiento según score + timeframe. 0 = no opera."""
    tf = (timeframe or "15m").lower()
    table = _LEVERAGE_TABLE.get(tf, _LEVERAGE_TABLE["15m"])
    if score < 55:
        bucket = "<55"
    elif score < 60:
        bucket = "55-60"
    elif score < 65:
        bucket = "60-65"
    elif score < 70:
        bucket = "65-70"
    elif score < 75:
        bucket = "70-75"
    elif score < 80:
        bucket = "75-80"
    elif score < 85:
        bucket = "80-85"
    else:
        bucket = ">85"
    return table.get(bucket, 5)


def _get_trailing_by_score_tf(score: float, timeframe: str) -> dict:
    """Devuelve trailing config según score + timeframe."""
    tf = (timeframe or "15m").lower()
    table = _TRAILING_TABLE.get(tf, _TRAILING_TABLE["15m"])
    bucket = "<70" if score < 70 else ("70-80" if score < 80 else ">=80")
    activation_r = table.get(bucket, table.get(">=80", 1.0))
    # callback rate: tighter for lower scores (protect capital)
    callback_rate = 0.6 if score < 70 else (0.8 if score < 80 else 1.0)
    return {"enabled": True, "activation_r": activation_r, "callback_rate": callback_rate}


def _get_breakeven_by_score_tf(score: float, timeframe: str) -> dict:
    """Devuelve breakeven config según score + timeframe."""
    tf = (timeframe or "15m").lower()
    table = _BREAKEVEN_TABLE.get(tf, _BREAKEVEN_TABLE["15m"])
    bucket = "<70" if score < 70 else ">=70"
    cfg = table.get(bucket, table.get(">=70", {"activation_r": 1.0, "lock_profit": 0.2}))
    return {"enabled": True, "activation_r": cfg["activation_r"], "lock_profit": cfg["lock_profit"]}


def _ensure_ia_risk_configs(bot: BotConfig) -> None:
    """
    Si un bot de IA no tiene configurados trailing/breakeven/dynamic_sl,
    inyecta defaults conservadores adaptados al timeframe. Solo afecta bots
    con ai_signal_mode=True. Persiste en DB solo si el campo está vacío
    (no sobrescribe config usuario).
    """
    needs_commit = False
    tf = bot.timeframe or "15m"

    if not bot.trailing_config:
        bot.trailing_config = _default_ia_trailing(tf)
        needs_commit = True
        logger.info(f"[ACTIVATOR] {bot.bot_name}: trailing_config por defecto ({tf})")

    if not bot.breakeven_config:
        bot.breakeven_config = _default_ia_breakeven(tf)
        needs_commit = True
        logger.info(f"[ACTIVATOR] {bot.bot_name}: breakeven_config por defecto ({tf})")

    if not bot.dynamic_sl_config:
        bot.dynamic_sl_config = _default_ia_dynamic_sl(tf)
        needs_commit = True
        logger.info(f"[ACTIVATOR] {bot.bot_name}: dynamic_sl_config por defecto ({tf})")

    # Nota: no hacemos db.commit() aquí — el caller hace commit después
