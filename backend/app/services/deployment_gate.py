"""
Deployment Gate — máquina de estados unificada de salud del sistema.

Reemplaza gates individuales (Kelly, Drift, Macro, etc.) con una sola
luz de semáforo: HEALTHY → DEGRADED → PAUSED.

Autonomous behaviour:
  - Proactively pauses ALL AI bots when gate enters PAUSED state.
  - Auto-resumes AI bots when gate returns to HEALTHY.
  - Uses ai_signal_config.autonomy_state to track system-paused bots.

Métricas de entrada:
  Sharpe 20d, Profit Factor, Max Drawdown, Drift PSI,
  WF validation, Confidence Decay divergence

Estados:
  HEALTHY   (sizing 100%) — todo verde
  DEGRADED  (sizing 50%)  — alguna amarilla
  PAUSED    (sizing 0%)   — alguna roja o múltiples amarillas
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import desc, func, select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.models.deployment_gate_log import DeploymentGateLog
from app.models.exchange_trade import ExchangeTrade
from app.models.model_confidence_decay import ModelConfidenceDecay
from app.models.model_validation_log import ModelValidationLog
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog
from app.models.symbol_deployment_gate_log import SymbolDeploymentGateLog
from app.services.autonomy_state import mark_paused, clear_pause


def _filter_real_ai_trades_query(
    days: int = 60,
    symbol: str | None = None,
    timeframe: str | None = None,
):
    """Build base query for REAL ai_bot trades (excludes paper bots).

    Optionally filter by bot symbol and/or timeframe for per-pair evaluation.
    Only includes trades closed after CLEAN_CUTOFF to avoid mixing old-model data.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Use the later of rolling cutoff and clean cutoff
    effective_cutoff = max(cutoff, CLEAN_CUTOFF)
    conditions = [
        ExchangeTrade.source == "ai_bot",
        ExchangeTrade.status == "closed",
        ExchangeTrade.closed_at >= effective_cutoff,
        BotConfig.paper_balance_id.is_(None),
    ]
    if symbol:
        conditions.append(BotConfig.symbol == symbol)
    if timeframe:
        conditions.append(BotConfig.timeframe == timeframe)
    return (
        select(ExchangeTrade)
        .join(BotConfig, ExchangeTrade.bot_id == BotConfig.id)
        .where(*conditions)
    )


