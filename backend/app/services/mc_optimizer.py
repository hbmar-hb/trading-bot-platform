"""
MC Optimizer — Optimiza los parámetros de una estrategia Monte Carlo
basándose en backtests recientes y trades reales del bot.

La IA "mejora" el setup ajustando parámetros como pivot_len, atr_mult,
entry_mode, sl_buffer, etc. y seleccionando la combinación que maximiza
una función de fitness combinada.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from loguru import logger

from app.engines.mc_setup_engine import MCSetupEngine, MCSetupContext
from app.engines.montecarlo_backtest_engine import (
    fetch_ohlcv,
    execute_strategy_code,
    run_backtest,
)
from app.models.bot_config import BotConfig
from app.models.montecarlo import MonteCarloStrategy
from app.services.database import SessionLocal


# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN DEL OPTIMIZADOR
# ═══════════════════════════════════════════════════════════════

# Parámetros que el optimizador puede ajustar y sus rangos
_OPTIMIZABLE_PARAMS = {
    "pivot_len": [3, 5, 7, 10],
    "atr_mult": [1.0, 1.5, 2.0, 2.5, 3.0],
    "atr_len": [10, 14, 20],
    "entry_mode": ["ob", "fvg", "ob_or_fvg"],
    "sl_buffer": [0.0, 0.01, 0.02, 0.03],
    "tp_multiplier": [1.5, 2.0, 2.5, 3.0],
}

# Máximo número de combinaciones a evaluar (para evitar explosión combinatoria)
_MAX_COMBINATIONS = 20


# ═══════════════════════════════════════════════════════════════
# OPTIMIZER
# ═══════════════════════════════════════════════════════════════

class MCOptimizer:
    """
    Optimizador de parámetros de estrategia Monte Carlo.
    """

    @classmethod
    def optimize(
        cls,
        bot: BotConfig,
        lookback_days: int = 14,
        n_sims: int = 500,
    ) -> dict:
        """
        Optimiza los parámetros de la estrategia MC asociada al bot.
        Retorna dict con: best_params, fitness, improvement, explanation.
        """
        mc_cfg = getattr(bot, "montecarlo_config", None) or {}
        strategy_id = mc_cfg.get("strategy_id")
        if not strategy_id:
            return {"error": "No strategy_id in montecarlo_config"}

        strategy_id = uuid.UUID(strategy_id)
        current_params = mc_cfg.get("optimized_params", {})

        # Cargar estrategia
        with SessionLocal() as db:
            strategy = db.get(MonteCarloStrategy, strategy_id)
            if not strategy:
                return {"error": f"Strategy {strategy_id} not found"}

        symbol = bot.symbol
        timeframe = bot.timeframe

        # Fetch datos
        import asyncio
        from datetime import timedelta
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=lookback_days)

        try:
            df = asyncio.run(fetch_ohlcv(symbol, timeframe, from_date, to_date))
        except Exception as exc:
            return {"error": f"Data fetch failed: {exc}"}

        if len(df) < 50:
            return {"error": f"Insufficient data: {len(df)} candles"}

        # Baseline: ejecutar con parámetros actuales
        try:
            baseline_result = cls._run_backtest_with_params(strategy.code, df, current_params)
            baseline_fitness = cls._compute_fitness(baseline_result)
        except Exception as exc:
            logger.warning(f"[MC OPTIMIZER] Baseline failed: {exc}")
            baseline_fitness = 0.0

        # Generar combinaciones de parámetros a probar
        param_grid = cls._build_param_grid(current_params, strategy.parameters or {})
        if not param_grid:
            return {
                "best_params": current_params,
                "fitness": baseline_fitness,
                "improvement": 0.0,
                "explanation": "No optimizable parameters found",
            }

        # Grid search
        best_params = current_params.copy()
        best_fitness = baseline_fitness
        results = []

        for combo in param_grid:
            try:
                result = cls._run_backtest_with_params(strategy.code, df, combo)
                fitness = cls._compute_fitness(result)
                results.append({"params": combo, "fitness": fitness, "metrics": result.metrics})

                if fitness > best_fitness:
                    best_fitness = fitness
                    best_params = combo.copy()
            except Exception as exc:
                logger.debug(f"[MC OPTIMIZER] Combo failed: {exc}")
                continue

        # Liberar memoria
        del df
        import gc
        gc.collect()

        improvement = ((best_fitness - baseline_fitness) / max(abs(baseline_fitness), 1e-10)) * 100

        # Generar explicación
        explanation = cls._build_explanation(
            current_params, best_params, baseline_fitness, best_fitness, improvement
        )

        return {
            "best_params": best_params,
            "baseline_params": current_params,
            "fitness": round(best_fitness, 4),
            "baseline_fitness": round(baseline_fitness, 4),
            "improvement_pct": round(improvement, 2),
            "explanation": explanation,
            "n_combinations_tested": len(results),
        }

    @classmethod
    def apply_optimization(cls, bot: BotConfig, result: dict) -> None:
        """Aplica los parámetros optimizados al bot y invalida el cache."""
        if "error" in result:
            logger.warning(f"[MC OPTIMIZER] Cannot apply: {result['error']}")
            return

        mc_cfg = getattr(bot, "montecarlo_config", None) or {}
        old_params = mc_cfg.get("optimized_params", {})
        new_params = result.get("best_params", {})

        if new_params == old_params:
            logger.info(f"[MC OPTIMIZER] No improvement for bot {bot.bot_name}, skipping apply")
            return

        # Guardar historial
        history = mc_cfg.get("optimization_history", [])
        history.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "old_params": old_params,
            "new_params": new_params,
            "improvement_pct": result.get("improvement_pct", 0),
            "fitness": result.get("fitness"),
        })
        mc_cfg["optimization_history"] = history[-20:]  # últimos 20

        # Aplicar nuevos parámetros
        mc_cfg["optimized_params"] = new_params
        mc_cfg["last_optimized_at"] = datetime.now(timezone.utc).isoformat()
        bot.montecarlo_config = mc_cfg

        # Invalidar cache para forzar recálculo con nuevos parámetros
        from app.engines.mc_setup_engine import MCSetupEngine
        MCSetupEngine.invalidate_cache(bot)

        logger.info(
            f"[MC OPTIMIZER] Applied optimization to bot {bot.bot_name}: "
            f"improvement={result.get('improvement_pct', 0):.1f}%, "
            f"params changed={set(new_params.keys()) != set(old_params.keys()) or any(new_params.get(k) != old_params.get(k) for k in new_params)}"
        )

    @staticmethod
    def _build_param_grid(
        current_params: dict,
        strategy_param_def: dict,
    ) -> List[dict]:
        """Construye grid de parámetros a probar basado en defaults + rangos."""
        grid = {}

        for param_name, param_def in strategy_param_def.items():
            if param_name not in _OPTIMIZABLE_PARAMS:
                continue

            param_type = param_def.get("type", "float")
            default_val = current_params.get(param_name)
            if default_val is None:
                default_val = param_def.get("default", param_def.get("value"))

            # Rangos predefinidos para parámetros conocidos
            if param_name in _OPTIMIZABLE_PARAMS:
                candidates = _OPTIMIZABLE_PARAMS[param_name]
            else:
                # Para parámetros numéricos, probar ±25% y ±50%
                if param_type in ("float", "int") and default_val is not None:
                    try:
                        base = float(default_val)
                        candidates = [
                            base * 0.5,
                            base * 0.75,
                            base,
                            base * 1.25,
                            base * 1.5,
                        ]
                        if param_type == "int":
                            candidates = list(set(int(round(c)) for c in candidates))
                    except (TypeError, ValueError):
                        continue
                else:
                    continue

            # Asegurar que el valor actual esté incluido
            if default_val is not None and default_val not in candidates:
                candidates = list(candidates) + [default_val]

            grid[param_name] = candidates

        if not grid:
            return []

        # Generar todas las combinaciones (limitado)
        keys = list(grid.keys())
        values = [grid[k] for k in keys]
        combinations = list(itertools.product(*values))

        if len(combinations) > _MAX_COMBINATIONS:
            import random
            random.seed(42)
            combinations = random.sample(combinations, _MAX_COMBINATIONS)

        return [
            {**current_params, **dict(zip(keys, combo))}
            for combo in combinations
        ]

    @staticmethod
    def _run_backtest_with_params(code: str, df, params: dict):
        """Ejecuta backtest con una combinación de parámetros."""
        signals = execute_strategy_code(code, df, params)
        return run_backtest(df, signals)

    @staticmethod
    def _compute_fitness(backtest_result) -> float:
        """
        Fitness function para seleccionar mejores parámetros.
        Combina: sharpe * win_rate * (1 - |max_dd|) * profit_factor
        """
        m = backtest_result.metrics
        if m.total_trades < 3:
            return 0.0

        sharpe = max(0, m.sharpe_ratio)
        wr = m.win_rate
        dd_component = max(0, 1 - abs(m.max_drawdown_pct))
        pf = m.profit_factor or 1.0

        # Penalizar drawdowns severos fuertemente
        if m.max_drawdown_pct < -0.30:
            dd_component *= 0.5
        if m.max_drawdown_pct < -0.50:
            dd_component *= 0.25

        return sharpe * wr * dd_component * pf

    @staticmethod
    def _build_explanation(
        old_params: dict,
        new_params: dict,
        baseline_fitness: float,
        best_fitness: float,
        improvement: float,
    ) -> str:
        """Genera explicación legible de los cambios."""
        changes = []
        for k in set(old_params.keys()) | set(new_params.keys()):
            old = old_params.get(k)
            new = new_params.get(k)
            if old != new:
                changes.append(f"{k}: {old} → {new}")

        if not changes:
            return "Sin cambios — los parámetros actuales son óptimos"

        change_str = "; ".join(changes)
        return (
            f"Fitness: {baseline_fitness:.3f} → {best_fitness:.3f} "
            f"(+{improvement:.1f}%). Cambios: {change_str}"
        )
