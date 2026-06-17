"""Regression tests for the shadow-mode plumbing in ai_scanner.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.ai_scanner import record_shadow_for_signal


BACKEND_DIR = Path(__file__).resolve().parent.parent
AI_SCANNER_PATH = BACKEND_DIR / "app" / "services" / "ai_scanner.py"


def _extract_build_signal_source(source: str) -> str:
    """Return the source text of the build_signal function."""
    lines = source.splitlines()
    start = None
    base_indent = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("def build_signal("):
            start = idx
            base_indent = len(line) - len(line.lstrip())
            break
    if start is None:
        raise RuntimeError("build_signal not found in ai_scanner.py")

    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() == "":
            end += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            break
        end += 1
    return "\n".join(lines[start:end])


def test_build_signal_source_does_not_call_shadow_recorders():
    """build_signal must NOT call record_shadow/record_candidate_shadow directly.

    Recording before db.commit() is what produced signal_id='None'.  This test
    guards against that regression by inspecting the source code.
    """
    source = AI_SCANNER_PATH.read_text(encoding="utf-8")
    build_signal_source = _extract_build_signal_source(source)

    assert "record_shadow(" not in build_signal_source, (
        "build_signal must not call record_shadow directly"
    )
    assert "record_candidate_shadow(" not in build_signal_source, (
        "build_signal must not call record_candidate_shadow directly"
    )


@pytest.fixture
def sample_result_dict():
    return {
        "symbol": "BTCUSDT",
        "status": "SIGNAL",
        "context": {},
        "_shadow_probs": {
            "live": 0.75,
            "shadow": 0.60,
            "candidate": 0.80,
        },
    }


def test_record_shadow_for_signal_records_both_modes(sample_result_dict):
    with (
        patch("ai.services.shadow_mode.record_shadow") as mock_live,
        patch("ai.services.candidate_shadow_mode.record_candidate_shadow") as mock_cand,
    ):
        record_shadow_for_signal("11111111-1111-1111-1111-111111111111", sample_result_dict)

    mock_live.assert_called_once_with(
        signal_id="11111111-1111-1111-1111-111111111111",
        live_prob=0.75,
        shadow_prob=0.60,
    )
    mock_cand.assert_called_once_with(
        signal_id="11111111-1111-1111-1111-111111111111",
        live_prob=0.75,
        candidate_prob=0.80,
    )


def test_record_shadow_for_signal_skips_none_signal_id(sample_result_dict):
    with (
        patch("ai.services.shadow_mode.record_shadow") as mock_live,
        patch("ai.services.candidate_shadow_mode.record_candidate_shadow") as mock_cand,
    ):
        record_shadow_for_signal("None", sample_result_dict)
        record_shadow_for_signal(None, sample_result_dict)
        record_shadow_for_signal("", sample_result_dict)

    mock_live.assert_not_called()
    mock_cand.assert_not_called()


def test_record_shadow_for_signal_ignores_missing_probs():
    with (
        patch("ai.services.shadow_mode.record_shadow") as mock_live,
        patch("ai.services.candidate_shadow_mode.record_candidate_shadow") as mock_cand,
    ):
        record_shadow_for_signal("11111111-1111-1111-1111-111111111111", {})

    mock_live.assert_not_called()
    mock_cand.assert_not_called()
