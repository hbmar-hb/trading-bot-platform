"""
MC Setup Engine — Convierte una estrategia Monte Carlo validada en un
'setup base' operativo que la IA usa para mejorar sus señales.

Flujo:
1. Carga estrategia MC desde DB
2. Ejecuta backtest histórico (90 días por defecto)
3. Ejecuta simulación Monte Carlo sobre los trades del backtest
4. Extrae 'setup context' con métricas clave para la IA
5. Guarda en caché (bot.montecarlo_config["setup_cache"])
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from loguru import logger

from app.engines.montecarlo_backtest_engine import (
    fetch_ohlcv,
    execute_strategy_code,
    run_backtest,
    BacktestResult,
    _to_ccxt_symbol,
)
from app.engines.montecarlo_engine import MonteCarloEngine, MonteCarloResult
from app.models.montecarlo import MonteCarloStrategy
from app.services.database import SessionLocal


# ═══════════════════════════════════════════════════════════════
# DATACLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class MCSetupContext:
    """Contexto de setup extraído de backtest + Monte Carlo."""

    direction_bias: str = "neutral"          # 'long' | 'short' | 'neutral'
    direction_confidence: float = 0.0        # 0-1
    win_rate_long: float = 0.0
    win_rate_short: float = 0.0
    win_rate_overall: float = 0.0

    # Rangos históricos de SL/TP como % desde el entry
    sl_range: dict = field(default_factory=lambda: {"min_pct": 0.0, "max_pct": 0.0, "median_pct": 0.0})
    tp_range: dict = field(default_factory=lambda: {"min_pct": 0.0, "max_pct": 0.0, "median_pct": 0.0})

    best_entry_mode: str = "mixed"           # 'ob' | 'fvg' | 'mixed' | 'unknown'

    # Parámetros óptimos actuales (seteados por IA o por defecto)
    optimal_params: dict = field(default_factory=dict)

    # Métricas crudas del backtest
    raw_metrics: dict = field(default_factory=dict)

    # Resultado de validación MC
    mc_validation: dict = field(default_factory=dict)

    computed_at: str = ""
    confidence_tier: str = "low"             # 'high' | 'medium' | 'low'

    # Métricas adicionales útiles para la IA
    avg_trade_pct: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MCSetupContext":
        return cls(**data)


# ═══════════════════════════════════════════════════════════════
# ENGINE
# ═══════════════════════════════════════════════════════════════

class MCSetupEngine:
    """
    Orquestador que ejecuta backtest MC + simulación MC y extrae
    el contexto de setup para que la IA lo consuma.
    """

    # TTL del caché en segundos (6 horas)
    CACHE_TTL_SECONDS = 6 * 3600

    # Número de simulaciones MC (reducido para ahorrar memoria/CPU)
    DEFAULT_N_SIMS = 1000

    # Lookback de días para backtest (reducido)
    DEFAULT_LOOKBACK_DAYS = 30

    @classmethod
    async def run_async(
        cls,
        strategy_id: uuid.UUID | str,
        symbol: str,
        timeframe: str,
        params: dict | None = None,
        lookback_days: int = None,
        n_sims: int = None,
    ) -> MCSetupContext:
        """Async implementation of the MC setup pipeline."""
        lookback_days = lookback_days or cls.DEFAULT_LOOKBACK_DAYS
        n_sims = n_sims or cls.DEFAULT_N_SIMS
        logger.info(
            f"[MC SETUP] Running setup for strategy={strategy_id}, "
            f"symbol={symbol}, timeframe={timeframe}, lookback={lookback_days}d"
        )

        # 1. Cargar estrategia desde DB
        with SessionLocal() as db:
            strategy = db.get(MonteCarloStrategy, strategy_id)
            if not strategy:
                logger.error(f"[MC SETUP] Strategy {strategy_id} not found")
                return MCSetupContext(
                    computed_at=datetime.now(timezone.utc).isoformat(),
                    mc_validation={"passed": False, "score": 0, "failures": ["strategy_not_found"]},
                )

        # 2. Parámetros
        effective_params = params or {}
        if not effective_params and strategy.parameters:
            effective_params = {
                k: v.get("default", v.get("value", 0))
                for k, v in strategy.parameters.items()
            }

        # 3. Fetch OHLCV (async)
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=lookback_days)

        try:
            df = await fetch_ohlcv(symbol, timeframe, from_date, to_date)
        except Exception as exc:
            logger.error(f"[MC SETUP] fetch_ohlcv failed: {exc}")
            return MCSetupContext(
                computed_at=datetime.now(timezone.utc).isoformat(),
                mc_validation={"passed": False, "score": 0, "failures": [f"data_fetch_error: {exc}"]},
            )

        if len(df) < 50:
            logger.warning(f"[MC SETUP] Insufficient data: {len(df)} candles")
            return MCSetupContext(
                computed_at=datetime.now(timezone.utc).isoformat(),
                mc_validation={"passed": False, "score": 0, "failures": ["insufficient_data"]},
            )

        # 4. Ejecutar estrategia en sandbox
        try:
            signals = execute_strategy_code(strategy.code, df, effective_params)
        except Exception as exc:
            logger.error(f"[MC SETUP] Strategy execution failed: {exc}")
            return MCSetupContext(
                computed_at=datetime.now(timezone.utc).isoformat(),
                mc_validation={"passed": False, "score": 0, "failures": [f"strategy_error: {exc}"]},
            )

        # 5. Backtest
        try:
            backtest_result = run_backtest(df, signals)
        except Exception as exc:
            logger.error(f"[MC SETUP] Backtest failed: {exc}")
            return MCSetupContext(
                computed_at=datetime.now(timezone.utc).isoformat(),
                mc_validation={"passed": False, "score": 0, "failures": [f"backtest_error: {exc}"]},
            )

        # Liberar DataFrame grande apenas no se necesita
        del df, signals
        import gc
        gc.collect()

        # 6. Simulación Monte Carlo
        mc_engine = MonteCarloEngine(initial_capital=10000.0)
        mc_engine.load_trades(backtest_result.trades)

        try:
            n_trades = len(backtest_result.trades)
            if n_trades < 15:
                mc_result = mc_engine.run_bootstrap(n_simulations=n_sims)
            else:
                mc_result = mc_engine.run_return_shuffle(n_simulations=n_sims)
        except Exception as exc:
            logger.error(f"[MC SETUP] MC simulation failed: {exc}")
            return MCSetupContext(
                computed_at=datetime.now(timezone.utc).isoformat(),
                mc_validation={"passed": False, "score": 0, "failures": [f"mc_error: {exc}"]},
            )

        validation = mc_engine.validate_strategy(mc_result)

        # 7. Extraer contexto
        context = cls._extract_context(
            backtest_result=backtest_result,
            mc_result=mc_result,
            validation=validation,
            optimal_params=effective_params,
        )

        # Liberar memoria del backtest
        del backtest_result, mc_result, mc_engine
        gc.collect()

        logger.info(
            f"[MC SETUP] Context extracted: bias={context.direction_bias}, "
            f"confidence={context.direction_confidence:.2f}, tier={context.confidence_tier}, "
            f"mc_score={context.mc_validation.get('score', 0)}, passed={context.mc_validation.get('passed')}"
        )

        return context

    @classmethod
    def run(
        cls,
        strategy_id: uuid.UUID | str,
        symbol: str,
        timeframe: str,
        params: dict | None = None,
        lookback_days: int = None,
        n_sims: int = None,
    ) -> MCSetupContext:
        """
        Synchronous wrapper around run_async().
        Safe to call from both sync and async contexts.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            # No event loop running — use asyncio.run directly
            return asyncio.run(
                cls.run_async(strategy_id, symbol, timeframe, params, lookback_days, n_sims)
            )
        else:
            # Already inside an event loop — offload to a new thread with its own loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    cls.run_async(strategy_id, symbol, timeframe, params, lookback_days, n_sims)
                )
                return future.result()

    @classmethod
    def _extract_context(
        cls,
        backtest_result: BacktestResult,
        mc_result: MonteCarloResult,
        validation: dict,
        optimal_params: dict,
    ) -> MCSetupContext:
        """Extrae métricas clave del backtest y MC en un contexto usable."""

        trades = backtest_result.trades
        metrics = backtest_result.metrics

        # Dirección predominante
        long_trades = [t for t in trades if t.direction == 1]
        short_trades = [t for t in trades if t.direction == -1]
        n_long = len(long_trades)
        n_short = len(short_trades)
        total = n_long + n_short

        if total == 0:
            return MCSetupContext(
                computed_at=datetime.now(timezone.utc).isoformat(),
                mc_validation=validation,
                optimal_params=optimal_params,
                confidence_tier="low",
            )

        win_rate_long = (
            sum(1 for t in long_trades if t.pnl_pct > 0) / n_long if n_long > 0 else 0.0
        )
        win_rate_short = (
            sum(1 for t in short_trades if t.pnl_pct > 0) / n_short if n_short > 0 else 0.0
        )

        # Bias direccional
        if n_long > n_short * 1.5:
            direction_bias = "long"
            direction_confidence = min(1.0, (n_long / total) ** 2)
        elif n_short > n_long * 1.5:
            direction_bias = "short"
            direction_confidence = min(1.0, (n_short / total) ** 2)
        else:
            direction_bias = "neutral"
            direction_confidence = 0.0

        # Rangos de SL/TP (estimados desde trades)
        sl_pcts = []
        tp_pcts = []
        for t in trades:
            if t.close_reason == "sl":
                sl_pct = abs(t.pnl_pct)
                sl_pcts.append(sl_pct)
            elif t.close_reason == "tp":
                tp_pct = abs(t.pnl_pct)
                tp_pcts.append(tp_pct)

        sl_range = {
            "min_pct": round(float(np.percentile(sl_pcts, 10)), 4) if sl_pcts else 0.01,
            "max_pct": round(float(np.percentile(sl_pcts, 90)), 4) if sl_pcts else 0.05,
            "median_pct": round(float(np.percentile(sl_pcts, 50)), 4) if sl_pcts else 0.025,
        }
        tp_range = {
            "min_pct": round(float(np.percentile(tp_pcts, 10)), 4) if tp_pcts else 0.01,
            "max_pct": round(float(np.percentile(tp_pcts, 90)), 4) if tp_pcts else 0.08,
            "median_pct": round(float(np.percentile(tp_pcts, 50)), 4) if tp_pcts else 0.04,
        }

        # Entry mode: inferir del código de la estrategia
        best_entry_mode = cls._infer_entry_mode(backtest_result)

        # Confidence tier basado en número de trades
        if total >= 30:
            confidence_tier = "high"
        elif total >= 10:
            confidence_tier = "medium"
        else:
            confidence_tier = "low"

        return MCSetupContext(
            direction_bias=direction_bias,
            direction_confidence=round(direction_confidence, 3),
            win_rate_long=round(win_rate_long, 3),
            win_rate_short=round(win_rate_short, 3),
            win_rate_overall=round(metrics.win_rate, 3),
            sl_range=sl_range,
            tp_range=tp_range,
            best_entry_mode=best_entry_mode,
            optimal_params=optimal_params,
            raw_metrics={
                "total_trades": metrics.total_trades,
                "winning_trades": metrics.winning_trades,
                "losing_trades": metrics.losing_trades,
                "profit_factor": round(metrics.profit_factor, 3) if metrics.profit_factor else None,
                "total_return_pct": round(metrics.total_return_pct, 3),
                "sharpe_ratio": round(metrics.sharpe_ratio, 3),
                "sortino_ratio": round(metrics.sortino_ratio, 3),
                "max_drawdown_pct": round(metrics.max_drawdown_pct, 3),
                "cagr": round(metrics.cagr, 3),
                "expectancy": round(metrics.expectancy, 3),
                "avg_trade_pct": round(metrics.avg_trade_pct, 3),
                "best_trade_pct": round(metrics.best_trade_pct, 3),
                "worst_trade_pct": round(metrics.worst_trade_pct, 3),
                "avg_bars": round(metrics.avg_bars, 1),
            },
            mc_validation=validation,
            computed_at=datetime.now(timezone.utc).isoformat(),
            confidence_tier=confidence_tier,
            avg_trade_pct=round(metrics.avg_trade_pct, 4),
            profit_factor=round(metrics.profit_factor, 3) if metrics.profit_factor else 0.0,
            sharpe_ratio=round(metrics.sharpe_ratio, 3),
            max_drawdown_pct=round(metrics.max_drawdown_pct, 3),
            total_trades=metrics.total_trades,
        )

    @staticmethod
    def _infer_entry_mode(backtest_result: BacktestResult) -> str:
        """Intenta inferir el modo de entrada predominante del backtest."""
        # Como el backtest no guarda qué tipo de setup generó cada señal,
        # usamos heurísticas: si la estrategia tiene OB/FVG en su nombre o parámetros
        # Esto es un placeholder; en una implementación avanzada se podría
        # analizar el código fuente de la estrategia
        return "mixed"

    # ═══════════════════════════════════════════════════════════════
    # CACHE helpers (operan sobre bot.montecarlo_config)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_cached(cls, bot) -> Optional[MCSetupContext]:
        """Carga contexto desde el cache del bot si no está stale."""
        mc_cfg = getattr(bot, "montecarlo_config", None) or {}
        setup_cache = mc_cfg.get("setup_cache")
        if not setup_cache:
            return None

        computed_at_str = setup_cache.get("computed_at")
        if not computed_at_str:
            return None

        try:
            computed_at = datetime.fromisoformat(computed_at_str)
            if computed_at.tzinfo is None:
                computed_at = computed_at.replace(tzinfo=timezone.utc)
        except Exception:
            return None

        age = (datetime.now(timezone.utc) - computed_at).total_seconds()
        if age > cls.CACHE_TTL_SECONDS:
            logger.debug(f"[MC SETUP] Cache stale ({age/3600:.1f}h), recalculation needed")
            return None

        context_dict = setup_cache.get("context")
        if not context_dict:
            return None

        try:
            return MCSetupContext.from_dict(context_dict)
        except Exception:
            return None

    @classmethod
    def set_cached(cls, bot, context: MCSetupContext) -> None:
        """Guarda contexto en el cache del bot."""
        mc_cfg = getattr(bot, "montecarlo_config", None) or {}
        mc_cfg["setup_cache"] = {
            "context": context.to_dict(),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        bot.montecarlo_config = mc_cfg

    @classmethod
    def invalidate_cache(cls, bot) -> None:
        """Invalida el cache para forzar recálculo."""
        mc_cfg = getattr(bot, "montecarlo_config", None) or {}
        if "setup_cache" in mc_cfg:
            del mc_cfg["setup_cache"]
            bot.montecarlo_config = mc_cfg
