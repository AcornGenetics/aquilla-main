"""
Unit tests for check_no_rapid_terminal_rise.

A "rapid terminal rise" is a sustained rise that starts fewer than
PCR_RAPID_RISE_MAX_REMAINING cycles before the end of the run AND covers
more than PCR_RAPID_RISE_FRACTION of the total signal range in the first
three post-rise cycles.  Such curves are artifacts, not genuine PCR.

True PCR amplification takes many cycles to develop.  A slow late-Cq rise
(barely emerging at run-end) has a small initial fraction and should pass.
"""
import numpy as np
import pytest
from sentri_curve.evaluator import check_no_rapid_terminal_rise
from sentri_curve.curve import Curve


def _make_curve(baseline_slice=(0, 5)):
    curve = Curve.__new__(Curve)
    curve.baseline_slice = baseline_slice
    curve.test_run = False
    return curve


def _cd(y):
    x = np.arange(1.0, len(y) + 1.0)
    arr = np.array(y, dtype=float)
    return x, arr, arr.copy()


# ---------------------------------------------------------------------------
# Passes: rise starts early enough (≥ 5 cycles remaining)
# ---------------------------------------------------------------------------

def test_early_rise_passes():
    """Normal PCR: rise at cycle 25 of 40 — plenty of cycles remaining."""
    baseline = [0.0] * 24
    rise = list(np.linspace(0.0, 3.0, 16))
    y = baseline + rise
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is True


def test_rise_exactly_at_max_remaining_passes():
    """Rise starting with exactly PCR_RAPID_RISE_MAX_REMAINING cycles left passes."""
    # max_remaining default = 5; rise at index 35 of 40 → remaining = 5
    baseline = [0.0] * 35
    # gradual: fraction in first 3 cycles < 0.65
    gradual = [0.1, 0.2, 0.35, 0.55, 0.80]
    y = baseline + gradual
    # signal_range = 0.80, rise_in_3 = 0.35 - 0.1 = 0.25, fraction = 0.25/0.80 = 0.31 < 0.65
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is True


# ---------------------------------------------------------------------------
# Passes: terminal rise is slow (small fraction of range in 3 cycles)
# ---------------------------------------------------------------------------

def test_slow_terminal_rise_passes():
    """Rise in last 2 cycles but covers only a small fraction — slow late-Cq signal."""
    # Mimics Set1 rox2: rise at cycle 39, signal barely emerges
    baseline = [-0.05] + [0.0] * 36 + [-0.06]
    tail = [0.04, 0.18]
    y = baseline + tail  # 40 cycles total
    # remaining = 2, rise_in_3 = 0.18-0.04 = 0.14, range ≈ 0.24, fraction ≈ 0.58 < 0.65
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is True


# ---------------------------------------------------------------------------
# Fails: terminal rise is rapid (large fraction of range in 3 cycles)
# ---------------------------------------------------------------------------

def test_rapid_terminal_rise_fails_3_remaining():
    """Rise in last 3 cycles covering most of the signal range — artifact."""
    baseline = [0.0] * 37
    # rapid: 0.05 → 0.17 → 0.39 (similar to Set2 rox4)
    tail = [0.05, 0.17, 0.39]
    y = baseline + tail  # 40 cycles
    # remaining = 3, range ≈ 0.39, rise_in_3 = 0.39-0.05 = 0.34, fraction = 0.87 > 0.65
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is False


def test_rapid_terminal_rise_fails_4_remaining():
    """Rise in last 4 cycles covering most of the signal range — artifact."""
    baseline = [0.0] * 36
    # rapid: 0.11 → 0.29 → 0.57 → 0.98 (similar to Set3 rox1)
    tail = [0.11, 0.29, 0.57, 0.98]
    y = baseline + tail  # 40 cycles
    # remaining = 4, range ≈ 0.98, rise_in_3 = 0.57-0.11 = 0.46, fraction = 0.47...
    # Actually: threshold is at 10% of range from baseline_mean ≈ 0.0
    # threshold ≈ 0.098, sustained_rise_index finds first 3 consecutive ≥ 0.098 → starts at idx 36
    # remaining = 40 - 36 = 4 < 5
    # end3 = min(36+3, 39) = 39
    # rise_in_3 = y[39] - y[36] = 0.98 - 0.11 = 0.87
    # range = 0.98 - 0.0 = 0.98
    # fraction = 0.87/0.98 = 0.89 > 0.65 → fails
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is False


def test_rapid_terminal_rise_fails_when_covers_full_range():
    """Rise in last 4 cycles that reaches plateau — clearly artificial."""
    baseline = [0.0] * 36
    tail = [0.2, 0.6, 1.0, 1.0]  # jumps to full plateau in 3 cycles
    y = baseline + tail
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_no_rise_passes():
    """Flat noise with no sustained rise passes the check."""
    y = [0.0 + 0.01 * np.sin(i) for i in range(40)]
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is True


def test_zero_signal_range_passes():
    """Perfectly flat signal (zero range) does not raise and passes."""
    y = [1.0] * 40
    assert check_no_rapid_terminal_rise(_cd(y), _make_curve()) is True
