"""Call Evidence Metric/Check collection (#298).

Builds the metric rows for a Call's evidence WITHOUT touching the decision logic:
- Checks come straight from ``evaluate_curve``'s ``results`` dict (already computed).
- Values are recomputed here by reusing the SAME pure helpers the checks use, so the
  numbers match what the engine saw. Nothing in ``evaluator.py`` (the checks or the
  cascade) is modified — this module is purely additive, so it cannot change a Call.

Each row is ``{name, value, threshold, passed}`` (the frozen call_evidence contract):
a Check is passed-only; a pure measure is value-only; a gated value carries all three.
"""


import numpy as np

from aq_curve import pcr_curve_config as config
from aq_curve.pcr_curve_helpers import (
    compute_cq,
    compute_r2,
    get_threshold,
    sustained_rise_index,
    trough_index,
)
from aq_curve.evaluator import _compute_stable_slope_cv, _find_log_phase_end


def check_metric_rows(results):
    """One passed-only row per Check in the evaluation ``results`` dict."""
    return [
        {"name": name, "value": None, "threshold": None, "passed": bool(passed)}
        for name, passed in results.items()
    ]


def collect_metrics(curve_data, curve):
    """Pure Metric *values* for one curve, reusing the engine helpers.

    Rows are pure measures — ``{name, value, threshold: None, passed: None}``. The
    pass/fail verdicts live in the Check rows (a Check's threshold/tiering is often
    contextual, so we never re-derive it here — that would risk diverging from the
    engine). Every value is guarded: a degenerate curve yields ``None``, not a crash.
    """
    xdata, y_corrected, y_raw = curve_data
    xdata = np.asarray(xdata, dtype=float)
    y_corrected = np.asarray(y_corrected, dtype=float)
    y_raw = np.asarray(y_raw, dtype=float)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    start, end = curve.baseline_slice

    try:
        threshold, baseline_mean = get_threshold(y_corrected, curve.baseline_slice)
    except Exception:
        threshold, baseline_mean = None, 0.0

    values = {}

    def emit(name, fn):
        try:
            v = fn()
            values[name] = None if v is None else float(v)
        except Exception:
            values[name] = None

    emit("threshold", lambda: threshold)
    emit("cq", lambda: compute_cq(xdata, y_corrected, threshold, min_consecutive))
    emit("n_cycles", lambda: len(y_corrected))
    emit("signal_range", lambda: float(np.max(y_corrected)) - float(np.min(y_corrected)))
    emit("abs_signal", lambda: float(np.max(y_corrected)))
    emit("baseline_std", lambda: float(np.std(y_corrected[start:end])))
    emit("baseline_slope", lambda: float(np.polyfit(xdata[start:end], y_corrected[start:end], 1)[0]))
    emit("amplitude_fraction", lambda: (float(np.max(y_corrected)) - baseline_mean) / float(np.max(y_corrected)))
    emit("slope_cv", lambda: _compute_stable_slope_cv(curve_data, curve))

    def terminal_slope():
        n = config.get_int("PCR_LATE_CYCLES")
        return float(np.polyfit(xdata[-n:], y_corrected[-n:], 1)[0])

    emit("terminal_slope", terminal_slope)

    def fold_change():
        base = float(np.mean(y_raw[start:end]))
        return float(np.max(y_raw)) / base if base else None

    emit("fold_change", fold_change)

    def log_phase_r2():
        floor = trough_index(y_corrected)
        rise = sustained_rise_index(y_corrected, threshold, min_consecutive, floor=floor)
        if rise is None:
            return None
        stop = _find_log_phase_end(y_corrected, rise)
        xs, ys = xdata[rise:stop + 1], y_corrected[rise:stop + 1]
        mask = ys > 0
        if int(mask.sum()) < 2:
            return None
        return compute_r2(xs[mask], np.log(ys[mask]))

    emit("log_phase_r2", log_phase_r2)

    def drop_ratio():
        rise = sustained_rise_index(y_corrected, threshold, min_consecutive)
        if rise is None:
            return None
        peak = float(np.max(y_corrected[rise:]))
        end_signal = float(np.mean(y_corrected[-3:]))
        return (peak - end_signal) / peak if peak > 0 else None

    emit("drop_ratio", drop_ratio)

    def per_cycle_fold():
        cq = values.get("cq")
        if cq is None:
            return None
        cq_idx = max(0, int(round(cq)) - 1)
        window = y_corrected[max(0, cq_idx - 2):cq_idx + 1]
        base = float(np.max(window)) if len(window) else 0.0
        after = min(cq_idx + 2, len(y_corrected) - 1)
        if base <= 0 or after <= cq_idx:
            return None
        return (float(y_corrected[after]) / base) ** (1.0 / (after - cq_idx))

    emit("per_cycle_fold", per_cycle_fold)

    def transition_count():
        rise = sustained_rise_index(y_corrected, threshold, min_consecutive)
        if rise is None:
            return None
        deriv = np.diff(y_corrected)[rise:]
        if len(deriv) < 2:
            return 0
        max_deriv = float(np.max(deriv))
        if max_deriv <= 0:
            return 0
        peak_threshold = max_deriv * config.get_float("PCR_PEAK_FRACTION")
        dip_threshold = peak_threshold * (1.0 - config.get_float("PCR_TRANSITION_DIP_TOLERANCE"))
        transitions, in_peak = 0, False
        for val in deriv:
            if val >= peak_threshold:
                if not in_peak:
                    transitions += 1
                    in_peak = True
            elif val < dip_threshold:
                in_peak = False
        return transitions

    emit("transition_count", transition_count)

    return [
        {"name": name, "value": value, "threshold": None, "passed": None}
        for name, value in values.items()
    ]
