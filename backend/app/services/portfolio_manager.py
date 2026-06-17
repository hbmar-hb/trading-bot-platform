"""Portfolio Manager — aggregated risk, correlation, sizing guard.

Evaluates total portfolio exposure before a new AI signal is executed
and optionally reduces sizing or blocks the trade if risk is too concentrated.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.models.bot_config import BotConfig
from app.models.position import Position
from app.models.ai_signal import AISignal


# ── Forward-level correlation buckets ─────────────────────────────────────────

_FORWARD_LEVEL_BUCKETS = {
    "tp1_distance_r": [(0, 0.8), (0.8, 1.5), (1.5, 2.5), (2.5, 999)],
    "tp1_strength": [(0, 0.5), (0.5, 0.8), (0.8, 1.0)],
    "forward_density": [(0, 1), (1, 3), (3, 5), (5, 999)],
}


def _bucket_value(value: float, buckets: list[tuple[float, float]]) -> str:
    for lo, hi in buckets:
        if lo <= value < hi:
            return f"{lo}-{hi}"
    return "other"


# ── Exposure limits (configurable per bot) ────────────────────────────────────

_DEFAULT_LIMITS = {
    "max_total_exposure_pct": 75.0,      # % of equity in open positions (raised for testing)
    "max_symbol_exposure_pct": 45.0,     # % of equity in a single symbol
    "max_directional_exposure_pct": 60.0,  # % of equity on one side (long/short)
    "alt_correlation_threshold": 3,      # number of alt longs before warning
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_open_ai_positions(db: Session, bot_id: str) -> list[Position]:
    return (
        db.query(Position)
        .filter(
            Position.bot_id == bot_id,
            Position.status == "open",
            Position.source == "ai_bot",
        )
        .all()
    )


def _get_all_open_positions_for_account(db: Session, account_type: str, account_id: str, source_filter: str | None = None) -> list[Position]:
    """Fetch all open positions linked to bots using the same account.
    
    source_filter: if provided (e.g. 'ai_bot'), only count positions with that source.
    This prevents TradingView/manual positions from blocking AI signals.
    """
    bots = (
        db.query(BotConfig)
        .filter(
            BotConfig.status == "active",
            (
                BotConfig.exchange_account_id == account_id
                if account_type == "real"
                else BotConfig.paper_balance_id == account_id
            ),
        )
        .all()
    )
    bot_ids = [b.id for b in bots]
    if not bot_ids:
        return []
    query = (
        db.query(Position)
        .filter(
            Position.bot_id.in_(bot_ids),
            Position.status == "open",
        )
    )
    if source_filter:
        query = query.filter(Position.source == source_filter)
    return query.all()


def _notional(pos: Position) -> float:
    return float(pos.quantity) * float(pos.entry_price)


def _is_alt(symbol: str) -> bool:
    """True if symbol is not BTC or ETH."""
    s = symbol.upper()
    return "BTC" not in s and "ETH" not in s


def _htf_bear_for_btc(db: Session) -> bool | None:
    """Check latest BTC HTF bias from ai_latest_scans if available."""
    try:
        from app.models.ai_scan import AILatestScan
        scan = (
            db.query(AILatestScan)
            .filter(AILatestScan.symbol == "BTCUSDT")
            .order_by(AILatestScan.updated_at.desc())
            .first()
        )
        if scan and scan.signal_data:
            bias = (scan.signal_data.get("features") or {}).get("htf_bias")
            return bias == "bear"
    except Exception:
        pass
    return None


def _calculate_portfolio_drawdown(
    all_positions: list[Position],
    equity: float,
) -> float:
    """
    Estima el drawdown del portfolio basado en PnL realizado (24h) + no realizado.
    Retorna 0.0 si no hay drawdown, o un valor positivo (ej: 0.08 = 8%).
    """
    from datetime import datetime, timedelta, timezone
    from app.services.cache import sync_redis

    if equity <= 0:
        return 0.0

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    # Realized PnL últimas 24h
    realized_24h = sum(
        float(p.realized_pnl or 0)
        for p in all_positions
        if p.closed_at and p.closed_at >= day_ago
    )
    # También incluir posiciones ya cerradas que no estén en all_positions
    # (all_positions solo tiene abiertas, así que buscamos en DB)

    # Unrealized PnL aproximado usando precios de Redis
    unrealized = 0.0
    for p in all_positions:
        price_key = f"price:{p.symbol}"
        cached = sync_redis.get(price_key)
        if cached:
            current_price = float(cached)
            if p.side == "long":
                u_pnl = (current_price - float(p.entry_price)) * float(p.quantity)
            else:
                u_pnl = (float(p.entry_price) - current_price) * float(p.quantity)
            unrealized += u_pnl

    total_pnl = realized_24h + unrealized
    if total_pnl >= 0:
        return 0.0

    return abs(total_pnl) / equity


def _btc_change_24h() -> float | None:
    """Devuelve el cambio % de BTC en 24h desde Redis cache, o None."""
    from app.services.cache import sync_redis
    try:
        raw = sync_redis.get("price_change:BTCUSDT")
        if raw:
            return float(raw)
    except Exception:
        pass
    return None


def _symbol_change_24h(symbol: str) -> float | None:
    """Devuelve el cambio % de un símbolo en 24h desde Redis cache, o None."""
    from app.services.cache import sync_redis
    try:
        # Normalizar símbolo a formato de Redis
        redis_key = symbol if ":" in symbol else symbol.replace("/USDT", "/USDT:USDT")
        raw = sync_redis.get(f"price_change:{redis_key}")
        if raw:
            return float(raw)
    except Exception:
        pass
    return None


def _calculate_concentration_risk(
    open_positions: list[Position],
    proposed_symbol: str,
    proposed_direction: str,
) -> dict:
    """FASE 3D: Correlation matrix proxy usando cambios 24h de Redis.
    Si 80%+ de las posiciones abiertas tienen el mismo signo de cambio 24h,
    significa que no hay diversificación real — reducir sizing.
    """
    from app.services.cache import sync_redis

    if len(open_positions) < 2:
        return {"concentrated": False, "same_sign_pct": 0.0}

    changes = []
    for p in open_positions:
        ch = _symbol_change_24h(p.symbol)
        if ch is not None:
            changes.append((p.symbol, p.side, ch))

    if len(changes) < 2:
        return {"concentrated": False, "same_sign_pct": 0.0}

    # Contar cuántas posiciones tienen cambio positivo vs negativo
    positive = sum(1 for _, _, ch in changes if ch > 0)
    negative = len(changes) - positive
    max_same = max(positive, negative)
    same_sign_pct = max_same / len(changes) * 100.0

    # Verificar si el símbolo propuesto se alinea con la mayoría
    proposed_change = _symbol_change_24h(proposed_symbol)
    proposed_aligns = False
    if proposed_change is not None:
        majority_sign = 1 if positive >= negative else -1
        proposed_aligns = (proposed_change > 0 and majority_sign > 0) or (proposed_change < 0 and majority_sign < 0)

    return {
        "concentrated": same_sign_pct >= 80.0,
        "same_sign_pct": round(same_sign_pct, 1),
        "positions_count": len(changes),
        "proposed_aligns": proposed_aligns,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate_portfolio_risk(
    db: Session,
    bot: BotConfig,
    proposed_notional: float,
    proposed_direction: str,
    equity: float,
) -> dict[str, Any]:
    """Return risk assessment before opening a new position."""
    # Paper trading never affects real portfolio — bypass all limits
    if bot.is_paper_trading:
        return {
            "blocked": False,
            "sizing_multiplier": 1.0,
            "total_exposure_pct": 0.0,
            "symbol_exposure_pct": 0.0,
            "directional_exposure_pct": 0.0,
            "open_positions": 0,
            "alt_longs": 0,
            "warnings": [],
        }

    cfg = bot.ai_signal_config or {}
    limits = cfg.get("portfolio_limits", _DEFAULT_LIMITS)

    # Each bot is independent — portfolio risk is evaluated per-bot, not account-wide.
    # This prevents one bot's positions from blocking another bot's signals.
    all_positions = _get_open_ai_positions(db, str(bot.id))

    # Build leverage map for margin-based exposure (notional / leverage = real capital at risk)
    proposed_leverage = bot.leverage or 1

    def _margin(pos: Position) -> float:
        return _notional(pos) / (pos.leverage or proposed_leverage or 1)

    total_notional = sum(_margin(p) for p in all_positions) + proposed_notional
    symbol_positions = [p for p in all_positions if p.symbol == bot.symbol]
    symbol_notional = sum(_margin(p) for p in symbol_positions)
    if proposed_direction in ("long", "short"):
        symbol_notional += proposed_notional  # directional only (proposed_notional is already margin)

    dir_positions = [p for p in all_positions if p.side == proposed_direction]
    dir_notional = sum(_margin(p) for p in dir_positions) + proposed_notional

    total_exposure_pct = (total_notional / equity * 100) if equity > 0 else 999
    symbol_exposure_pct = (symbol_notional / equity * 100) if equity > 0 else 999
    dir_exposure_pct = (dir_notional / equity * 100) if equity > 0 else 999

    warnings = []
    blocked = False
    sizing_multiplier = 1.0

    max_total = limits.get("max_total_exposure_pct", 50.0)
    if total_exposure_pct > max_total * 1.5:
        # Only block at 150% of the nominal limit; between 100-150% reduce sizing
        warnings.append(
            f"Total exposure {total_exposure_pct:.1f}% exceeds hard limit {max_total * 1.5:.1f}%"
        )
        blocked = True
    elif total_exposure_pct > max_total:
        warnings.append(
            f"Total exposure {total_exposure_pct:.1f}% exceeds soft limit {max_total}% — sizing reduced 50%"
        )
        sizing_multiplier *= 0.5

    max_sym = limits.get("max_symbol_exposure_pct", 30.0)
    if symbol_exposure_pct > max_sym:
        warnings.append(
            f"Symbol exposure {symbol_exposure_pct:.1f}% exceeds limit {max_sym}%"
        )
        sizing_multiplier *= 0.5

    max_dir = limits.get("max_directional_exposure_pct", 40.0)
    if dir_exposure_pct > max_dir:
        warnings.append(
            f"Directional exposure {dir_exposure_pct:.1f}% exceeds limit {max_dir}%"
        )
        sizing_multiplier *= 0.5

    # Alt correlation risk
    alt_longs = sum(
        1 for p in all_positions
        if p.side == "long" and _is_alt(p.symbol)
    )
    alt_threshold = limits.get("alt_correlation_threshold", 3)
    if proposed_direction == "long" and _is_alt(bot.symbol):
        alt_longs += 1
    if alt_longs >= alt_threshold:
        btc_bear = _htf_bear_for_btc(db)
        if btc_bear:
            warnings.append(
                f"Correlation risk: {alt_longs} alt LONGs while BTC HTF is bearish"
            )
            sizing_multiplier *= 0.5
        elif btc_bear is False:
            warnings.append(
                f"Note: {alt_longs} alt LONGs while BTC HTF is bullish (acceptable)"
            )
        else:
            warnings.append(
                f"Note: {alt_longs} alt LONGs (BTC HTF unknown, caution)"
            )
            sizing_multiplier *= 0.7

    # BTC 24h correlation — si BTC cae fuerte, reducir LONGs en alts
    btc_change = _btc_change_24h()
    if btc_change is not None and btc_change < -3.0:
        if proposed_direction == "long" and _is_alt(bot.symbol):
            warnings.append(
                f"BTC cae {btc_change:.1f}% (24h) — reducir LONG alts"
            )
            sizing_multiplier *= 0.5

    # FASE 3D: Concentration risk — si 80%+ de posiciones abiertas se mueven igual,
    # no hay diversificación real. Reducir sizing.
    conc = _calculate_concentration_risk(all_positions, bot.symbol, proposed_direction)
    if conc["concentrated"]:
        warnings.append(
            f"Concentration risk: {conc['same_sign_pct']:.0f}% of open positions move together "
            f"({conc['positions_count']} positions) — sizing reduced 30%"
        )
        sizing_multiplier *= 0.70
        if conc["proposed_aligns"]:
            warnings.append(
                f"Proposed {bot.symbol} aligns with majority direction — extra 20% reduction"
            )
            sizing_multiplier *= 0.80

    # FASE 2E: Correlation matrix proxy — evitar duplicar misma posición reciente
    # Si ya hay una posición abierta en el mismo par+dirección en las últimas 24h,
    # reducir sizing 50% (es correlación 1.0, no diversificación).
    from datetime import timedelta
    recent_same_trade = [
        p for p in all_positions
        if p.symbol == bot.symbol
        and p.side == proposed_direction
        and p.opened_at is not None
        and (datetime.now(timezone.utc) - p.opened_at.replace(tzinfo=timezone.utc) if p.opened_at.tzinfo is None else p.opened_at) < timedelta(hours=24)
    ]
    if recent_same_trade:
        warnings.append(
            f"Duplicate position: {len(recent_same_trade)} recent {proposed_direction} in {bot.symbol} "
            f"(opened within 24h) — sizing reduced 50%"
        )
        sizing_multiplier *= 0.5

    # Portfolio drawdown guard
    drawdown = _calculate_portfolio_drawdown(all_positions, equity)
    if drawdown > 0.10:   # 10% drawdown
        warnings.append(
            f"Portfolio drawdown {drawdown:.1%} — sizing reducido 50%"
        )
        sizing_multiplier *= 0.5
    elif drawdown > 0.05:  # 5% drawdown
        warnings.append(
            f"Portfolio drawdown {drawdown:.1%} — sizing reducido 25%"
        )
        sizing_multiplier *= 0.75

    return {
        "blocked": blocked,
        "sizing_multiplier": round(sizing_multiplier, 2),
        "total_exposure_pct": round(total_exposure_pct, 1),
        "symbol_exposure_pct": round(symbol_exposure_pct, 1),
        "directional_exposure_pct": round(dir_exposure_pct, 1),
        "open_positions": len(all_positions),
        "alt_longs": alt_longs,
        "warnings": warnings,
    }


def get_portfolio_summary(db: Session, user_id: str) -> dict[str, Any]:
    """Return aggregated REAL portfolio view for dashboard.
    
    Paper positions are excluded so the dashboard reflects actual live exposure.
    """
    bots = (
        db.query(BotConfig)
        .filter(BotConfig.user_id == user_id, BotConfig.status == "active")
        .filter(BotConfig.paper_balance_id.is_(None))
        .all()
    )

    bot_ids = [b.id for b in bots]
    positions = (
        db.query(Position)
        .filter(Position.bot_id.in_(bot_ids), Position.status == "open")
        .all()
    ) if bot_ids else []

    total_long = sum(_notional(p) for p in positions if p.side == "long")
    total_short = sum(_notional(p) for p in positions if p.side == "short")
    by_symbol: dict[str, dict] = {}
    for p in positions:
        s = p.symbol
        if s not in by_symbol:
            by_symbol[s] = {"long": 0.0, "short": 0.0, "net": 0.0}
        n = _notional(p)
        by_symbol[s][p.side] += n
        by_symbol[s]["net"] += n if p.side == "long" else -n

    return {
        "open_count": len(positions),
        "total_long": round(total_long, 2),
        "total_short": round(total_short, 2),
        "net_exposure": round(total_long - total_short, 2),
        "by_symbol": [
            {"symbol": k, **{sk: round(sv, 2) for sk, sv in v.items()}}
            for k, v in by_symbol.items()
        ],
    }


# ── Consolidated PortfolioManager (moved from risk.portfolio_manager) ──────────

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioCheckResult:
    allowed: bool
    reason: str
    max_correlation: float
    sector_exposure_pct: float


class PortfolioManager:
    """Check portfolio-level risk before opening a new position.

    Uses a hardcoded correlation matrix as fallback; can be upgraded to
    dynamic hourly-return correlation when historical price data is available.
    """

    # Hardcoded based on typical crypto correlations (24h returns)
    _CORRELATION_MATRIX: dict[str, dict[str, float]] = {
        "BTC":  {"ETH": 0.85, "SOL": 0.75, "BNB": 0.70, "XRP": 0.55, "DOGE": 0.60, "ADA": 0.55, "AVAX": 0.65},
        "ETH":  {"BTC": 0.85, "SOL": 0.70, "BNB": 0.65, "XRP": 0.50, "DOGE": 0.55, "ADA": 0.60, "AVAX": 0.70},
        "SOL":  {"BTC": 0.75, "ETH": 0.70, "BNB": 0.60, "XRP": 0.45, "DOGE": 0.50, "ADA": 0.55, "AVAX": 0.65},
        "BNB":  {"BTC": 0.70, "ETH": 0.65, "SOL": 0.60, "XRP": 0.45, "DOGE": 0.50, "ADA": 0.50, "AVAX": 0.55},
        "XRP":  {"BTC": 0.55, "ETH": 0.50, "SOL": 0.45, "BNB": 0.45, "DOGE": 0.40, "ADA": 0.45, "AVAX": 0.45},
        "DOGE": {"BTC": 0.60, "ETH": 0.55, "SOL": 0.50, "BNB": 0.50, "XRP": 0.40, "ADA": 0.45, "AVAX": 0.50},
        "ADA":  {"BTC": 0.55, "ETH": 0.60, "SOL": 0.55, "BNB": 0.50, "XRP": 0.45, "DOGE": 0.45, "AVAX": 0.55},
        "AVAX": {"BTC": 0.65, "ETH": 0.70, "SOL": 0.65, "BNB": 0.55, "XRP": 0.45, "DOGE": 0.50, "ADA": 0.55},
    }
    _CORRELATION_DEFAULT = 0.5
    _CORRELATION_THRESHOLD = 0.92
    _MAX_SECTOR_EXPOSURE = 0.60  # 60% of equity in one "crypto" sector

    @classmethod
    def _extract_base(cls, ccxt_symbol: str) -> str:
        return ccxt_symbol.split("/")[0] if "/" in ccxt_symbol else ccxt_symbol.split(":")[0]

    @classmethod
    def get_correlation(cls, sym_a: str, sym_b: str) -> float:
        """Return estimated correlation between two symbols (0-1)."""
        base_a = cls._extract_base(sym_a)
        base_b = cls._extract_base(sym_b)
        if base_a == base_b:
            return 1.0
        return cls._CORRELATION_MATRIX.get(base_a, {}).get(base_b, cls._CORRELATION_DEFAULT)

    @classmethod
    def check_new_position(
        cls,
        new_symbol: str,
        new_direction: str,
        new_notional: float,
        open_positions: list,
        total_equity: float,
    ) -> PortfolioCheckResult:
        """
        Return PortfolioCheckResult indicating whether the new position is allowed.

        Args:
            new_symbol: CCXT symbol of the proposed trade
            new_direction: "long" or "short"
            new_notional: position size in USDT
            open_positions: list of Position ORM objects (must have .symbol, .side, .notional or .quantity*.entry_price)
            total_equity: total account equity in USDT
        """
        max_corr = 0.0
        same_direction_notional = 0.0

        for pos in open_positions:
            corr = cls.get_correlation(new_symbol, pos.symbol)
            max_corr = max(max_corr, corr)

            # Warn if correlated asset already open in same direction, but don't block.
            # In crypto most alts correlate to BTC; blocking destroys signal flow.
            if pos.side == new_direction and corr >= cls._CORRELATION_THRESHOLD:
                pass  # sizing reduction handled by evaluate_portfolio_risk

            # Accumulate same-direction exposure for sector cap
            if pos.side == new_direction:
                pos_notional = getattr(pos, "notional", None)
                if pos_notional is None:
                    qty = float(getattr(pos, "quantity", 0) or 0)
                    entry = float(getattr(pos, "entry_price", 0) or 0)
                    pos_notional = qty * entry
                same_direction_notional += float(pos_notional)

        same_direction_notional += new_notional
        sector_exposure_pct = (same_direction_notional / total_equity) if total_equity > 0 else 0.0

        # Don't block on sector exposure; return sizing guidance instead.
        # Hard blocking here kills profitable signals in correlated markets.
        if sector_exposure_pct > cls._MAX_SECTOR_EXPOSURE:
            return PortfolioCheckResult(
                allowed=True,
                reason=f"sector exposure high: {sector_exposure_pct:.1%} > {cls._MAX_SECTOR_EXPOSURE:.0%} — consider reducing sizing",
                max_correlation=max_corr,
                sector_exposure_pct=sector_exposure_pct,
            )

        return PortfolioCheckResult(
            allowed=True,
            reason="portfolio checks passed",
            max_correlation=max_corr,
            sector_exposure_pct=sector_exposure_pct,
        )


def get_forward_level_stats(
    db: Session,
    ticker: str | None = None,
    timeframe: str | None = None,
    min_signals: int = 5,
) -> dict[str, Any]:
    """
    Compute performance correlation segmented by forward-level features.

    Returns dict with keys:
      - by_tp1_source: stats grouped by tp1_source (eq_high, fvg_bear, fallback, etc.)
      - by_distance_r: stats grouped by tp1_distance_r buckets
      - by_density: stats grouped by forward_density buckets
      - by_strength: stats grouped by tp1_strength buckets
      - summary: overall aggregated stats
    """
    from sqlalchemy import func

    query = db.query(AISignal).filter(AISignal.outcome.notin_(["PENDING", "INVALID"]))
    if ticker:
        query = query.filter(AISignal.ticker == ticker)
    if timeframe:
        query = query.filter(AISignal.timeframe == timeframe)

    signals = query.all()
    if not signals:
        return {"summary": {}, "segments": {}}

    def _segment_stats(rows: list[AISignal]) -> dict:
        total = len(rows)
        wins = [r for r in rows if r.outcome == "SUCCESS"]
        losses = [r for r in rows if r.outcome in ("FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")]
        win_rate = len(wins) / total if total > 0 else 0.0
        avg_pnl = sum((r.pnl_pct or 0) for r in rows) / total if total > 0 else 0.0
        gross_profit = sum(max(r.pnl_pct or 0, 0) for r in rows)
        gross_loss = sum(min(r.pnl_pct or 0, 0) for r in rows)
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float("inf")
        expectancy = avg_pnl
        return {
            "total_signals": total,
            "win_rate": round(win_rate, 3),
            "avg_pnl_pct": round(avg_pnl, 3),
            "profit_factor": round(profit_factor, 3),
            "expectancy": round(expectancy, 3),
        }

    # By tp1_source
    by_source: dict[str, list[AISignal]] = {}
    for s in signals:
        src = (s.features or {}).get("tp1_source", "unknown")
        by_source.setdefault(src, []).append(s)

    # By tp1_distance_r buckets
    by_distance: dict[str, list[AISignal]] = {}
    for s in signals:
        dist = (s.features or {}).get("tp1_distance_r", 1.5)
        bucket = _bucket_value(dist, _FORWARD_LEVEL_BUCKETS["tp1_distance_r"])
        by_distance.setdefault(bucket, []).append(s)

    # By forward_density buckets
    by_density: dict[str, list[AISignal]] = {}
    for s in signals:
        density = (s.features or {}).get("forward_density", 0)
        bucket = _bucket_value(density, _FORWARD_LEVEL_BUCKETS["forward_density"])
        by_density.setdefault(bucket, []).append(s)

    # By tp1_strength buckets
    by_strength: dict[str, list[AISignal]] = {}
    for s in signals:
        strength = (s.features or {}).get("tp1_strength", 0.0)
        bucket = _bucket_value(strength, _FORWARD_LEVEL_BUCKETS["tp1_strength"])
        by_strength.setdefault(bucket, []).append(s)

    def _filter_min(data: dict[str, list[AISignal]]) -> dict[str, dict]:
        return {k: _segment_stats(v) for k, v in data.items() if len(v) >= min_signals}

    return {
        "summary": _segment_stats(signals),
        "segments": {
            "by_tp1_source": _filter_min(by_source),
            "by_distance_r": _filter_min(by_distance),
            "by_density": _filter_min(by_density),
            "by_strength": _filter_min(by_strength),
        },
    }
