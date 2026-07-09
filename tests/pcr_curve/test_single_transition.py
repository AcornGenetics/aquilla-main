import numpy as np
import pytest
from aq_curve.evaluator import check_single_transition


def test_single_transition(curve_data, curve):
    assert check_single_transition(curve_data, curve)[0]


class _Curve:
    baseline_slice = (0, 10)


def _curve_data(signal):
    y = np.array(signal, dtype=float)
    x = np.arange(1.0, len(y) + 1.0)
    return x, y, y.copy()


def _pcr_sigmoid(n_cycles=40, amplitude=0.5, midpoint=25, steepness=0.7):
    """
    Baseline-corrected logistic curve matching the signal range of a real PCR run
    (0 → ~0.5 V).  Baseline (cycles 1–10) is clipped to zero after mean subtraction;
    the exponential rise begins around cycle 22 and reaches its inflection at cycle 25.
    On the log-scale graph this appears as a smooth S-curve identical to real data.
    """
    c = np.arange(1, n_cycles + 1, dtype=float)
    y = amplitude / (1 + np.exp(-steepness * (c - midpoint)))
    y -= float(np.mean(y[:10]))
    return np.clip(y, 0.0, None)


def test_minor_dip_within_tolerance_passes(monkeypatch):
    """
    A dip that stays within PCR_TRANSITION_DIP_TOLERANCE of the peak threshold
    should not split a continuous rise into a second transition.

    Signal: logistic sigmoid, 0 → 0.5 V, inflection at cycle 25.
    Cycle 24 (index 23) is depressed so the derivative at that step is 0.034 V/cycle.
    After the perturbation:
      max_deriv  ≈ 0.117  (at the compensated step after the dip)
      peak_threshold = 0.117 * 0.3 ≈ 0.0352
      dip_threshold  = 0.0352 * 0.95 ≈ 0.0334
    0.034 ∈ [0.0334, 0.0352) → tolerance zone → group stays open → 1 transition.
    """
    monkeypatch.setenv("PCR_THRESHOLD_FRACTION", "0.1")
    monkeypatch.setenv("PCR_SUSTAINED_CYCLES", "3")
    monkeypatch.setenv("PCR_PEAK_FRACTION", "0.3")
    monkeypatch.setenv("PCR_TRANSITION_DIP_TOLERANCE", "0.05")
    monkeypatch.setenv("PCR_MAX_TRANSITIONS", "1")

    y = _pcr_sigmoid()
    # Depress index 23 (cycle 24) so the derivative from index 22→23 = 0.034.
    # The following step compensates upward, keeping the rest of the curve intact.
    y[23] = y[22] + 0.034
    assert check_single_transition(_curve_data(y), _Curve())[0]


def test_large_dip_outside_tolerance_counts_as_new_transition(monkeypatch):
    """
    A dip that falls below the tolerance band should end the current group
    and count the following rise as a new transition.

    Same sigmoid as above, but index 23 is depressed further so the derivative
    at that step is 0.030 V/cycle.
    After the perturbation:
      max_deriv  ≈ 0.121
      peak_threshold = 0.121 * 0.3 ≈ 0.0364
      dip_threshold  = 0.0364 * 0.95 ≈ 0.0345
    0.030 < 0.0345 → below tolerance → group breaks → 2 transitions → check fails.
    """
    monkeypatch.setenv("PCR_THRESHOLD_FRACTION", "0.1")
    monkeypatch.setenv("PCR_SUSTAINED_CYCLES", "3")
    monkeypatch.setenv("PCR_PEAK_FRACTION", "0.3")
    monkeypatch.setenv("PCR_TRANSITION_DIP_TOLERANCE", "0.05")
    monkeypatch.setenv("PCR_MAX_TRANSITIONS", "1")

    y = _pcr_sigmoid()
    # Depress index 23 (cycle 24) so the derivative from index 22→23 = 0.030.
    y[23] = y[22] + 0.030
    assert not check_single_transition(_curve_data(y), _Curve())[0]
