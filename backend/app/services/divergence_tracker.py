"""
Paper vs Real Trading Divergence Tracker.

Compara métricas de ejecución entre posiciones paper y reales
para detectar cuándo el paper trading no refleja fielmente
la realidad del mercado (slippage, liquidez, timing).

Regla de bloqueo: divergencia weighted > 15% con ≥100 trades comparados.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select, and_

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.models.paper_real_divergence import PaperRealDivergence
from app.models.position import Position

# ── Constantes ──────────────────────────────────────────────
DIVERGENCE_WINDOW_DAYS = 7
MIN_TRADES_TO_EVALUATE = 20
BLOCK_THRESHOLD_PCT = Decimal("15.0")
CRITICAL_THRESHOLD_PCT = Decimal("10.0")


def _avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values) / len(values)


def _divergence_pct(paper: Decimal | None, real: Decimal | None) -> Decimal | None:
    """Divergencia porcentual: |paper - real| / |real| * 100"""
    if paper is None or real is None or real == 0:
        return None
    return abs(paper - real) / abs(real) * Decimal("100")


def compute_divergence_for_symbol(
    db: Session,
    symbol: str,
    direction: str,
    days: int = DIVERGENCE_WINDOW_DAYS,
) -> PaperRealDivergence | None:
    """
    Calcula divergencia paper-vs-real para un símbolo/dirección
    en la ventana de tiempo dada y persiste el resultado.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Posiciones paper cerradas — se identifican por exchange=='paper',
    # ya que el source de posiciones paper sigue siendo 'ai_bot'/'bot'.
    paper_positions = db.execute(
        select(Position).where(
            and_(
                Position.symbol == symbol,
                Position.side == direction,
                Position.status == "closed",
                Position.exchange == "paper",
                Position.closed_at >= cutoff,
            )
        )
    ).scalars().all()

    # Posiciones reales cerradas (exchange != 'paper')
    real_positions = db.execute(
        select(Position).where(
            and_(
                Position.symbol == symbol,
                Position.side == direction,
                Position.status == "closed",
                Position.exchange != "paper",
                Position.closed_at >= cutoff,
            )
        )
    ).scalars().all()

    paper_count = len(paper_positions)
    real_count = len(real_positions)

    if paper_count < MIN_TRADES_TO_EVALUATE or real_count < MIN_TRADES_TO_EVALUATE:
        return None

    paper_entries = [p.entry_price for p in paper_positions]
    paper_exits = [p.realized_pnl for p in paper_positions if p.realized_pnl is not None]
    # Para exit price necesitamos el precio de cierre — usar el último exchange_trade o el unrealized
    # Como proxy usamos: entry_price + realized_pnl / (quantity * leverage) aproximado
    # Pero es complejo. Vamos a usar el exchange_trade exit price si existe.
    paper_exit_prices = []
    for p in paper_positions:
        if p.exchange_trades:
            exits = [t.exit_price for t in p.exchange_trades if t.exit_price is not None]
            if exits:
                paper_exit_prices.append(sum(exits) / len(exits))

    real_entries = [p.entry_price for p in real_positions]
    real_exits = [p.realized_pnl for p in real_positions if p.realized_pnl is not None]
    real_exit_prices = []
    for p in real_positions:
        if p.exchange_trades:
            exits = [t.exit_price for t in p.exchange_trades if t.exit_price is not None]
            if exits:
                real_exit_prices.append(sum(exits) / len(exits))

    paper_avg_entry = _avg(paper_entries)
    real_avg_entry = _avg(real_entries)
    entry_div = _divergence_pct(paper_avg_entry, real_avg_entry)

    paper_avg_exit = _avg(paper_exit_prices)
    real_avg_exit = _avg(real_exit_prices)
    exit_div = _divergence_pct(paper_avg_exit, real_avg_exit)

    paper_avg_pnl = _avg(paper_exits)
    real_avg_pnl = _avg(real_exits)
    pnl_div = _divergence_pct(paper_avg_pnl, real_avg_pnl)

    # Weighted divergence: 30% entry + 30% exit + 40% pnl
    weighted = None
    if entry_div is not None or exit_div is not None or pnl_div is not None:
        parts = []
        if entry_div is not None:
            parts.append(entry_div * Decimal("0.3"))
        if exit_div is not None:
            parts.append(exit_div * Decimal("0.3"))
        if pnl_div is not None:
            parts.append(pnl_div * Decimal("0.4"))
        if parts:
            weighted = sum(parts)

    is_critical = False
    block_reason = None
    if weighted is not None and weighted >= CRITICAL_THRESHOLD_PCT:
        is_critical = True
        if weighted >= BLOCK_THRESHOLD_PCT:
            block_reason = (
                f"Weighted divergence {weighted:.2f}% >= {BLOCK_THRESHOLD_PCT}% "
                f"({paper_count} paper, {real_count} real trades)"
            )
        else:
            block_reason = (
                f"Weighted divergence {weighted:.2f}% >= {CRITICAL_THRESHOLD_PCT}% "
                f"— warning level"
            )

    record = PaperRealDivergence(
        id=uuid.uuid4(),
        symbol=symbol,
        direction=direction,
        window_start=cutoff,
        window_end=datetime.now(timezone.utc),
        paper_count=paper_count,
        real_count=real_count,
        paper_avg_entry=paper_avg_entry,
        real_avg_entry=real_avg_entry,
        entry_divergence_pct=entry_div,
        paper_avg_exit=paper_avg_exit,
        real_avg_exit=real_avg_exit,
        exit_divergence_pct=exit_div,
        paper_avg_pnl_pct=paper_avg_pnl,
        real_avg_pnl_pct=real_avg_pnl,
        pnl_divergence_pct=pnl_div,
        weighted_divergence_pct=weighted,
        is_critical=is_critical,
        block_reason=block_reason,
    )
    db.add(record)
    db.commit()
    return record


