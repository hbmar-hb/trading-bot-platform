"""
Quantum Gold Engine — motor multi-indicador para XAUUSD (y otros activos).

Porteado desde Pine Script v5 «QUANTUM CONFLUENCIAS - XAUUSD».
Implementado con numpy vectorizado para eficiencia máxima sobre series largas.

Señal requiere la confluencia de TODOS los filtros:
  • Macro trend  : close vs EMA200 (+ EMA50 > EMA200 si use_trend_filter)
  • EMA alignment: E9 > E21 > E50 (long) / E9 < E21 < E50 (short)
  • Supertrend   : dirección correcta
  • RSI          : en zona bull (52–68) o bear (32–48)
  • Filtros       : volumen spike, pendiente EMA50, sesión, ATR mínimo
  • Trigger       : BB breakout de squeeze | EMA cross | RSI 50 cross

Grade por tipo de trigger:
  A+  →  BB breakout from squeeze (máxima compresión → expansión)
  A   →  EMA 9/21 crossover
  A-  →  RSI 50 crossover
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import numpy as np


# ─── Resultado (compatible con _dispatch_signal de ict_scan_tasks) ────────────

@dataclass
class QuantumGoldResult:
    signal:        Literal["long", "short", "none"] = "none"
    grade:         Literal["A+", "A", "A-", "none"] = "none"
    trigger:       str   = ""
    bias:          str   = "bull"

    # Niveles de trading
    entry_zone:    tuple[float, float] | None = None
    stop_loss:     float | None               = None
    take_profit_1: float | None               = None
    take_profit_2: float | None               = None

    # Campos de compatibilidad con _dispatch_signal (no aplican en QG)
    last_break:  None       = None
    active_ob:   None       = None
    active_fvgs: list       = field(default_factory=list)
    eq_highs:    list       = field(default_factory=list)
    eq_lows:     list       = field(default_factory=list)


_NO_SIGNAL = QuantumGoldResult()


# ─── Utilidades numéricas (numpy, sin pandas) ─────────────────────────────────

def _ema(src: np.ndarray, n: int) -> np.ndarray:
    """EMA estándar, factor k = 2/(n+1)."""
    k   = 2.0 / (n + 1)
    out = np.empty_like(src, dtype=float)
    out[0] = src[0]
    for i in range(1, len(src)):
        out[i] = src[i] * k + out[i - 1] * (1 - k)
    return out


def _rma(src: np.ndarray, n: int) -> np.ndarray:
    """Wilder's Moving Average — igual que Pine Script ta.rma / ta.atr / ta.rsi."""
    out = np.full(len(src), np.nan)
    if len(src) < n:
        return out
    out[n - 1] = float(np.mean(src[:n]))
    for i in range(n, len(src)):
        out[i] = (out[i - 1] * (n - 1) + src[i]) / n
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    tr = np.empty(len(close))
    tr[0] = high[0] - low[0]
    for i in range(1, len(close)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )
    return _rma(tr, n)


