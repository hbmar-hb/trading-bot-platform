"""
Módulo de validación Monte Carlo para estrategias de trading.
Integra con pipelines de señales XGBoost + ICT+SMC.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from enum import Enum
import json
from datetime import datetime


class SimulationType(Enum):
    RETURN_SHUFFLE = "return_shuffle"      # Baraja retornos por trade
    BOOTSTRAP = "bootstrap"                 # Muestreo con reemplazo
    PARAMETER_PERTURBATION = "param_perturb"  # Perturba parámetros de entrada
    EQUITY_PATH = "equity_path"             # Simula múltiples caminos de equity


@dataclass
class Trade:
    """Trade individual con métricas mínimas necesarias."""
    entry_time: datetime
    exit_time: datetime
    direction: int  # 1 = LONG, -1 = SHORT
    entry_price: float
    exit_price: float
    pnl_pct: float  # P&L como porcentaje del capital
    pnl_abs: float  # P&L absoluto
    duration_bars: int
    max_drawdown_pct: float  # MDD intra-trade

    @property
    def is_winner(self) -> bool:
        return self.pnl_pct > 0


@dataclass
class MonteCarloResult:
    """Resultado agregado de una simulación Monte Carlo."""
    simulation_type: SimulationType
    n_simulations: int
    original_sharpe: float
    original_max_dd: float
    original_cagr: float
    original_win_rate: float

    # Percentiles de las simulaciones
    sharpe_p5: float
    sharpe_p50: float
    sharpe_p95: float

    max_dd_p5: float      # Peor escenario razonable (5%)
    max_dd_p50: float
    max_dd_p95: float

    cagr_p5: float
    cagr_p50: float
    cagr_p95: float

    win_rate_p5: float
    win_rate_p50: float
    win_rate_p95: float

    # Probabilidades clave
    prob_profit: float           # % simulaciones con profit > 0
    prob_sharpe_above_1: float   # % simulaciones con Sharpe > 1
    prob_dd_below_20: float      # % simulaciones con MDD < 20%
    prob_ruin: float             # % simulaciones con drawdown > 50%

    # Equity curves de todas las simulaciones (para visualización)
    equity_curves: Optional[np.ndarray] = None

    def to_dict(self) -> Dict:
        return {
            "simulation_type": self.simulation_type.value,
            "n_simulations": self.n_simulations,
            "original_metrics": {
                "sharpe": round(float(self.original_sharpe), 3),
                "max_drawdown": round(float(self.original_max_dd), 3),
                "cagr": round(float(self.original_cagr), 3),
                "win_rate": round(float(self.original_win_rate), 3)
            },
            "percentiles": {
                "sharpe": {
                    "p5": round(float(self.sharpe_p5), 3),
                    "p50": round(float(self.sharpe_p50), 3),
                    "p95": round(float(self.sharpe_p95), 3)
                },
                "max_drawdown": {
                    "p5": round(float(self.max_dd_p5), 3),
                    "p50": round(float(self.max_dd_p50), 3),
                    "p95": round(float(self.max_dd_p95), 3)
                },
                "cagr": {
                    "p5": round(float(self.cagr_p5), 3),
                    "p50": round(float(self.cagr_p50), 3),
                    "p95": round(float(self.cagr_p95), 3)
                },
                "win_rate": {
                    "p5": round(float(self.win_rate_p5), 3),
                    "p50": round(float(self.win_rate_p50), 3),
                    "p95": round(float(self.win_rate_p95), 3)
                }
            },
            "probabilities": {
                "profit": round(float(self.prob_profit), 3),
                "sharpe_above_1": round(float(self.prob_sharpe_above_1), 3),
                "dd_below_20pct": round(float(self.prob_dd_below_20), 3),
                "ruin": round(float(self.prob_ruin), 3)
            }
        }


class MonteCarloEngine:
    """
    Motor de simulación Monte Carlo para validación de estrategias.
    """

    def __init__(self, initial_capital: float = 10000.0, risk_free_rate: float = 0.0):
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        self._trades: List[Trade] = []

    def load_trades(self, trades: List[Trade]) -> 'MonteCarloEngine':
        """Carga una lista de trades para analizar."""
        self._trades = trades
        return self

    def load_from_dataframe(self, df: pd.DataFrame) -> 'MonteCarloEngine':
        """
        Carga trades desde un DataFrame con columnas:
        entry_time, exit_time, direction, entry_price, exit_price,
        pnl_pct, pnl_abs, duration_bars, max_drawdown_pct
        """
        self._trades = [
            Trade(
                entry_time=row['entry_time'],
                exit_time=row['exit_time'],
                direction=row['direction'],
                entry_price=row['entry_price'],
                exit_price=row['exit_price'],
                pnl_pct=row['pnl_pct'],
                pnl_abs=row['pnl_abs'],
                duration_bars=row['duration_bars'],
                max_drawdown_pct=row['max_drawdown_pct']
            )
            for _, row in df.iterrows()
        ]
        return self

    def load_from_dicts(self, trades: List[dict]) -> 'MonteCarloEngine':
        """Carga trades desde lista de diccionarios (desde JSONB)."""
        self._trades = [
            Trade(
                entry_time=datetime.fromisoformat(t['entry_time']) if isinstance(t['entry_time'], str) else t['entry_time'],
                exit_time=datetime.fromisoformat(t['exit_time']) if isinstance(t['exit_time'], str) else t['exit_time'],
                direction=t.get('direction', 1),
                entry_price=t['entry_price'],
                exit_price=t['exit_price'],
                pnl_pct=t['pnl_pct'],
                pnl_abs=t.get('pnl_abs', 0.0),
                duration_bars=t.get('duration_bars', 0),
                max_drawdown_pct=t.get('max_drawdown_pct', 0.0)
            )
            for t in trades
        ]
        return self

    def _calculate_metrics(self, returns: np.ndarray, n_bars: int = 252) -> Tuple[float, float, float, float]:
        """
        Calcula métricas clave desde una serie de retornos por trade.
        Returns: (sharpe, max_dd, cagr, win_rate)
        """
        if len(returns) == 0:
            return 0.0, 0.0, 0.0, 0.0

        # Equity curve
        equity = self.initial_capital * np.cumprod(1 + returns)

        # Sharpe ratio (anualizado, asumiendo ~trades por año)
        mean_ret = np.mean(returns)
        std_ret = np.std(returns)
        sharpe = (mean_ret - self.risk_free_rate) / std_ret * np.sqrt(n_bars) if std_ret > 0 else 0.0

        # Max Drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        max_dd = np.min(drawdown)

        # CAGR
        total_return = equity[-1] / equity[0] - 1
        n_periods = len(returns)
        cagr = (1 + total_return) ** (n_bars / n_periods) - 1 if n_periods > 0 else 0.0

        # Win rate
        win_rate = np.sum(returns > 0) / len(returns)

        return float(sharpe), float(max_dd), float(cagr), float(win_rate)

    def run_return_shuffle(self, n_simulations: int = 10000,
                           save_equity_curves: bool = False) -> MonteCarloResult:
        """
        Simulación Tipo 1: Reordenación de retornos.
        Baraja aleatoriamente la secuencia de trades para ver si el
        rendimiento depende del orden específico.
        """
        if len(self._trades) < 5:
            raise ValueError("Se necesitan al menos 5 trades para Monte Carlo")

        original_returns = np.array([t.pnl_pct for t in self._trades])
        orig_sharpe, orig_max_dd, orig_cagr, orig_wr = self._calculate_metrics(original_returns)

        sharpe_sims = np.zeros(n_simulations)
        max_dd_sims = np.zeros(n_simulations)
        cagr_sims = np.zeros(n_simulations)
        wr_sims = np.zeros(n_simulations)
        profit_sims = np.zeros(n_simulations, dtype=bool)

        equity_curves = [] if save_equity_curves else None

        for i in range(n_simulations):
            shuffled = np.random.permutation(original_returns)

            sharpe_sims[i], max_dd_sims[i], cagr_sims[i], wr_sims[i] = \
                self._calculate_metrics(shuffled)

            profit_sims[i] = np.prod(1 + shuffled) > 1.0

            if save_equity_curves:
                eq = self.initial_capital * np.cumprod(1 + shuffled)
                equity_curves.append(eq.tolist())

        return MonteCarloResult(
            simulation_type=SimulationType.RETURN_SHUFFLE,
            n_simulations=n_simulations,
            original_sharpe=orig_sharpe,
            original_max_dd=orig_max_dd,
            original_cagr=orig_cagr,
            original_win_rate=orig_wr,

            sharpe_p5=float(np.percentile(sharpe_sims, 5)),
            sharpe_p50=float(np.percentile(sharpe_sims, 50)),
            sharpe_p95=float(np.percentile(sharpe_sims, 95)),

            max_dd_p5=float(np.percentile(max_dd_sims, 5)),
            max_dd_p50=float(np.percentile(max_dd_sims, 50)),
            max_dd_p95=float(np.percentile(max_dd_sims, 95)),

            cagr_p5=float(np.percentile(cagr_sims, 5)),
            cagr_p50=float(np.percentile(cagr_sims, 50)),
            cagr_p95=float(np.percentile(cagr_sims, 95)),

            win_rate_p5=float(np.percentile(wr_sims, 5)),
            win_rate_p50=float(np.percentile(wr_sims, 50)),
            win_rate_p95=float(np.percentile(wr_sims, 95)),

            prob_profit=float(np.mean(profit_sims)),
            prob_sharpe_above_1=float(np.mean(sharpe_sims > 1.0)),
            prob_dd_below_20=float(np.mean(max_dd_sims > -0.20)),
            prob_ruin=float(np.mean(max_dd_sims < -0.50)),

            equity_curves=np.array(equity_curves) if equity_curves else None
        )

    def run_bootstrap(self, n_simulations: int = 10000,
                      block_size: Optional[int] = None) -> MonteCarloResult:
        """
        Simulación Tipo 2: Bootstrap con bloques.
        Muestrea con reemplazo bloques de trades para preservar
        autocorrelación temporal.
        """
        original_returns = np.array([t.pnl_pct for t in self._trades])
        n_trades = len(original_returns)

        if block_size is None:
            block_size = max(3, int(np.sqrt(n_trades)))

        orig_sharpe, orig_max_dd, orig_cagr, orig_wr = self._calculate_metrics(original_returns)

        sharpe_sims = np.zeros(n_simulations)
        max_dd_sims = np.zeros(n_simulations)
        cagr_sims = np.zeros(n_simulations)
        wr_sims = np.zeros(n_simulations)
        profit_sims = np.zeros(n_simulations, dtype=bool)

        for i in range(n_simulations):
            n_blocks = int(np.ceil(n_trades / block_size))
            blocks = []
            for _ in range(n_blocks):
                start_idx = np.random.randint(0, n_trades - block_size + 1)
                blocks.append(original_returns[start_idx:start_idx + block_size])

            bootstrapped = np.concatenate(blocks)[:n_trades]

            sharpe_sims[i], max_dd_sims[i], cagr_sims[i], wr_sims[i] = \
                self._calculate_metrics(bootstrapped)
            profit_sims[i] = np.prod(1 + bootstrapped) > 1.0

        return MonteCarloResult(
            simulation_type=SimulationType.BOOTSTRAP,
            n_simulations=n_simulations,
            original_sharpe=orig_sharpe,
            original_max_dd=orig_max_dd,
            original_cagr=orig_cagr,
            original_win_rate=orig_wr,

            sharpe_p5=float(np.percentile(sharpe_sims, 5)),
            sharpe_p50=float(np.percentile(sharpe_sims, 50)),
            sharpe_p95=float(np.percentile(sharpe_sims, 95)),

            max_dd_p5=float(np.percentile(max_dd_sims, 5)),
            max_dd_p50=float(np.percentile(max_dd_sims, 50)),
            max_dd_p95=float(np.percentile(max_dd_sims, 95)),

            cagr_p5=float(np.percentile(cagr_sims, 5)),
            cagr_p50=float(np.percentile(cagr_sims, 50)),
            cagr_p95=float(np.percentile(cagr_sims, 95)),

            win_rate_p5=float(np.percentile(wr_sims, 5)),
            win_rate_p50=float(np.percentile(wr_sims, 50)),
            win_rate_p95=float(np.percentile(wr_sims, 95)),

            prob_profit=float(np.mean(profit_sims)),
            prob_sharpe_above_1=float(np.mean(sharpe_sims > 1.0)),
            prob_dd_below_20=float(np.mean(max_dd_sims > -0.20)),
            prob_ruin=float(np.mean(max_dd_sims < -0.50))
        )

    def run_equity_path(self, n_simulations: int = 10000) -> MonteCarloResult:
        """
        Simulación Tipo 4: Simulación de múltiples caminos de equity.
        Similar a bootstrap pero guarda todas las equity curves para visualización.
        """
        original_returns = np.array([t.pnl_pct for t in self._trades])
        n_trades = len(original_returns)
        block_size = max(3, int(np.sqrt(n_trades)))

        orig_sharpe, orig_max_dd, orig_cagr, orig_wr = self._calculate_metrics(original_returns)

        sharpe_sims = np.zeros(n_simulations)
        max_dd_sims = np.zeros(n_simulations)
        cagr_sims = np.zeros(n_simulations)
        wr_sims = np.zeros(n_simulations)
        profit_sims = np.zeros(n_simulations, dtype=bool)
        equity_curves = []

        for i in range(n_simulations):
            n_blocks = int(np.ceil(n_trades / block_size))
            blocks = []
            for _ in range(n_blocks):
                start_idx = np.random.randint(0, n_trades - block_size + 1)
                blocks.append(original_returns[start_idx:start_idx + block_size])

            path_returns = np.concatenate(blocks)[:n_trades]

            sharpe_sims[i], max_dd_sims[i], cagr_sims[i], wr_sims[i] = \
                self._calculate_metrics(path_returns)
            profit_sims[i] = np.prod(1 + path_returns) > 1.0

            eq = self.initial_capital * np.cumprod(1 + path_returns)
            equity_curves.append(eq.tolist())

        return MonteCarloResult(
            simulation_type=SimulationType.EQUITY_PATH,
            n_simulations=n_simulations,
            original_sharpe=orig_sharpe,
            original_max_dd=orig_max_dd,
            original_cagr=orig_cagr,
            original_win_rate=orig_wr,

            sharpe_p5=float(np.percentile(sharpe_sims, 5)),
            sharpe_p50=float(np.percentile(sharpe_sims, 50)),
            sharpe_p95=float(np.percentile(sharpe_sims, 95)),

            max_dd_p5=float(np.percentile(max_dd_sims, 5)),
            max_dd_p50=float(np.percentile(max_dd_sims, 50)),
            max_dd_p95=float(np.percentile(max_dd_sims, 95)),

            cagr_p5=float(np.percentile(cagr_sims, 5)),
            cagr_p50=float(np.percentile(cagr_sims, 50)),
            cagr_p95=float(np.percentile(cagr_sims, 95)),

            win_rate_p5=float(np.percentile(wr_sims, 5)),
            win_rate_p50=float(np.percentile(wr_sims, 50)),
            win_rate_p95=float(np.percentile(wr_sims, 95)),

            prob_profit=float(np.mean(profit_sims)),
            prob_sharpe_above_1=float(np.mean(sharpe_sims > 1.0)),
            prob_dd_below_20=float(np.mean(max_dd_sims > -0.20)),
            prob_ruin=float(np.mean(max_dd_sims < -0.50)),

            equity_curves=np.array(equity_curves)
        )

    def run_parameter_perturbation(self, param_ranges: Dict[str, Tuple[float, float]],
                                    n_simulations: int = 1000) -> MonteCarloResult:
        """
        Simulación Tipo 3: Perturbación de parámetros.
        Útil cuando hay parámetros optimizables (stop loss, take profit, etc.)
        y quieres ver la sensibilidad.

        Args:
            param_ranges: Dict con {nombre_param: (min, max)}
        """
        raise NotImplementedError(
            "Parameter perturbation requiere integración con el motor de señales. "
            "Implementa generando trades con parámetros aleatorios dentro de los rangos."
        )

    def validate_strategy(self, result: MonteCarloResult,
                          min_prob_profit: float = 0.70,
                          min_prob_sharpe: float = 0.60,
                          max_prob_ruin: float = 0.05,
                          min_sharpe_p5: float = 0.5) -> Dict:
        """
        Valida si la estrategia pasa los umbrales de aceptación Montecarlo.
        Returns dict con:
            - passed: bool
            - score: float (0-100)
            - failures: list de checks fallidos
        """
        checks = {
            "profit_probability": result.prob_profit >= min_prob_profit,
            "sharpe_probability": result.prob_sharpe_above_1 >= min_prob_sharpe,
            "ruin_probability": result.prob_ruin <= max_prob_ruin,
            "sharpe_robustness": result.sharpe_p5 >= min_sharpe_p5,
            "drawdown_robustness": result.max_dd_p5 > -0.30  # Peor 5% no pierde >30%
        }

        passed = all(checks.values())
        score = sum(checks.values()) / len(checks) * 100

        failures = [k for k, v in checks.items() if not v]

        return {
            "passed": passed,
            "score": round(score, 1),
            "checks": checks,
            "failures": failures,
            "timestamp": datetime.now().isoformat()
        }


# ═══════════════════════════════════════════════════════════════
# INTEGRACIÓN CON EL PIPELINE ACTUAL
# ═══════════════════════════════════════════════════════════════

class TradingValidator:
    """
    Wrapper de alto nivel que integra el motor Montecarlo con tu
    sistema de trading existente.
    """

    def __init__(self, initial_capital: float = 10000.0):
        self.mc_engine = MonteCarloEngine(initial_capital=initial_capital)
        self.last_result: Optional[MonteCarloResult] = None
        self.last_validation: Optional[Dict] = None

    def validate_from_trade_log(self, trade_log_path: str) -> Dict:
        """
        Carga un log de trades (CSV/JSON) y ejecuta validación completa.
        """
        if trade_log_path.endswith('.csv'):
            df = pd.read_csv(trade_log_path, parse_dates=['entry_time', 'exit_time'])
        elif trade_log_path.endswith('.json'):
            with open(trade_log_path) as f:
                data = json.load(f)
            df = pd.DataFrame(data)
        else:
            raise ValueError("Formato no soportado. Usa CSV o JSON.")

        self.mc_engine.load_from_dataframe(df)

        result_shuffle = self.mc_engine.run_return_shuffle(n_simulations=10000)
        result_bootstrap = self.mc_engine.run_bootstrap(n_simulations=10000)

        validation_shuffle = self.mc_engine.validate_strategy(result_shuffle)
        validation_bootstrap = self.mc_engine.validate_strategy(result_bootstrap)

        self.last_result = result_shuffle

        return {
            "return_shuffle": {
                "result": result_shuffle.to_dict(),
                "validation": validation_shuffle
            },
            "bootstrap": {
                "result": result_bootstrap.to_dict(),
                "validation": validation_bootstrap
            },
            "overall_passed": validation_shuffle["passed"] and validation_bootstrap["passed"],
            "overall_score": round((validation_shuffle["score"] + validation_bootstrap["score"]) / 2, 1)
        }

    def validate_live_trades(self, trades: List[Trade]) -> Dict:
        """Valida trades en tiempo real (desde tu bot en ejecución)."""
        self.mc_engine.load_trades(trades)

        result = self.mc_engine.run_return_shuffle(n_simulations=5000)
        validation = self.mc_engine.validate_strategy(result)

        self.last_result = result
        self.last_validation = validation

        return {
            "result": result.to_dict(),
            "validation": validation,
            "recommendation": self._generate_recommendation(result, validation)
        }

    def validate_live_from_dicts(self, trades: List[dict]) -> Dict:
        """Valida trades desde diccionarios (para API)."""
        self.mc_engine.load_from_dicts(trades)

        result = self.mc_engine.run_return_shuffle(n_simulations=5000)
        validation = self.mc_engine.validate_strategy(result)

        self.last_result = result
        self.last_validation = validation

        return {
            "result": result.to_dict(),
            "validation": validation,
            "recommendation": self._generate_recommendation(result, validation)
        }

    def _generate_recommendation(self, result: MonteCarloResult,
                                  validation: Dict) -> str:
        """Genera recomendación accionable basada en los resultados."""
        if validation["passed"]:
            return "✅ ESTRATEGIA VÁLIDA. Continuar operativa normal."

        recs = []
        if not validation["checks"].get("profit_probability", True):
            recs.append("La probabilidad de profit es baja. Revisar edge del modelo.")
        if not validation["checks"].get("sharpe_probability", True):
            recs.append("Sharpe inestable. Considerar reducir tamaño de posición.")
        if not validation["checks"].get("ruin_probability", True):
            recs.append("RIESGO DE RUINA ELEVADO. DETENER OPERATIVA INMEDIATAMENTE.")
        if not validation["checks"].get("drawdown_robustness", True):
            recs.append("Drawdown potencialmente severo. Ajustar stops más conservadores.")

        return "⚠️ " + " | ".join(recs) if recs else "Revisar configuración."

    def should_trade(self, min_score: float = 70.0) -> bool:
        """Decide si la estrategia está lo suficientemente validada para operar."""
        if self.last_validation is None:
            return False
        return self.last_validation["passed"] and self.last_validation["score"] >= min_score
