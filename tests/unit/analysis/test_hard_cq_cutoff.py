"""
Tests for the hard Cq cutoff (PCR_CQ_HARD_MAX).

Any threshold crossing with a Cq strictly greater than PCR_CQ_HARD_MAX is called
Not Detected regardless of curve shape or per-cycle-fold evidence — it overrides
the late-Cq-confident rescue path. A Cq at or below the cutoff is unaffected.

Fixtures are real baseline-corrected curves captured from optics logs:
  * PAST_CUTOFF  — run5_2026-07-16 FAM well 4 (Cq ~38.6): a terminal-spike artifact
    that the late-Cq path used to promote to Detected.
  * WITHIN_CUTOFF — aba_form_3_set_3 FAM well 1 (Cq ~35.4): a genuine late riser
    below the cutoff that must stay Detected.
"""
import numpy as np
import pytest

from aq_curve import evaluator as evaluator_module
from aq_curve import pcr_curve_config as config
from aq_curve.curve import Curve

# run5_2026-07-16_20-20-59.log, FAM well 4 — crosses at Cq ~38.6 (> 36).
PAST_CUTOFF = [
    0.03496, 0.02862, 0.00462, 0.00463, -0.00471, -0.00175, -0.00712, 0.00709,
    -0.00031, 0.0068, -0.00564, 0.00047, 0.00515, 0.00179, -0.00648, -4e-05,
    0.00066, -0.00778, -0.00407, -0.00625, -0.00538, -0.00652, 0.00524, -0.01252,
    -0.01183, -0.00997, -0.01903, -0.01819, -0.02139, -0.01924, -0.02876,
    -0.03066, -0.02464, -0.02517, -0.02803, -0.02654, -0.01865, -0.00992,
    0.0193, 0.07623,
]

# aba_form_3_set_3_2026-05-08_20-05-19.log, FAM well 1 — crosses at Cq ~35.4 (<= 36).
WITHIN_CUTOFF = [
    -0.07761, -0.06425, -0.02999, -0.0319, -0.00847, -0.0041, 0.00333, 0.00239,
    0.00058, -0.00386, -0.00243, -0.00082, 0.00605, 0.00951, -0.01063, -0.01575,
    -0.00411, -0.00054, -0.0057, -0.00617, -0.00944, -0.00325, -0.0057, -0.0045,
    -0.0098, -0.00654, -0.00773, -0.01021, -0.00887, -0.01918, -0.01275,
    -0.01106, -0.00069, 0.00919, 0.03985, 0.08355, 0.16296, 0.28478, 0.43407,
    0.56264,
]


def _make_curve():
    curve = Curve.__new__(Curve)
    curve.baseline_slice = (5, 15)
    curve.test_run = False
    curve.cross_talk_matrix = Curve.DEFAULT_CROSS_TALK_MATRIX
    curve.thresholds = Curve.DEFAULT_THRESHOLDS
    return curve


def _evaluate(y, monkeypatch):
    arr = np.array(y, dtype=float)
    x = np.arange(1.0, len(arr) + 1.0)
    monkeypatch.setattr(
        evaluator_module, "get_curve_data", lambda *a, **k: (x, arr, arr.copy())
    )
    return evaluator_module.evaluate_curve(_make_curve(), "fixture.log", "fam", 1)


def test_cq_past_hard_max_is_undetected(monkeypatch):
    """A crossing past PCR_CQ_HARD_MAX is Not Detected, overriding the late path."""
    ev = _evaluate(PAST_CUTOFF, monkeypatch)
    assert ev["flags"]["cq_after_hard_max"] is True
    assert ev["status"] == "undetected"
    assert ev["decision_reason"] == "cq_after_hard_max"


def test_cq_within_hard_max_still_detected(monkeypatch):
    """A late crossing at or below the cutoff is unaffected and stays Detected."""
    ev = _evaluate(WITHIN_CUTOFF, monkeypatch)
    assert ev["flags"]["cq_after_hard_max"] is False
    assert ev["status"] == "detected"


def test_hard_max_default_is_36():
    assert config.get_float("PCR_CQ_HARD_MAX") == 36
