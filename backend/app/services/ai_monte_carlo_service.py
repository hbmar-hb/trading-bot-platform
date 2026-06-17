"""
Servicio de integración IA + Monte Carlo.
Evalúa un símbolo+timeframe con el motor de IA y una estrategia de backtesting,
computa un joint score y opcionalmente recalibra parámetros.
"""
from __future__ import annotations

import asyncio
import copy
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_scan import AIWatchlistItem, AILatestScan
from app.models.montecarlo import MonteCarloStrategy
from app.services.ai_scanner import build_signal, fetch_ohlcv, htf_for
from app.engines.montecarlo_engine import MonteCarloEngine
from app.engines.montecarlo_backtest_engine import (
    fetch_ohlcv as fetch_ohlcv_backtest,
    execute_strategy_code,
    run_backtest,
)
from app.core.constants import validate_timeframe


# ═══════════════════════════════════════════════════════════════
# EVALUACIÓN IA
# ═══════════════════════════════════════════════════════════════

async def evaluate_ai_signal(symbol: str, timeframe: str) -> Optional[dict]:
    """
    Obtiene la señal de IA para un símbolo+timeframe sin persistir en DB.
    Retorna el dict de la señal o None si no hay señal.
    """
    try:
        timeframe = validate_timeframe(timeframe)
    except ValueError:
        return None

    htf = htf_for(timeframe)
    coros = [fetch_ohlcv(symbol, timeframe)]
    if htf:
        coros.append(fetch_ohlcv(symbol, htf))

    results = await asyncio.gather(*coros)
    sym, ohlcv = results[0]
    htf_ohlcv = results[1][1] if htf else None

    if not ohlcv or len(ohlcv) < 50:
        return None

    result_dict, sig = build_signal(symbol, timeframe, ohlcv, htf_ohlcv=htf_ohlcv)

    if sig is None:
        # No hay señal pero sí contexto
        return {
            "status": "NO_SIGNAL",
            "context": result_dict.get("context", {}),
            "symbol": symbol,
            "timeframe": timeframe,
        }

    # Serializar señal sin persistir
    from app.services.ai_scanner import signal_to_dict
    return signal_to_dict(sig)


# ═══════════════════════════════════════════════════════════════
# EVALUACIÓN BACKTEST
# ═══════════════════════════════════════════════════════════════

async def evaluate_strategy_backtest(
    symbol: str,
    timeframe: str,
    strategy: MonteCarloStrategy,
    lookback_days: int = 90,
    initial_capital: float = 10000.0,
    fee_rate: float = 0.0006,
    slippage_pct: float = 0.0,
) -> Optional[dict]:
    """
    Ejecuta backtest de una estrategia sobre un par+timeframe.
    Retorna dict con trades, metrics, equity_curve.
    """
    from_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    to_date = datetime.now(timezone.utc)

    try:
        df = await fetch_ohlcv_backtest(symbol, timeframe, from_date, to_date)
    except Exception as e:
        logger.warning(f"[AI-MC] Error fetching data for backtest: {e}")
        return None

    params = {}
    for k, v in (strategy.parameters or {}).items():
        params[k] = v.get("value", v.get("default")) if isinstance(v, dict) else v

    try:
        signals = execute_strategy_code(strategy.code, df, params)
    except Exception as e:
        logger.warning(f"[AI-MC] Strategy execution error: {e}")
        return {"error": str(e)}

    result = run_backtest(
        df, signals,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage_pct=slippage_pct,
    )

    trades_json = [
        {
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl_pct": t.pnl_pct,
            "pnl_abs": t.pnl_abs,
            "duration_bars": t.duration_bars,
            "max_drawdown_pct": t.max_drawdown_pct,
            "close_reason": t.close_reason,
        }
        for t in result.trades
    ]

    metrics = result.metrics
    return {
        "trades": trades_json,
        "metrics": {
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "win_rate": metrics.win_rate,
            "profit_factor": metrics.profit_factor,
            "total_return_pct": metrics.total_return_pct,
            "total_pnl_abs": metrics.total_pnl_abs,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "cagr": metrics.cagr,
            "expectancy": metrics.expectancy,
            "avg_trade_pct": metrics.avg_trade_pct,
            "best_trade_pct": metrics.best_trade_pct,
            "worst_trade_pct": metrics.worst_trade_pct,
            "avg_bars": metrics.avg_bars,
        },
        "equity_curve": result.equity_curve,
    }


# ═══════════════════════════════════════════════════════════════
# SIMULACIÓN MONTE CARLO
# ═══════════════════════════════════════════════════════════════

def evaluate_monte_carlo(trades: list, initial_capital: float = 10000.0) -> Optional[dict]:
    """Ejecuta simulación Monte Carlo sobre trades."""
    if len(trades) < 5:
        return None

    engine = MonteCarloEngine(initial_capital=initial_capital)
    engine.load_from_dicts(trades)

    result = engine.run_return_shuffle(n_simulations=5000)
    validation = engine.validate_strategy(result)

    return {
        "result": result.to_dict(),
        "validation": validation,
    }


