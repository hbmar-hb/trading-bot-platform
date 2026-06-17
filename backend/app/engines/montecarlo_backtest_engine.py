"""
Motor de backtesting histórico para estrategias Monte Carlo.
Obtiene datos de Binance, ejecuta estrategias Python en sandbox,
y simula trades con fees y slippage.
"""
from __future__ import annotations

import asyncio
import ccxt.async_support as ccxt
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from app.engines.montecarlo_indicators import AVAILABLE_INDICATORS, list_indicators


# ═══════════════════════════════════════════════════════════════
# DATACLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class BacktestTrade:
    entry_time: datetime
    exit_time: datetime
    direction: int  # 1 = LONG, -1 = SHORT
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float
    duration_bars: int
    max_drawdown_pct: float
    close_reason: str = ""  # "tp", "sl", "signal", "end_of_data"


@dataclass
class BacktestMetrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: Optional[float]
    total_return_pct: float
    total_pnl_abs: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    cagr: float
    expectancy: float
    avg_trade_pct: float
    best_trade_pct: float
    worst_trade_pct: float
    avg_bars: float


@dataclass
class BacktestResult:
    trades: List[BacktestTrade]
    metrics: BacktestMetrics
    equity_curve: List[dict]  # [{timestamp, equity, drawdown}]
    parameters: dict
    symbol: str
    timeframe: str


# ═══════════════════════════════════════════════════════════════
# FETCH DE DATOS
# ═══════════════════════════════════════════════════════════════

