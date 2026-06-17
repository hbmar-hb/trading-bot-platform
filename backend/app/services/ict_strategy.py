"""
Smart Money Engine signal strategy.
Generates long/short signals from SmeOutput.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from app.services.ict_engine import SmeOutput, SmeBox, Candle, SmartMoneyEngine, IndicatorConfig, StructureConfig, OBConfig, FVGConfig, IFVGConfig, FibConfig


# ── Output ───────────────────────────────────────────────────────────────────

@dataclass
class ICTSignal:
    direction:        str    # 'long' | 'short' | 'none'
    strength:         str    # 'strong' | 'medium' | 'weak' | 'none'
    entry_price:      float
    stop_loss:        float
    take_profit_1:    float
    take_profit_2:    float
    take_profit_3:    float
    take_profit_4:    float
    take_profit_5:    float
    risk_reward_1:    float
    risk_reward_2:    float
    risk_reward_3:    float
    risk_reward_4:    float
    risk_reward_5:    float
    risk_pct:         float
    confluence_score: int    # 0-12
    bias:             str
    setup_type:       str
    poi_type:         str
    poi_id:           str
    poi_top:          float
    poi_bottom:       float
    notes:            List[str] = field(default_factory=list)
    grade:            str = ''
    entry_time:       int = 0

    def to_dict(self) -> dict:
        return {
            "direction":        self.direction,
            "strength":         self.strength,
            "grade":            self.grade,
            "entry_price":      round(self.entry_price, 4),
            "stop_loss":        round(self.stop_loss, 4),
            "take_profit_1":    round(self.take_profit_1, 4),
            "take_profit_2":    round(self.take_profit_2, 4),
            "take_profit_3":    round(self.take_profit_3, 4),
            "take_profit_4":    round(self.take_profit_4, 4),
            "take_profit_5":    round(self.take_profit_5, 4),
            "risk_reward_1":    round(self.risk_reward_1, 2),
            "risk_reward_2":    round(self.risk_reward_2, 2),
            "risk_reward_3":    round(self.risk_reward_3, 2),
            "risk_reward_4":    round(self.risk_reward_4, 2),
            "risk_reward_5":    round(self.risk_reward_5, 2),
            "risk_pct":         self.risk_pct,
            "confluence_score": self.confluence_score,
            "bias":             self.bias,
            "setup_type":       self.setup_type,
            "poi_type":         self.poi_type,
            "poi_id":           self.poi_id,
            "poi_top":          round(self.poi_top, 4),
            "poi_bottom":       round(self.poi_bottom, 4),
            "notes":            self.notes,
            "entry_time":       self.entry_time,
        }

    @staticmethod
    def none_signal() -> "ICTSignal":
        return ICTSignal(
            direction='none', strength='none', grade='',
            entry_price=0, stop_loss=0,
            take_profit_1=0, take_profit_2=0, take_profit_3=0,
            take_profit_4=0, take_profit_5=0,
            risk_reward_1=0, risk_reward_2=0, risk_reward_3=0,
            risk_reward_4=0, risk_reward_5=0,
            risk_pct=0, confluence_score=0,
            bias='neutral', setup_type='none',
            poi_type='none', poi_id='', poi_top=0, poi_bottom=0,
        )


# ── Strategy config ──────────────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    min_score:                int   = 4
    poi_proximity_pct:        float = 0.5   # % from price to consider "at POI"
    stop_buffer_pct:          float = 0.15
    rr_tp1:                   float = 1.5
    rr_tp2:                   float = 3.0
    rr_tp3:                   float = 5.0
    rr_tp4:                   float = 7.0
    rr_tp5:                   float = 10.0
    default_risk_pct:         float = 1.0
    require_sweep:            bool  = False
    reject_asia:              bool  = False
    reject_equilibrium:       bool  = False
    min_rr:                   float = 1.2
    use_structural_sl_tp:     bool  = True
    max_sl_pct:               float = 0.02
    min_sl_pct:               float = 0.003
    recent_structure_bars:    int   = 30
    sl_tp_recency_bars:       int   = 20
    require_premium_discount: bool  = False
    pd_lookback:              int   = 50
    min_pd_distance:          float = 0.0
    require_htf_alignment:    bool  = False
    htf_min_strength:         float = 0.0
    use_volume:               bool  = True
    vol_spike_threshold:      float = 1.5


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _compute_atr(candles: List[Candle], length: int = 14) -> float:
    if len(candles) < length + 1:
        return 0.0
    trs = []
    for i in range(-length, 0):
        c = candles[i]
        p = candles[i - 1]
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        trs.append(tr)
    return _mean(trs)


def _compute_pd_position(candles: List[Candle], lookback: int = 50) -> float:
    if len(candles) < 5:
        return 0.5
    window = candles[-lookback:] if len(candles) > lookback else candles
    highs = [c.high for c in window]
    lows  = [c.low for c in window]
    range_h = max(highs)
    range_l = min(lows)
    if range_h == range_l:
        return 0.5
    return (candles[-1].close - range_l) / (range_h - range_l)


def _vol_spike(candles: List[Candle], threshold: float = 1.5, length: int = 20) -> bool:
    if len(candles) < length + 1:
        return False
    volumes = [c.volume for c in candles[-length - 1:-1]]
    if not any(volumes):
        return False
    avg = sum(volumes) / len(volumes)
    return candles[-1].volume > avg * threshold


def _detect_liquidity_sweep(candles: List[Candle], direction: str,
                            swing_low: Optional[float], swing_high: Optional[float],
                            lookback_bars: int = 8) -> bool:
    if len(candles) < lookback_bars + 1:
        return False
    recent = candles[-lookback_bars:]
    is_long = direction == "long"
    if is_long and swing_low is not None:
        for c in recent:
            if c.low < swing_low and c.close > swing_low:
                return True
    elif not is_long and swing_high is not None:
        for c in recent:
            if c.high > swing_high and c.close < swing_high:
                return True
    return False


# ── Structural SL/TP ─────────────────────────────────────────────────────────

def _build_structural_levels(
    output: SmeOutput,
    direction: str,
    entry: float,
    score: int,
    candles: List[Candle],
    scfg: StrategyConfig,
) -> Tuple[float, float, float, float, float, float]:
    is_long = direction == "long"
    atr = _compute_atr(candles)
    buffer_mult = 0.5 if score >= 6 else (1.0 if score >= 4 else 1.5)
    atr_buffer = atr * buffer_mult if atr > 0 else entry * 0.005

    n = len(candles)
    bar_ms = candles[-1].time - candles[-2].time if n >= 2 else 0
    recent_ms = bar_ms * scfg.sl_tp_recency_bars
    cutoff = candles[-1].time - recent_ms if recent_ms > 0 and n >= 2 else 0

    def _recent(t: int) -> bool:
        return t >= cutoff

    # SL candidates
    sl_candidates = []
    for box in output.boxes:
        if box.type == "OB":
            if is_long and box.direction == "bull" and box.bottom < entry:
                sl_candidates.append(box.bottom)
            elif not is_long and box.direction == "bear" and box.top > entry:
                sl_candidates.append(box.top)
        elif box.type == "FVG":
            if is_long and box.direction == "bull" and box.bottom < entry:
                sl_candidates.append(box.bottom)
            elif not is_long and box.direction == "bear" and box.top > entry:
                sl_candidates.append(box.top)

    for line in output.lines:
        if line.type in ("STRONG", "FIB"):
            if is_long and line.price < entry:
                sl_candidates.append(line.price)
            elif not is_long and line.price > entry:
                sl_candidates.append(line.price)

    if is_long:
        if sl_candidates:
            raw_sl = max(p for p in sl_candidates)
            sl = raw_sl - atr_buffer
        else:
            sl = entry - atr_buffer
    else:
        if sl_candidates:
            raw_sl = min(p for p in sl_candidates)
            sl = raw_sl + atr_buffer
        else:
            sl = entry + atr_buffer

    # Clamp SL
    risk_distance = abs(entry - sl)
    risk_pct = risk_distance / entry if entry > 0 else 0.0
    if risk_pct > scfg.max_sl_pct:
        sl = entry * (1 - scfg.max_sl_pct) if is_long else entry * (1 + scfg.max_sl_pct)
    elif risk_pct < scfg.min_sl_pct:
        sl = entry * (1 - scfg.min_sl_pct) if is_long else entry * (1 + scfg.min_sl_pct)
    risk_distance = abs(entry - sl)
    if risk_distance <= 0:
        risk_distance = entry * 0.003

    # TP candidates
    def _r_for(price: float) -> float:
        return abs(price - entry) / risk_distance if risk_distance > 0 else 0.0

    tp_candidates = []
    for box in output.boxes:
        if box.type == "OB":
            if is_long and box.direction == "bear" and box.top > entry:
                tp_candidates.append(box.top)
            elif not is_long and box.direction == "bull" and box.bottom < entry:
                tp_candidates.append(box.bottom)
        elif box.type == "FVG":
            if is_long and box.direction == "bear" and box.top > entry:
                tp_candidates.append(box.top)
            elif not is_long and box.direction == "bull" and box.bottom < entry:
                tp_candidates.append(box.bottom)

    for line in output.lines:
        if line.type in ("STRONG", "FIB"):
            if is_long and line.price > entry:
                tp_candidates.append(line.price)
            elif not is_long and line.price < entry:
                tp_candidates.append(line.price)

    tp_candidates = sorted(set(tp_candidates), key=lambda p: abs(p - entry))
    tp_prices = []
    for p in tp_candidates:
        if len(tp_prices) >= 5:
            break
        if _r_for(p) >= scfg.min_rr:
            tp_prices.append(p)

    rr_targets = [scfg.rr_tp1, scfg.rr_tp2, scfg.rr_tp3, scfg.rr_tp4, scfg.rr_tp5]
    for i in range(5):
        if len(tp_prices) > i:
            continue
        fallback = entry + risk_distance * rr_targets[i] if is_long else entry - risk_distance * rr_targets[i]
        tp_prices.append(fallback)

    if is_long:
        tp_prices = sorted(tp_prices)
    else:
        tp_prices = sorted(tp_prices, reverse=True)

    return (sl, *tp_prices[:5])


# ── Signal engine ────────────────────────────────────────────────────────────

def _find_poi(output: SmeOutput, price: float, direction: str, prox: float) -> Tuple[Optional[SmeBox], str, str]:
    is_long = direction == "long"
    for box in output.boxes:
        if box.type not in ("OB", "FVG"):
            continue
        bias_ok = (is_long and box.direction == "bull") or (not is_long and box.direction == "bear")
        if not bias_ok:
            continue
        inside = box.bottom <= price <= box.top
        dist_to_box = min(abs(price - box.top), abs(price - box.bottom)) / price
        near = dist_to_box < prox
        if inside or near:
            if box.type == "OB":
                return box, "OB", "OB_RETEST"
            return box, "FVG", "FVG_FILL"
    return None, "none", "none"


def generate_ict_signal(
    output: SmeOutput,
    current_price: float,
    strategy_config: Optional[StrategyConfig] = None,
    candles: Optional[List[Candle]] = None,
) -> ICTSignal:
    scfg = strategy_config or StrategyConfig()

    swing_trend = output.dashboard.swing_trend if output.dashboard else "ranging"
    internal_trend = output.dashboard.internal_trend if output.dashboard else "ranging"
    htf_direction = output.htf_bias.get("direction", "neutral") if output.htf_bias else "neutral"
    htf_strength = output.htf_bias.get("strength", 0.0) if output.htf_bias else 0.0

    pd_pos = 0.5
    if candles and len(candles) >= 5:
        pd_pos = _compute_pd_position(candles, scfg.pd_lookback)

    vol_spike = False
    if scfg.use_volume and candles:
        vol_spike = _vol_spike(candles, scfg.vol_spike_threshold)

    prox = scfg.poi_proximity_pct / 100.0

    n = len(candles) if candles else 0
    bar_ms = candles[-1].time - candles[-2].time if n >= 2 else 0
    last_time = candles[-1].time if n else 0
    recent_cutoff = last_time - bar_ms * scfg.recent_structure_bars if bar_ms else 0

    candidates = []

    # ── Strategy 1: trade fresh structure breaks (BOS / CHoCH) ─────────────────
    for line in output.lines:
        if line.type not in ("BOS", "CHoCH", "INTERNAL_BOS", "INTERNAL_CHoCH"):
            continue
        # Only consider breaks that happened on the last candle or very recently.
        # end_time marks the confirming close, so we use that for recency.
        if line.end_time < recent_cutoff:
            continue

        direction = "long" if line.direction == "bull" else "short"
        is_long = direction == "long"
        score = 0
        notes = []
        setup_type = line.type

        if line.type in ("BOS", "CHoCH"):
            score += 2
            notes.append(f"Swing {line.label} ({line.direction})")
        else:
            score += 1
            notes.append(f"Internal {line.label} ({line.direction})")

        if swing_trend == ("bull" if is_long else "bear"):
            score += 1
            notes.append("Swing trend aligned")
        if internal_trend == ("bull" if is_long else "bear"):
            score += 1
            notes.append("Internal trend aligned")

        htf_aligned = htf_direction == ("bull" if is_long else "bear") and htf_strength >= scfg.htf_min_strength
        if htf_aligned:
            score += 1
            notes.append(f"HTF {htf_direction} aligned")

        if vol_spike:
            score += 1
            notes.append("Volume spike")

        if scfg.require_premium_discount:
            if is_long and pd_pos > 0.4 + scfg.min_pd_distance:
                continue
            if not is_long and pd_pos < 0.6 - scfg.min_pd_distance:
                continue

        poi, poi_type, poi_setup = _find_poi(output, current_price, direction, prox)
        if poi is not None:
            score += 2
            notes.append(f"Price at {poi_type} ({poi.direction})")
            if poi.grade in ("A", "B"):
                score += 1
                notes.append(f"{poi_type} grade {poi.grade}")

        if scfg.require_sweep:
            fib_high = output.dashboard.fib_high if output.dashboard else None
            fib_low = output.dashboard.fib_low if output.dashboard else None
            sweep = _detect_liquidity_sweep(candles or [], direction, swing_low=fib_low, swing_high=fib_high)
            if not sweep:
                continue
            notes.append("Liquidity sweep confirmed")

        candidates.append((score, direction, poi, poi_type, setup_type, notes, line.start_time))

    # ── Strategy 2: POI retest when no fresh structure break ───────────────────
    if not candidates:
        for direction in ("long", "short"):
            is_long = direction == "long"
            score = 0
            notes = []

            if swing_trend == ("bull" if is_long else "bear"):
                score += 1
                notes.append("Swing trend aligned")
            if internal_trend == ("bull" if is_long else "bear"):
                score += 1
                notes.append("Internal trend aligned")

            htf_aligned = htf_direction == ("bull" if is_long else "bear") and htf_strength >= scfg.htf_min_strength
            if htf_aligned:
                score += 1
                notes.append(f"HTF {htf_direction} aligned")

            if vol_spike:
                score += 1
                notes.append("Volume spike")

            if scfg.require_premium_discount:
                if is_long and pd_pos > 0.4 + scfg.min_pd_distance:
                    continue
                if not is_long and pd_pos < 0.6 - scfg.min_pd_distance:
                    continue

            poi, poi_type, setup_type = _find_poi(output, current_price, direction, prox)
            if poi is None:
                continue
            score += 2
            notes.append(f"Price at {poi_type} ({poi.direction})")
            if poi.grade in ("A", "B"):
                score += 1
                notes.append(f"{poi_type} grade {poi.grade}")

            if scfg.require_sweep:
                fib_high = output.dashboard.fib_high if output.dashboard else None
                fib_low = output.dashboard.fib_low if output.dashboard else None
                sweep = _detect_liquidity_sweep(candles or [], direction, swing_low=fib_low, swing_high=fib_high)
                if not sweep:
                    continue
                notes.append("Liquidity sweep confirmed")

            candidates.append((score, direction, poi, poi_type, setup_type, notes, last_time))

    if not candidates:
        return ICTSignal.none_signal()

    candidates.sort(key=lambda x: x[0], reverse=True)
    score, direction, poi, poi_type, setup_type, notes, entry_time = candidates[0]

    if scfg.require_htf_alignment:
        htf_ok = htf_direction == ("bull" if direction == "long" else "bear") and htf_strength >= scfg.htf_min_strength
        if not htf_ok:
            return ICTSignal.none_signal()

    if score < scfg.min_score:
        return ICTSignal.none_signal()

    if scfg.reject_asia and candles:
        try:
            hour_utc = datetime.fromtimestamp(candles[-1].time / 1000, tz=timezone.utc).hour
            if 2 <= hour_utc <= 6:
                return ICTSignal.none_signal()
        except Exception:
            pass

    if scfg.reject_equilibrium and candles:
        if 0.45 < pd_pos < 0.55:
            return ICTSignal.none_signal()

    entry = current_price
    if scfg.use_structural_sl_tp and candles:
        stop, tp1, tp2, tp3, tp4, tp5 = _build_structural_levels(output, direction, entry, score, candles, scfg)
    else:
        buf_pct = scfg.stop_buffer_pct / 100
        if poi is not None:
            if direction == "long":
                stop = poi.bottom * (1 - buf_pct)
            else:
                stop = poi.top * (1 + buf_pct)
        else:
            atr = _compute_atr(candles or [])
            stop = entry - atr * 1.5 if direction == "long" else entry + atr * 1.5
        risk = max(abs(entry - stop), entry * 0.001)
        rr_targets = [scfg.rr_tp1, scfg.rr_tp2, scfg.rr_tp3, scfg.rr_tp4, scfg.rr_tp5]
        tp_prices = []
        for rr in rr_targets:
            tp_prices.append(entry + risk * rr if direction == "long" else entry - risk * rr)
        tp1, tp2, tp3, tp4, tp5 = tp_prices

    risk = max(abs(entry - stop), entry * 0.001)
    rr1 = abs(tp1 - entry) / risk if risk > 0 else 0

    if rr1 < scfg.min_rr:
        return ICTSignal.none_signal()

    strength = 'strong' if score >= 7 else ('medium' if score >= 4 else 'weak')
    grade = 'A+' if score >= 7 else ('A' if score >= 4 else 'B+') if direction == 'long' else \
            'A-' if score >= 7 else ('A' if score >= 4 else 'B-')

    return ICTSignal(
        direction=direction,
        strength=strength,
        grade=grade,
        entry_price=entry,
        stop_loss=stop,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        take_profit_4=tp4,
        take_profit_5=tp5,
        risk_reward_1=rr1,
        risk_reward_2=abs(tp2 - entry) / risk if risk > 0 else 0,
        risk_reward_3=abs(tp3 - entry) / risk if risk > 0 else 0,
        risk_reward_4=abs(tp4 - entry) / risk if risk > 0 else 0,
        risk_reward_5=abs(tp5 - entry) / risk if risk > 0 else 0,
        risk_pct=scfg.default_risk_pct,
        confluence_score=score,
        bias="bull" if direction == "long" else "bear",
        setup_type=setup_type,
        poi_type=poi_type or "none",
        poi_id=poi.id if poi else "",
        poi_top=poi.top if poi else 0,
        poi_bottom=poi.bottom if poi else 0,
        notes=notes,
        entry_time=entry_time if entry_time else (candles[-1].time if candles else 0),
    )


# ── Historical signal scanning ───────────────────────────────────────────────

@dataclass
class HistoricalSignalResult:
    entry_time:           int
    direction:            str
    grade:                str
    confluence_score:     int
    entry_price:          float
    stop_loss:            float
    take_profit_1:        float
    take_profit_2:        float
    take_profit_3:        float
    take_profit_4:        float
    take_profit_5:        float
    outcome:              str
    outcome_time:         int
    outcome_price:        float
    candles_to_outcome:   int

    def to_dict(self) -> dict:
        return {
            "entry_time":           self.entry_time,
            "direction":            self.direction,
            "grade":                self.grade,
            "confluence_score":     self.confluence_score,
            "entry_price":          round(self.entry_price, 4),
            "stop_loss":            round(self.stop_loss, 4),
            "take_profit_1":        round(self.take_profit_1, 4),
            "take_profit_2":        round(self.take_profit_2, 4),
            "take_profit_3":        round(self.take_profit_3, 4),
            "take_profit_4":        round(self.take_profit_4, 4),
            "take_profit_5":        round(self.take_profit_5, 4),
            "outcome":              self.outcome,
            "outcome_time":         self.outcome_time,
            "outcome_price":        round(self.outcome_price, 4),
            "candles_to_outcome":   self.candles_to_outcome,
        }


def scan_historical_signals(
    candles: List[Candle],
    timeframe: str = '1h',
    strategy_config: Optional[StrategyConfig] = None,
    engine_config: Optional[IndicatorConfig] = None,
    min_context_bars: int = 100,
    context_window: int = 200,
    step: int = 5,
    cooldown_bars: int = 20,
    max_signals: int = 20,
    max_forward_bars: int = 100,
) -> dict:
    """Scan candle history for Smart Money Engine signals and evaluate outcomes."""

    scfg = strategy_config or StrategyConfig()
    ecfg = engine_config or IndicatorConfig()
    ecfg.structure.timeframes = [timeframe]
    ecfg.ob.timeframes = [timeframe]
    ecfg.fvg.timeframes = [timeframe]
    ecfg.ifvg.timeframes = [timeframe]

    n = len(candles)
    results: List[HistoricalSignalResult] = []
    last_signal_bar = -999

    i = max(min_context_bars, context_window)
    while i < n - 1 and len(results) < max_signals:
        if (i - last_signal_bar) < cooldown_bars:
            i += step
            continue

        window_start = max(0, i - context_window + 1)
        window = candles[window_start:i + 1]

        try:
            output = SmartMoneyEngine(ecfg).process(window, current_price=window[-1].close, timeframe=timeframe)
            signal = generate_ict_signal(output, window[-1].close, scfg, candles=window)
        except Exception:
            i += step
            continue

        if signal.direction == 'none':
            i += step
            continue

        is_long = signal.direction == 'long'
        tp_levels = [
            ('TP1', signal.take_profit_1),
            ('TP2', signal.take_profit_2),
            ('TP3', signal.take_profit_3),
            ('TP4', signal.take_profit_4),
            ('TP5', signal.take_profit_5),
        ]

        best_tp_idx = -1
        best_tp_name = ''
        best_tp_price = 0.0
        best_tp_time = 0
        best_tp_bars = 0
        sl_hit = False
        sl_time = 0
        sl_bars = 0

        for j in range(i + 1, min(i + max_forward_bars + 1, n)):
            c = candles[j]

            for k in range(len(tp_levels) - 1, -1, -1):
                tp_name, tp_price = tp_levels[k]
                if tp_price == 0:
                    continue
                hit = (is_long and c.high >= tp_price) or (not is_long and c.low <= tp_price)
                if hit:
                    if k > best_tp_idx:
                        best_tp_idx = k
                        best_tp_name = tp_name
                        best_tp_price = tp_price
                        best_tp_time = c.time
                        best_tp_bars = j - i
                    break

            sl_triggered = (is_long and c.low <= signal.stop_loss) or \
                           (not is_long and c.high >= signal.stop_loss)
            if sl_triggered:
                sl_hit = True
                sl_time = c.time
                sl_bars = j - i
                break

        if sl_hit and best_tp_idx < 0:
            outcome_str = 'SL'
            outcome_time = sl_time
            outcome_price = signal.stop_loss
            outcome_bars = sl_bars
        elif best_tp_idx >= 0:
            outcome_str = best_tp_name
            outcome_time = best_tp_time
            outcome_price = best_tp_price
            outcome_bars = best_tp_bars
        else:
            outcome_str = 'OPEN'
            outcome_time = 0
            outcome_price = 0.0
            outcome_bars = 0

        results.append(HistoricalSignalResult(
            entry_time=candles[i].time,
            direction=signal.direction,
            grade=signal.grade,
            confluence_score=signal.confluence_score,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            take_profit_3=signal.take_profit_3,
            take_profit_4=signal.take_profit_4,
            take_profit_5=signal.take_profit_5,
            outcome=outcome_str,
            outcome_time=outcome_time,
            outcome_price=outcome_price,
            candles_to_outcome=outcome_bars,
        ))
        last_signal_bar = i
        i += step

    tp_wins = [r for r in results if r.outcome.startswith('TP')]
    sl_hits = [r for r in results if r.outcome == 'SL']
    open_sig = [r for r in results if r.outcome == 'OPEN']
    closed = len(tp_wins) + len(sl_hits)

    stats = {
        "total":         len(results),
        "wins":          len(tp_wins),
        "losses":        len(sl_hits),
        "open":          len(open_sig),
        "win_rate":      round(len(tp_wins) / closed, 3) if closed > 0 else 0,
        "tp2_or_better": len([r for r in tp_wins if r.outcome not in ('TP1',)]),
        "tp3_or_better": len([r for r in tp_wins if r.outcome not in ('TP1', 'TP2')]),
    }

    return {"signals": [r.to_dict() for r in results], "stats": stats}
