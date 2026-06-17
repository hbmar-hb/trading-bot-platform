"""
Smart Money Engine — Python port of the Pine Script SMC indicator.
Detects swing/internal structure, order blocks, fair value gaps, inverse FVGs,
Fibonacci retracements, strong/weak levels and HTF trend bias.
Output is JSON-serializable for frontend canvas rendering.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
import json


BULL = 1
BEAR = -1
NONE = 0


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Candle:
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float = 0.0
    time:   int   = 0   # milliseconds


@dataclass
class SmeBox:
    id:             str
    type:           str     # "FVG" | "OB" | "IFVG" | "OTE"
    direction:      str     # "bull" | "bear"
    timeframe:      str
    top:            float
    bottom:         float
    left:           int     # ms
    right:          int     # ms
    midline:        float
    border_color:   str
    bg_color:       str
    border_style:   str     # "dotted" | "dashed" | "solid"
    border_width:   int
    label:          str
    text_color:     str
    show_midline:   bool
    grade:          str = ""  # A/B/C for OBs
    mitigated:      bool = False
    filled:         bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SmeLine:
    id:             str
    type:           str     # "BOS" | "CHoCH" | "INTERNAL_BOS" | "INTERNAL_CHoCH" | "FIB" | "STRONG" | "WEAK"
    price:          float
    start_time:     int     # ms
    end_time:       int     # ms
    timeframe:      str
    color:          str
    line_style:     str     # "solid" | "dashed" | "dotted"
    line_width:     int
    label:          str
    label_position: str
    show_label:     bool
    direction:      str = "bull"   # "bull" | "bear"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SmeLabel:
    id:             str
    text:           str
    time:           int     # ms
    price:          float
    color:          str
    text_color:     str
    size:           str     # "small" | "tiny"
    style:          str     # "label_up" | "label_down" | "label_left"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SmeDashboard:
    swing_trend:    str
    internal_trend: str
    fib_high:       Optional[float]
    fib_low:        Optional[float]
    active_obs:     int
    active_fvgs:    int
    active_ifvgs:   int
    timeframe:      str
    htf_bias:       str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SmeOutput:
    boxes:                  List[SmeBox]    = field(default_factory=list)
    lines:                  List[SmeLine]   = field(default_factory=list)
    labels:                 List[SmeLabel]  = field(default_factory=list)
    dashboard:              Optional[SmeDashboard] = None
    current_trend:          str             = "ranging"
    pd_position:            float           = 0.5
    htf_bias:               Optional[Dict]  = None
    timestamp:              int             = 0

    def to_dict(self) -> dict:
        return {
            "boxes":         [b.to_dict() for b in self.boxes],
            "lines":         [l.to_dict() for l in self.lines],
            "labels":        [lb.to_dict() for lb in self.labels],
            "dashboard":     self.dashboard.to_dict() if self.dashboard else None,
            "current_trend": self.current_trend,
            "pd_position":   round(self.pd_position, 4),
            "htf_bias":      self.htf_bias,
            "timestamp":     self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ── Configuration ────────────────────────────────────────────────────────────

@dataclass
class StructureConfig:
    enabled:                 bool      = True
    timeframes:              List[str] = field(default_factory=lambda: ["1h"])
    swing_len:               int       = 10
    internal_len:            int       = 5
    min_move_atr_mult:       float     = 0.5
    show_swing_struct:       bool      = True
    show_internal_struct:    bool      = True
    show_swing_labels:       bool      = True
    show_strong_weak:        bool      = True
    bull_color:              str       = "#1B5E20"
    bear_color:              str       = "#FF5252"
    choch_bull_color:        str       = "#1B5E20"
    choch_bear_color:        str       = "#FF5252"
    bos_bull_color:          str       = "#1B5E20"
    bos_bear_color:          str       = "#FF5252"
    internal_bull_color:     str       = "#1B5E20"
    internal_bear_color:     str       = "#FF5252"
    strong_weak_bull_color:  str       = "#1B5E20"
    strong_weak_bear_color:  str       = "#FF5252"
    label_text_color:        str       = "#FFFFFF"
    line_extension_bars:     int       = 50


@dataclass
class OBConfig:
    enabled:              bool      = True
    timeframes:           List[str] = field(default_factory=lambda: ["1h"])
    show_ob:              bool      = True
    max_per_tf:           int       = 10
    lookback:             int       = 30
    extension_bars:       int       = 10
    mitigation:           str       = "wick"   # "close" | "wick"
    min_volume_grade:     float     = 1.2
    show_grade:           bool      = True
    show_midline:         bool      = True
    bull_bg_color:        str       = "#1B5E20"
    bear_bg_color:        str       = "#FF5252"
    bull_border_color:    str       = "#1B5E20"
    bear_border_color:    str       = "#FF5252"
    text_color:           str       = "#FFFFFF"
    grade_a_color:        str       = "#FFD600"
    grade_b_color:        str       = "#FFFFFF"
    grade_c_color:        str       = "#9E9E9E"


@dataclass
class FVGConfig:
    enabled:              bool      = True
    timeframes:           List[str] = field(default_factory=lambda: ["1h"])
    show_fvg:             bool      = True
    filter_enabled:       bool      = True
    max_per_tf:           int       = 10
    max_ifvg_per_tf:      int       = 5
    min_size_atr_mult:    float     = 0.5
    extension_bars:       int       = 5
    show_fvg_midline:     bool      = True
    bull_bg_color:        str       = "#2962FF"
    bear_bg_color:        str       = "#FF6D00"
    bull_border_color:    str       = "#2962FF"
    bear_border_color:    str       = "#FF6D00"
    text_color:           str       = "#FFFFFF"


@dataclass
class IFVGConfig:
    enabled:              bool      = False
    timeframes:           List[str] = field(default_factory=lambda: ["1h"])
    show_ifvg:            bool      = True
    max_per_tf:           int       = 5
    bull_border_color:    str       = "#2962FF"
    bear_border_color:    str       = "#FF6D00"
    text_color:           str       = "#FFFFFF"


@dataclass
class FibConfig:
    enabled:              bool      = True
    show_fib:             bool      = True
    show_fib_ote:         bool      = True
    ote_color:            str       = "#FFD600"
    line_color:           str       = "#9E9E9E"
    text_color:           str       = "#BDBDBD"


@dataclass
class MultiTimeframeConfig:
    enabled:              bool      = True
    auto_htf:             bool      = True
    htf_resolution:       Optional[str] = None
    htf_min_strength:     float     = 0.0
    show_htf_structure:   bool      = True
    htf_ema_len:          int       = 50


@dataclass
class VolumeConfig:
    use_volume:           bool      = True
    spike_threshold:      float     = 1.5
    length:               int       = 20


@dataclass
class IndicatorConfig:
    structure:  StructureConfig      = field(default_factory=StructureConfig)
    ob:         OBConfig             = field(default_factory=OBConfig)
    fvg:        FVGConfig            = field(default_factory=FVGConfig)
    ifvg:       IFVGConfig           = field(default_factory=IFVGConfig)
    fib:        FibConfig            = field(default_factory=FibConfig)
    multi_tf:   MultiTimeframeConfig = field(default_factory=MultiTimeframeConfig)
    volume:     VolumeConfig         = field(default_factory=VolumeConfig)
    atr_length: int                  = 14
    tick_size:  float                = 0.01


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) >= 8:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        a = alpha if alpha is not None else int(h[6:8], 16) / 255
    else:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        a = alpha if alpha is not None else 1.0
    return f"rgba({r},{g},{b},{a:.3f})"


def _compute_atr(candles: List[Candle], length: int = 14) -> List[float]:
    n = len(candles)
    atr_vals = [0.0] * n
    trs = []
    for i in range(1, n):
        c, p = candles[i], candles[i - 1]
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        trs.append(tr)
        if len(trs) >= length:
            window = trs[-length:]
            atr_vals[i] = sum(window) / length
        elif trs:
            atr_vals[i] = sum(trs) / len(trs)
    return atr_vals


def _compute_vol_sma(volumes: List[float], length: int = 20) -> List[float]:
    n = len(volumes)
    out = [0.0] * n
    for i in range(n):
        window = volumes[max(0, i - length + 1):i + 1]
        out[i] = sum(window) / len(window) if window else 0.0
    return out


def _compute_ema(values: List[float], length: int) -> Optional[float]:
    if len(values) < length:
        return None
    k = 2.0 / (length + 1)
    ema = sum(values[:length]) / length
    for v in values[length:]:
        ema = v * k + ema * (1 - k)
    return ema


def _detect_pivot_highs(candles: List[Candle], left: int, right: int) -> List[int]:
    """Return central bar indices where a pivot high is confirmed."""
    pivots = []
    n = len(candles)
    for i in range(left, n - right):
        hi = candles[i].high
        window = candles[i - left:i + right + 1]
        if all(c.high <= hi for c in window):
            pivots.append(i)
    return pivots


def _detect_pivot_lows(candles: List[Candle], left: int, right: int) -> List[int]:
    pivots = []
    n = len(candles)
    for i in range(left, n - right):
        lo = candles[i].low
        window = candles[i - left:i + right + 1]
        if all(c.low >= lo for c in window):
            pivots.append(i)
    return pivots


def _trend_name(trend: int) -> str:
    return "bull" if trend == BULL else "bear" if trend == BEAR else "ranging"


# ── Engine ───────────────────────────────────────────────────────────────────

class SmartMoneyEngine:
    TF_MS = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
        "1D": 86_400_000, "1w": 604_800_000, "1W": 604_800_000,
    }

    def __init__(self, config: Optional[IndicatorConfig] = None):
        self.config = config or IndicatorConfig()
        self._box_counter = 0
        self._line_counter = 0
        self._label_counter = 0

    def _next_box_id(self) -> str:
        self._box_counter += 1
        return f"BOX:{self._box_counter}"

    def _next_line_id(self) -> str:
        self._line_counter += 1
        return f"LINE:{self._line_counter}"

    def _next_label_id(self) -> str:
        self._label_counter += 1
        return f"LABEL:{self._label_counter}"

    def _resolve_htf(self, tf_name: str) -> str:
        mtf = self.config.multi_tf
        if not mtf.auto_htf and mtf.htf_resolution:
            return mtf.htf_resolution
        mapping = {
            "1m": "5m", "5m": "15m", "15m": "1h",
            "1h": "4h", "4h": "1d", "1d": "1w",
            "1D": "1w", "1w": "1w", "1W": "1w",
        }
        return mapping.get(tf_name, "4h")

    def _compute_htf_bias(self, candles: List[Candle], tf_name: str, htf_tf: str,
                          htf_candles: Optional[List[Candle]] = None) -> Tuple[str, float]:
        mtf = self.config.multi_tf
        if not mtf.enabled or not htf_tf or htf_tf == tf_name:
            return "neutral", 0.0

        ema_len = mtf.htf_ema_len
        if htf_candles and len(htf_candles) >= ema_len:
            closes = [c.close for c in htf_candles]
            ema = _compute_ema(closes, ema_len)
            if ema is not None:
                last_close = htf_candles[-1].close
                if last_close > ema:
                    return "bull", 1.0
                elif last_close < ema:
                    return "bear", 1.0

        # Fallback: derive from current candles using a higher-period EMA approximation
        if len(candles) >= ema_len:
            factor = 4 if htf_tf in ("4h", "1d") else 1
            sampled = candles[::max(1, factor)]
            if len(sampled) >= ema_len:
                closes = [c.close for c in sampled]
                ema = _compute_ema(closes, ema_len)
                if ema is not None:
                    last_close = sampled[-1].close
                    if last_close > ema:
                        return "bull", 0.7
                    elif last_close < ema:
                        return "bear", 0.7
        return "neutral", 0.0

    def process(
        self,
        candles: Dict[str, List[Candle]],
        current_price: Optional[float] = None,
        timeframe: str = "1h",
    ) -> SmeOutput:
        # Support passing a plain list for backwards compatibility
        if isinstance(candles, list):
            candles = {timeframe: candles}
        tf_name = timeframe
        htf_tf = self._resolve_htf(tf_name)
        htf_candles = candles.get(htf_tf) if htf_tf != tf_name else None
        candles = candles.get(tf_name, [])
        cfg = self.config
        sc = cfg.structure
        obc = cfg.ob
        fc = cfg.fvg
        ic = cfg.ifvg
        fibc = cfg.fib
        vc = cfg.volume

        n = len(candles)
        if n == 0:
            return SmeOutput()

        ts = candles[-1].time
        tf_ms = self.TF_MS.get(tf_name, 60_000)
        current_price = current_price if current_price is not None else candles[-1].close

        # Precompute ATR and volume
        atr_vals = _compute_atr(candles, cfg.atr_length)
        volumes = [c.volume for c in candles]
        vol_sma = _compute_vol_sma(volumes, vc.length)
        has_volume = any(v > 0 for v in volumes)

        # Precompute pivot central indices
        swing_high_pivots = _detect_pivot_highs(candles, sc.swing_len, sc.swing_len)
        swing_low_pivots = _detect_pivot_lows(candles, sc.swing_len, sc.swing_len)
        internal_high_pivots = _detect_pivot_highs(candles, sc.internal_len, sc.internal_len)
        internal_low_pivots = _detect_pivot_lows(candles, sc.internal_len, sc.internal_len)

        warmup_bars = max(sc.swing_len * 3, 50)

        # HTF bias
        htf_tf = self._resolve_htf(tf_name)
        htf_direction, htf_strength = self._compute_htf_bias(candles, tf_name, htf_tf, htf_candles)

        # Output accumulators
        output_boxes: List[SmeBox] = []
        output_lines: List[SmeLine] = []
        output_labels: List[SmeLabel] = []

        # Swing structure state
        sw_high_level: Optional[float] = None
        sw_low_level: Optional[float] = None
        sw_prev_high: Optional[float] = None
        sw_prev_low: Optional[float] = None
        sw_high_bar: Optional[int] = None
        sw_low_bar: Optional[int] = None
        sw_trend = NONE
        sw_high_broken = False
        sw_low_broken = False

        # Trailing strong/weak
        trail_high: Optional[float] = None
        trail_low: Optional[float] = None
        trail_high_bar: Optional[int] = None
        trail_low_bar: Optional[int] = None

        # Internal structure state
        int_high_level: Optional[float] = None
        int_low_level: Optional[float] = None
        int_high_bar: Optional[int] = None
        int_low_bar: Optional[int] = None
        int_trend = NONE
        int_high_broken = False
        int_low_broken = False

        # Live collections
        obs: List[Dict] = []
        fvgs: List[Dict] = []
        ifvgs: List[Dict] = []
        ifvg_queue: List[Tuple[float, float, int]] = []

        def make_box(box_type: str, direction: str, top: float, bottom: float,
                     left: int, right: int, bg_color: str, border_color: str,
                     border_style: str, border_width: int, label: str,
                     text_color: str, show_midline: bool, grade: str = "") -> SmeBox:
            mid = (top + bottom) / 2.0
            return SmeBox(
                id=self._next_box_id(),
                type=box_type,
                direction=direction,
                timeframe=tf_name,
                top=top,
                bottom=bottom,
                left=left,
                right=right,
                midline=mid,
                border_color=border_color,
                bg_color=bg_color,
                border_style=border_style,
                border_width=border_width,
                label=label,
                text_color=text_color,
                show_midline=show_midline,
                grade=grade,
            )

        def make_line(line_type: str, price: float, start_bar: int, end_bar: int,
                      color: str, style: str, width: int, label: str,
                      label_position: str = "left", direction: str = "bull") -> SmeLine:
            return SmeLine(
                id=self._next_line_id(),
                type=line_type,
                price=price,
                start_time=candles[start_bar].time if 0 <= start_bar < n else ts,
                end_time=candles[end_bar].time if 0 <= end_bar < n else ts + tf_ms * sc.line_extension_bars,
                timeframe=tf_name,
                color=color,
                line_style=style,
                line_width=width,
                label=label,
                label_position=label_position,
                show_label=True,
                direction=direction,
            )

        def make_label(text: str, bar: int, price: float, text_color: str,
                       style: str = "label_down", size: str = "small") -> SmeLabel:
            return SmeLabel(
                id=self._next_label_id(),
                text=text,
                time=candles[bar].time if 0 <= bar < n else ts,
                price=price,
                color="transparent",
                text_color=text_color,
                size=size,
                style=style,
            )

        def find_bullish_ob(from_bar: int, to_bar: int) -> Tuple[Optional[float], Optional[float], Optional[int]]:
            if from_bar < 0 or to_bar <= from_bar:
                from_bar = max(0, to_bar - obc.lookback)
            for idx in range(to_bar - 1, from_bar - 1, -1):
                if idx < 0:
                    break
                if candles[idx].close < candles[idx].open:
                    return candles[idx].high, candles[idx].low, idx
            return None, None, None

        def find_bearish_ob(from_bar: int, to_bar: int) -> Tuple[Optional[float], Optional[float], Optional[int]]:
            if from_bar < 0 or to_bar <= from_bar:
                from_bar = max(0, to_bar - obc.lookback)
            for idx in range(to_bar - 1, from_bar - 1, -1):
                if idx < 0:
                    break
                if candles[idx].close > candles[idx].open:
                    return candles[idx].high, candles[idx].low, idx
            return None, None, None

        # Main bar-by-bar simulation
        for i in range(n):
            c = candles[i]
            atr_val = atr_vals[i] if atr_vals[i] > 0 else c.high - c.low
            vol_spike = has_volume and volumes[i] > vol_sma[i] * vc.spike_threshold if vc.use_volume else False
            is_warmed = i >= warmup_bars

            # ── Swing pivot confirmation ──
            if i - sc.swing_len in swing_high_pivots:
                central = i - sc.swing_len
                sw_prev_high = sw_high_level
                sw_high_level = candles[central].high
                sw_high_bar = central
                sw_high_broken = False
                if sc.show_swing_labels and is_warmed:
                    lbl = "HH" if sw_high_level > (sw_prev_high or sw_high_level) else "LH"
                    output_labels.append(make_label(lbl, central, sw_high_level + atr_val * 0.3,
                                                    sc.bear_color, "label_down"))

            if i - sc.swing_len in swing_low_pivots:
                central = i - sc.swing_len
                sw_prev_low = sw_low_level
                sw_low_level = candles[central].low
                sw_low_bar = central
                sw_low_broken = False
                if sc.show_swing_labels and is_warmed:
                    lbl = "LL" if sw_low_level < (sw_prev_low or sw_low_level) else "HL"
                    output_labels.append(make_label(lbl, central, sw_low_level - atr_val * 0.3,
                                                    sc.bull_color, "label_up"))

            # ── Internal pivot confirmation ──
            if i - sc.internal_len in internal_high_pivots:
                central = i - sc.internal_len
                int_high_level = candles[central].high
                int_high_bar = central
                int_high_broken = False

            if i - sc.internal_len in internal_low_pivots:
                central = i - sc.internal_len
                int_low_level = candles[central].low
                int_low_bar = central
                int_low_broken = False

            # ── Swing breaks ──
            sw_bull_break = (sw_high_level is not None and not sw_high_broken and
                             c.close > sw_high_level and is_warmed)
            sw_bear_break = (sw_low_level is not None and not sw_low_broken and
                             c.close < sw_low_level and is_warmed)

            if sw_bull_break:
                sw_high_broken = True
                bull_type = "CHoCH" if sw_trend == BEAR else "BOS"
                sw_trend = BULL
                if sw_low_level is not None:
                    trail_low = sw_low_level
                    trail_low_bar = sw_low_bar if sw_low_bar is not None else i
                if sc.show_swing_struct:
                    output_lines.append(make_line("CHoCH" if bull_type == "CHoCH" else "BOS",
                                                   sw_high_level, sw_high_bar or i, i,
                                                   sc.bull_color, "solid", 2, bull_type, "left",
                                                   direction="bull"))

                # Create bullish OB
                if obc.enabled:
                    oH, oL, oB = find_bullish_ob(sw_low_bar or max(0, i - 40), i)
                    if oH is not None and oL is not None and oB is not None:
                        grade = "B" if vol_spike else "C"
                        box = make_box("OB", "bull", oH, oL,
                                       candles[oB].time, c.time,
                                       _hex_to_rgba(obc.bull_bg_color, 0.92),
                                       _hex_to_rgba(obc.bull_border_color, 0.4),
                                       "dotted", 1, "OB",
                                       obc.text_color, obc.show_midline, grade)
                        output_boxes.append(box)
                        obs.append({
                            "box": box, "bias": BULL,
                            "top": oH, "bottom": oL, "bar": oB,
                        })
                        if obc.show_grade:
                            output_labels.append(make_label(grade, oB, oH, obc.grade_b_color, "label_down"))

            if sw_bear_break:
                sw_low_broken = True
                bear_type = "CHoCH" if sw_trend == BULL else "BOS"
                sw_trend = BEAR
                if sw_high_level is not None:
                    trail_high = sw_high_level
                    trail_high_bar = sw_high_bar if sw_high_bar is not None else i
                if sc.show_swing_struct:
                    output_lines.append(make_line("CHoCH" if bear_type == "CHoCH" else "BOS",
                                                   sw_low_level, sw_low_bar or i, i,
                                                   sc.bear_color, "solid", 2, bear_type, "left",
                                                   direction="bear"))

                # Create bearish OB
                if obc.enabled:
                    oH, oL, oB = find_bearish_ob(sw_high_bar or max(0, i - 40), i)
                    if oH is not None and oL is not None and oB is not None:
                        grade = "B" if vol_spike else "C"
                        box = make_box("OB", "bear", oH, oL,
                                       candles[oB].time, c.time,
                                       _hex_to_rgba(obc.bear_bg_color, 0.92),
                                       _hex_to_rgba(obc.bear_border_color, 0.4),
                                       "dotted", 1, "OB",
                                       obc.text_color, obc.show_midline, grade)
                        output_boxes.append(box)
                        obs.append({
                            "box": box, "bias": BEAR,
                            "top": oH, "bottom": oL, "bar": oB,
                        })
                        if obc.show_grade:
                            output_labels.append(make_label(grade, oB, oH, obc.grade_b_color, "label_down"))

            # ── Internal breaks ──
            int_bull_break = (int_high_level is not None and not int_high_broken and
                              c.close > int_high_level and is_warmed)
            int_bear_break = (int_low_level is not None and not int_low_broken and
                              c.close < int_low_level and is_warmed)

            if int_bull_break:
                int_high_broken = True
                bull_type = "CHoCH" if int_trend == BEAR else "BOS"
                int_trend = BULL
                if sc.show_internal_struct:
                    # Skip if coincides with swing level
                    if int_high_level != sw_high_level:
                        output_lines.append(make_line("INTERNAL_CHoCH" if bull_type == "CHoCH" else "INTERNAL_BOS",
                                                       int_high_level, int_high_bar or i, i,
                                                       sc.internal_bull_color, "dashed", 1, bull_type, "left",
                                                       direction="bull"))

            if int_bear_break:
                int_low_broken = True
                bear_type = "CHoCH" if int_trend == BULL else "BOS"
                int_trend = BEAR
                if sc.show_internal_struct:
                    if int_low_level != sw_low_level:
                        output_lines.append(make_line("INTERNAL_CHoCH" if bear_type == "CHoCH" else "INTERNAL_BOS",
                                                       int_low_level, int_low_bar or i, i,
                                                       sc.internal_bear_color, "dashed", 1, bear_type, "left",
                                                       direction="bear"))

            # ── Trailing strong/weak ──
            if sw_trend == BULL:
                if trail_low is None or c.low < trail_low:
                    trail_low = c.low
                    trail_low_bar = i
                if trail_high is None or c.high > trail_high:
                    trail_high = c.high
                    trail_high_bar = i
            elif sw_trend == BEAR:
                if trail_high is None or c.high > trail_high:
                    trail_high = c.high
                    trail_high_bar = i
                if trail_low is None or c.low < trail_low:
                    trail_low = c.low
                    trail_low_bar = i
            else:
                if trail_high is None or c.high > trail_high:
                    trail_high = c.high
                    trail_high_bar = i
                if trail_low is None or c.low < trail_low:
                    trail_low = c.low
                    trail_low_bar = i

            # ── Update OBs: extend & mitigate ──
            if obc.enabled:
                j = 0
                while j < len(obs):
                    ob = obs[j]
                    box = ob["box"]
                    bias = ob["bias"]
                    mitigated = False
                    if bias == BULL:
                        check = c.close if obc.mitigation == "close" else c.low
                        if check < box.bottom:
                            mitigated = True
                    else:
                        check = c.close if obc.mitigation == "close" else c.high
                        if check > box.top:
                            mitigated = True

                    if mitigated:
                        output_boxes.remove(box)
                        obs.pop(j)
                        continue
                    else:
                        box.right = c.time
                        j += 1

                # Cap OB count
                while len(obs) > obc.max_per_tf:
                    old = obs.pop(0)
                    output_boxes.remove(old["box"])

            # ── Update FVGs: extend & fill ──
            if fc.show_fvg:
                j = 0
                while j < len(fvgs):
                    fvg = fvgs[j]
                    box = fvg["box"]
                    bias = fvg["bias"]
                    filled = False
                    if bias == BULL:
                        if c.low <= box.bottom:
                            filled = True
                    else:
                        if c.high >= box.top:
                            filled = True

                    if filled:
                        if ic.enabled:
                            ifvg_queue.append((box.top, box.bottom, BULL if bias == BEAR else BEAR))
                        output_boxes.remove(box)
                        fvgs.pop(j)
                        continue
                    else:
                        box.right = c.time
                        j += 1

                while len(fvgs) > fc.max_per_tf:
                    old = fvgs.pop(0)
                    output_boxes.remove(old["box"])

            # ── Process queued IFVGs ──
            if ic.enabled and ifvg_queue:
                for top, bottom, bias in ifvg_queue:
                    border = ic.bull_border_color if bias == BULL else ic.bear_border_color
                    box = make_box("IFVG", "bull" if bias == BULL else "bear",
                                   top, bottom, c.time, c.time,
                                   "rgba(0,0,0,0)", _hex_to_rgba(border, 0.7),
                                   "dashed", 1, "IFVG", ic.text_color, False)
                    output_boxes.append(box)
                    ifvgs.append({"box": box, "bias": bias})
                ifvg_queue.clear()

            # ── Update IFVGs: extend & mitigate ──
            if ic.enabled:
                j = 0
                while j < len(ifvgs):
                    ifvg = ifvgs[j]
                    box = ifvg["box"]
                    bias = ifvg["bias"]
                    mitigated = False
                    if bias == BULL:
                        if c.close < box.bottom:
                            mitigated = True
                    else:
                        if c.close > box.top:
                            mitigated = True

                    if mitigated:
                        output_boxes.remove(box)
                        ifvgs.pop(j)
                        continue
                    else:
                        box.right = c.time
                        j += 1

                while len(ifvgs) > ic.max_per_tf:
                    old = ifvgs.pop(0)
                    output_boxes.remove(old["box"])

            # ── Detect FVGs ──
            if fc.show_fvg and i >= 2 and is_warmed:
                # Bullish FVG
                if c.low > candles[i - 2].high:
                    top = c.low
                    bottom = candles[i - 2].high
                    size = top - bottom
                    min_size = atr_val * fc.min_size_atr_mult if fc.filter_enabled else 0.0
                    if size > min_size:
                        box = make_box("FVG", "bull", top, bottom,
                                       candles[i - 1].time, c.time,
                                       _hex_to_rgba(fc.bull_bg_color, 0.95),
                                       _hex_to_rgba(fc.bull_border_color, 0.5),
                                       "dotted", 1, "FVG", fc.text_color, fc.show_fvg_midline)
                        output_boxes.append(box)
                        fvgs.append({"box": box, "bias": BULL})

                # Bearish FVG
                if c.high < candles[i - 2].low:
                    top = candles[i - 2].low
                    bottom = c.high
                    size = top - bottom
                    min_size = atr_val * fc.min_size_atr_mult if fc.filter_enabled else 0.0
                    if size > min_size:
                        box = make_box("FVG", "bear", top, bottom,
                                       candles[i - 1].time, c.time,
                                       _hex_to_rgba(fc.bear_bg_color, 0.95),
                                       _hex_to_rgba(fc.bear_border_color, 0.5),
                                       "dotted", 1, "FVG", fc.text_color, fc.show_fvg_midline)
                        output_boxes.append(box)
                        fvgs.append({"box": box, "bias": BEAR})

        # ── Final drawings: Fibonacci & strong/weak levels ──
        if fibc.show_fib and trail_high is not None and trail_low is not None and trail_high != trail_low:
            left_bar = min(trail_high_bar or n - 1, trail_low_bar or n - 1)
            right_bar = n - 1 + 10
            fib_range = trail_high - trail_low
            levels = {
                "0":     trail_high,
                "0.236": trail_high - fib_range * 0.236,
                "0.382": trail_high - fib_range * 0.382,
                "0.5":   trail_high - fib_range * 0.5,
                "0.618": trail_high - fib_range * 0.618,
                "0.786": trail_high - fib_range * 0.786,
                "1":     trail_low,
            }
            for lbl, price in levels.items():
                output_lines.append(make_line("FIB", price, left_bar, right_bar,
                                              fibc.line_color, "dotted", 1, lbl, "left"))
            if fibc.show_fib_ote:
                ote_top = trail_high - fib_range * 0.5
                ote_bottom = trail_high - fib_range * 0.618
                output_boxes.append(make_box("OTE", "neutral", ote_top, ote_bottom,
                                             candles[left_bar].time,
                                             candles[min(n - 1, right_bar)].time,
                                             _hex_to_rgba(fibc.ote_color, 0.85),
                                             "rgba(0,0,0,0)", "solid", 0, "OTE",
                                             fibc.text_color, False))

        if sc.show_strong_weak and trail_high is not None and trail_low is not None:
            right_bar = n - 1 + 20
            hi_label = "Strong High" if sw_trend == BEAR else "Weak High"
            lo_label = "Strong Low" if sw_trend == BULL else "Weak Low"
            output_lines.append(make_line("STRONG", trail_high, trail_high_bar or n - 1, right_bar,
                                          sc.strong_weak_bear_color, "dashed", 1, hi_label, "left"))
            output_lines.append(make_line("STRONG", trail_low, trail_low_bar or n - 1, right_bar,
                                          sc.strong_weak_bull_color, "dashed", 1, lo_label, "left"))

        # ── Dashboard ──
        dashboard = SmeDashboard(
            swing_trend=_trend_name(sw_trend),
            internal_trend=_trend_name(int_trend),
            fib_high=trail_high,
            fib_low=trail_low,
            active_obs=len(obs),
            active_fvgs=len(fvgs),
            active_ifvgs=len(ifvgs),
            timeframe=tf_name,
            htf_bias=htf_direction,
        )

        # ── PD position ──
        pd_position = 0.5
        if n >= 5:
            lookback = min(50, n)
            window = candles[-lookback:]
            range_h = max(c.high for c in window)
            range_l = min(c.low for c in window)
            if range_h != range_l:
                pd_position = (candles[-1].close - range_l) / (range_h - range_l)

        return SmeOutput(
            boxes=output_boxes,
            lines=output_lines,
            labels=output_labels,
            dashboard=dashboard,
            current_trend=_trend_name(sw_trend),
            pd_position=pd_position,
            htf_bias={
                "direction": htf_direction,
                "strength": round(htf_strength, 2),
                "timeframe": htf_tf,
            } if htf_direction != "neutral" else None,
            timestamp=ts,
        )

    def clear(self):
        self._box_counter = 0
        self._line_counter = 0
        self._label_counter = 0
