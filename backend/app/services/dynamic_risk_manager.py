"""Dynamic Risk Manager — post-entry risk control layer.

Four algorithms:
  1. EmergencyBrake     — cut losses aggressively on drawdown spikes
  2. ScaleOutProfit     — systematic profit-taking at +1%/+2%/+5%/+10%
  3. TimeDecayExit      — exit if trade doesn't move favourably within N bars
  4. ExposureCapBySymbol — pre-trade hard cap on risk per ticker

All evaluators are pure functions (no I/O).  State is persisted in
Position.extra_config via the caller (TrailingWorker / BotActivator).
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════
# Defaults derived from user trade analysis (17-18 May)
# ═══════════════════════════════════════════════════════════

_DEFAULT_EB_THRESHOLDS: dict[str, dict] = {
    "DOGE/USDT:USDT":  {"activation": 0.015, "reduction": 0.80},
    "PENGU/USDT:USDT": {"activation": 0.020, "reduction": 0.70},
    "ONDO/USDT:USDT":  {"activation": 0.020, "reduction": 0.70},
    "SOL/USDT:USDT":   {"activation": 0.025, "reduction": 0.70},
    "BTC/USDT:USDT":   {"activation": 0.030, "reduction": 0.70},
    "ETH/USDT:USDT":   {"activation": 0.030, "reduction": 0.70},
    "DEFAULT":         {"activation": 0.035, "reduction": 0.70},
}

_DEFAULT_SCALE_OUT_LEVELS: list[dict] = [
    {"trigger": 0.01, "close": 0.30, "move_sl_to": "entry"},
    {"trigger": 0.02, "close": 0.20, "move_sl_to": "entry_plus_0.5atr"},
    {"trigger": 0.05, "close": 0.20, "move_sl_to": "tp1"},
    {"trigger": 0.10, "close": 0.15, "move_sl_to": "trailing"},
]

_DEFAULT_TIME_DECAY: dict[str, dict] = {
    "5m":  {"max_bars": 6,  "profit_threshold": 0.005},
    "15m": {"max_bars": 8,  "profit_threshold": 0.008},
    "1h":  {"max_bars": 6,  "profit_threshold": 0.010},
    "4h":  {"max_bars": 4,  "profit_threshold": 0.015},
    "1d":  {"max_bars": 3,  "profit_threshold": 0.020},
}

_DEFAULT_EXPOSURE_CAPS: dict[str, float] = {
    "DOGE/USDT:USDT":  0.02,
    "PENGU/USDT:USDT": 0.03,
    "ONDO/USDT:USDT":  0.04,
    "SOL/USDT:USDT":   0.05,
    "BTC/USDT:USDT":   0.05,
    "ETH/USDT:USDT":   0.05,
    "DEFAULT":         0.04,
}

_DEFAULT_SLIPPAGE_MULTIPLIERS: dict[str, float] = {
    "DOGE/USDT:USDT":  3.0,
    "PENGU/USDT:USDT": 2.5,
    "ONDO/USDT:USDT":  2.0,
    "DEFAULT":         1.0,
}

_TF_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360,
    "8h": 480, "12h": 720, "1d": 1440, "3d": 4320, "1w": 10080,
}


def _dynamic_risk_config(bot) -> dict:
    """Extract dynamic_risk config from bot (ai_signal_config or dynamic_risk_config)."""
    # Prefer dedicated column if it exists and has data
    if hasattr(bot, "dynamic_risk_config") and bot.dynamic_risk_config:
        return dict(bot.dynamic_risk_config)
    # Fallback to ai_signal_config nested key
    cfg = bot.ai_signal_config or {}
    return cfg.get("dynamic_risk", {})


def _merge_defaults(user_cfg: dict | list | None, defaults: dict | list) -> dict | list:
    """Shallow-merge user overrides on top of defaults.

    Handles both dict configs (thresholds, schedules) and list configs (levels).
    """
    if not user_cfg:
        if isinstance(defaults, list):
            return list(defaults)
        return dict(defaults)
    if isinstance(defaults, list):
        # For list configs (scale-out levels), return user override if provided,
        # otherwise return a copy of defaults.
        if isinstance(user_cfg, list):
            return list(user_cfg)
        return list(defaults)
    merged = dict(defaults)
    merged.update(user_cfg)
    return merged


# ═══════════════════════════════════════════════════════════
# 1. Emergency Brake
# ═══════════════════════════════════════════════════════════

class EmergencyBrake:
    """Reduce position size aggressively when drawdown exceeds symbol threshold.

    MVP: uses drawdown % only (no candle-rejection check) because TrailingWorker
    receives only price ticks, not full OHLC.  A future version can inject
    candle data from price_monitor.py.
    """

    @classmethod
    def evaluate(
        cls,
        position,
        current_price: Decimal,
        atr_14: Decimal | None = None,
        user_cfg: dict | None = None,
    ) -> dict:
        """Return action dict.

        Keys:
            action: "EMERGENCY_REDUCE" | "HOLD"
            reduce_by: float  (0.0–1.0)  only when action==EMERGENCY_REDUCE
            new_sl: float | None           suggested SL for remainder
            reason: str
        """
        extra = dict(position.extra_config or {})
        if extra.get("emergency_brake_triggered"):
            return {"action": "HOLD"}

        thresholds = _merge_defaults(
            (user_cfg or {}).get("thresholds"), _DEFAULT_EB_THRESHOLDS
        )
        cfg = thresholds.get(position.symbol, thresholds["DEFAULT"])
        activation = float(cfg.get("activation", 0.035))
        reduction = float(cfg.get("reduction", 0.70))

        entry = position.entry_price
        side = position.side

        if side == "long":
            drawdown_pct = float((entry - current_price) / entry)
        else:
            drawdown_pct = float((current_price - entry) / entry)

        if drawdown_pct <= 0:
            return {"action": "HOLD"}

        # Optional ATR-based floor
        if atr_14 and atr_14 > 0:
            atr_drawdown = float(atr_14 * Decimal("1.5") / entry)
            threshold = max(activation, atr_drawdown)
        else:
            threshold = activation

        if drawdown_pct >= threshold:
            return {
                "action": "EMERGENCY_REDUCE",
                "reduce_by": reduction,
                "new_sl": float(entry),  # breakeven for remainder
                "reason": (
                    f"emergency_brake: drawdown {drawdown_pct:.2%} >= "
                    f"threshold {threshold:.2%}"
                ),
            }

        return {"action": "HOLD"}


# ═══════════════════════════════════════════════════════════
# 2. Scale-Out Profit
# ═══════════════════════════════════════════════════════════

class ScaleOutProfit:
    """Systematically close portions of a winning position and advance SL."""

    @classmethod
    def evaluate(
        cls,
        position,
        current_price: Decimal,
        atr_14: Decimal | None = None,
        user_cfg: dict | None = None,
    ) -> dict:
        """Return action dict.

        Keys:
            action: "SCALE_OUT" | "HOLD"
            close_pct: float   (0.0–1.0)
            new_sl: float | None
            level: float       trigger level that fired
            reason: str
        """
        extra = dict(position.extra_config or {})
        hit_levels = set(extra.get("scale_out_levels_hit", []))

        levels = _merge_defaults(
            (user_cfg or {}).get("levels"), _DEFAULT_SCALE_OUT_LEVELS
        )

        entry = position.entry_price
        side = position.side

        if side == "long":
            profit_pct = float((current_price - entry) / entry)
        else:
            profit_pct = float((entry - current_price) / entry)

        if profit_pct <= 0:
            return {"action": "HOLD"}

        # Evaluate levels in ascending order; trigger the first unhit one
        for lvl in levels:
            trigger = float(lvl["trigger"])
            if trigger not in hit_levels and profit_pct >= trigger:
                move_sl_to = lvl.get("move_sl_to", "entry")
                new_sl = cls._resolve_sl(
                    position, move_sl_to, atr_14
                )
                return {
                    "action": "SCALE_OUT",
                    "close_pct": float(lvl["close"]),
                    "new_sl": new_sl,
                    "level": trigger,
                    "reason": f"scale_out: +{profit_pct:.2%} >= trigger {trigger:.2%}",
                }

        return {"action": "HOLD"}

    @classmethod
    def _resolve_sl(cls, position, move_sl_to: str, atr_14: Decimal | None) -> float | None:
        entry = float(position.entry_price)
        side = position.side
        tps = position.current_tp_prices or []

        if move_sl_to == "entry":
            return entry

        if move_sl_to == "entry_plus_0.5atr":
            if atr_14 and atr_14 > 0:
                buffer = float(atr_14) * 0.5
                return entry + buffer if side == "long" else entry - buffer
            return entry

        if move_sl_to == "tp1":
            tp1 = next((t for t in tps if t.get("level") == 1), None)
            if tp1:
                return float(tp1["price"]) * 0.95 if side == "long" else float(tp1["price"]) * 1.05
            return entry

        if move_sl_to == "trailing":
            # Signal to caller: keep existing trailing logic, don't force a static SL
            return None

        return entry


# ═══════════════════════════════════════════════════════════
# 3. Time Decay Exit
# ═══════════════════════════════════════════════════════════

class TimeDecayExit:
    """Exit a position if it hasn't moved favourably within a bar budget."""

    @classmethod
    def evaluate(
        cls,
        position,
        current_price: Decimal,
        user_cfg: dict | None = None,
        bot_timeframe: str | None = None,
    ) -> dict:
        """Return action dict.

        Keys:
            action: "TIME_EXIT" | "PROTECT_PROFIT" | "HOLD"
            reason: str
            new_sl: float | None   only for PROTECT_PROFIT
        """
        extra = dict(position.extra_config or {})
        if extra.get("time_decay_exited") or extra.get("time_decay_protected"):
            return {"action": "HOLD"}

        schedule = _merge_defaults(
            (user_cfg or {}).get("schedule"), _DEFAULT_TIME_DECAY
        )
        # Position model does not have timeframe; use bot_timeframe or fallback
        tf = bot_timeframe or getattr(position, "timeframe", None) or "15m"
        cfg = schedule.get(tf, schedule.get("15m", {"max_bars": 8, "profit_threshold": 0.008}))
        max_bars = int(cfg.get("max_bars", 8))
        profit_threshold = float(cfg.get("profit_threshold", 0.008))

        opened_at = position.opened_at
        if opened_at is None:
            return {"action": "HOLD"}
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)

        elapsed_min = (datetime.now(timezone.utc) - opened_at).total_seconds() / 60.0
        tf_min = _TF_MINUTES.get(tf, 15)
        # FASE 1K FIX: Añadir buffer del 30% para gaps de liquidez (fines de semana,
        # pausas en mercado). Además persistir conteo para no penalizar reevaluaciones.
        # El conteo real de barras de mercado requiere OHLCV; esto es un fallback.
        effective_max_bars = int(max_bars * 1.3)
        bars_since_entry = int(elapsed_min / tf_min)

        # Persistir último conteo para evitar cerrar prematuramente en reevaluaciones
        prev_bars = extra.get("time_decay_last_bars", 0)
        if bars_since_entry > prev_bars:
            extra["time_decay_last_bars"] = bars_since_entry
            # Nota: en producción esto debería guardarse en DB; aquí solo afecta
            # la evaluación actual del worker.

        if bars_since_entry < effective_max_bars:
            return {"action": "HOLD"}

        entry = position.entry_price
        side = position.side
        if side == "long":
            profit_pct = float((current_price - entry) / entry)
        else:
            profit_pct = float((entry - current_price) / entry)

        if profit_pct < profit_threshold:
            return {
                "action": "TIME_EXIT",
                "reason": (
                    f"time_decay: {bars_since_entry} bars >= {max_bars}, "
                    f"profit {profit_pct:.2%} < threshold {profit_threshold:.2%}"
                ),
            }

        # Time exceeded but profitable → protect profit
        buffer_pct = 0.002
        new_sl = float(entry * (Decimal("1") + Decimal(str(buffer_pct)))) if side == "long" else float(entry * (Decimal("1") - Decimal(str(buffer_pct))))
        return {
            "action": "PROTECT_PROFIT",
            "new_sl": new_sl,
            "reason": (
                f"time_decay_protect: {bars_since_entry} bars >= {max_bars}, "
                f"profit {profit_pct:.2%} >= threshold {profit_threshold:.2%}"
            ),
        }


