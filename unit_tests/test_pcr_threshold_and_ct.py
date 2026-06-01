import numpy as np
import pytest
from aq_curve.pcr_curve_helpers import get_threshold, interpolate_ct, compute_cq


# --- get_threshold (relative / fraction-based) ---

def test_threshold_is_fraction_of_signal_range():
    # baseline mean ≈ 0, max ≈ 1.0  →  threshold = 0 + 0.1 * 1.0 = 0.1
    y = np.array([0.0] * 10 + [1.0] * 10)
    threshold, baseline_mean = get_threshold(y, (0, 10))
    assert abs(baseline_mean) < 1e-9
    assert abs(threshold - 0.1) < 1e-6


def test_threshold_scales_with_amplitude():
    # Same fraction, double amplitude → double threshold
    y_low = np.array([0.0] * 10 + [1.0] * 10)
    y_high = np.array([0.0] * 10 + [2.0] * 10)
    t_low, _ = get_threshold(y_low, (0, 10))
    t_high, _ = get_threshold(y_high, (0, 10))
    assert abs(t_high - 2 * t_low) < 1e-6


def test_threshold_respects_pcr_threshold_env_override(monkeypatch):
    monkeypatch.setenv("PCR_THRESHOLD", "0.99")
    y = np.array([0.0] * 5 + [1.0] * 5)
    threshold, _ = get_threshold(y, (0, 5))
    assert threshold == pytest.approx(0.99)


def test_threshold_respects_fraction_env_override(monkeypatch):
    monkeypatch.setenv("PCR_THRESHOLD_FRACTION", "0.2")
    y = np.array([0.0] * 10 + [1.0] * 10)
    threshold, _ = get_threshold(y, (0, 10))
    assert threshold == pytest.approx(0.2)


def test_threshold_flat_signal_does_not_raise():
    y = np.zeros(20)
    threshold, baseline_mean = get_threshold(y, (0, 10))
    assert threshold == pytest.approx(baseline_mean)


# --- interpolate_ct ---

def test_interpolate_ct_exact_crossing():
    # ydata crosses threshold=0.5 exactly between index 1 (y=0.0) and index 2 (y=1.0)
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([0.0, 0.0, 1.0])
    ct = interpolate_ct(x, y, 0.5, start_idx=2)
    assert ct == pytest.approx(2.5)


def test_interpolate_ct_start_at_zero():
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 3.0])
    ct = interpolate_ct(x, y, 0.5, start_idx=0)
    assert ct == pytest.approx(1.0)


def test_interpolate_ct_quarter_crossing():
    # y goes 0 → 0.4 between cycles 5 and 6, threshold = 0.1 → 25% of the way across
    x = np.array([5.0, 6.0])
    y = np.array([0.0, 0.4])
    ct = interpolate_ct(x, y, 0.1, start_idx=1)
    assert ct == pytest.approx(5.25)


# --- compute_cq (fractional) ---

def test_compute_cq_returns_fractional_value():
    # Flat baseline then linear ramp crossing threshold somewhere between integer cycles.
    x = np.arange(1.0, 41.0)
    y = np.zeros(40)
    # Ramp starts at cycle 11: y[10] = 0.0, y[11] = 0.05, y[12] = 0.10, ...
    for i in range(10, 40):
        y[i] = (i - 10) * 0.05
    # With fraction=0.1 and max≈1.45, threshold ≈ 0.145.
    # That falls between y[12]=0.10 and y[13]=0.15 at x=13→14.
    threshold_env = "0.145"
    import os
    old = os.environ.get("PCR_THRESHOLD")
    os.environ["PCR_THRESHOLD"] = threshold_env
    try:
        cq = compute_cq(x, y, 0.145, min_consecutive=1, skip_cycles=7)
        assert cq is not None
        assert 13.0 < cq < 14.0
    finally:
        if old is None:
            del os.environ["PCR_THRESHOLD"]
        else:
            os.environ["PCR_THRESHOLD"] = old


def test_compute_cq_no_crossing_returns_none():
    x = np.arange(1.0, 41.0)
    y = np.zeros(40)
    cq = compute_cq(x, y, 1.0, min_consecutive=3, skip_cycles=7)
    assert cq is None