# ═══════════════════════════════════════════════════════════════
# JOINT SCORE
# ═══════════════════════════════════════════════════════════════

def compute_ai_score(signal: dict) -> float:
    """Calcula AI Health Score 0-100."""
    if signal.get("status") == "NO_SIGNAL":
        return 0.0

    tier = signal.get("quality_tier", "WEAK")
    status = signal.get("anti_fake_status", "BLOCK")
    prob = signal.get("success_probability")
    features = signal.get("features", {})
    backtest_wr = features.get("backtest_wr_30d", 0.5)

    tier_score = {"STRONG": 100, "MODERATE": 60, "WEAK": 20}.get(tier, 0)
    status_score = {"CLEAR": 100, "CAUTION": 50, "BLOCK": 0}.get(status, 0)

    if prob is not None:
        prob_score = 100 if prob > 0.6 else (50 if prob > 0.45 else 0)
    else:
        prob_score = 50  # Modelo no listo, neutral

    wr_score = 100 if backtest_wr > 0.5 else (50 if backtest_wr > 0.4 else 0)

    return (tier_score + status_score + prob_score + wr_score) / 4.0


def compute_recommendation(joint_score: float) -> str:
    if joint_score >= 75:
        return "✅ OPERAR"
    elif joint_score >= 50:
        return "⚠️ OPERAR CON CAUTELA"
    else:
        return "❌ NO OPERAR"


# ═══════════════════════════════════════════════════════════════
# RECALIBRACIÓN AUTOMÁTICA
# ═══════════════════════════════════════════════════════════════

def _generate_param_combinations(params: dict, max_combos: int = 20) -> List[dict]:
    """
    Genera combinaciones de parámetros para grid search.
    Solo varía parámetros numéricos (int/float).
    """
    numeric_params = {}
    fixed_params = {}

    for k, v in params.items():
        if isinstance(v, dict):
            ptype = v.get("type", "float")
            default = v.get("default")
            if ptype in ("int", "float") and default is not None:
                numeric_params[k] = v
            else:
                fixed_params[k] = v.get("value", v.get("default"))
        elif isinstance(v, (int, float)):
            numeric_params[k] = {"type": "int" if isinstance(v, int) else "float", "default": v}
        else:
            fixed_params[k] = v

    if not numeric_params:
        return [fixed_params]

    # Generar variaciones: 0.5x, 0.75x, 1.0x, 1.25x, 1.5x del default
    variations = {}
    for k, meta in numeric_params.items():
        default = meta["default"]
        ptype = meta.get("type", "float")
        mults = [0.5, 0.75, 1.0, 1.25, 1.5]
        vals = []
        for m in mults:
            v = default * m
            if ptype == "int":
                v = max(1, int(round(v)))
            vals.append(v)
        # Eliminar duplicados
        seen = set()
        unique_vals = []
        for v in vals:
            key = round(v, 4)
            if key not in seen:
                seen.add(key)
                unique_vals.append(v)
        variations[k] = unique_vals

    # Generar combinaciones y limitar
    keys = list(variations.keys())
    vals_lists = [variations[k] for k in keys]
    combos = []
    for combo_vals in itertools.product(*vals_lists):
        combo = dict(fixed_params)
        for k, v in zip(keys, combo_vals):
            combo[k] = v
        combos.append(combo)
        if len(combos) >= max_combos:
            break

    return combos