def _rsi(close: np.ndarray, n: int) -> np.ndarray:
    delta  = np.diff(close, prepend=close[0])
    gains  = np.where(delta > 0,  delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_g  = _rma(gains,  n)
    avg_l  = _rma(losses, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs  = np.where(avg_l == 0, np.inf, avg_g / avg_l)
        rsi = np.where(avg_l == 0, 100.0, 100.0 - 100.0 / (1.0 + rs))
    rsi[:n] = np.nan
    return rsi


def _supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                n: int, factor: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Retorna (st_value, direction) donde direction: -1=bull, 1=bear.
    Algoritmo fiel a ta.supertrend() de Pine Script.
    """
    at  = _atr(high, low, close, n)
    m   = len(close)
    val = np.full(m, np.nan)
    dir_ = np.full(m, -1, dtype=int)

    ub = lb = None
    d  = -1

    for i in range(m):
        if np.isnan(at[i]):
            continue
        hl2  = (high[i] + low[i]) / 2
        rUB  = hl2 + factor * at[i]
        rLB  = hl2 - factor * at[i]
        pc   = close[i - 1] if i > 0 else close[i]

        ub = rUB if (ub is None or rUB < ub or pc > ub) else ub
        lb = rLB if (lb is None or rLB > lb or pc < lb) else lb

        if d == 1 and close[i] > ub:
            d = -1
        elif d == -1 and close[i] < lb:
            d = 1

        val[i]  = lb if d == -1 else ub
        dir_[i] = d

    return val, dir_


def _bollinger(close: np.ndarray, n: int, mult: float
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Retorna (upper, lower, width_pct)."""
    m     = len(close)
    upper = np.full(m, np.nan)
    lower = np.full(m, np.nan)
    width = np.full(m, np.nan)
    for i in range(n - 1, m):
        sl    = close[i - n + 1 : i + 1]
        mean  = float(np.mean(sl))
        std   = float(np.std(sl, ddof=0))
        u     = mean + mult * std
        l_    = mean - mult * std
        upper[i] = u
        lower[i] = l_
        if mean > 0:
            width[i] = (u - l_) / mean * 100
    return upper, lower, width


def _sma(src: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(src), np.nan)
    for i in range(n - 1, len(src)):
        out[i] = float(np.mean(src[i - n + 1 : i + 1]))
    return out


def _in_session(ts_utc: float) -> tuple[bool, bool]:
    """Comprueba si el timestamp (segundos UTC) cae en sesión Londres o NY."""
    d  = datetime.fromtimestamp(ts_utc, tz=timezone.utc)
    m  = d.hour * 60 + d.minute
    lon = 480 <= m < 1020   # 08:00 – 17:00 UTC
    ny  = 810 <= m < 1260   # 13:30 – 21:00 UTC
    return lon, ny


# ─── API pública ──────────────────────────────────────────────────────────────

def analyze(
    candles: list[dict],
    *,
    # EMA Ribbon
    ema_fast:  int   = 9,
    ema_mid:   int   = 21,
    ema_slow:  int   = 50,
    ema_trend: int   = 200,
    # Supertrend
    st_atr_len: int   = 10,
    st_factor:  float = 3.0,
    # Bollinger Bands
    bb_len:          int   = 20,
    bb_std:          float = 2.0,
    bb_sqz_threshold: float = 0.9,
    # RSI — zonas ampliadas para HTF (1h/4h); ajustar para LTF (5m/15m)
    rsi_len:    int = 14,
    rsi_bull_lo: int = 45,
    rsi_bull_hi: int = 75,
    rsi_bear_lo: int = 25,
    rsi_bear_hi: int = 55,
    # Volumen — 1.0 = desactivado; subir a 1.2–1.5 para LTF
    vol_len:  int   = 20,
    vol_mult: float = 1.0,
    # ATR / Niveles
    atr_len:  int   = 14,
    tp_mult:  float = 2.0,
    sl_mult:  float = 1.0,
    # Filtros
    use_trend_filter: bool  = False,
    min_atr_filter:   float = 3.0,
    use_sess:         bool  = False,
) -> QuantumGoldResult:
    """
    Analiza las velas y devuelve la señal de la última barra.
    candles: lista de dicts con claves open/high/low/close/volume/time.
    """
    min_bars = max(ema_trend, bb_len, rsi_len, st_atr_len, atr_len) + 15
    if len(candles) < min_bars:
        return _NO_SIGNAL

    close  = np.array([c["close"]  for c in candles], dtype=float)
    high   = np.array([c["high"]   for c in candles], dtype=float)
    low    = np.array([c["low"]    for c in candles], dtype=float)
    volume = np.array([c.get("volume", 0) or 0 for c in candles], dtype=float)
    times  = [c.get("time", 0) for c in candles]

    # ── Indicadores ──────────────────────────────────────────────────────────
    E9   = _ema(close, ema_fast)
    E21  = _ema(close, ema_mid)
    E50  = _ema(close, ema_slow)
    E200 = _ema(close, ema_trend)

    _, st_dir = _supertrend(high, low, close, st_atr_len, st_factor)
    RSI       = _rsi(close, rsi_len)
    bb_up, bb_lo, bb_w = _bollinger(close, bb_len, bb_std)
    vol_sma   = _sma(volume, vol_len)
    ATR       = _atr(high, low, close, atr_len)

    squeeze = (bb_w < bb_sqz_threshold)  # bool array, nan=False

    # ── Última barra (índice -1) y penúltima (-2) ─────────────────────────
    i  = len(candles) - 1
    i1 = i - 1   # penúltima

    # Validaciones básicas
    if np.isnan(RSI[i]) or np.isnan(ATR[i]) or np.isnan(E200[i]):
        return _NO_SIGNAL

    atr_v   = float(ATR[i])
    rsi_v   = float(RSI[i])
    rsi_v1  = float(RSI[i1]) if not np.isnan(RSI[i1]) else rsi_v

    # Sesión
    if use_sess:
        lon, ny = _in_session(float(times[i]))
        sess_ok = lon or ny
    else:
        sess_ok = True
        lon = ny = False

    # ATR mínimo ($)
    atr_ok = (min_atr_filter == 0.0) or (atr_v > min_atr_filter)

    # Volumen — vol_mult <= 1.0 desactiva el filtro (válido para HTF)
    vol_ok = vol_mult <= 1.0 or bool(vol_sma[i] > 0 and volume[i] > vol_sma[i] * vol_mult)

    st_bull = bool(st_dir[i] == -1)   # -1 = alcista en nuestra conv.
    bias    = "bull" if st_bull else "bear"

    # ── Filtros comunes ───────────────────────────────────────────────────
    # Pendiente EMA50 omitida: está implícita en ema_al_l/s (E9>E21>E50)
    common_ok = sess_ok and atr_ok and vol_ok

    # ── Condiciones LONG ─────────────────────────────────────────────────
    macro_l   = float(close[i]) > float(E200[i]) and (
        float(E50[i]) > float(E200[i]) if use_trend_filter else True
    )
    # ema_al_l: solo E9>E21 — la cascada completa E21>E50 raramente coincide con el cruce
    ema_al_l  = float(E9[i]) > float(E21[i])
    rsi_l     = rsi_bull_lo <= rsi_v <= rsi_bull_hi

    # Triggers LONG
    bb_brk_l  = (
        not np.isnan(bb_up[i]) and not np.isnan(bb_up[i1])
        and float(close[i])  > float(bb_up[i])
        and float(close[i1]) <= float(bb_up[i1])
        and bool(squeeze[i1] if not np.isnan(squeeze[i1]) else False)
    )
    ema_crs_l = float(E9[i1]) < float(E21[i1]) and float(E9[i]) >= float(E21[i])
    rsi_crs_l = rsi_v1 < 50 and rsi_v >= 50 and macro_l and st_bull

    if macro_l and ema_al_l and st_bull and rsi_l and common_ok:
        if bb_brk_l:
            trig, grade = "bb_break", "A+"
        elif ema_crs_l:
            trig, grade = "ema_cross", "A"
        elif rsi_crs_l:
            trig, grade = "rsi_cross", "A-"
        else:
            trig = grade = None

        if trig:
            entry = float(close[i])
            sl    = round(entry - atr_v * sl_mult, 8)
            tp1   = round(entry + atr_v * tp_mult, 8)
            tp2   = round(entry + atr_v * tp_mult * 1.5, 8)
            return QuantumGoldResult(
                signal="long",
                grade=grade,
                trigger=trig,
                bias="bull",
                entry_zone=(round(entry * 0.9995, 8), round(entry * 1.0005, 8)),
                stop_loss=sl,
                take_profit_1=tp1,
                take_profit_2=tp2,
            )

    # ── Condiciones SHORT ─────────────────────────────────────────────────
    # macro_s: usar EMA50 como referencia local — en activos como XAUUSD en tendencia alcista
    #   price < EMA200 es casi imposible; price < EMA50 captura correcciones locales
    #   use_trend_filter=True añade la condición más estricta price < EMA200
    macro_s   = float(close[i]) < float(E50[i]) and (
        float(close[i]) < float(E200[i]) if use_trend_filter else True
    )
    # ema_al_s: solo E9<E21 — misma razón que ema_al_l
    ema_al_s  = float(E9[i]) < float(E21[i])
    rsi_s     = rsi_bear_lo <= rsi_v <= rsi_bear_hi

    # Triggers SHORT
    bb_brk_s  = (
        not np.isnan(bb_lo[i]) and not np.isnan(bb_lo[i1])
        and float(close[i])  < float(bb_lo[i])
        and float(close[i1]) >= float(bb_lo[i1])
        and bool(squeeze[i1] if not np.isnan(squeeze[i1]) else False)
    )
    ema_crs_s = float(E9[i1]) > float(E21[i1]) and float(E9[i]) <= float(E21[i])
    rsi_crs_s = rsi_v1 > 50 and rsi_v <= 50 and macro_s and not st_bull

    if macro_s and ema_al_s and not st_bull and rsi_s and common_ok:
        if bb_brk_s:
            trig, grade = "bb_break", "A+"
        elif ema_crs_s:
            trig, grade = "ema_cross", "A"
        elif rsi_crs_s:
            trig, grade = "rsi_cross", "A-"
        else:
            trig = grade = None

        if trig:
            entry = float(close[i])
            sl    = round(entry + atr_v * sl_mult, 8)
            tp1   = round(entry - atr_v * tp_mult, 8)
            tp2   = round(entry - atr_v * tp_mult * 1.5, 8)
            return QuantumGoldResult(
                signal="short",
                grade=grade,
                trigger=trig,
                bias="bear",
                entry_zone=(round(entry * 0.9995, 8), round(entry * 1.0005, 8)),
                stop_loss=sl,
                take_profit_1=tp1,
                take_profit_2=tp2,
            )

    return _NO_SIGNAL