def _filter_paper_ai_trades_query(days: int = 60):
    """Build base query for PAPER ai_bot trades."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    effective_cutoff = max(cutoff, CLEAN_CUTOFF)
    return (
        select(ExchangeTrade)
        .join(BotConfig, ExchangeTrade.bot_id == BotConfig.id)
        .where(
            ExchangeTrade.source == "ai_bot",
            ExchangeTrade.status == "closed",
            ExchangeTrade.closed_at >= effective_cutoff,
            BotConfig.paper_balance_id.isnot(None),
        )
    )

# Fecha de corte: solo evaluamos trades generados por el motor actual.
# Trades anteriores a esta fecha provienen del motor antiguo/intermedio.
CLEAN_CUTOFF = datetime(2026, 6, 10, tzinfo=timezone.utc)

# ── Thresholds ──────────────────────────────────────────────
# Thresholds calibrated for institutional risk management
# A system with Sharpe < -3 or PF < 0.8 is already losing money consistently.
_MAX_DD_PAUSE_PCT = Decimal("15.0")
_MAX_DD_DEGRADE_PCT = Decimal("10.0")
_SHARPE_DEGRADE = Decimal("-1.0")  # Realistic risk floor
_SHARPE_PAUSE = Decimal("-2.0")  # No edge — stop real trading
_PF_DEGRADE = Decimal("1.0")  # Realistic risk floor
_PF_PAUSE = Decimal("0.8")  # Losing system — stop real trading
_DRIFT_DEGRADE = Decimal("0.15")
_DRIFT_PAUSE = Decimal("0.20")
_DECAY_DEGRADE = Decimal("70.0")
_DECAY_PAUSE = Decimal("100.0")
_EXPECTANCY_DEGRADE = Decimal("0.0")  # Realistic risk floor
_EXPECTANCY_PAUSE = Decimal("-0.5")  # Negative expectancy — stop real trading

# Minimum trades required before trade-based metrics are evaluated
_MIN_TRADES_FOR_EVAL = 10

_SIZING_HEALTHY = Decimal("1.00")
_SIZING_DEGRADED = Decimal("0.50")
_SIZING_PAUSED = Decimal("0.00")


def _latest_metric(db: Session, model_class, attr: str):
    """Fetch latest value of an attribute from a model."""
    try:
        row = db.execute(
            select(model_class).order_by(desc(model_class.created_at)).limit(1)
        ).scalars().first()
        if row:
            return getattr(row, attr, None)
    except Exception:
        pass
    return None


_REFERENCE_CAPITAL = 10000.0  # Base para normalizar drawdown y sharpe


def _compute_sharpe_from_trades(
    db: Session,
    days: int = 20,
    paper: bool = False,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> Decimal | None:
    """Compute rolling Sharpe from daily trade returns (percentage-based).

    By default uses REAL trades only (paper=False). Set paper=True for paper trades.
    Optionally filter by symbol/timeframe for per-pair evaluation.
    """
    try:
        if paper:
            trades = db.execute(_filter_paper_ai_trades_query(days)).scalars().all()
        else:
            trades = db.execute(
                _filter_real_ai_trades_query(days, symbol=symbol, timeframe=timeframe)
            ).scalars().all()
        if not trades:
            return None
        from app.services.institutional_health import _daily_returns_from_trades, _sharpe
        daily = _daily_returns_from_trades(trades)
        daily_pct = [r / _REFERENCE_CAPITAL for r in daily]
        sharpe = _sharpe(daily_pct)
        return Decimal(str(sharpe)) if sharpe is not None else None
    except Exception:
        return None


def _compute_pf_and_dd_from_trades(
    db: Session,
    days: int = 60,
    paper: bool = False,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> tuple[Decimal | None, Decimal | None]:
    """Compute Profit Factor and Max Drawdown from trades.

    By default uses REAL trades only (paper=False). Set paper=True for paper trades.
    Optionally filter by symbol/timeframe for per-pair evaluation.
    """
    try:
        if paper:
            trades = db.execute(_filter_paper_ai_trades_query(days)).scalars().all()
        else:
            trades = db.execute(
                _filter_real_ai_trades_query(days, symbol=symbol, timeframe=timeframe)
            ).scalars().all()
        if not trades:
            return None, None
        pnls = [float(t.realized_pnl or 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else None

        cum = 0.0
        eq = []
        for p in pnls:
            cum += p
            eq.append(_REFERENCE_CAPITAL + cum)
        from app.services.institutional_health import _max_drawdown
        max_dd, _ = _max_drawdown(eq)
        return (Decimal(str(pf)) if pf is not None else None,
                Decimal(str(max_dd * 100)) if max_dd is not None else None)
    except Exception:
        return None, None


def _compute_expectancy_from_trades(
    db: Session,
    days: int = 30,
    paper: bool = False,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> Decimal | None:
    """Compute average expectancy (avg PnL per trade) from recent trades.

    By default uses REAL trades only (paper=False). Set paper=True for paper trades.
    Optionally filter by symbol/timeframe for per-pair evaluation.
    """
    try:
        if paper:
            trades = db.execute(_filter_paper_ai_trades_query(days)).scalars().all()
        else:
            trades = db.execute(
                _filter_real_ai_trades_query(days, symbol=symbol, timeframe=timeframe)
            ).scalars().all()
        if not trades:
            return None
        pnls = [float(t.realized_pnl or 0) for t in trades]
        expectancy = sum(pnls) / len(pnls) if pnls else None
        return Decimal(str(expectancy)) if expectancy is not None else None
    except Exception:
        return None


def _count_ai_trades(
    db: Session,
    days: int = 60,
    paper: bool = False,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> int | None:
    """Count closed AI trades in the lookback window.

    By default counts REAL trades only (paper=False). Set paper=True for paper trades.
    Optionally filter by symbol/timeframe for per-pair evaluation.
    """
    try:
        if paper:
            trades = db.execute(_filter_paper_ai_trades_query(days)).scalars().all()
        else:
            trades = db.execute(
                _filter_real_ai_trades_query(days, symbol=symbol, timeframe=timeframe)
            ).scalars().all()
        return len(trades)
    except Exception:
        return None


def _compute_paper_real_divergence(db: Session, days: int = 20) -> Decimal | None:
    """Compute divergence between paper and real performance.

    Returns (real_expectancy - paper_expectancy). Positive means real outperforms paper.
    Used as advisory metric only — does NOT affect gate state.
    """
    real_exp = _compute_expectancy_from_trades(db, days=days, paper=False)
    paper_exp = _compute_expectancy_from_trades(db, days=days, paper=True)
    if real_exp is not None and paper_exp is not None:
        return Decimal(str(float(real_exp) - float(paper_exp)))
    return None


def evaluate_deployment_gate(db: Session) -> DeploymentGateLog:
    """
    Evaluates unified deployment gate and persists result.
    Also proactively manages bot statuses based on gate state.
    Returns the log record.
    """
    reasons = []
    state = "HEALTHY"
    sizing = _SIZING_HEALTHY

    # ── Gather metrics ──
    # REAL trades only for gate decision (paper trades are advisory only)
    sharpe = _compute_sharpe_from_trades(db, days=20, paper=False)
    pf, max_dd = _compute_pf_and_dd_from_trades(db, days=60, paper=False)
    expectancy = _compute_expectancy_from_trades(db, days=30, paper=False)
    drift_psi = _latest_metric(db, ModelValidationLog, "drift_psi_max")
    wf_passed = _latest_metric(db, ModelValidationLog, "wf_passed")
    decay_div = _latest_metric(db, ModelConfidenceDecay, "divergence_pct")

    # Paper trades metrics (advisory only — do NOT affect gate state)
    paper_sharpe = _compute_sharpe_from_trades(db, days=20, paper=True)
    paper_pf, _ = _compute_pf_and_dd_from_trades(db, days=60, paper=True)
    paper_expectancy = _compute_expectancy_from_trades(db, days=30, paper=True)
    divergence = _compute_paper_real_divergence(db, days=20)

    # Count trade sample sizes
    trade_count = _count_ai_trades(db, days=60, paper=False)
    paper_trade_count = _count_ai_trades(db, days=60, paper=True)
    insufficient_data = trade_count is not None and trade_count < _MIN_TRADES_FOR_EVAL

    # ── Evaluate rules ──
    red_flags = 0
    yellow_flags = 0

    if max_dd is not None and not insufficient_data:
        if max_dd >= _MAX_DD_PAUSE_PCT:
            red_flags += 1
            reasons.append(f"Max DD {float(max_dd):.1f}% >= {_MAX_DD_PAUSE_PCT}%")
        elif max_dd >= _MAX_DD_DEGRADE_PCT:
            yellow_flags += 1
            reasons.append(f"Max DD {float(max_dd):.1f}% >= {_MAX_DD_DEGRADE_PCT}%")

    if sharpe is not None and not insufficient_data:
        if sharpe <= _SHARPE_PAUSE:
            red_flags += 1
            reasons.append(f"Sharpe {float(sharpe):.2f} <= {_SHARPE_PAUSE}")
        elif sharpe <= _SHARPE_DEGRADE:
            yellow_flags += 1
            reasons.append(f"Sharpe {float(sharpe):.2f} <= {_SHARPE_DEGRADE}")

    if pf is not None and not insufficient_data:
        if pf <= _PF_PAUSE:
            red_flags += 1
            reasons.append(f"PF {float(pf):.2f} <= {_PF_PAUSE}")
        elif pf <= _PF_DEGRADE:
            yellow_flags += 1
            reasons.append(f"PF {float(pf):.2f} <= {_PF_DEGRADE}")

    if expectancy is not None and not insufficient_data:
        if expectancy <= _EXPECTANCY_PAUSE:
            red_flags += 1
            reasons.append(f"Expectancy {float(expectancy):.4f} <= {_EXPECTANCY_PAUSE}")
        elif expectancy <= _EXPECTANCY_DEGRADE:
            yellow_flags += 1
            reasons.append(f"Expectancy {float(expectancy):.4f} <= {_EXPECTANCY_DEGRADE}")

    if drift_psi is not None:
        if drift_psi >= _DRIFT_PAUSE:
            red_flags += 1
            reasons.append(f"Drift PSI {float(drift_psi):.2f} >= {_DRIFT_PAUSE}")
        elif drift_psi >= _DRIFT_DEGRADE:
            yellow_flags += 1
            reasons.append(f"Drift PSI {float(drift_psi):.2f} >= {_DRIFT_DEGRADE}")

    if decay_div is not None:
        if decay_div >= _DECAY_PAUSE:
            red_flags += 1
            reasons.append(f"Confidence decay {float(decay_div):.1f}% >= {_DECAY_PAUSE}%")
        elif decay_div >= _DECAY_DEGRADE:
            yellow_flags += 1
            reasons.append(f"Confidence decay {float(decay_div):.1f}% >= {_DECAY_DEGRADE}%")

    if wf_passed is False:
        yellow_flags += 1
        reasons.append("Walk-forward validation failed")

    # ── Determine state ──
    if red_flags >= 4 or yellow_flags >= 6:
        state = "PAUSED"
        sizing = _SIZING_PAUSED
    elif yellow_flags >= 1 or red_flags >= 1:
        state = "DEGRADED"
        sizing = _SIZING_DEGRADED

    log = DeploymentGateLog(
        id=uuid.uuid4(),
        state=state,
        sizing_multiplier=sizing,
        sharpe_20=sharpe,
        profit_factor=pf,
        max_drawdown_pct=max_dd,
        drift_psi_max=drift_psi,
        wf_passed=wf_passed,
        confidence_decay_divergence=decay_div,
        reasons=reasons,
        extra_data={
            "red_flags": red_flags,
            "yellow_flags": yellow_flags,
            "expectancy": float(expectancy) if expectancy is not None else None,
            "trade_count": trade_count,
            # Paper metrics — advisory only, for model evaluation
            "paper_sharpe": float(paper_sharpe) if paper_sharpe is not None else None,
            "paper_pf": float(paper_pf) if paper_pf is not None else None,
            "paper_expectancy": float(paper_expectancy) if paper_expectancy is not None else None,
            "paper_trade_count": paper_trade_count,
            "paper_real_divergence": float(divergence) if divergence is not None else None,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(log)
    db.commit()

    # ── AUTONOMOUS BOT MANAGEMENT ──
    _proactively_manage_bots(db, state)

    return log


def _evaluate_symbol_gate_core(
    db: Session, symbol: str, timeframe: str, lookback_days: int | None = None
) -> SymbolDeploymentGateLog:
    """Evaluate per-symbol/TF health using the SAME thresholds as global gate.

    Args:
        lookback_days: if provided, overrides the default lookbacks for
                       a short-term regime-aware evaluation.

    Returns the log record (not yet committed — caller must commit).
    """
    reasons = []
    state = "HEALTHY"
    sizing = _SIZING_HEALTHY

    # Default lookbacks: sharpe=20, pf/dd=60, expectancy=30, count=60
    # Short lookback for regime-aware: sharpe=5, pf/dd=5, expectancy=5, count=5
    sharpe_days = lookback_days if lookback_days else 20
    pf_dd_days = lookback_days if lookback_days else 60
    exp_days = lookback_days if lookback_days else 30
    count_days = lookback_days if lookback_days else 60

    sharpe = _compute_sharpe_from_trades(
        db, days=sharpe_days, paper=False, symbol=symbol, timeframe=timeframe
    )
    pf, max_dd = _compute_pf_and_dd_from_trades(
        db, days=pf_dd_days, paper=False, symbol=symbol, timeframe=timeframe
    )
    expectancy = _compute_expectancy_from_trades(
        db, days=exp_days, paper=False, symbol=symbol, timeframe=timeframe
    )
    trade_count = _count_ai_trades(
        db, days=count_days, paper=False, symbol=symbol, timeframe=timeframe
    )
    insufficient_data = trade_count is not None and trade_count < _MIN_TRADES_FOR_EVAL

    red_flags = 0
    yellow_flags = 0

    if max_dd is not None and not insufficient_data:
        if max_dd >= _MAX_DD_PAUSE_PCT:
            red_flags += 1
            reasons.append(f"Max DD {float(max_dd):.1f}% >= {_MAX_DD_PAUSE_PCT}%")
        elif max_dd >= _MAX_DD_DEGRADE_PCT:
            yellow_flags += 1
            reasons.append(f"Max DD {float(max_dd):.1f}% >= {_MAX_DD_DEGRADE_PCT}%")

    if sharpe is not None and not insufficient_data:
        if sharpe <= _SHARPE_PAUSE:
            red_flags += 1
            reasons.append(f"Sharpe {float(sharpe):.2f} <= {_SHARPE_PAUSE}")
        elif sharpe <= _SHARPE_DEGRADE:
            yellow_flags += 1
            reasons.append(f"Sharpe {float(sharpe):.2f} <= {_SHARPE_DEGRADE}")

    if pf is not None and not insufficient_data:
        if pf <= _PF_PAUSE:
            red_flags += 1
            reasons.append(f"PF {float(pf):.2f} <= {_PF_PAUSE}")
        elif pf <= _PF_DEGRADE:
            yellow_flags += 1
            reasons.append(f"PF {float(pf):.2f} <= {_PF_DEGRADE}")

    if expectancy is not None and not insufficient_data:
        if expectancy <= _EXPECTANCY_PAUSE:
            red_flags += 1
            reasons.append(f"Expectancy {float(expectancy):.4f} <= {_EXPECTANCY_PAUSE}")
        elif expectancy <= _EXPECTANCY_DEGRADE:
            yellow_flags += 1
            reasons.append(f"Expectancy {float(expectancy):.4f} <= {_EXPECTANCY_DEGRADE}")

    if red_flags >= 4 or yellow_flags >= 6:
        state = "PAUSED"
        sizing = _SIZING_PAUSED
    elif yellow_flags >= 1 or red_flags >= 1:
        state = "DEGRADED"
        sizing = _SIZING_DEGRADED

    log = SymbolDeploymentGateLog(
        id=uuid.uuid4(),
        symbol=symbol,
        timeframe=timeframe,
        state=state,
        sizing_multiplier=sizing,
        sharpe_20=sharpe,
        profit_factor=pf,
        max_drawdown_pct=max_dd,
        expectancy=expectancy,
        trade_count=trade_count,
        reasons=reasons,
        extra_data={
            "red_flags": red_flags,
            "yellow_flags": yellow_flags,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return log


def evaluate_symbol_deployment_gate(
    db: Session, symbol: str, timeframe: str
) -> SymbolDeploymentGateLog:
    """Evaluate and persist per-symbol/TF deployment gate status."""
    log = _evaluate_symbol_gate_core(db, symbol, timeframe)
    db.add(log)
    db.commit()
    logger.info(
        f"[SYM GATE] {symbol}/{timeframe} → {log.state} "
        f"(Sharpe={log.sharpe_20}, PF={log.profit_factor}, "
        f"Trades={log.trade_count}, Reasons={log.reasons})"
    )
    return log


def evaluate_symbol_deployment_gate_regime_aware(
    db: Session, symbol: str, timeframe: str
) -> SymbolDeploymentGateLog:
    """Evaluate per-symbol/TF gate with regime-aware lookback.

    If the market regime has changed since the last evaluation,
    uses a shorter lookback (last 5 days) to reflect current conditions.
    If the short lookback is HEALTHY, overrides the long-term PAUSED state.
    """
    # Get latest log for regime comparison
    latest = db.execute(
        select(SymbolDeploymentGateLog)
        .where(
            SymbolDeploymentGateLog.symbol == symbol,
            SymbolDeploymentGateLog.timeframe == timeframe,
        )
        .order_by(desc(SymbolDeploymentGateLog.created_at))
        .limit(1)
    ).scalar_one_or_none()

    # Detect current regime from ai_latest_scans
    current_regime = None
    try:
        from app.models.ai_scan import AILatestScan
        scan = db.execute(
            select(AILatestScan)
            .where(AILatestScan.symbol == symbol, AILatestScan.timeframe == timeframe)
            .order_by(desc(AILatestScan.scanned_at))
            .limit(1)
        ).scalar_one_or_none()
        if scan and scan.context:
            current_regime = scan.context.get("regime")
    except Exception:
        pass

    previous_regime = None
    if latest and latest.extra_data:
        previous_regime = latest.extra_data.get("regime")

    regime_changed = bool(
        current_regime and previous_regime and current_regime != previous_regime
    )

    if regime_changed and latest and latest.state == "PAUSED":
        # Reevaluate with SHORT lookback (5 days) for current regime
        log_short = _evaluate_symbol_gate_core(db, symbol, timeframe, lookback_days=5)
        if log_short.state == "HEALTHY":
            log_short.reasons.append(
                f"Regime changed ({previous_regime} → {current_regime}), "
                f"short lookback HEALTHY — auto-reset"
            )
            db.add(log_short)
            db.commit()
            logger.info(
                f"[SYM GATE REGIME] {symbol}/{timeframe} → HEALTHY "
                f"(regime {previous_regime} → {current_regime}, short lookback)"
            )
            return log_short

    # Standard evaluation
    log = _evaluate_symbol_gate_core(db, symbol, timeframe)
    # Store regime for next comparison
    if current_regime:
        extra = dict(log.extra_data or {})
        extra["regime"] = current_regime
        log.extra_data = extra
    db.add(log)
    db.commit()
    logger.info(
        f"[SYM GATE] {symbol}/{timeframe} → {log.state} "
        f"(Sharpe={log.sharpe_20}, PF={log.profit_factor}, "
        f"Trades={log.trade_count}, Reasons={log.reasons})"
    )
    return log


def _proactively_manage_bots(db: Session, gate_state: str) -> dict:
    """DEPRECATED: Global gate no longer blocks bots.
    
    The global deployment gate is kept for monitoring/logging only.
    Only per-symbol/TF gates control execution. This function now
    only logs advisory messages and cleans up legacy block flags.
    """
    # Clean up any legacy global gate blocks (should be rare/none)
    bots = db.execute(
        select(BotConfig).where(
            BotConfig.ai_signal_mode == True,
            BotConfig.status == "active",
            BotConfig.paper_balance_id.is_(None),
            BotConfig.ai_signal_config["execution_blocked_reason"].astext == "deployment_gate",
        )
    ).scalars().all()

    unblocked = 0
    for bot in bots:
        cfg = bot.ai_signal_config or {}
        autonomy = cfg.get("autonomy_state", {})
        if clear_pause(autonomy, "deployment_gate"):
            cfg.pop("execution_blocked", None)
            cfg.pop("execution_blocked_reason", None)
            cfg["autonomy_state"] = autonomy
            bot.ai_signal_config = cfg
            unblocked += 1
            logger.info(
                f"[DEPLOYMENT_GATE] Cleared legacy global block for {bot.bot_name}"
            )

    if unblocked:
        db.commit()

    if gate_state == "PAUSED":
        logger.warning(
            f"[DEPLOYMENT_GATE] Global gate is PAUSED (advisory only) — "
            f"per-symbol gates now control execution"
        )
    elif gate_state == "DEGRADED":
        logger.info(
            f"[DEPLOYMENT_GATE] Global gate is DEGRADED (advisory only)"
        )

    return {"blocked_bots": 0, "unblocked_bots": unblocked}


def _proactively_manage_symbol_gates(db: Session) -> dict:
    """Block/unblock bots based on per-symbol/TF gate states.

    A bot can be blocked by EITHER the global gate OR its symbol gate.
    Both must be HEALTHY for execution.
    """
    blocked = 0
    unblocked = 0

    # Find latest state per (symbol, timeframe)
    from sqlalchemy import func

    subq = (
        db.query(
            SymbolDeploymentGateLog.symbol,
            SymbolDeploymentGateLog.timeframe,
            func.max(SymbolDeploymentGateLog.created_at).label("max_created"),
        )
        .group_by(SymbolDeploymentGateLog.symbol, SymbolDeploymentGateLog.timeframe)
        .subquery()
    )

    latest_rows = (
        db.query(SymbolDeploymentGateLog)
        .join(
            subq,
            (
                SymbolDeploymentGateLog.symbol == subq.c.symbol
                and SymbolDeploymentGateLog.timeframe == subq.c.timeframe
                and SymbolDeploymentGateLog.created_at == subq.c.max_created
            ),
        )
        .all()
    )

    for row in latest_rows:
        bots = (
            db.query(BotConfig)
            .filter(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
                BotConfig.paper_balance_id.is_(None),
                BotConfig.symbol == row.symbol,
                BotConfig.timeframe == row.timeframe,
            )
            .all()
        )
        for bot in bots:
            cfg = bot.ai_signal_config or {}
            autonomy = cfg.get("autonomy_state", {})
            global_blocks = cfg.get("execution_blocked_reason") == "deployment_gate"

            if row.state == "PAUSED":
                if mark_paused(autonomy, "symbol_deployment_gate"):
                    cfg["execution_blocked"] = True
                    cfg["execution_blocked_reason"] = "symbol_deployment_gate"
                    cfg["autonomy_state"] = autonomy
                    bot.ai_signal_config = cfg
                    blocked += 1
                    logger.warning(
                        f"[SYM GATE] Auto-blocked bot {bot.bot_name} — "
                        f"{row.symbol}/{row.timeframe} gate PAUSED"
                    )
            elif row.state == "HEALTHY":
                if clear_pause(autonomy, "symbol_deployment_gate"):
                    # Only clear block if global gate also doesn't block
                    if not global_blocks:
                        cfg.pop("execution_blocked", None)
                        cfg.pop("execution_blocked_reason", None)
                    cfg["autonomy_state"] = autonomy
                    bot.ai_signal_config = cfg
                    unblocked += 1
                    logger.info(
                        f"[SYM GATE] Auto-unblocked bot {bot.bot_name} — "
                        f"{row.symbol}/{row.timeframe} gate HEALTHY"
                    )

    if blocked or unblocked:
        db.commit()

    return {"blocked_bots": blocked, "unblocked_bots": unblocked}


def get_symbol_gate_status(db: Session, symbol: str, timeframe: str) -> dict:
    """Returns latest per-symbol deployment gate status."""
    row = (
        db.query(SymbolDeploymentGateLog)
        .filter(
            SymbolDeploymentGateLog.symbol == symbol,
            SymbolDeploymentGateLog.timeframe == timeframe,
        )
        .order_by(desc(SymbolDeploymentGateLog.created_at))
        .first()
    )

    if not row:
        return {
            "state": "HEALTHY",
            "sizing_multiplier": 1.0,
            "reasons": [],
            "metrics": {},
        }

    return {
        "state": row.state,
        "sizing_multiplier": float(row.sizing_multiplier),
        "reasons": row.reasons or [],
        "metrics": {
            "sharpe_20": float(row.sharpe_20) if row.sharpe_20 else None,
            "profit_factor": float(row.profit_factor) if row.profit_factor else None,
            "max_drawdown_pct": float(row.max_drawdown_pct) if row.max_drawdown_pct else None,
            "expectancy": float(row.expectancy) if row.expectancy else None,
            "trade_count": row.trade_count,
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def get_latest_gate_status(db: Session) -> dict:
    """Returns latest deployment gate status."""
    row = db.execute(
        select(DeploymentGateLog).order_by(desc(DeploymentGateLog.created_at)).limit(1)
    ).scalars().first()

    if not row:
        return {"state": "HEALTHY", "sizing_multiplier": 1.0, "reasons": [], "metrics": {}}

    return {
        "state": row.state,
        "sizing_multiplier": float(row.sizing_multiplier),
        "reasons": row.reasons or [],
        "metrics": {
            "sharpe_20": float(row.sharpe_20) if row.sharpe_20 else None,
            "profit_factor": float(row.profit_factor) if row.profit_factor else None,
            "max_drawdown_pct": float(row.max_drawdown_pct) if row.max_drawdown_pct else None,
            "drift_psi_max": float(row.drift_psi_max) if row.drift_psi_max else None,
            "wf_passed": row.wf_passed,
            "confidence_decay_divergence": float(row.confidence_decay_divergence) if row.confidence_decay_divergence else None,
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