async def recalibrate_strategy(
    symbol: str,
    timeframe: str,
    strategy: MonteCarloStrategy,
    lookback_days: int = 90,
    target_score: float = 60.0,
) -> Optional[dict]:
    """
    Grid search automático sobre parámetros de la estrategia.
    Solo retorna la recalibración si MEJORA respecto al baseline (parámetros originales).
    """
    from_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    to_date = datetime.now(timezone.utc)

    try:
        df = await fetch_ohlcv_backtest(symbol, timeframe, from_date, to_date)
    except Exception as e:
        logger.warning(f"[AI-MC] Recalibration fetch error: {e}")
        return None

    # ── Baseline: parámetros originales ──────────────────────────────────────
    baseline_params = {}
    for k, v in (strategy.parameters or {}).items():
        baseline_params[k] = v.get("value", v.get("default")) if isinstance(v, dict) else v

    baseline_result = None
    baseline_fitness = -1.0
    try:
        signals = execute_strategy_code(strategy.code, df, baseline_params)
        baseline_result = run_backtest(df, signals, initial_capital=10000.0, fee_rate=0.0006, slippage_pct=0.0)
        m = baseline_result.metrics
        baseline_fitness = max(0, m.sharpe_ratio) * max(0, m.win_rate) * max(0.01, 1 + m.max_drawdown_pct)
        logger.info(f"[AI-MC] Baseline fitness for {symbol} {timeframe}: {baseline_fitness:.4f}")
    except Exception as e:
        logger.warning(f"[AI-MC] Baseline evaluation failed: {e}")
        return None

    # ── Grid search ──────────────────────────────────────────────────────────
    combinations = _generate_param_combinations(strategy.parameters or {}, max_combos=20)
    logger.info(f"[AI-MC] Recalibrating {len(combinations)} combinations for {symbol} {timeframe}")

    best_result = None
    best_score = -1.0
    best_params = None
    results = []

    for params in combinations:
        try:
            signals = execute_strategy_code(strategy.code, df, params)
            result = run_backtest(df, signals, initial_capital=10000.0, fee_rate=0.0006, slippage_pct=0.0)

            m = result.metrics
            # Fitness: Sharpe * WinRate * (1 - |MaxDD|)
            fitness = max(0, m.sharpe_ratio) * max(0, m.win_rate) * max(0.01, 1 + m.max_drawdown_pct)

            results.append({
                "params": params,
                "metrics": {
                    "total_trades": m.total_trades,
                    "win_rate": m.win_rate,
                    "sharpe_ratio": m.sharpe_ratio,
                    "max_drawdown_pct": m.max_drawdown_pct,
                    "cagr": m.cagr,
                },
                "fitness": round(fitness, 4),
            })

            if fitness > best_score:
                best_score = fitness
                best_result = result
                best_params = params
        except Exception as e:
            logger.debug(f"[AI-MC] Recalibration combo failed: {e}")
            continue

    if best_result is None:
        return None

    # ── Solo aplicar si mejora respecto al baseline ──────────────────────────
    if best_score <= baseline_fitness:
        logger.info(
            f"[AI-MC] Recalibration REJECTED for {symbol} {timeframe}: "
            f"best={best_score:.4f} <= baseline={baseline_fitness:.4f}"
        )
        return {
            "best_params": baseline_params,
            "baseline_params": baseline_params,
            "all_results": results,
            "metrics": {
                "total_trades": baseline_result.metrics.total_trades,
                "winning_trades": baseline_result.metrics.winning_trades,
                "losing_trades": baseline_result.metrics.losing_trades,
                "win_rate": baseline_result.metrics.win_rate,
                "profit_factor": baseline_result.metrics.profit_factor,
                "total_return_pct": baseline_result.metrics.total_return_pct,
                "sharpe_ratio": baseline_result.metrics.sharpe_ratio,
                "max_drawdown_pct": baseline_result.metrics.max_drawdown_pct,
                "cagr": baseline_result.metrics.cagr,
                "expectancy": baseline_result.metrics.expectancy,
            },
            "equity_curve": baseline_result.equity_curve,
            "monte_carlo": evaluate_monte_carlo([
                {
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl_pct": t.pnl_pct,
                    "pnl_abs": t.pnl_abs,
                    "duration_bars": t.duration_bars,
                    "max_drawdown_pct": t.max_drawdown_pct,
                    "close_reason": t.close_reason,
                }
                for t in baseline_result.trades
            ]),
            "improved": False,
            "baseline_fitness": round(baseline_fitness, 4),
            "best_fitness": round(best_score, 4),
        }

    logger.info(
        f"[AI-MC] Recalibration ACCEPTED for {symbol} {timeframe}: "
        f"best={best_score:.4f} > baseline={baseline_fitness:.4f}"
    )

    # Ejecutar Monte Carlo con la mejor combinación
    trades_json = [
        {
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl_pct": t.pnl_pct,
            "pnl_abs": t.pnl_abs,
            "duration_bars": t.duration_bars,
            "max_drawdown_pct": t.max_drawdown_pct,
            "close_reason": t.close_reason,
        }
        for t in best_result.trades
    ]

    mc = evaluate_monte_carlo(trades_json)

    return {
        "best_params": best_params,
        "baseline_params": baseline_params,
        "all_results": results,
        "metrics": {
            "total_trades": best_result.metrics.total_trades,
            "winning_trades": best_result.metrics.winning_trades,
            "losing_trades": best_result.metrics.losing_trades,
            "win_rate": best_result.metrics.win_rate,
            "profit_factor": best_result.metrics.profit_factor,
            "total_return_pct": best_result.metrics.total_return_pct,
            "sharpe_ratio": best_result.metrics.sharpe_ratio,
            "max_drawdown_pct": best_result.metrics.max_drawdown_pct,
            "cagr": best_result.metrics.cagr,
            "expectancy": best_result.metrics.expectancy,
        },
        "equity_curve": best_result.equity_curve,
        "monte_carlo": mc,
        "improved": True,
        "baseline_fitness": round(baseline_fitness, 4),
        "best_fitness": round(best_score, 4),
    }