def is_symbol_blocked(
    db: Session,
    symbol: str,
    direction: str | None = None,
    threshold_pct: Decimal = BLOCK_THRESHOLD_PCT,
) -> tuple[bool, str | None]:
    """
    Devuelve (is_blocked, reason) si el símbolo está bloqueado
    por divergencia paper-vs-real crítica.
    """
    q = select(PaperRealDivergence).where(
        and_(
            PaperRealDivergence.symbol == symbol,
            PaperRealDivergence.is_critical == True,
        )
    ).order_by(PaperRealDivergence.window_end.desc())

    if direction:
        q = q.where(PaperRealDivergence.direction == direction)

    latest = db.execute(q.limit(1)).scalars().first()
    if latest is None:
        return False, None

    if latest.block_reason and latest.weighted_divergence_pct is not None:
        if latest.weighted_divergence_pct >= threshold_pct:
            return True, latest.block_reason

    return False, None


def get_divergence_summary(db: Session, limit: int = 50) -> list[dict]:
    """Devuelve resumen de divergencias más recientes."""
    rows = db.execute(
        select(PaperRealDivergence)
        .order_by(PaperRealDivergence.window_end.desc())
        .limit(limit)
    ).scalars().all()

    return [
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
    ]


def run_divergence_scan(db: Session, days: int = DIVERGENCE_WINDOW_DAYS) -> dict:
    """
    Escanea TODOS los símbolos/direcciones con actividad reciente
    y calcula divergencia para cada par.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Encontrar pares activos
    pairs = db.execute(
        select(Position.symbol, Position.side)
        .where(
            and_(
                Position.status == "closed",
                Position.closed_at >= cutoff,
            )
        )
        .group_by(Position.symbol, Position.side)
    ).all()

    results: list[PaperRealDivergence | None] = []
    blocked: list[tuple[str, str, str]] = []

    for symbol, direction in pairs:
        rec = compute_divergence_for_symbol(db, symbol, direction, days=days)
        if rec:
            results.append(rec)
            if rec.is_critical and rec.block_reason and rec.weighted_divergence_pct and rec.weighted_divergence_pct >= BLOCK_THRESHOLD_PCT:
                blocked.append((symbol, direction, rec.block_reason))

    return {
        "pairs_scanned": len(pairs),
        "records_created": len([r for r in results if r is not None]),
        "blocked_pairs": [
            {"symbol": s, "direction": d, "reason": r} for s, d, r in blocked
        ],
    }
