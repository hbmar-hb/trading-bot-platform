"""Build training dataset from resolved AISignal records.

X = 15 market-structure features stored per signal.
y = 1 if FAILURE (fake/bad signal), 0 if SUCCESS.
"""
from __future__ import annotations

import pandas as pd

FEATURE_COLS = [
    "fvg_aligned_count",
    "ob_distance_atr",
    "sweep_detected",
    "pd_position",
    "hour_utc",
    "day_of_week",
    "eq_highs_count",
    "eq_lows_count",
    "volume_ratio",
    "spread_atr",
    "score",
    # Encoded categoricals (added below)
    "trigger_ob",
    "trigger_fvg",
    "bias_bull",
    "sweep_bool",
    "break_choch",
]


def build_dataset_sync() -> tuple[pd.DataFrame, pd.Series]:
    """
    Query resolved signals from DB (sync session) and build X/y.
    Call from Celery tasks (uses synchronous SessionLocal).
    """
    from app.models.ai_signal import AISignal
    from app.services.database import SessionLocal

    with SessionLocal() as db:
        rows = (
            db.query(AISignal)
            .filter(AISignal.outcome.in_(["SUCCESS", "FAILURE"]))
            .all()
        )

    return _build_from_rows(rows)


def _build_from_rows(rows) -> tuple[pd.DataFrame, pd.Series]:
    records = []
    for s in rows:
        if not s.features:
            continue
        rec = dict(s.features)
        rec["score"] = s.score or 0
        rec["label"] = 1 if s.outcome == "FAILURE" else 0
        records.append(rec)

    if not records:
        return pd.DataFrame(), pd.Series(dtype=float)

    df = pd.DataFrame(records)

    # Encode categoricals
    df["trigger_ob"]   = (df.get("trigger",    "") == "ob").astype(int)
    df["trigger_fvg"]  = (df.get("trigger",    "") == "fvg").astype(int)
    df["bias_bull"]    = (df.get("bias",        "") == "bull").astype(int)
    df["sweep_bool"]   = df.get("sweep_detected", False).astype(int)
    df["break_choch"]  = (df.get("break_type", "") == "CHoCH").astype(int)

    available = [c for c in FEATURE_COLS if c in df.columns]
    X = df[available].fillna(0)
    y = df["label"]

    return X, y