# ═══════════════════════════════════════════════════════════
# 4. Exposure Cap by Symbol
# ═══════════════════════════════════════════════════════════

class ExposureCapBySymbol:
    """Pre-trade hard cap on aggregate risk per symbol across all open positions."""

    @classmethod
    def check(
        cls,
        symbol: str,
        proposed_risk_pct: float,
        open_positions: list,
        user_cfg: dict | None = None,
    ) -> dict:
        """Return dict with keys:
            allowed: bool
            reason: str   (empty when allowed)
            max_allowed: float | None   (remaining headroom in % terms)
            slippage_multiplier: float
        """
        caps = _merge_defaults(
            (user_cfg or {}).get("exposure_caps"), _DEFAULT_EXPOSURE_CAPS
        )
        slippage_mults = _merge_defaults(
            (user_cfg or {}).get("slippage_multipliers"), _DEFAULT_SLIPPAGE_MULTIPLIERS
        )

        cap = float(caps.get(symbol, caps["DEFAULT"]))
        slippage_mult = float(slippage_mults.get(symbol, slippage_mults["DEFAULT"]))

        # Sum current exposure for this exact symbol
        current_exposure = 0.0
        for pos in open_positions:
            if pos.symbol == symbol:
                # Prefer stored initial_risk_pct; fallback to rough estimate
                extra = dict(pos.extra_config or {})
                risk_pct = float(extra.get("initial_risk_pct", 0))
                # initial_risk_pct may be stored as percentage (e.g. 1.43) or decimal (0.0143)
                if risk_pct > 1.0:
                    risk_pct = risk_pct / 100.0
                if risk_pct <= 0 and pos.entry_price and pos.current_sl_price:
                    risk_pct = float(abs(pos.entry_price - pos.current_sl_price) / pos.entry_price)
                current_exposure += risk_pct

        total = current_exposure + proposed_risk_pct
        if total > cap:
            remaining = max(0.0, cap - current_exposure)
            return {
                "allowed": False,
                "reason": (
                    f"exposure_cap: {symbol} {current_exposure:.2%} + "
                    f"{proposed_risk_pct:.2%} > cap {cap:.2%}"
                ),
                "max_allowed": remaining,
                "slippage_multiplier": slippage_mult,
            }

        return {
            "allowed": True,
            "reason": "",
            "max_allowed": cap - total,
            "slippage_multiplier": slippage_mult,
        }