async def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    from_date: datetime,
    to_date: datetime,
) -> pd.DataFrame:
    """
    Obtiene datos OHLCV probando múltiples exchanges públicos.
    symbol: formato CCXT (ej: BTC/USDT:USDT) o nativo (BTCUSDT)
    """
    # Normalizar símbolo a CCXT
    sym = _to_ccxt_symbol(symbol)

    # Normalizar timeframe
    tf_map = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h",
        "1d": "1d", "3d": "3d", "1w": "1w", "1M": "1M",
    }
    tf_clean = str(timeframe).strip().lower()
    tf = tf_map.get(tf_clean, tf_clean)

    since_ms = int(from_date.timestamp() * 1000)
    to_ms = int(to_date.timestamp() * 1000)

    # Probar exchanges en orden hasta que uno funcione
    exchange_classes = [
        ("binance", ccxt.binance),
        ("bingx", ccxt.bingx),
        ("bybit", ccxt.bybit),
        ("okx", ccxt.okx),
    ]

    last_error = None
    for ex_name, ex_cls in exchange_classes:
        exchange = ex_cls({"options": {"defaultType": "swap"}})
        all_candles = []
        try:
            # Algunos exchanges necesitan enableRateLimit
            exchange.enableRateLimit = True
            current_since = since_ms
            for _ in range(100):  # max 100 llamadas
                ohlcv = await exchange.fetch_ohlcv(sym, tf, since=current_since, limit=1000)
                if not ohlcv:
                    break
                all_candles.extend(ohlcv)
                current_since = ohlcv[-1][0] + 1
                if ohlcv[-1][0] >= to_ms:
                    break
        except Exception as exc:
            last_error = exc
            continue
        finally:
            await exchange.close()

        if all_candles:
            break
    else:
        # Ningún exchange pudo obtener datos
        err_detail = f"{last_error}" if last_error else "no data"
        raise ValueError(f"No se obtuvieron datos para {sym} {tf} en ningún exchange: {err_detail}")

    df = pd.DataFrame(
        all_candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[(df.index >= from_date) & (df.index <= to_date)]
    df = df.sort_index()
    df = df.drop_duplicates()

    if len(df) < 50:
        raise ValueError(f"Datos insuficientes: solo {len(df)} velas")

    return df.astype(float)


def _to_ccxt_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    s = symbol.replace(".P", "").replace(".p", "")
    for quote in ["USDT", "USDC", "BTC", "ETH", "USD"]:
        if s.endswith(quote):
            base = s[: -len(quote)]
            return f"{base}/{quote}:{quote}"
    return symbol


# ═══════════════════════════════════════════════════════════════
# SANDBOX DE ESTRATEGIA
# ═══════════════════════════════════════════════════════════════

import builtins as _builtins

# Módulos permitidos en estrategias de usuario
_ALLOWED_IMPORTS = {
    "numpy", "pandas", "math", "random", "datetime", "itertools",
    "collections", "statistics", "typing", "fractions", "decimal", "json",
    "dataclasses", "functools", "operator", "copy", "numbers", "re",
    "string", "enum", "inspect", "warnings", "contextlib", "types",
    "builtins", "abc", "heapq", "bisect", "traceback", "sys",
    "weakref", "pickle", "marshal", "codecs", "io", "struct",
}

# Builtins peligrosos que queremos bloquear
_DANGEROUS_BUILTINS = {"open", "exec", "eval", "compile", "input", "exit", "quit", "help"}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Import seguro que solo permite módulos de la lista blanca."""
    root = name.split(".")[0]
    if root not in _ALLOWED_IMPORTS:
        raise ImportError(f"Import de '{root}' no permitido. Módulos disponibles: {', '.join(sorted(_ALLOWED_IMPORTS))}")
    return __import__(name, globals, locals, fromlist, level)


def _build_strategy_namespace() -> dict:
    """Construye el namespace seguro para ejecutar estrategias."""
    safe_builtins = {k: v for k, v in _builtins.__dict__.items() if k not in _DANGEROUS_BUILTINS}
    safe_builtins["__import__"] = _safe_import
    ns = {
        "__builtins__": safe_builtins,
        "__name__": "__main__",
        "__file__": "",
        "__doc__": None,
        "__package__": None,
        "np": np,
        "pd": pd,
    }
    # Exponer todos los indicadores
    for name, func in AVAILABLE_INDICATORS.items():
        ns[name] = func
    return ns


def execute_strategy_code(
    code: str,
    df: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    """
    Ejecuta el código de estrategia del usuario en un sandbox restringido.
    El código debe definir una función `strategy(df, params)` que retorne
    un DataFrame con columnas:
        - signal: 1=long, -1=short, 0=none (o NaN) en cada barra
        - stop_loss (opcional): precio de SL
        - take_profit (opcional): precio de TP
    """
    namespace = _build_strategy_namespace()

    try:
        exec(code, namespace)
    except Exception as e:
        raise ValueError(f"Error en el código de estrategia: {e}")

    if "strategy" not in namespace:
        raise ValueError("El código debe definir una función llamada 'strategy(df, params)'")

    strategy_fn = namespace["strategy"]
    try:
        signals = strategy_fn(df.copy(), params)
    except Exception as e:
        raise ValueError(f"Error ejecutando la estrategia: {e}")

    if not isinstance(signals, pd.DataFrame):
        raise ValueError("La función strategy debe retornar un DataFrame")

    required_cols = {"signal"}
    missing = required_cols - set(signals.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas en el retorno: {missing}")

    # Asegurar que el índice coincida con df
    signals = signals.reindex(df.index)
    signals["signal"] = signals["signal"].fillna(0).astype(int)

    return signals


# ═══════════════════════════════════════════════════════════════
# MOTOR DE BACKTEST
# ═══════════════════════════════════════════════════════════════

def run_backtest(
    df: pd.DataFrame,
    signals: pd.DataFrame,
    initial_capital: float = 10000.0,
    fee_rate: float = 0.0006,
    slippage_pct: float = 0.0,
) -> BacktestResult:
    """
    Simula la ejecución de trades basándose en las señales.
    Asume que una señal en barra i se ejecuta al open de barra i+1.
    """
    capital = initial_capital
    equity = capital
    equity_curve = []
    trades: List[BacktestTrade] = []

    position: Optional[dict] = None  # {direction, entry_price, entry_idx, stop_loss, take_profit}
    peak_equity = capital

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    index = df.index

    for i in range(len(df) - 1):
        current_signal = signals["signal"].iloc[i]
        next_open = opens[i + 1]
        next_high = highs[i + 1]
        next_low = lows[i + 1]
        next_close = closes[i + 1]

        # ── Cerrar posición abierta ──
        if position is not None:
            exited = False
            exit_price = next_close
            reason = "signal"

            # Check SL/TP en la siguiente barra
            sl = position.get("stop_loss")
            tp = position.get("take_profit")
            direction = position["direction"]

            if direction == 1:  # LONG
                if sl is not None and next_low <= sl:
                    exit_price = min(next_open, sl) if next_open > sl else sl
                    reason = "sl"
                    exited = True
                elif tp is not None and next_high >= tp:
                    exit_price = max(next_open, tp) if next_open < tp else tp
                    reason = "tp"
                    exited = True
                elif current_signal == -1:
                    exit_price = next_open
                    reason = "signal"
                    exited = True
            else:  # SHORT
                if sl is not None and next_high >= sl:
                    exit_price = max(next_open, sl) if next_open < sl else sl
                    reason = "sl"
                    exited = True
                elif tp is not None and next_low <= tp:
                    exit_price = min(next_open, tp) if next_open > tp else tp
                    reason = "tp"
                    exited = True
                elif current_signal == 1:
                    exit_price = next_open
                    reason = "signal"
                    exited = True

            if exited:
                # Aplicar slippage
                if slippage_pct > 0:
                    slip = exit_price * slippage_pct
                    exit_price = exit_price + slip if direction == -1 else exit_price - slip

                raw_pnl_pct = (exit_price - position["entry_price"]) / position["entry_price"]
                if direction == -1:
                    raw_pnl_pct = -raw_pnl_pct

                # Fee entrada + salida
                fee_pct = fee_rate * 2
                pnl_pct = raw_pnl_pct - fee_pct
                pnl_abs = capital * pnl_pct

                # Max drawdown intra-trade (estimado con high/low de velas intermedias)
                mid_prices = highs[position["entry_idx"]:i+1] if direction == 1 else lows[position["entry_idx"]:i+1]
                if direction == 1:
                    worst_price = np.min(lows[position["entry_idx"]:i+1]) if i > position["entry_idx"] else position["entry_price"]
                else:
                    worst_price = np.max(highs[position["entry_idx"]:i+1]) if i > position["entry_idx"] else position["entry_price"]
                mdd = (worst_price - position["entry_price"]) / position["entry_price"]
                if direction == -1:
                    mdd = -mdd
                mdd = min(mdd, 0.0)

                trades.append(BacktestTrade(
                    entry_time=position["entry_time"],
                    exit_time=index[i + 1],
                    direction=direction,
                    entry_price=position["entry_price"],
                    exit_price=exit_price,
                    pnl_pct=pnl_pct,
                    pnl_abs=pnl_abs,
                    duration_bars=i + 1 - position["entry_idx"],
                    max_drawdown_pct=mdd,
                    close_reason=reason,
                ))

                capital += pnl_abs
                position = None

        # ── Abrir nueva posición ──
        if position is None and current_signal in (1, -1):
            entry_price = next_open
            if slippage_pct > 0:
                slip = entry_price * slippage_pct
                entry_price = entry_price + slip if current_signal == 1 else entry_price - slip

            sl = signals.get("stop_loss", pd.Series(np.nan, index=df.index)).iloc[i]
            tp = signals.get("take_profit", pd.Series(np.nan, index=df.index)).iloc[i]

            position = {
                "direction": current_signal,
                "entry_price": entry_price,
                "entry_idx": i + 1,
                "entry_time": index[i + 1],
                "stop_loss": float(sl) if pd.notna(sl) else None,
                "take_profit": float(tp) if pd.notna(tp) else None,
            }

        # ── Equity curve ──
        equity = capital
        if position is not None:
            unrealized = (next_close - position["entry_price"]) / position["entry_price"]
            if position["direction"] == -1:
                unrealized = -unrealized
            equity = capital + capital * unrealized

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0

        equity_curve.append({
            "timestamp": index[i + 1].isoformat(),
            "equity": round(equity, 4),
            "drawdown": round(dd, 6),
        })

    # Cerrar posición abierta al final si existe
    if position is not None and len(df) > 0:
        last_close = closes[-1]
        raw_pnl_pct = (last_close - position["entry_price"]) / position["entry_price"]
        if position["direction"] == -1:
            raw_pnl_pct = -raw_pnl_pct
        fee_pct = fee_rate * 2
        pnl_pct = raw_pnl_pct - fee_pct
        pnl_abs = capital * pnl_pct

        trades.append(BacktestTrade(
            entry_time=position["entry_time"],
            exit_time=index[-1],
            direction=position["direction"],
            entry_price=position["entry_price"],
            exit_price=last_close,
            pnl_pct=pnl_pct,
            pnl_abs=pnl_abs,
            duration_bars=len(df) - 1 - position["entry_idx"],
            max_drawdown_pct=0.0,
            close_reason="end_of_data",
        ))
        capital += pnl_abs

    metrics = _compute_metrics(trades, initial_capital, len(df))

    return BacktestResult(
        trades=trades,
        metrics=metrics,
        equity_curve=equity_curve,
        parameters={"fee_rate": fee_rate, "slippage_pct": slippage_pct},
        symbol="",
        timeframe="",
    )


def _compute_metrics(trades: List[BacktestTrade], initial_capital: float, n_bars: int) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics(
            total_trades=0, winning_trades=0, losing_trades=0, win_rate=0.0,
            profit_factor=None, total_return_pct=0.0, total_pnl_abs=0.0,
            sharpe_ratio=0.0, sortino_ratio=0.0, max_drawdown_pct=0.0,
            cagr=0.0, expectancy=0.0, avg_trade_pct=0.0, best_trade_pct=0.0,
            worst_trade_pct=0.0, avg_bars=0.0,
        )

    returns = np.array([t.pnl_pct for t in trades])
    wins = returns[returns > 0]
    losses = returns[returns <= 0]

    total_trades = len(trades)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    total_win = float(np.sum(wins)) if len(wins) > 0 else 0.0
    total_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
    profit_factor = total_win / total_loss if total_loss > 0 else None

    total_pnl_abs = sum(t.pnl_abs for t in trades)
    total_return_pct = total_pnl_abs / initial_capital

    # Sharpe
    mean_ret = np.mean(returns)
    std_ret = np.std(returns)
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    # Sortino
    downside = returns[returns < 0]
    downside_std = np.std(downside) if len(downside) > 0 else 0.0
    sortino = (mean_ret / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

    # Max Drawdown desde equity curve simulada
    equity = initial_capital * np.cumprod(1 + returns)
    peak = np.maximum.accumulate(equity)
    drawdowns = (equity - peak) / peak
    max_dd = float(np.min(drawdowns))

    # CAGR
    n_years = n_bars / (252 * 24) if n_bars > 0 else 0  # aprox para 1h
    cagr = (1 + total_return_pct) ** (1 / n_years) - 1 if n_years > 0 and total_return_pct > -1 else 0.0

    # Expectancy
    expectancy = mean_ret if total_trades > 0 else 0.0

    avg_trade = float(np.mean(returns))
    best_trade = float(np.max(returns))
    worst_trade = float(np.min(returns))
    avg_bars = float(np.mean([t.duration_bars for t in trades]))

    return BacktestMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
        total_return_pct=round(total_return_pct, 4),
        total_pnl_abs=round(total_pnl_abs, 4),
        sharpe_ratio=round(sharpe, 3),
        sortino_ratio=round(sortino, 3),
        max_drawdown_pct=round(max_dd, 4),
        cagr=round(cagr, 4),
        expectancy=round(expectancy, 4),
        avg_trade_pct=round(avg_trade, 4),
        best_trade_pct=round(best_trade, 4),
        worst_trade_pct=round(worst_trade, 4),
        avg_bars=round(avg_bars, 1),
    )


# ═══════════════════════════════════════════════════════════════
# TEMPLATE DE ESTRATEGIA POR DEFECTO
# ═══════════════════════════════════════════════════════════════

DEFAULT_STRATEGY_CODE = '''def strategy(df, params):
    """
    Estrategia de ejemplo: EMA Crossover + RSI Filter.
    Compra cuando EMA rápida cruza por encima de EMA lenta y RSI > 50.
    Vende cuando EMA rápida cruza por debajo de EMA lenta y RSI < 50.
    """
    fast = params.get("ema_fast", 9)
    slow = params.get("ema_slow", 21)
    rsi_period = params.get("rsi_period", 14)
    sl_atr = params.get("sl_atr", 2.0)
    tp_atr = params.get("tp_atr", 3.0)

    ema_fast = ema(df, fast)
    ema_slow = ema(df, slow)
    rsi_val = rsi(df, rsi_period)
    atr_val = atr(df, 14)

    long_signal = cross_above(ema_fast, ema_slow) & (rsi_val > 50)
    short_signal = cross_below(ema_fast, ema_slow) & (rsi_val < 50)

    signal = pd.Series(0, index=df.index, dtype=int)
    signal[long_signal] = 1
    signal[short_signal] = -1

    stop_loss = pd.Series(np.nan, index=df.index)
    take_profit = pd.Series(np.nan, index=df.index)

    for i in range(len(df)):
        if signal.iloc[i] == 1:
            stop_loss.iloc[i] = df["close"].iloc[i] - atr_val.iloc[i] * sl_atr
            take_profit.iloc[i] = df["close"].iloc[i] + atr_val.iloc[i] * tp_atr
        elif signal.iloc[i] == -1:
            stop_loss.iloc[i] = df["close"].iloc[i] + atr_val.iloc[i] * sl_atr
            take_profit.iloc[i] = df["close"].iloc[i] - atr_val.iloc[i] * tp_atr

    return pd.DataFrame({
        "signal": signal,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    })
'''


def get_default_strategy() -> dict:
    return {
        "name": "EMA Crossover + RSI",
        "description": "Estrategia de ejemplo con cruce de EMAs y filtro RSI",
        "code": DEFAULT_STRATEGY_CODE,
        "parameters": {
            "ema_fast": {"default": 9, "min": 3, "max": 50, "type": "int"},
            "ema_slow": {"default": 21, "min": 5, "max": 100, "type": "int"},
            "rsi_period": {"default": 14, "min": 5, "max": 30, "type": "int"},
            "sl_atr": {"default": 2.0, "min": 0.5, "max": 5.0, "type": "float"},
            "tp_atr": {"default": 3.0, "min": 1.0, "max": 10.0, "type": "float"},
        },
        "indicators": ["ema", "rsi", "atr", "cross_above", "cross_below"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3C: Walk-Forward Validation (Out-of-Sample)
# ═══════════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass


@dataclass
class WalkForwardResult:
    """Resultado de backtest con validación out-of-sample."""
    train_result: BacktestResult
    oos_result: BacktestResult
    overfit_detected: bool
    overfit_reasons: list[str]


def run_backtest_with_walk_forward(
    df: pd.DataFrame,
    signals: pd.DataFrame,
    initial_capital: float = 10000.0,
    fee_rate: float = 0.0006,
    slippage_pct: float = 0.0,
    oos_split: float = 0.2,
) -> WalkForwardResult:
    """Ejecuta backtest con walk-forward validation.

    Divide los datos en train (1 - oos_split) y test/OOS (oos_split).
    Correr el backtest en ambos conjuntos y detecta overfitting comparando
    métricas de train vs OOS.

    Args:
        df: DataFrame con OHLCV completo.
        signals: DataFrame con señales generadas.
        initial_capital: Capital inicial.
        fee_rate: Comisión por trade (entry + exit).
        slippage_pct: Slippage simulado.
        oos_split: Porcentaje de datos reservados para OOS (default 20%).

    Returns:
        WalkForwardResult con train, OOS, y flag de overfitting.
    """
    n = len(df)
    split_idx = int(n * (1 - oos_split))

    if split_idx < 50 or (n - split_idx) < 20:
        # Datos insuficientes para WFV — correr todo como train
        train_result = run_backtest(df, signals, initial_capital, fee_rate, slippage_pct)
        return WalkForwardResult(
            train_result=train_result,
            oos_result=train_result,  # dummy
            overfit_detected=False,
            overfit_reasons=["insufficient_data_for_oos"],
        )

    # Split data
    df_train = df.iloc[:split_idx].copy()
    signals_train = signals.iloc[:split_idx].copy()
    df_oos = df.iloc[split_idx:].copy()
    signals_oos = signals.iloc[split_idx:].copy()

    # Backtest en train
    train_result = run_backtest(df_train, signals_train, initial_capital, fee_rate, slippage_pct)

    # Backtest en OOS (mismos parámetros, datos no vistos)
    oos_result = run_backtest(df_oos, signals_oos, initial_capital, fee_rate, slippage_pct)

    # Detectar overfitting
    overfit_reasons = []
    overfit_detected = False

    tm = train_result.metrics
    om = oos_result.metrics

    # Criterio 1: Win rate en OOS < 60% del win rate en train
    if tm.win_rate > 0 and om.win_rate < tm.win_rate * 0.6:
        overfit_detected = True
        overfit_reasons.append(
            f"OOS win_rate ({om.win_rate:.1%}) < 60% of train win_rate ({tm.win_rate:.1%})"
        )

    # Criterio 2: Profit factor en OOS < 50% del profit factor en train
    if tm.profit_factor and tm.profit_factor > 0:
        if not om.profit_factor or om.profit_factor < tm.profit_factor * 0.5:
            overfit_detected = True
            overfit_reasons.append(
                f"OOS profit_factor ({om.profit_factor or 0:.2f}) < 50% of train PF ({tm.profit_factor:.2f})"
            )

    # Criterio 3: Max drawdown en OOS > 2× el max drawdown en train
    if tm.max_drawdown_pct and om.max_drawdown_pct:
        if abs(om.max_drawdown_pct) > abs(tm.max_drawdown_pct) * 2.0:
            overfit_detected = True
            overfit_reasons.append(
                f"OOS max_drawdown ({om.max_drawdown_pct:.1%}) > 2× train DD ({tm.max_drawdown_pct:.1%})"
            )

    # Criterio 4: OOS Sharpe < 0 (ruinoso) mientras train Sharpe > 1
    if tm.sharpe_ratio and tm.sharpe_ratio > 1.0:
        if not om.sharpe_ratio or om.sharpe_ratio < 0.0:
            overfit_detected = True
            overfit_reasons.append(
                f"OOS sharpe ({om.sharpe_ratio or 0:.2f}) < 0 while train sharpe ({tm.sharpe_ratio:.2f}) > 1"
            )

    logger.info(
        f"[WFV] Train: WR={tm.win_rate:.1%} PF={tm.profit_factor:.2f} Sharpe={tm.sharpe_ratio:.2f} "
        f"| OOS: WR={om.win_rate:.1%} PF={om.profit_factor:.2f} Sharpe={om.sharpe_ratio:.2f} "
        f"| Overfit={'YES' if overfit_detected else 'NO'} ({len(overfit_reasons)} reasons)"
    )

    return WalkForwardResult(
        train_result=train_result,
        oos_result=oos_result,
        overfit_detected=overfit_detected,
        overfit_reasons=overfit_reasons,
    )
