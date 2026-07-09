import numpy as np
import pytest
from unittest.mock import patch
from aq_curve.evaluator import check_no_mountain_shape, check_late_cq_tier
from aq_curve.curve import Curve


def _make_curve():
    curve = Curve.__new__(Curve)
    curve.baseline_slice = (0, 5)
    curve.test_run = False
    return curve


def _curve_data(y):
    x = np.arange(1.0, len(y) + 1.0)
    return x, np.array(y, dtype=float), np.array(y, dtype=float)


# --- Fix 2: mountain drop ratio tightened at late Cq ---

def test_mountain_passes_early_cq_at_0_35():
    # drop_ratio ~0.30 with Cq ~20 — passes at 0.35 threshold
    y = [0.0] * 5 + list(np.linspace(0.0, 1.0, 15)) + list(np.linspace(1.0, 0.70, 20))
    cd = _curve_data(y)
    curve = _make_curve()
    assert check_no_mountain_shape(cd, curve)[0] is True


def test_mountain_rejected_late_cq_drop_ratio_above_0_25():
    # Late-Cq curve (Cq ~36) with drop_ratio ~0.353 — fails at 0.25 late threshold
    baseline = [0.05] * 5
    # flat baseline then rises to peak then drops: peak at cycle ~20, then falls hard
    rise = list(np.linspace(0.05, 1.0, 15))
    fall = list(np.linspace(1.0, 0.647, 20))  # drop_ratio = (1.0-0.647)/1.0 ≈ 0.353
    y = baseline + rise + fall
    # Force Cq to be reported as >= 35 by patching compute_cq
    cd = _curve_data(y)
    curve = _make_curve()
    with patch("aq_curve.evaluator.compute_cq", return_value=36.0):
        result = check_no_mountain_shape(cd, curve)[0]
    assert result is False


def test_mountain_rejected_early_cq_drop_ratio_above_0_35():
    # drop_ratio ~0.38 with Cq ~20 — rejected at the standard 0.35 threshold
    # (mean of last 3 fall values ≈ 0.621, so drop_ratio ≈ 0.379)
    baseline = [0.05] * 5
    rise = list(np.linspace(0.05, 1.0, 15))
    fall = list(np.linspace(1.0, 0.60, 20))
    y = baseline + rise + fall
    cd = _curve_data(y)
    curve = _make_curve()
    with patch("aq_curve.evaluator.compute_cq", return_value=20.0):
        result = check_no_mountain_shape(cd, curve)[0]
    # drop_ratio ~0.38 > 0.35 → rejected at early Cq too
    assert result is False


# --- Fix 1: per-cycle fold-rise check at Cq ≥ 35 ---

def test_late_cq_tier_rejects_bg_fam_like_curve():
    # BG FAM: base ~0.112 at Cq, +2 cycles = 0.247 → fold 2.2× < 3.5 threshold
    y = [0.05] * 35 + [0.112, 0.150, 0.247, 0.786, 0.900]
    cd = _curve_data(y)
    curve = _make_curve()
    cq = 36.0  # 0-based index 35, 1-based cycle 36 ≈ Cq
    result = check_late_cq_tier(cd, curve, cq)[0]
    assert result is False


def test_late_cq_tier_passes_genuine_doubling():
    # Genuine exponential: 0.10 → 0.20 → 0.40 at Cq+0, +1, +2 → fold 4× >= 3.5
    y = [0.05] * 35 + [0.10, 0.20, 0.40, 0.80, 0.90]
    cd = _curve_data(y)
    curve = _make_curve()
    cq = 36.0
    result = check_late_cq_tier(cd, curve, cq)[0]
    assert result is True


def test_late_cq_tier_uses_two_cycle_window_not_five():
    # Signal is flat at Cq+2 and Cq+3 but jumps at Cq+5 (old window would pass, new fails)
    y = [0.05] * 35 + [0.10, 0.12, 0.13, 0.14, 0.80]  # big jump only at cycle +5
    cd = _curve_data(y)
    curve = _make_curve()
    cq = 36.0
    result = check_late_cq_tier(cd, curve, cq)[0]
    # fold at +2: 0.13/0.10 = 1.3 → fails (confirms 2-cycle window is used)
    assert result is False
