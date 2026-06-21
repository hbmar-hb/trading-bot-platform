"""Confluence engine V2.1 — combines ICT + SMC into a scored trading setup.

Scoring breakdown (max ~100 pts):
  HTF Bias aligned      : +20
  Liquidity sweep       : +25
  Structure break type  : CHoCH +20 | BOS +12
  Entry trigger         : OB +12    | FVG +8
  Premium/Discount      : up to +15
  EQ obstacle penalty   : -8
  Killzone              : timing feature (no score base)
  Aligned FVGs          : feature only (no score base)

Confidence thresholds: HIGH ≥75, MEDIUM ≥55, LOW <55.

The anti-fake XGBoost + ensemble layers activate automatically once
≥200 labeled outcomes are available (tracked by OutcomeTracker).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from app.core.ict_engine import ICTResult, analyze as ict_analyze
from app.engines.smc_engine import SMCContext, analyze_smc, compute_atr, compute_adx
from app.engines.adaptive_trend_engine import analyze_adaptive_trend

_ADX_TREND_THRESHOLD = 25.0  # below this → ranging market

# V2.1 maximum confluence score (CHoCH 20 + OB 12 + FVG 8 + Sweep 25 + PD 15 + HTF 20)
# Used to normalize scores to the 0-100 range.
_MAX_CONFLUENCE_ABS = 100.0

# ── Adaptive weights ──────────────────────────────────────────────────────────
ADAPTIVE_WEIGHTS_PATH = "/app/ai/models/adaptive_weights.json"


def _load_adaptive_weights(ticker: str | None = None, timeframe: str | None = None, bot_id: str | None = None) -> dict[str, float]:
    """Load adaptive weights from XGBoost feature importance.
    Priority: bot-specific → ticker/timeframe-specific → global → empty.
    Returns empty dict if file missing or malformed."""
    try:
        import json
        with open(ADAPTIVE_WEIGHTS_PATH, "r") as f:
            payload = json.load(f)

        # Try bot-specific first
        if bot_id:
            by_bot = payload.get("by_bot", {})
            bot_weights = by_bot.get(bot_id)
            if bot_weights:
                return {k: float(v) for k, v in bot_weights.items()}

        # Try ticker-specific next
        if ticker and timeframe:
            by_ticker = payload.get("by_ticker", {})
            ticker_data = by_ticker.get(ticker.upper(), {})
            specific = ticker_data.get(timeframe)
            if specific:
                return {k: float(v) for k, v in specific.items()}

        # Fallback to global
        global_weights = payload.get("global", {})
        return {k: float(v) for k, v in global_weights.items()}
    except Exception:
        return {}


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ConfluenceResult:
    direction:  str    # 'long' | 'short'
    score:      float  # 0-100
    confidence: str    # 'HIGH' | 'MEDIUM' | 'LOW'

    entry_price:  float
    entry_zone:   tuple[float, float]
    stop_loss:    float
    take_profit_1: float
    take_profit_2: float
    risk_reward:  float  # TP1 R:R

    components: dict = field(default_factory=dict)
    features:   dict = field(default_factory=dict)
    warnings:   list = field(default_factory=list)
    explanation: str = ""

    ict: ICTResult = field(repr=False, default=None)
    smc: SMCContext = field(repr=False, default=None)

    # Forward structural exit levels (EQ highs/lows, FVGs ahead of price)
    forward_levels: list[dict] = field(default_factory=list)
    # Support/resistance levels behind entry for dynamic SL management
    support_levels: list[dict] = field(default_factory=list)
    # Recommended TP1 closure % based on distance between structural levels
    tp1_close_pct: float = 0.50


# ── Pure scoring (re-usable for bot-specific weight re-calculation) ───────────

# V2.1 configurable defaults (backwards-compatible: gates OFF or at current levels)
_DEFAULT_CONFLUENCE_CONFIG: dict = {
    "require_liquidity_sweep": {"enabled": False, "timeframes": ["15m", "1h"]},
    "pd_gate_strictness": 0.75,
    "asia_gate_enabled": True,
    "killzone_gate_mode": "disabled",  # "disabled" | "asia_only" | "strict"
}


def _compute_confluence_score(
    features: dict,
    direction: str,
    weights: dict,
    at_bonus: float = 0.0,
    mc_bonus: float = 0.0,
    entry_mid: float | None = None,
    apply_hard_gates: bool = True,
    timeframe: str | None = None,
    confluence_config: dict | None = None,
) -> tuple[float | None, dict, list]:
    """Re-compute confluence score from persisted features + optional weights.

    When ``apply_hard_gates=False`` (e.g. re-scoring an already-accepted signal
    in the activator), hard rejection gates (equilibrium, Asia hours, deep
    premium/discount) are skipped — only weight-dependent penalties/bonuses
    are applied.  This lets a bot with different adaptive weights re-evaluate
    the numeric score without re-running the full ICT/SMC market analysis.
    """
    cfg = {**_DEFAULT_CONFLUENCE_CONFIG, **(confluence_config or {})}
    is_long = direction == "long"
    ranging = features.get("market_regime") == "ranging"
    hour_utc = features.get("hour_utc", 12)
    score = 0.0
    components: dict = {}
    warnings: list = []

    def w(key: str, base: float) -> float:
        if not weights:
            return base
        return weights.get(key, base)

    # ── V2.1 Configurable Gates (applied before scoring) ─────────────────────
    if apply_hard_gates:
        # Gate 1: Liquidity sweep (optional, off by default for backwards compat)
        sweep_cfg = cfg.get("require_liquidity_sweep", {})
        if sweep_cfg.get("enabled", False):
            tf_list = sweep_cfg.get("timeframes", ["15m", "1h"])
            if timeframe in tf_list and not features.get("sweep_detected"):
                warnings.append("NO_LIQUIDITY_SWEEP — gate rejected")
                return None, {}, warnings

        # Gate 2: Premium/Discount strictness (default 0.75 = current behaviour)
        pd_strict = cfg.get("pd_gate_strictness", 0.75)
        pd_pos = features.get("pd_position", 0.5)
        if is_long and pd_pos > pd_strict:
            warnings.append(f"LONG en premium ({pd_pos:.2f}) > strictness {pd_strict} — gate rejected")
            return None, {}, warnings
        if not is_long and pd_pos < (1.0 - pd_strict):
            warnings.append(f"SHORT en discount ({pd_pos:.2f}) < {1.0 - pd_strict:.2f} — gate rejected")
            return None, {}, warnings

        # Gate 3: Asia session (default ON = current behaviour)
        if cfg.get("asia_gate_enabled", True) and 2 <= hour_utc <= 6:
            warnings.append(f"Hora UTC {hour_utc:02d}h en zona Asia — manipulación ARL, NO TRADE")
            return None, {}, warnings

        # Gate 4: Killzone (default disabled = current behaviour)
        kz_mode = cfg.get("killzone_gate_mode", "disabled")
        if kz_mode == "strict" and timeframe in ("15m", "1h"):
            kz_name, _, _ = _killzone_score(hour_utc, ranging)
            if kz_name is None:
                warnings.append(f"Fuera de killzone (UTC {hour_utc:02d}h) — gate rejected")
                return None, {}, warnings

    # ── Adaptive Trend (pre-computed bonus passed in) ────────────────────────
    score += at_bonus

    # ── V2.1 PILLAR 1: HTF Bias (20 pts) ─────────────────────────────────────
    if features.get("htf_aligned") is True:
        score += w("htf_bias", 20.0)
        components["htf_bias"] = "Sesgo HTF alineado +20pts"
    elif features.get("htf_bias") is not None:
        # HTF bias exists but not aligned — already gated or penalized upstream
        warnings.append("HTF bias presente pero no alineado — sin bonus")

    # ── V2.1 PILLAR 2: Liquidity sweep (25 pts) ──────────────────────────────
    if features.get("sweep_detected"):
        score += w("sweep", 25.0)
        sweep_type = features.get("sweep_type", "BSL")
        label = "Buy-Side (BSL)" if sweep_type == "BSL" else "Sell-Side (SSL)"
        components["sweep"] = f"Sweep de liquidez {label}"
    else:
        warn = "Sin sweep de liquidez previo — confluencia reducida"
        if ranging:
            warn += " (rango)"
        warnings.append(warn)

    # ── V2.1 PILLAR 3: Structure break (20 pts) ──────────────────────────────
    break_type = features.get("break_type")
    if break_type == "CHoCH":
        score += w("structure_CHoCH", 20.0)
        components["structure"] = "CHoCH — cambio de sesgo confirmado"
    elif break_type == "BOS":
        score += w("structure_BOS", 12.0)
        components["structure"] = "BOS — continuación de tendencia"

    # ── V2.1 PILLAR 4: POI Quality (20 pts) ──────────────────────────────────
    trigger = features.get("trigger")
    if trigger == "ob":
        score += w("trigger_OB", 12.0)
        components["trigger"] = "Order Block activo"
    elif trigger == "fvg":
        score += w("trigger_FVG", 8.0)
        components["trigger"] = "Fair Value Gap activo"

    # FVGs alineados: registrados como feature para ML pero NO suman score base
    # (FVG sin desplazamiento es ruido según diagnóstico V2.1)
    fvg_count = features.get("fvg_aligned_count", 0) or 0
    if fvg_count > 0:
        components["fvg_context"] = (
            f"{fvg_count} FVG{'s' if fvg_count > 1 else ''} "
            f"sin llenar alineado{'s' if fvg_count > 1 else ''}"
        )

    # ── V2.1 PILLAR 5: Premium / Discount (15 pts) ───────────────────────────
    pd_pos = features.get("pd_position", 0.5)
    if apply_hard_gates:
        # Hard gate: equilibrium puro
        if 0.45 < pd_pos < 0.55:
            warnings.append(f"Precio en equilibrium puro ({pd_pos:.2f}) — NO TRADE según SMC")
            return None, {}, warnings

    # PD Directional Guard (V2.1 rebalanceado)
    pd_strict = cfg.get("pd_gate_strictness", 0.75)
    if is_long:
        if apply_hard_gates and pd_pos > pd_strict:
            warnings.append(f"LONG en premium profundo ({pd_pos:.2f}) > {pd_strict} — NO TRADE")
            return None, {}, warnings
        elif pd_pos > 0.60:
            score -= w("pd_counter", 20.0)
            warnings.append(f"LONG en premium ({pd_pos:.2f}) — penalizado -20pts")
            components["pd_array"] = f"LONG en premium ({pd_pos:.2f}) — penalizado"
        elif pd_pos <= 0.20:
            score += w("pd_array", 15.0)
            components["pd_array"] = f"Precio en discount óptimo ({pd_pos:.2f})"
        elif pd_pos <= 0.30:
            score += w("pd_array", 10.0)
            components["pd_array"] = f"Precio en discount aceptable ({pd_pos:.2f})"
        elif pd_pos <= 0.45:
            score += w("pd_array", 5.0)
            components["pd_array"] = f"Precio en discount marginal ({pd_pos:.2f})"
            warnings.append(f"Precio en discount marginal ({pd_pos:.2f}) — riesgo moderado")
    else:  # short
        if apply_hard_gates and pd_pos < (1.0 - pd_strict):
            warnings.append(f"SHORT en discount profundo ({pd_pos:.2f}) < {1.0 - pd_strict:.2f} — NO TRADE")
            return None, {}, warnings
        elif pd_pos < 0.40:
            score -= w("pd_counter", 20.0)
            warnings.append(f"SHORT en discount ({pd_pos:.2f}) — penalizado -20pts")
            components["pd_array"] = f"SHORT en discount ({pd_pos:.2f}) — penalizado"
        elif pd_pos >= 0.80:
            score += w("pd_array", 15.0)
            components["pd_array"] = f"Precio en premium óptimo ({pd_pos:.2f})"
        elif pd_pos >= 0.70:
            score += w("pd_array", 10.0)
            components["pd_array"] = f"Precio en premium aceptable ({pd_pos:.2f})"
        elif pd_pos >= 0.55:
            score += w("pd_array", 5.0)
            components["pd_array"] = f"Precio en premium marginal ({pd_pos:.2f})"
            warnings.append(f"Precio en premium marginal ({pd_pos:.2f}) — riesgo moderado")

    # ── Killzone ─────────────────────────────────────────────────────────────
    # V2.1: Killzone ya no suma score base. Es timing feature para ML.
    # Solo aplica gate de Asia (ya cubierto arriba en gates configurables).
    kz, kz_score, kz_pts = _killzone_score(hour_utc, ranging)
    if kz:
        components["killzone"] = f"Killzone {kz} ({hour_utc:02d}h UTC)"
    else:
        warnings.append(f"Fuera de killzone óptima (hora UTC: {hour_utc:02d}h) — señal débil")

    # ── 7. EQ obstacle penalty ───────────────────────────────────────────────
    if entry_mid is not None:
        eq_highs_count = features.get("eq_highs_count", 0) or 0
        eq_lows_count = features.get("eq_lows_count", 0) or 0
        if is_long and eq_highs_count > 0:
            score -= w("eq_obstacle", 8.0)
            warnings.append("EQ High cercano actúa como techo")
        elif not is_long and eq_lows_count > 0:
            score -= w("eq_obstacle", 8.0)
            warnings.append("EQ Low cercano actúa como suelo")

    # ── Monte Carlo (pre-computed bonus passed in) ───────────────────────────
    score += mc_bonus

    # Normalize
    score = max(0.0, min(100.0, (score / _MAX_CONFLUENCE_ABS) * 100.0))

    return score, components, warnings


# ── Public API ─────────────────────────────────────────────────────────────────

def analyze_confluence(
    candles:    list[dict],
    ticker:     str,
    timeframe:  str,
    pivot_len:  int   = 5,
    atr_mult:   float = 0.3,
    atr_len:    int   = 14,
    entry_mode: str   = "ob_or_fvg",
    adaptive_params: dict | None = None,
    mc_context: "MCSetupContext | None" = None,
    signal_time: datetime | None = None,
    confluence_config: dict | None = None,
    htf_bias: str | None = None,
) -> Optional[ConfluenceResult]:
    """
    Run ICT + SMC analysis and return a scored ConfluenceResult.
    Returns None when the ICT engine finds no actionable signal.
    candles must be CLOSED candles only (exclude the current forming bar).
    
    adaptive_params: optional dict from scanner_regime_optimizer to override
    defaults based on current market regime.
    """
    # Apply adaptive overrides if provided (with explicit type casting)
    if adaptive_params:
        pivot_len  = int(adaptive_params.get("pivot_len", pivot_len))
        atr_mult   = float(adaptive_params.get("atr_mult", atr_mult))
        atr_len    = int(adaptive_params.get("atr_len", atr_len))
        entry_mode = str(adaptive_params.get("entry_mode", entry_mode))

    ict = ict_analyze(candles, pivot_len, atr_mult, atr_len, entry_mode)

    if ict.signal == "none" or ict.entry_zone is None:
        return None

    smc = analyze_smc(candles, ict)

    df        = pd.DataFrame(candles)[["open", "high", "low", "close", "volume"]].astype(float)
    atr_val   = compute_atr(df, atr_len)
    adx_val   = compute_adx(df, atr_len)
    is_long   = ict.signal == "long"
    direction = ict.signal
    ranging   = adx_val < _ADX_TREND_THRESHOLD  # True → reduce timing/sweep weights

    # ── Load adaptive weights (if available) ────────────────────────────────
    file_adaptive = _load_adaptive_weights(ticker, timeframe)

    # Merge: adaptive_params (from LLM regime optimizer) > file_adaptive > base
    merged_adaptive = dict(file_adaptive or {})
    if adaptive_params:
        # Map weight_* keys to the keys used by w()
        for key in [
            "structure_CHoCH", "structure_BOS",
            "trigger_OB", "trigger_FVG",
            "fvg_context", "sweep", "pd_array",
            "killzone", "eq_obstacle",
        ]:
            llm_key = f"weight_{key}"
            if llm_key in adaptive_params:
                merged_adaptive[key] = adaptive_params[llm_key]

    score      = 0.0
    components: dict = {}
    warnings:   list = []

    # ═══════════════════════════════════════════════════════════════════════════
    # DEFENSIVE INITIALIZATION — prevents UnboundLocalError if a future refactor
    # introduces a code path that skips an assignment block.
    # All variables that are conditionally assigned later MUST have a safe default.
    # ═══════════════════════════════════════════════════════════════════════════
    sl = 0.0
    risk = 0.0
    tp1 = 0.0
    tp2 = 0.0
    rr = 0.0
    tp1_source = ""
    tp2_source = ""
    sl_adjusted_by_mc = False
    tp_adjusted_by_mc = False
    confidence = "LOW"
    mc_bonus = 0.0
    mc_component = None
    at_bonus = 0.0
    at_component = None
    tp1_close_pct = 0.50
    tp1_distance_r = 1.5
    tp1_strength = 0.0
    forward_density = 0

    # ── Adaptive Trend Pro — directional confluence filter ───────────────────
    # Calls the trend-following engine based on ATR trailing stops.
    # It acts as an independent directional filter: if the trend engine
    # disagrees with ICT, we penalise score; if aligned, we bonus it.
    adaptive_trend = analyze_adaptive_trend(candles, ticker, timeframe)
    at_bonus = 0.0
    at_component = None
    if adaptive_trend:
        ict_dir = 1 if is_long else -1
        at_dir = adaptive_trend.trend
        cs = adaptive_trend.composite_score

        if ict_dir == at_dir:
            # Aligned — bonus proportional to trend confidence
            at_bonus = 8.0 + min(10.0, cs / 8.0)
            at_component = (
                f"Adaptive Trend aligned ({'bullish' if at_dir == 1 else 'bearish'}, "
                f"score={cs:.1f})"
            )
        elif adaptive_trend.confirmed_signal:
            # Divergence WITH confirmed signal — proportional penalty by confidence
            if cs > 60:
                at_bonus = -20.0
            elif cs > 30:
                at_bonus = -15.0
            else:
                at_bonus = -10.0
            at_component = (
                f"Adaptive Trend DIVERGENT (confirmed) — ICT={'LONG' if is_long else 'SHORT'} "
                f"vs Trend={'bullish' if at_dir == 1 else 'bearish'} "
                f"(score={cs:.1f}, penalty={at_bonus:.0f})"
            )
            warnings.append(at_component)
        else:
            # Divergence WITHOUT confirmed signal (ranging / low conviction)
            # Light penalty so high-score signals (65+) still pass
            at_bonus = -8.0
            at_component = (
                f"Adaptive Trend DIVERGENT (ranging) — ICT={'LONG' if is_long else 'SHORT'} "
                f"vs Trend={'bullish' if at_dir == 1 else 'bearish'} "
                f"(score={cs:.1f}, penalty=-8)"
            )
            warnings.append(at_component)

        # Extra confirmed-signal bonus (rare, but high conviction)
        if adaptive_trend.confirmed_signal and adaptive_trend.signal_direction == direction:
            at_bonus += 5.0
            at_component += " + confirmed flip"

        if at_component:
            components["adaptive_trend"] = at_component

    # ── Monte Carlo bonus (computed before pure scoring for component string) ─
    mc_bonus = 0.0
    mc_component = None
    if mc_context:
        mc_dir = mc_context.direction_bias
        mc_conf = mc_context.direction_confidence
        signal_dir = direction

        if mc_dir == signal_dir and mc_conf > 0.5:
            mc_bonus = 10.0 + min(15.0, mc_conf * 20)
            mc_component = f"MC Setup aligned ({mc_dir}, conf={mc_conf:.2f}) +{mc_bonus:.0f}"
        elif mc_dir != "neutral" and mc_dir != signal_dir and mc_conf > 0.7:
            mc_bonus = -20.0
            mc_component = f"MC Setup CONTRADICTS ({mc_dir} vs {signal_dir}, conf={mc_conf:.2f}) {mc_bonus:.0f}"
            warnings.append(mc_component)
        elif mc_dir != "neutral" and mc_dir != signal_dir:
            mc_bonus = -10.0
            mc_component = f"MC Setup mild contradiction ({mc_dir} vs {signal_dir}) {mc_bonus:.0f}"
            warnings.append(mc_component)

        if mc_context.best_entry_mode not in ("mixed", "unknown"):
            current_trigger = ict.trigger or "none"
            if current_trigger == mc_context.best_entry_mode:
                mc_bonus += 5.0
                if mc_component:
                    mc_component += ", entry_mode aligned +5"
            elif current_trigger != "none":
                mc_bonus -= 3.0
                if mc_component:
                    mc_component += ", entry_mode mismatch -3"

    entry_mid = (ict.entry_zone[0] + ict.entry_zone[1]) / 2

    # Build features snapshot for pure scoring (mirrors what is persisted to DB)
    _score_features = {
        "break_type": ict.last_break.kind if ict.last_break else None,
        "trigger": ict.trigger,
        "fvg_aligned_count": smc.fvg_aligned_count,
        "sweep_detected": smc.liquidity_sweep is not None,
        "sweep_type": smc.liquidity_sweep,
        "pd_position": round(smc.pd_position, 3),
        "eq_highs_count": len(ict.eq_highs),
        "eq_lows_count": len(ict.eq_lows),
        "hour_utc": signal_time.hour if signal_time else datetime.now(timezone.utc).hour,
        "day_of_week": signal_time.weekday() if signal_time else datetime.now(timezone.utc).weekday(),
        "market_regime": "ranging" if ranging else "trending",
        "htf_aligned": (
            (direction == "long" and htf_bias == "bull") or
            (direction == "short" and htf_bias == "bear")
        ) if htf_bias is not None else None,
    }

    score, components, warnings = _compute_confluence_score(
        _score_features,
        direction,
        merged_adaptive,
        at_bonus=at_bonus,
        mc_bonus=mc_bonus,
        entry_mid=entry_mid,
        apply_hard_gates=True,
        timeframe=timeframe,
        confluence_config=confluence_config,
    )
    if score is None:
        return None

    # Restore detailed component strings that only analyze_confluence can produce
    if at_component:
        components["adaptive_trend"] = at_component
    if mc_component:
        components["mc_setup"] = mc_component

    # MC high-confidence contradiction gate (post-normalization)
    if mc_context and mc_context.confidence_tier == "high" and mc_bonus <= -20 and score < 45:
        logger.info(f"[CONFLUENCE] {ticker}/{timeframe}: MC high-confidence contradiction, signal suppressed")
        return None

    if score >= 60:
        confidence = "HIGH"
    elif score >= 40:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # ── Levels ────────────────────────────────────────────────────────────────
    ez  = ict.entry_zone
    mid = (ez[0] + ez[1]) / 2

    # SL: ATR-based for LTF (15m/30m) to avoid noise-hits on micro EQ levels.
    # For HTF (1h+) use structural EQ levels which represent real support/resistance.
    # Evidence: PEPE 15m SL @ 0.003376 vs entry @ 0.003369 = 0.2% → impossible.
    # Score+Timeframe aware SL multipliers: tighter for lower timeframes
    _SL_ATR_MULT = {"15m": 1.5, "30m": 2.0, "1h": 2.0, "4h": 2.5}
    atr_sl_mult = _SL_ATR_MULT.get(timeframe, None)

    if is_long:
        if atr_sl_mult is not None:
            # LTF: force ATR-based SL, ignore micro EQ levels
            sl = ez[0] - atr_val * atr_sl_mult
            risk = mid - sl
            if risk <= 0:
                sl = mid * (1.0 - 0.01 * atr_sl_mult)
                risk = mid - sl
        else:
            # HTF: structural EQ levels
            valid_sl = [l for l in ict.eq_lows if l < mid] if ict.eq_lows else []
            sl   = max(valid_sl) if valid_sl else ez[0] - atr_val * 2.0
            risk = mid - sl
            if risk <= 0:
                sl   = mid * 0.99
                risk = mid - sl
    else:
        if atr_sl_mult is not None:
            # LTF: force ATR-based SL
            sl = ez[1] + atr_val * atr_sl_mult
            risk = sl - mid
            if risk <= 0:
                sl = mid * (1.0 + 0.01 * atr_sl_mult)
                risk = sl - mid
        else:
            # HTF: structural EQ levels
            valid_sl = [h for h in ict.eq_highs if h > mid] if ict.eq_highs else []
            sl   = min(valid_sl) if valid_sl else ez[1] + atr_val * 2.0
            risk = sl - mid
            if risk <= 0:
                sl   = mid * 1.01
                risk = sl - mid

    # TP1 / TP2: use forward structural levels (EQ, FVG) ahead of price
    forward = ict.forward_levels
    if len(forward) >= 2:
        tp1 = forward[0].price
        tp2 = forward[1].price
        tp1_source = forward[0].kind
        tp2_source = forward[1].kind
    elif len(forward) == 1:
        tp1 = forward[0].price
        tp2 = mid + risk * 2.0 if is_long else mid - risk * 2.0
        tp1_source = forward[0].kind
        tp2_source = "fallback_2R"
    else:
        tp1 = mid + risk * 1.5 if is_long else mid - risk * 1.5
        tp2 = mid + risk * 2.5 if is_long else mid - risk * 2.5
        tp1_source = "fallback_1.5R"
        tp2_source = "fallback_2.5R"

    # Ensure TP1 < TP2 for long, TP1 > TP2 for short
    if is_long and tp2 <= tp1:
        tp2 = tp1 + risk * 0.5
    elif not is_long and tp2 >= tp1:
        tp2 = tp1 - risk * 0.5

    # ── VALIDACIÓN: TP1 debe estar al menos a 1.5× la distancia del SL ──
    # Esto garantiza R:R mínimo de 1.5:1 incluso cuando forward levels
    # estructurales están muy cerca del entry.
    min_tp1 = mid + risk * 1.5 if is_long else mid - risk * 1.5
    if is_long and tp1 < min_tp1:
        tp1 = min_tp1
        tp1_source = f"{tp1_source}_min1.5R"
        warnings.append(f"TP1 extended to minimum 1.5×SL ({abs(tp1-mid)/mid*100:.2f}%)")
    elif not is_long and tp1 > min_tp1:
        tp1 = min_tp1
        tp1_source = f"{tp1_source}_min1.5R"
        warnings.append(f"TP1 extended to minimum 1.5×SL ({abs(tp1-mid)/mid*100:.2f}%)")

    rr = abs(tp1 - mid) / risk if risk > 0 else 0.0

    # Apply MC Setup ranges to SL/TP if available
    sl_adjusted_by_mc = False
    tp_adjusted_by_mc = False
    if mc_context:
        # Adjust SL to fall within MC historical range
        mc_sl_median = mc_context.sl_range.get("median_pct", 0.025)
        mc_sl_max = mc_context.sl_range.get("max_pct", 0.05)
        risk_pct = (risk / mid * 100) if risk > 0 else 0.0
        if risk_pct > 0:
            if risk_pct > mc_sl_max * 100 * 1.5:
                # SL too wide → tighten to MC max
                new_sl = mid * (1.0 - mc_sl_max) if is_long else mid * (1.0 + mc_sl_max)
                sl = new_sl
                risk = abs(mid - sl)
                sl_adjusted_by_mc = True
                warnings.append(f"SL tightened by MC setup (was {risk_pct:.2f}%, now {mc_sl_max*100:.2f}%)")
            elif risk_pct < mc_context.sl_range.get("min_pct", 0.01) * 100 * 0.5:
                # SL too tight → widen to MC median
                new_sl = mid * (1.0 - mc_sl_median) if is_long else mid * (1.0 + mc_sl_median)
                sl = new_sl
                risk = abs(mid - sl)
                sl_adjusted_by_mc = True
                warnings.append(f"SL widened by MC setup (was {risk_pct:.2f}%, now {mc_sl_median*100:.2f}%)")

        # Adjust TP to align with MC historical range
        mc_tp_median = mc_context.tp_range.get("median_pct", 0.04)
        current_tp1_pct = abs(tp1 - mid) / mid
        if current_tp1_pct < mc_tp_median * 0.5:
            # TP too close → extend to MC median
            tp1 = mid * (1.0 + mc_tp_median) if is_long else mid * (1.0 - mc_tp_median)
            tp_adjusted_by_mc = True
            warnings.append(f"TP1 extended by MC setup to {mc_tp_median*100:.2f}%")

        # Recalculate RR and ensure TP ordering after MC adjustments
        if sl_adjusted_by_mc or tp_adjusted_by_mc:
            rr = abs(tp1 - mid) / risk if risk > 0 else 0.0
            if is_long and tp2 <= tp1:
                tp2 = tp1 + risk * 0.5
            elif not is_long and tp2 >= tp1:
                tp2 = tp1 - risk * 0.5

    # Dynamic TP1 closure % based on distance to first structural level
    # Close LESS in TP1 if the first target is close (price likely reaches 2nd target)
    # Close MORE in TP1 if the first target is far (harder to reach)
    if len(forward) >= 1:
        dist_r = forward[0].distance_pct / (risk / mid * 100) if risk > 0 else 1.5
        if dist_r < 0.8:
            tp1_close_pct = 0.35   # 1st level very close → let 65% run to 2nd
        elif dist_r < 1.5:
            tp1_close_pct = 0.50   # moderate distance → balanced 50/50
        else:
            tp1_close_pct = 0.65   # 1st level far → take 65% at TP1
    else:
        tp1_close_pct = 0.50

    # ── Ensemble indicators (RSI / Stoch / Volume Profile) ──────────────────
    rsi_val = _compute_rsi(df["close"], 14)
    stoch_k, stoch_d = _compute_stoch(df, 14, 3, 3)
    poc = _compute_volume_profile_poc(df, 20)

    # ── Features for future ML training ──────────────────────────────────────
    last = df.iloc[-1]
    vol_avg = float(df["volume"].iloc[-20:].mean()) if len(df) >= 20 else float(df["volume"].mean())

    # ATR history para dynamic leverage (últimos 30 valores, truncados)
    atr_series = pd.Series(
        pd.concat([
            (df["high"] - df["low"]),
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        .rolling(atr_len).mean()
        .dropna()
        .values
    )
    atr_history = [round(float(v), 6) for v in atr_series.tolist()[-30:]]

    # Serialize forward and support levels for storage / downstream use
    forward_levels_serial = [
        {"price": round(l.price, 6), "kind": l.kind, "distance_pct": l.distance_pct, "liquidity_type": l.liquidity_type}
        for l in forward
    ]
    support_levels_serial = [
        {"price": round(l.price, 6), "kind": l.kind, "distance_pct": l.distance_pct}
        for l in ict.support_levels
    ]

    # POI strength map (mirrors ict_engine.py)
    _poi_strength = {
        "eq_high": 1.00, "eq_low": 1.00,
        "swing_high": 0.95, "swing_low": 0.95,
        "breaker_block_bear": 0.88, "breaker_block_bull": 0.88,
        "ob_bear": 0.82, "ob_bull": 0.82,
        "fvg_bear": 0.70, "fvg_bull": 0.70,
    }

    # Forward-level-derived features for ML training
    risk_pct = (risk / mid * 100) if risk > 0 else 0.0
    if forward and risk_pct > 0:
        tp1_distance_r = round(forward[0].distance_pct / risk_pct, 3)
        tp1_strength = round(_poi_strength.get(forward[0].kind, 0.5), 2)
        forward_density = len(forward)
    else:
        # Fallback mechanical: model learns that 1.5R mechanical != 0.8R structural
        tp1_distance_r = 1.5
        tp1_strength = 0.0
        forward_density = 0

    # pd_score, killzone vars were computed inside _compute_confluence_score;
    # recompute here for features persistence
    pd_score = max(0.0, 1.0 - abs(smc.pd_position - 0.5) * 2.0)
    hour_utc = signal_time.hour if signal_time else datetime.now(timezone.utc).hour
    kz, kz_score, kz_pts = _killzone_score(hour_utc, ranging)

    features = {
        "break_type":        ict.last_break.kind if ict.last_break else None,
        "trigger":           ict.trigger,
        "bias":              ict.bias,
        "fvg_aligned_count": smc.fvg_aligned_count,
        "ob_distance_atr":   round(smc.ob_distance_atr, 3) if smc.ob_distance_atr is not None else None,
        "sweep_detected":    smc.liquidity_sweep is not None,
        "sweep_type":        smc.liquidity_sweep,
        "pd_position":       round(smc.pd_position, 3),
        "pd_score":          round(pd_score, 3),
        "trading_range":     smc.trading_range,
        "killzone":          kz,
        "killzone_score":    round(kz_score, 3),
        "hour_utc":          hour_utc,
        "day_of_week":       datetime.now(timezone.utc).weekday(),
        "eq_highs_count":    len(ict.eq_highs),
        "eq_lows_count":     len(ict.eq_lows),
        "volume_ratio":      round(float(last["volume"]) / vol_avg, 3) if vol_avg > 0 else 1.0,
        "spread_atr":        round(float(last["high"] - last["low"]) / atr_val, 3) if atr_val > 0 else 0.0,
        "atr_value":         round(float(atr_val), 6),
        "atr_history":       atr_history,
        "adx":               round(adx_val, 1),
        "market_regime":     "ranging" if ranging else "trending",
        "at_bonus":          round(at_bonus, 1),
        "mc_bonus":          round(mc_bonus, 1),
        "score":             round(score, 1),
        # Forward structural levels for exit management
        "forward_levels":    forward_levels_serial,
        "support_levels":    support_levels_serial,
        "tp1_source":        tp1_source,
        "tp2_source":        tp2_source,
        "tp1_close_pct":     tp1_close_pct,
        # Forward-level ML features (P0)
        "tp1_distance_r":    tp1_distance_r,
        "tp1_strength":      tp1_strength,
        "forward_density":   forward_density,
        # Ensemble indicators
        "rsi":               round(rsi_val, 1),
        "stoch_k":           round(stoch_k, 1),
        "stoch_d":           round(stoch_d, 1),
        "poc":               round(poc, 4) if poc is not None else None,
        # Adaptive Trend Pro features (directional confluence)
        **(adaptive_trend.features if adaptive_trend else {}),
        # MC Setup features
        **({
            "mc_setup_score": mc_context.mc_validation.get("score", 0) if mc_context else None,
            "mc_direction_bias": mc_context.direction_bias if mc_context else None,
            "mc_direction_confidence": mc_context.direction_confidence if mc_context else None,
            "mc_confidence_tier": mc_context.confidence_tier if mc_context else None,
            "mc_win_rate_long": mc_context.win_rate_long if mc_context else None,
            "mc_win_rate_short": mc_context.win_rate_short if mc_context else None,
            "mc_sharpe": mc_context.sharpe_ratio if mc_context else None,
            "mc_max_dd": mc_context.max_drawdown_pct if mc_context else None,
            "mc_profit_factor": mc_context.profit_factor if mc_context else None,
            "mc_total_trades": mc_context.total_trades if mc_context else None,
            "sl_adjusted_by_mc": sl_adjusted_by_mc if mc_context else False,
            "tp_adjusted_by_mc": tp_adjusted_by_mc if mc_context else False,
        }),
    }

    explanation = _build_explanation(direction, score, components)

    return ConfluenceResult(
        direction     = direction,
        score         = round(score, 1),
        confidence    = confidence,
        entry_price   = round(mid, 6),
        entry_zone    = (ez[0], ez[1]),
        stop_loss     = round(sl, 6),
        take_profit_1 = round(tp1, 6),
        take_profit_2 = round(tp2, 6),
        risk_reward   = round(rr, 2),
        components    = components,
        features      = features,
        warnings      = warnings,
        explanation   = explanation,
        ict           = ict,
        smc           = smc,
        forward_levels= forward_levels_serial,
        support_levels= support_levels_serial,
        tp1_close_pct = tp1_close_pct,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _killzone_score(hour: int, ranging: bool) -> tuple[str | None, float, float]:
    """Return (killzone_name, killzone_score_0_1, score_points).

    Hybrid approach: gate duro SOLO para Asia 02-06 UTC (manipulación ARL).
    Todo lo demás pasa como feature gradual para que XGBoost aprenda.

    killzone_score:
        1.0  → London-NY overlap (13-16 UTC)  máxima volatilidad
        0.8  → London (7-10) o NY (13-16)
        0.5  → Pre-NY (11-12)
        0.3  → Post-NY (17-20)
        0.2  → Asia early (00-01, 07) o Late (21-23)
        0.1  → Off hours (todo lo demás)
    """
    # Points multiplier: ranging markets benefit more from killzone timing
    base_pts = 5.0 if ranging else 10.0

    if 13 <= hour <= 16:
        return "London_NY_overlap", 1.0, base_pts * 1.2
    if 7 <= hour <= 10:
        return "London", 0.8, base_pts
    if 11 <= hour <= 12:
        return "Pre_NY", 0.5, base_pts * 0.6
    if 17 <= hour <= 20:
        return "Post_NY", 0.3, base_pts * 0.4
    if hour in (0, 1, 21, 22, 23):
        return "Late/Early", 0.2, base_pts * 0.2
    return None, 0.1, 0.0


def _build_explanation(direction: str, score: float, components: dict) -> str:
    label = "LONG" if direction == "long" else "SHORT"
    lines = [f"Setup {label} — confluencia {score:.0f}/100"]
    for v in components.values():
        lines.append(f"• {v}")
    return "\n".join(lines)


# ── Technical indicators for ensemble confirmation ────────────────────────────

def _compute_rsi(series: pd.Series, period: int = 14) -> float:
    """Return last RSI value."""
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    last = rsi.iloc[-1]
    return float(last) if pd.notna(last) else 50.0


def _compute_stoch(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> tuple[float, float]:
    """Return (stoch_k, stoch_d) last values."""
    if len(df) < k + smooth + d - 1:
        return 50.0, 50.0
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    stoch_k_raw = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, 1e-10)
    stoch_k = stoch_k_raw.rolling(smooth).mean()
    stoch_d = stoch_k.rolling(d).mean()
    k_val = stoch_k.iloc[-1]
    d_val = stoch_d.iloc[-1]
    return (
        float(k_val) if pd.notna(k_val) else 50.0,
        float(d_val) if pd.notna(d_val) else 50.0,
    )


def _compute_volume_profile_poc(df: pd.DataFrame, bins: int = 20) -> float | None:
    """Return Price of Control (POC) = price level with highest volume."""
    if len(df) < bins:
        return None
    # Bin prices and sum volume per bin
    price_vol = df.groupby(pd.cut(df["close"], bins=bins), observed=False)["volume"].sum()
    if price_vol.empty or price_vol.isna().all():
        return None
    poc_bin = price_vol.idxmax()
    return float(poc_bin.mid) if hasattr(poc_bin, "mid") else float(poc_bin.left)