# ═══════════════════════════════════════════════════════════════
# EVALUACIÓN COMPLETA
# ═══════════════════════════════════════════════════════════════

async def evaluate_symbol_strategy(
    symbol: str,
    timeframe: str,
    strategy_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    lookback_days: int = 90,
    recalibrate: bool = False,
) -> dict:
    """
    Orquesta la evaluación completa: IA + Backtest + Monte Carlo.
    """
    # 1. Obtener estrategia
    from app.models.montecarlo import MonteCarloStrategy
    result = await db.execute(
        select(MonteCarloStrategy)
        .where(MonteCarloStrategy.id == strategy_id, MonteCarloStrategy.user_id == user_id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return {"error": "Estrategia no encontrada"}

    # 2. Obtener señal IA
    ai_signal = await evaluate_ai_signal(symbol, timeframe)
    ai_score = compute_ai_score(ai_signal) if ai_signal else 0.0

    # 3. Backtest
    backtest = await evaluate_strategy_backtest(
        symbol, timeframe, strategy, lookback_days=lookback_days
    )

    # 4. Monte Carlo
    mc_data = None
    if backtest and backtest.get("trades") and len(backtest["trades"]) >= 5:
        mc_data = evaluate_monte_carlo(backtest["trades"])

    mc_score = mc_data["validation"]["score"] if mc_data and mc_data.get("validation") else 0.0

    # 5. Joint Score
    joint_score = (ai_score * 0.5) + (mc_score * 0.5)
    recommendation = compute_recommendation(joint_score)

    # 6. Recalibración (solo si mejora respecto al baseline)
    recalibration = None
    if recalibrate and joint_score < 60:
        recalibration = await recalibrate_strategy(
            symbol, timeframe, strategy, lookback_days=lookback_days
        )
        if recalibration:
            # Recompute joint score with recalibrated results
            rec_mc = recalibration.get("monte_carlo")
            rec_mc_score = rec_mc["validation"]["score"] if rec_mc and rec_mc.get("validation") else 0.0
            rec_joint = (ai_score * 0.5) + (rec_mc_score * 0.5)
            recalibration["joint_score_after"] = round(rec_joint, 1)
            recalibration["recommendation_after"] = compute_recommendation(rec_joint)
            recalibration["original_joint_score"] = round(joint_score, 1)

            # Solo mostrar como mejora si realmente mejora
            if not recalibration.get("improved", True):
                recalibration["recommendation_after"] = (
                    f"{recalibration['recommendation_after']} (recalibración no mejoró — se mantiene baseline)"
                )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "ai_signal": ai_signal,
        "ai_score": round(ai_score, 1),
        "backtest": backtest,
        "monte_carlo": mc_data,
        "mc_score": round(mc_score, 1),
        "joint_score": round(joint_score, 1),
        "recommendation": recommendation,
        "recalibration": recalibration,
    }


# ═══════════════════════════════════════════════════════════════
# SCAN DEL WATCHLIST
# ═══════════════════════════════════════════════════════════════

async def scan_watchlist(
    strategy_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    lookback_days: int = 90,
) -> List[dict]:
    """
    Evalúa todos los pares del watchlist del usuario.
    """
    # Obtener watchlist
    result = await db.execute(
        select(AIWatchlistItem)
        .where(AIWatchlistItem.user_id == user_id)
        .order_by(AIWatchlistItem.symbol)
    )
    items = result.scalars().all()

    if not items:
        return []

    # Obtener latest scans para mostrar info previa
    symbols = [i.symbol for i in items]
    scan_result = await db.execute(
        select(AILatestScan)
        .where(AILatestScan.symbol.in_(symbols))
    )
    scans = {s.symbol: s for s in scan_result.scalars().all()}

    evaluations = []
    for item in items:
        symbol = item.symbol
        timeframe = item.timeframe or "1h"

        # Obtener señal IA rápido (sin backtest pesado)
        ai_signal = await evaluate_ai_signal(symbol, timeframe)
        ai_score = compute_ai_score(ai_signal) if ai_signal else 0.0

        latest = scans.get(symbol)
        latest_data = None
        if latest and latest.signal_data:
            latest_data = {
                "score": latest.signal_data.get("score"),
                "direction": latest.signal_data.get("direction"),
                "quality_tier": latest.signal_data.get("quality_tier"),
                "scanned_at": latest.scanned_at.isoformat() if latest.scanned_at else None,
            }

        evaluations.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "ai_score": round(ai_score, 1),
            "ai_signal": ai_signal,
            "latest_scan": latest_data,
            "recommendation": compute_recommendation(ai_score),
        })

    # Ordenar por ai_score descendente
    evaluations.sort(key=lambda x: x["ai_score"], reverse=True)
    return evaluations
