"""Motor de análisis ICT (Inner Circle Trader) / SMC (Smart Money Concepts).

Detecta estructura de mercado (BOS/CHoCH), Order Blocks, Fair Value Gaps
y Equal Highs/Lows para generar señales de entrada de alta confluencia.

Input:  lista de dicts OHLCV  {open, high, low, close, volume}
Output: ICTResult con sesgo, última rotura de estructura y señal de entrada
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd


# ─── Tipos de datos ──────────────────────────────────────────────────────────

@dataclass
class SwingPoint:
    bar: int
    price: float
    kind: Literal["high", "low"]
    label: str = ""   # HH | LH | HL | LL


@dataclass
class OrderBlock:
    bar: int
    top: float
    bottom: float
    kind: Literal["bull", "bear"]
    mitigated: bool = False


@dataclass
class FVG:
    """Fair Value Gap (imbalance de 3 velas)."""
    bar: int          # índice de la vela central
    top: float
    bottom: float
    kind: Literal["bull", "bear"]
    filled: bool = False


@dataclass
class StructureBreak:
    bar: int
    level: float
    kind: Literal["BOS", "CHoCH"]
    direction: Literal["bull", "bear"]
    swing: SwingPoint
    ob: OrderBlock | None = None


@dataclass
class ICTResult:
    bias: Literal["bull", "bear"]
    last_break: StructureBreak | None
    active_ob: OrderBlock | None
    active_fvgs: list[FVG] = field(default_factory=list)
    eq_highs: list[float] = field(default_factory=list)
    eq_lows: list[float] = field(default_factory=list)
    signal: Literal["long", "short", "none"] = "none"
    entry_zone: tuple[float, float] | None = None
    trigger: str = ""   # "ob" | "fvg"


# ─── API pública ─────────────────────────────────────────────────────────────

def analyze(
    candles: list[dict],
    pivot_len: int = 5,
    atr_mult: float = 1.5,
    atr_len: int = 14,
    entry_mode: str = "ob_or_fvg",
) -> ICTResult:
    """
    Ejecuta el análisis ICT completo sobre velas OHLCV.

    Args:
        candles:    lista de dicts {open, high, low, close, volume}
        pivot_len:  barras a cada lado para confirmar pivot
        atr_mult:   multiplicador ATR para filtro de tamaño de pivot
        atr_len:    período del ATR
        entry_mode: "ob" | "fvg" | "ob_or_fvg" — qué zona activa la señal

    Returns:
        ICTResult con señal de entrada y contexto estructural completo
    """
    df = pd.DataFrame(candles)[["open", "high", "low", "close", "volume"]].astype(float)
    df = df.reset_index(drop=True)

    min_bars = pivot_len * 2 + atr_len + 5
    if len(df) < min_bars:
        return ICTResult(bias="bull", last_break=None, active_ob=None)

    atr = _compute_atr(df, atr_len)
    valid_h, valid_l = _detect_pivots(df, pivot_len, atr_mult, atr)
    fvgs = _detect_fvg(df)
    eq_highs, eq_lows = _detect_eqhl(df, valid_h, valid_l, atr)

    # ─── State machine — refleja exactamente las var variables de Pine Script ─
    active_h: SwingPoint | None = None
    active_l: SwingPoint | None = None
    prev_sw_h: float | None = None
    prev_sw_l: float | None = None
    used_h = False
    used_l = False
    bull_bias = True
    last_break: StructureBreak | None = None
    active_ob: OrderBlock | None = None

    for i in range(len(df)):
        if valid_h.iloc[i]:
            prev_sw_h = active_h.price if active_h else None
            label = ""
            if prev_sw_h is not None:
                label = "HH" if df["high"].iloc[i] > prev_sw_h else "LH"
            active_h = SwingPoint(bar=i, price=float(df["high"].iloc[i]), kind="high", label=label)
            used_h = False

        if valid_l.iloc[i]:
            prev_sw_l = active_l.price if active_l else None
            label = ""
            if prev_sw_l is not None:
                label = "HL" if df["low"].iloc[i] > prev_sw_l else "LL"
            active_l = SwingPoint(bar=i, price=float(df["low"].iloc[i]), kind="low", label=label)
            used_l = False

        if active_h is None or active_l is None:
            continue

        close_i = float(df["close"].iloc[i])
        body_break_u = not used_h and close_i > active_h.price
        body_break_d = not used_l and close_i < active_l.price

        if body_break_u:
            used_h = True
            bk: Literal["BOS", "CHoCH"] = "BOS" if bull_bias else "CHoCH"
            ob = _find_order_block(df, active_h.bar, "bull")
            last_break = StructureBreak(
                bar=i, level=active_h.price, kind=bk,
                direction="bull", swing=active_h, ob=ob,
            )
            if bk == "CHoCH":
                bull_bias = True
                active_ob = ob

        if body_break_d:
            used_l = True
            bk = "BOS" if not bull_bias else "CHoCH"
            ob = _find_order_block(df, active_l.bar, "bear")
            last_break = StructureBreak(
                bar=i, level=active_l.price, kind=bk,
                direction="bear", swing=active_l, ob=ob,
            )
            if bk == "CHoCH":
                bull_bias = False
                active_ob = ob

    # ─── Evaluar señal de entrada en la vela actual ───────────────────────────
    signal, entry_zone, trigger = _evaluate_entry(df, last_break, active_ob, fvgs, entry_mode)

    relevant_fvgs = [
        f for f in fvgs
        if not f.filled
        and f.kind == ("bull" if bull_bias else "bear")
        and f.bar > len(df) - 100
    ]

    return ICTResult(
        bias="bull" if bull_bias else "bear",
        last_break=last_break,
        active_ob=active_ob,
        active_fvgs=relevant_fvgs[-5:],
        eq_highs=eq_highs,
        eq_lows=eq_lows,
        signal=signal,
        entry_zone=entry_zone,
        trigger=trigger,
    )


# ─── Cálculos internos ────────────────────────────────────────────────────────

def _compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    h = df["high"]
    l = df["low"]
    prev_c = df["close"].shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _detect_pivots(
    df: pd.DataFrame, pivot_len: int, atr_mult: float, atr: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """
    Pivot high en barra i si es el máximo en ventana 2·n+1 centrada en i,
    y la mecha sobre velas vecinas supera atr_mult × ATR.
    """
    n = pivot_len

    roll_h = df["high"].rolling(2 * n + 1, center=True).max()
    is_pivot_h = df["high"] == roll_h
    neighbor_h = pd.concat([df["close"].shift(1), df["close"].shift(-1)], axis=1).max(axis=1)
    valid_h = is_pivot_h & ((df["high"] - neighbor_h) >= atr_mult * atr)

    roll_l = df["low"].rolling(2 * n + 1, center=True).min()
    is_pivot_l = df["low"] == roll_l
    neighbor_l = pd.concat([df["close"].shift(1), df["close"].shift(-1)], axis=1).min(axis=1)
    valid_l = is_pivot_l & ((neighbor_l - df["low"]) >= atr_mult * atr)

    return valid_h.fillna(False), valid_l.fillna(False)


def _find_order_block(
    df: pd.DataFrame,
    swing_bar: int,
    direction: Literal["bull", "bear"],
) -> OrderBlock | None:
    """
    Bull OB = última vela bajista (close < open) antes del swing high.
    Bear OB = última vela alcista (close > open) antes del swing low.
    Busca en las 15 barras previas al swing.
    """
    start = max(0, swing_bar - 15)
    sub = df.iloc[start : swing_bar + 1]

    if direction == "bull":
        candidates = sub[sub["close"] < sub["open"]]
        if candidates.empty:
            return None
        row = candidates.iloc[-1]
        return OrderBlock(
            bar=int(candidates.index[-1]),
            top=float(row["open"]),
            bottom=float(row["close"]),
            kind="bull",
        )
    else:
        candidates = sub[sub["close"] > sub["open"]]
        if candidates.empty:
            return None
        row = candidates.iloc[-1]
        return OrderBlock(
            bar=int(candidates.index[-1]),
            top=float(row["close"]),
            bottom=float(row["open"]),
            kind="bear",
        )


def _detect_fvg(df: pd.DataFrame) -> list[FVG]:
    """
    Bullish FVG: high[i-1] < low[i+1]  → gap alcista, soporte en pullback
    Bearish FVG: low[i-1]  > high[i+1] → gap bajista, resistencia en pullback
    Un FVG queda filled cuando precio regresa y toca la zona.
    """
    fvgs: list[FVG] = []
    highs = df["high"].values
    lows = df["low"].values

    for i in range(1, len(df) - 1):
        if highs[i - 1] < lows[i + 1]:
            fvgs.append(FVG(
                bar=i,
                top=float(lows[i + 1]),
                bottom=float(highs[i - 1]),
                kind="bull",
            ))
        elif lows[i - 1] > highs[i + 1]:
            fvgs.append(FVG(
                bar=i,
                top=float(lows[i - 1]),
                bottom=float(highs[i + 1]),
                kind="bear",
            ))

    for fvg in fvgs:
        later_start = fvg.bar + 2
        if later_start >= len(df):
            continue
        later_lows = lows[later_start:]
        later_highs = highs[later_start:]
        if fvg.kind == "bull":
            fvg.filled = bool(np.any(later_lows <= fvg.top))
        else:
            fvg.filled = bool(np.any(later_highs >= fvg.bottom))

    return fvgs


def _detect_eqhl(
    df: pd.DataFrame,
    valid_h: pd.Series,
    valid_l: pd.Series,
    atr: pd.Series,
    tolerance: float = 0.15,
) -> tuple[list[float], list[float]]:
    """
    Equal Highs / Equal Lows — pools de liquidez acumulada.
    Dos pivots son «iguales» si están dentro de ATR × tolerance entre sí.
    """
    atr_val = float(atr.dropna().iloc[-1]) if not atr.dropna().empty else 0.0
    threshold = atr_val * tolerance

    h_prices = df.loc[valid_h, "high"].values.tolist()
    l_prices = df.loc[valid_l, "low"].values.tolist()

    return _find_clusters(h_prices, threshold), _find_clusters(l_prices, threshold)


def _find_clusters(prices: list[float], threshold: float) -> list[float]:
    clusters: list[float] = []
    used: set[int] = set()
    for i, p in enumerate(prices):
        for j in range(i + 1, len(prices)):
            if i not in used and j not in used and abs(p - prices[j]) <= threshold:
                clusters.append((p + prices[j]) / 2.0)
                used.add(i)
                used.add(j)
    return clusters


def _evaluate_entry(
    df: pd.DataFrame,
    last_break: StructureBreak | None,
    active_ob: OrderBlock | None,
    fvgs: list[FVG],
    entry_mode: str,
) -> tuple[Literal["long", "short", "none"], tuple[float, float] | None, str]:
    """
    Determina si la vela actual toca una zona de entrada válida (OB o FVG).
    Solo evalúa la última vela del DataFrame — corresponde a la vela en curso.
    """
    if last_break is None:
        return "none", None, ""

    direction = last_break.direction
    cur_high = float(df["high"].iloc[-1])
    cur_low = float(df["low"].iloc[-1])

    # ── Order Block ──────────────────────────────────────────────────────────
    if active_ob and not active_ob.mitigated and entry_mode in ("ob", "ob_or_fvg"):
        ob = active_ob
        in_zone = cur_low <= ob.top and cur_high >= ob.bottom
        if in_zone:
            if direction == "bull":
                return "long", (ob.bottom, ob.top), "ob"
            else:
                return "short", (ob.bottom, ob.top), "ob"

    # ── Fair Value Gap ────────────────────────────────────────────────────────
    if entry_mode in ("fvg", "ob_or_fvg"):
        target_kind = "bull" if direction == "bull" else "bear"
        recent_fvgs = [
            f for f in fvgs
            if not f.filled and f.kind == target_kind and f.bar > len(df) - 80
        ]
        for fvg in reversed(recent_fvgs):
            in_zone = cur_low <= fvg.top and cur_high >= fvg.bottom
            if in_zone:
                if direction == "bull":
                    return "long", (fvg.bottom, fvg.top), "fvg"
                else:
                    return "short", (fvg.bottom, fvg.top), "fvg"

    return "none", None, ""
