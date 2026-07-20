import numpy as np
from aq_curve import pcr_curve_config as config
from aq_curve.pcr_curve_helpers import (
    compute_cq,
    compute_r2,
    count_threshold_crossings,
    get_baseline_values,
    get_curve_data,
    get_threshold,
    sustained_rise_index,
    trough_index,
)


def _spike_only_crossings(y_corrected, threshold):
    """Return True if every threshold crossing is caused by an isolated spike rather than sustained rise."""
    diffs = np.abs(np.diff(y_corrected))
    median_diff = float(np.median(diffs))
    if median_diff == 0:
        return False
    multiplier = config.get_float("PCR_SPIKE_CROSSING_MULTIPLIER")
    spike_mask = diffs > median_diff * multiplier
    above = y_corrected >= threshold
    crossing_indices = [i + 1 for i in range(len(above) - 1) if not above[i] and above[i + 1]]
    if not crossing_indices:
        return False
    for idx in crossing_indices:
        if not spike_mask[idx - 1]:
            return False
    return True


def check_threshold_crossing(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    crossings = count_threshold_crossings(y_corrected, threshold)
    return crossings >= 1


def check_threshold_oscillation(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    rise_index = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if rise_index is None:
        return True
    post_rise = y_corrected[rise_index:]
    crossings = count_threshold_crossings(post_rise, threshold)
    return crossings <= 2


def check_baseline_length(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    min_baseline_cycles = config.get_int("PCR_MIN_BASELINE_CYCLES")
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is not None and start < 7:
        start = 7
    return start is not None and start >= min_baseline_cycles


def check_baseline_stability(curve_data, curve):
    # Composite Check: passes only if BOTH baseline std and slope are in range. Both
    # values are emitted as their own Metric rows; the check's own verdict is the AND.
    xdata, y_corrected, _ = curve_data
    start, end = curve.baseline_slice
    baseline_values = y_corrected[start:end]
    max_std = config.get_float("PCR_BASELINE_STD_MAX")
    max_slope = config.get_float("PCR_BASELINE_SLOPE_MAX")
    std = float(np.std(baseline_values))
    slope = abs(float(np.polyfit(xdata[start:end], baseline_values, 1)[0]))
    std_ok = std <= max_std
    slope_ok = slope <= max_slope
    rows = [
        {"name": "baseline_std", "value": std, "threshold": max_std, "passed": std_ok},
        {"name": "baseline_slope", "value": slope, "threshold": max_slope, "passed": slope_ok},
    ]
    return std_ok and slope_ok, rows


def check_cycle_location(curve_data, curve):
    xdata, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    cq = compute_cq(xdata, y_corrected, threshold, min_consecutive)
    if cq is None:
        return False
    min_cq = config.get_int("PCR_CQ_MIN")
    max_cq = config.get_int("PCR_CQ_MAX")
    return min_cq <= cq <= max_cq


def check_log_phase_linearity(curve_data, curve):
    xdata, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    cq = compute_cq(xdata, y_corrected, threshold, min_consecutive)
    # Anchor the rise scan at the dip trough so the leading optical artifact
    # cannot mis-anchor the log phase at index 0.
    floor = trough_index(y_corrected)
    start = sustained_rise_index(y_corrected, threshold, min_consecutive, floor=floor)
    if start is None:
        return False, []
    end = _find_log_phase_end(y_corrected, start)
    x_segment = xdata[start:end + 1]
    y_segment = y_corrected[start:end + 1]
    mask = y_segment > 0
    x_segment = x_segment[mask]
    log_segment = np.log(y_segment[mask])
    if len(log_segment) < 2:
        return True, []
    r2 = compute_r2(x_segment, log_segment)
    late_threshold = config.get_float("PCR_LATE_CQ_THRESHOLD")
    if cq is not None and cq >= late_threshold:
        min_r2 = config.get_float("PCR_LATE_R2_MIN")
    elif cq is not None and cq >= 30:
        min_r2 = config.get_float("PCR_LOG_PHASE_R2_MID")
    else:
        min_r2 = config.get_float("PCR_LOG_PHASE_R2_MIN")
    passed = r2 >= min_r2
    return passed, [{"name": "log_phase_r2", "value": float(r2), "threshold": float(min_r2), "passed": bool(passed)}]


def check_monotonic_rise(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    signal_range = float(np.max(y_corrected)) - float(np.min(y_corrected))
    max_drop = config.get_float("PCR_MAX_DROP_RELATIVE") * signal_range
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False
    segment = y_corrected[start:]
    drops = np.diff(segment)
    return np.all(drops >= -max_drop)


def check_no_late_drift(curve_data, curve):
    xdata, y_corrected, _ = curve_data
    late_cycles = config.get_int("PCR_LATE_CYCLES")
    slope = np.polyfit(
        xdata[-late_cycles:],
        y_corrected[-late_cycles:],
        1,
    )[0]
    neg_drift_min = config.get_float("PCR_LATE_NEGATIVE_DRIFT_MIN")
    terminal_slope = float(slope)
    passed = terminal_slope >= -neg_drift_min
    return passed, [{"name": "terminal_slope", "value": terminal_slope, "threshold": -neg_drift_min, "passed": bool(passed)}]


def check_negative_drop(curve_data, curve):
    _, y_corrected, _ = curve_data
    window = config.get_int("PCR_NEGATIVE_DROP_WINDOW")
    signal_range = float(np.max(y_corrected)) - float(np.min(y_corrected))
    min_val = float(np.min(y_corrected[-window:]))
    drop_min = config.get_float("PCR_NEGATIVE_DROP_MIN")
    return min_val >= drop_min * signal_range


def check_no_mountain_shape(curve_data, curve):
    xdata, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    rise_index = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if rise_index is None:
        return True, []
    rise_segment = y_corrected[rise_index:]
    peak_offset = int(np.argmax(rise_segment))
    peak_signal = float(rise_segment[peak_offset])
    end_signal = float(np.mean(y_corrected[-3:]))
    if peak_signal <= 0:
        return True, []
    drop_ratio = (peak_signal - end_signal) / peak_signal
    peak_cycle = rise_index + peak_offset
    total_cycles = len(y_corrected)
    cq = compute_cq(xdata, y_corrected, threshold, min_consecutive)
    late_threshold = config.get_float("PCR_LATE_CQ_THRESHOLD")
    if cq is not None and cq >= late_threshold:
        threshold_ratio = config.get_float("PCR_MOUNTAIN_DROP_RATIO_LATE")
    else:
        threshold_ratio = config.get_float("PCR_MOUNTAIN_DROP_RATIO")
    passed = not (drop_ratio > threshold_ratio and peak_cycle < total_cycles - 8)
    return passed, [{"name": "drop_ratio", "value": float(drop_ratio), "threshold": float(threshold_ratio), "passed": bool(passed)}]


def check_end_above_midpoint(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    rise_index = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if rise_index is None:
        return True
    rise_len = len(y_corrected) - rise_index
    midpoint_idx = rise_index + rise_len // 2
    midpoint_signal = float(y_corrected[midpoint_idx])
    end_signal = float(np.mean(y_corrected[-5:]))
    fraction = config.get_float("PCR_END_MIDPOINT_FRACTION")
    return end_signal >= midpoint_signal * fraction


def check_sigmoidal_profile(curve_data, curve):
    xdata, y_corrected, _ = curve_data
    threshold, baseline_mean = get_threshold(y_corrected, curve.baseline_slice)
    min_peak_fraction = config.get_float("PCR_MIN_PEAK_FRACTION")
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    max_val = float(np.max(y_corrected))
    if max_val <= 0:
        return False
    amplitude_fraction = (max_val - baseline_mean) / max_val
    if amplitude_fraction < min_peak_fraction:
        return False
    # Anchor the rise scan at the dip trough so the leading optical artifact
    # cannot mis-anchor it at index 0, then measure the slope over the log
    # phase only ([start:end]). Fitting through the trailing plateau dilutes
    # the slope for late risers; fitting from the trough adds a long flat
    # baseline for late risers. The log-phase window avoids both.
    floor = trough_index(y_corrected)
    start = sustained_rise_index(y_corrected, threshold, min_consecutive, floor=floor)
    if start is None:
        return False
    end = _find_log_phase_end(y_corrected, start)
    slope = float(np.polyfit(xdata[start:end + 1], y_corrected[start:end + 1], 1)[0])
    signal_range = float(np.max(y_corrected)) - float(np.min(y_corrected))
    post_rise_min = config.get_float("PCR_POST_RISE_SLOPE_MIN")
    return slope >= post_rise_min * signal_range


def check_signal_range(curve_data, curve):
    _, y_corrected, y_raw = curve_data
    start, end = curve.baseline_slice
    baseline_values = y_raw[start:end]
    baseline_mean = float(np.mean(baseline_values))
    if baseline_mean <= 0:
        return False, []
    peak = float(np.max(y_raw))
    min_peak_fraction = config.get_float("PCR_SIGNAL_RANGE_PEAK_FRACTION")
    min_fold = config.get_float("PCR_MIN_FOLD")
    if peak <= 0:
        return False, []
    amplitude_fraction = (peak - baseline_mean) / peak
    fold_change = peak / baseline_mean
    relative_ok = amplitude_fraction >= min_peak_fraction or fold_change >= min_fold
    min_abs_signal = config.get_float("PCR_MIN_ABS_SIGNAL")
    abs_signal = float(np.max(y_corrected))
    abs_ok = abs_signal >= min_abs_signal
    rows = [
        {"name": "amplitude_fraction", "value": float(amplitude_fraction), "threshold": float(min_peak_fraction), "passed": bool(amplitude_fraction >= min_peak_fraction)},
        {"name": "fold_change", "value": float(fold_change), "threshold": float(min_fold), "passed": bool(fold_change >= min_fold)},
        {"name": "abs_signal", "value": abs_signal, "threshold": float(min_abs_signal), "passed": bool(abs_ok)},
    ]
    return relative_ok and abs_ok, rows


def check_single_transition(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False, []
    deriv = np.diff(y_corrected)
    rise_deriv = deriv[start:]
    if len(rise_deriv) < 2:
        return True, []
    max_deriv = float(np.max(rise_deriv))
    if max_deriv <= 0:
        return True, []
    peak_fraction = config.get_float("PCR_PEAK_FRACTION")
    peak_threshold = max_deriv * peak_fraction
    dip_tolerance = config.get_float("PCR_TRANSITION_DIP_TOLERANCE")
    dip_threshold = peak_threshold * (1.0 - dip_tolerance)
    transitions = 0
    in_peak = False
    for val in rise_deriv:
        if val >= peak_threshold:
            if not in_peak:
                transitions += 1
                in_peak = True
        elif val < dip_threshold:
            in_peak = False
        # values in [dip_threshold, peak_threshold): maintain current state
    max_transitions = config.get_int("PCR_MAX_TRANSITIONS")
    passed = transitions <= max_transitions
    return passed, [{"name": "transition_count", "value": float(transitions), "threshold": float(max_transitions), "passed": bool(passed)}]


def check_no_rapid_terminal_rise(curve_data, curve):
    """Return False if the signal rises abruptly in the final few cycles.

    True PCR amplification takes many cycles to develop.  A curve whose
    sustained rise starts with fewer than PCR_RAPID_RISE_MAX_REMAINING cycles
    left AND covers more than PCR_RAPID_RISE_FRACTION of the total signal range
    in the first three post-rise cycles is an unphysiologically fast artifact.
    """
    xdata, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    rise_idx = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if rise_idx is None:
        return True

    n = len(y_corrected)
    cycles_remaining = n - rise_idx
    max_remaining = config.get_int("PCR_RAPID_RISE_MAX_REMAINING")
    onset_cycle = float(xdata[rise_idx]) if rise_idx < len(xdata) else float(n)
    late_cycle = config.get_float("PCR_RAPID_RISE_LATE_CYCLE")
    # A rise is "terminal" if it starts in the last few cycles OR its onset is
    # after the late-cycle cutoff (35). The cycles-remaining test alone lets a
    # steep rise that starts exactly at cycle 36 (5 cycles left) slip through as
    # non-terminal; anchoring to the absolute cycle catches any rapid rise that
    # first emerges after cycle 35.
    if cycles_remaining >= max_remaining and onset_cycle <= late_cycle:
        return True

    signal_range = float(np.max(y_corrected)) - float(np.min(y_corrected))
    if signal_range <= 0:
        return True

    end3 = min(rise_idx + 3, n - 1)
    rise_in_3 = float(y_corrected[end3] - y_corrected[rise_idx])
    fraction = rise_in_3 / signal_range
    max_fraction = config.get_float("PCR_RAPID_RISE_FRACTION")
    return fraction < max_fraction


def check_smooth_features(curve_data, curve):
    _, y_corrected, _ = curve_data
    diffs = np.diff(y_corrected)
    abs_diffs = np.abs(diffs)
    median_diff = float(np.median(abs_diffs))
    max_diff = float(np.max(abs_diffs))
    if median_diff == 0:
        max_allowed = config.get_float("PCR_MAX_DIFF")
        return max_diff <= max_allowed
    multiplier = config.get_float("PCR_SPIKE_MULTIPLIER")
    return max_diff <= median_diff * multiplier


def check_stable_slope(curve_data, curve):
    slope_cv = _compute_stable_slope_cv(curve_data, curve)
    max_cv = config.get_float("PCR_LOG_PHASE_SLOPE_CV_MAX")
    passed = True if slope_cv is None else slope_cv <= max_cv
    rows = (
        []
        if slope_cv is None
        else [{"name": "slope_cv", "value": float(slope_cv), "threshold": max_cv, "passed": bool(passed)}]
    )
    return passed, rows


def check_biphasic_stable_slope(curve_data, curve):
    slope_cv = _compute_stable_slope_cv(curve_data, curve)
    if slope_cv is None:
        return True
    max_cv = config.get_float("BIPHASIC_LOG_PHASE_SLOPE_CV_MAX")
    return slope_cv <= max_cv


def check_biphasic_peaks(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False
    min_total_cycles = config.get_int("BIPHASIC_MIN_TOTAL_CYCLES")
    y_segment = y_corrected[start:]
    if len(y_segment) < min_total_cycles:
        return False
    smooth_window = config.get_int("BIPHASIC_SMOOTH_WINDOW")
    smoothed = _smooth_series(y_segment, smooth_window)
    deriv = np.diff(smoothed)
    if len(deriv) < 3:
        return False
    max_deriv = float(np.max(deriv))
    if max_deriv <= 0:
        return False
    peak_fraction = config.get_float("BIPHASIC_PEAK_FRACTION")
    peak_mask = deriv >= max_deriv * peak_fraction
    groups = _group_true_indices(peak_mask)
    peaks = []
    for group_start, group_end in groups:
        group_slice = deriv[group_start:group_end + 1]
        peak_offset = int(np.argmax(group_slice))
        peak_index = group_start + peak_offset
        peaks.append((peak_index, float(group_slice[peak_offset]), group_start, group_end))
    min_separation = config.get_int("BIPHASIC_MIN_PEAK_SEPARATION")
    second_peak_fraction = config.get_float("BIPHASIC_SECOND_PEAK_FRACTION")
    dip_fraction = config.get_float("BIPHASIC_DIP_FRACTION")
    if len(peaks) >= 2:
        peaks.sort(key=lambda item: item[0])
        for idx in range(len(peaks) - 1):
            first_peak = peaks[idx]
            second_peak = peaks[idx + 1]
            if second_peak[0] - first_peak[0] < min_separation:
                continue
            if second_peak[1] < max_deriv * second_peak_fraction:
                continue
            valley_start = first_peak[3] + 1
            valley_end = second_peak[2]
            if valley_end <= valley_start:
                continue
            valley_min = float(np.min(deriv[valley_start:valley_end]))
            if valley_min <= max_deriv * dip_fraction:
                return True
    peak_index = int(np.argmax(deriv))
    if peak_index >= len(deriv) - 2:
        return False
    dip_threshold = max_deriv * dip_fraction
    rise_threshold = max_deriv * second_peak_fraction
    min_rise_cycles = config.get_int("BIPHASIC_MIN_RISE_CYCLES")
    dip_index = None
    rise_count = 0
    for idx, value in enumerate(deriv):
        if idx <= peak_index:
            continue
        if dip_index is None:
            if idx - peak_index < min_separation:
                continue
            if value <= dip_threshold:
                dip_index = idx
            continue
        if value >= rise_threshold:
            rise_count += 1
            if rise_count >= min_rise_cycles:
                return True
        else:
            rise_count = 0
    return False


def check_sustained_increase(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    min_rise_cycles = config.get_int("PCR_MIN_RISE_CYCLES")
    if _has_sustained_increase(y_corrected, threshold, min_consecutive, min_rise_cycles):
        return True
    start, end = curve.baseline_slice
    baseline_mean = float(np.mean(y_corrected[start:end]))
    return _has_sustained_increase(
        y_corrected,
        baseline_mean,
        min_consecutive,
        min_rise_cycles,
    )


def _compute_stable_slope_cv(curve_data, curve):
    xdata, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    # Skip the leading dip artifact when locating the log phase.
    floor = trough_index(y_corrected)
    start = sustained_rise_index(y_corrected, threshold, min_consecutive, floor=floor)
    if start is None:
        return None
    end = _find_log_phase_end(y_corrected, start)
    x_segment = xdata[start:end + 1]
    y_segment = y_corrected[start:end + 1]
    mask = y_segment > 0
    x_segment = x_segment[mask]
    log_segment = np.log(y_segment[mask])
    if len(log_segment) < 3:
        return None
    slopes = np.diff(log_segment) / np.diff(x_segment)
    mean_slope = float(np.mean(slopes))
    if mean_slope == 0:
        return None
    return float(np.std(slopes)) / abs(mean_slope)


def _smooth_series(ydata, window):
    if window is None or window <= 1:
        return ydata
    window = min(window, len(ydata))
    if window <= 1:
        return ydata
    kernel = np.ones(window) / float(window)
    return np.convolve(ydata, kernel, mode="same")


def _group_true_indices(mask):
    groups = []
    start = None
    for idx, value in enumerate(mask):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            groups.append((start, idx - 1))
            start = None
    if start is not None:
        groups.append((start, len(mask) - 1))
    return groups


def _has_sustained_increase(y_corrected, threshold, min_consecutive, min_rise_cycles):
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False
    if len(y_corrected) - 1 - start < min_rise_cycles:
        return False
    rise_segment = y_corrected[start:]
    increases = np.sum(np.diff(rise_segment) > 0)
    return increases >= min_rise_cycles


def _find_log_phase_end(y_corrected, start):
    if start >= len(y_corrected) - 3:
        return len(y_corrected) - 1
    diffs = np.diff(y_corrected)
    rise_slice = diffs[start:]
    if len(rise_slice) == 0:
        return len(y_corrected) - 1
    max_slope = float(np.max(rise_slice))
    flatten_fraction = config.get_float("PCR_LOG_PHASE_SLOPE_FLATTEN_FRACTION")
    min_points = config.get_int("PCR_LOG_PHASE_SLOPE_MIN_POINTS")
    if max_slope <= 0:
        return min(start + min_points, len(y_corrected) - 1)
    flatten_threshold = max_slope * flatten_fraction
    # Skip slow inhibitor-suppressed initial rise; only include cycles with slope >= 10% of peak
    min_slope = max_slope * config.get_float("PCR_LOG_PHASE_MIN_SLOPE")
    genuine_start = start
    for idx in range(start, len(diffs)):
        if diffs[idx] >= min_slope:
            genuine_start = idx
            break
    end = len(y_corrected) - 1
    for idx in range(genuine_start, len(diffs)):
        if idx - genuine_start >= min_points and diffs[idx] < flatten_threshold:
            end = idx
            break
    if end <= start:
        end = min(start + min_points, len(y_corrected) - 1)
    return end


def check_late_cq_tier(curve_data, curve, cq):
    xdata, y_corrected, _ = curve_data
    cq_idx = max(0, int(round(cq)) - 1)
    window_before = y_corrected[max(0, cq_idx - 2):cq_idx + 1]
    if len(window_before) == 0:
        return False, []
    base_signal = float(np.max(window_before))
    if base_signal <= 0:
        return False, []
    # Per-cycle fold from Cq to Cq+2: genuine amplification doubles each cycle
    # (~4× over 2 cycles), while background noise shows ~1.1×/cycle (~2.2× over 2)
    after_idx = min(cq_idx + 2, len(y_corrected) - 1)
    if after_idx <= cq_idx:
        return False, []
    fold_2 = float(y_corrected[after_idx]) / base_signal
    cycles_elapsed = after_idx - cq_idx
    per_cycle_fold = fold_2 ** (1.0 / cycles_elapsed)
    min_fold = config.get_float("PCR_LATE_PER_CYCLE_FOLD_MIN")
    passed = per_cycle_fold >= min_fold
    return passed, [{"name": "per_cycle_fold", "value": float(per_cycle_fold), "threshold": float(min_fold), "passed": bool(passed)}]


def _run_check(check, curve_data, curve):
    """Run a check, normalizing its return to ``(passed, value_rows)``.

    A check returns either a bare bool (legacy) or ``(passed, [metric rows])`` — the
    Metric value row(s) it computed. The value is computed *before* the pass/fail
    inside the check, so a curve that fails still logs its numbers. On exception the
    check fails closed with no rows.
    """
    try:
        out = check(curve_data, curve)
    except Exception:
        return False, []
    if isinstance(out, tuple):
        passed, rows = out
        return bool(passed), list(rows)
    return bool(out), []


def _collect_checks(checks, curve_data, curve, prefix=""):
    """Run a list of checks -> (``{name: passed}`` dict, all Metric rows).

    The dict is exactly what ``evaluate_curve``'s cascade consumes (so the decision
    logic is unchanged); the rows carry each check's value(s) plus a passed-only row
    for the check verdict itself.
    """
    passes = {}
    rows = []
    for check in checks:
        name = prefix + check.__name__
        passed, value_rows = _run_check(check, curve_data, curve)
        passes[name] = passed
        rows.extend(value_rows)
        rows.append({"name": name, "value": None, "threshold": None, "passed": passed})
    return passes, rows


def check_signal_basics(curve_data, curve):
    checks = [
        check_baseline_length,
        check_baseline_stability,
        check_cycle_location,
        check_log_phase_linearity,
        check_monotonic_rise,
        check_no_late_drift,
        check_negative_drop,
        check_no_mountain_shape,
        check_no_rapid_terminal_rise,
        check_end_above_midpoint,
        check_sigmoidal_profile,
        check_signal_range,
        check_single_transition,
        check_smooth_features,
        check_stable_slope,
        check_sustained_increase,
        check_threshold_oscillation,
    ]
    return _collect_checks(checks, curve_data, curve)


def check_biphasic_basics(curve_data, curve):
    checks = [
        check_baseline_length,
        check_baseline_stability,
        check_signal_range,
        check_smooth_features,
        check_sustained_increase,
        check_biphasic_peaks,
        check_negative_drop,
        check_biphasic_stable_slope,
    ]
    return _collect_checks(checks, curve_data, curve, prefix="biphasic_")


def evaluate_curve(curve, log_name, dye, well):
    curve_data = get_curve_data(curve, log_name, dye, well)
    xdata, y_corrected, y_raw = curve_data
    tc_passed, metric_rows = _run_check(check_threshold_crossing, curve_data, curve)
    metric_rows.append(
        {"name": "check_threshold_crossing", "value": None, "threshold": None, "passed": tc_passed}
    )
    results = {"check_threshold_crossing": tc_passed}
    typical_results, typical_rows = check_signal_basics(curve_data, curve)
    results.update(typical_results)
    metric_rows.extend(typical_rows)
    biphasic_results, biphasic_rows = check_biphasic_basics(curve_data, curve)
    results.update(biphasic_results)
    metric_rows.extend(biphasic_rows)

    threshold_pass = results["check_threshold_crossing"]
    mountain_shape_detected = not (
        typical_results.get("check_no_mountain_shape", True)
        and typical_results.get("check_end_above_midpoint", True)
    )
    rapid_rise_detected = not typical_results.get("check_no_rapid_terminal_rise", True)
    baseline_fail = any(
        not typical_results.get(name, False)
        for name in ("check_baseline_length", "check_baseline_stability")
    )
    other_fail = any(not passed for passed in typical_results.values())
    typical_pass = not curve.test_run and threshold_pass and not (baseline_fail or other_fail)
    biphasic_pass = (
        not curve.test_run
        and threshold_pass
        and all(biphasic_results.values())
    )

    threshold_val, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    cq = compute_cq(xdata, y_corrected, threshold_val, min_consecutive)
    late_threshold = config.get_float("PCR_LATE_CQ_THRESHOLD")

    signal_range_pass = typical_results.get("check_signal_range", True)
    spike_only_crossings = threshold_pass and _spike_only_crossings(y_corrected, threshold_val)
    if spike_only_crossings:
        threshold_pass = False

    # Evaluate late-Cq confidence up-front so it can override strict shape checks
    # that are inherently harder to pass for a signal that barely emerged near run-end.
    if cq is not None and cq >= late_threshold:
        late_ok, late_rows = _run_check(
            lambda cd, c: check_late_cq_tier(cd, c, cq),
            curve_data,
            curve,
        )
        metric_rows.extend(late_rows)
        late_confident = (
            late_ok
            and threshold_pass
            and not baseline_fail
            and not rapid_rise_detected
            and typical_results.get("check_threshold_oscillation", True)
        )
    else:
        late_ok = False
        late_confident = False

    if late_confident:
        status = "detected"
        decision_reason = "late_cq_confident"
    elif not threshold_pass or not signal_range_pass:
        status = "undetected"
        decision_reason = "threshold_fail" if not threshold_pass else "signal_range_fail"
    elif mountain_shape_detected or rapid_rise_detected:
        status = "undetected"
        decision_reason = "mountain_shape" if mountain_shape_detected else "rapid_rise"
    elif cq is None and not typical_results.get("check_sustained_increase", True):
        # No Cq and no sustained increase: threshold was crossed by noise or a spike
        status = "undetected"
        decision_reason = "no_cq_no_increase"
    elif cq is not None and cq >= late_threshold:
        if late_ok and (typical_pass or biphasic_pass):
            status = "detected"
            decision_reason = "typical_or_biphasic_pass"
        else:
            status = "inconclusive"
            decision_reason = "late_cq_not_confident"
    elif typical_pass or biphasic_pass:
        status = "detected"
        decision_reason = "typical_or_biphasic_pass"
    else:
        status = "inconclusive"
        decision_reason = "test_run" if curve.test_run else "both_paths_failed"

    # Shared pure measures, emitted once (checks emit their own specific values).
    metric_rows.extend([
        {"name": "cq", "value": None if cq is None else float(cq), "threshold": None, "passed": None},
        {"name": "threshold", "value": float(threshold_val), "threshold": None, "passed": None},
        {"name": "n_cycles", "value": float(len(y_corrected)), "threshold": None, "passed": None},
        # Guard against a well/channel with no signal (e.g. ROX Unavailable, or an
        # aborted/truncated read): np.max on an empty array raises and would sink the
        # entire Run's results. An empty curve has no range -> 0.0.
        {"name": "signal_range", "value": (float(np.max(y_corrected)) - float(np.min(y_corrected))) if len(y_corrected) else 0.0, "threshold": None, "passed": None},
        # The RAW baseline floor (mean fluorescence over the baseline cycles of the
        # uncorrected curve) -- the level that drifts up as optics age. Feeds the
        # upstream Baseline Increase metric. Read from y_raw, NOT the baseline-
        # corrected curve (whose baseline is ~0 by construction). An empty curve's
        # baseline is UNKNOWN, not 0: emit None (like cq), never 0.0. A 0 gets pooled
        # into the upstream all-time-median reference and drags it to 0, which NULLs
        # out the increase for every real run on the device (#319 follow-up).
        {"name": "baseline_rfu", "value": float(np.mean(get_baseline_values(y_raw, curve.baseline_slice))) if len(y_raw) else None, "threshold": None, "passed": None},
    ])
    # Dedup by name (first wins): a check reused across typical/biphasic emits its
    # value once; a shared measure is not overwritten by a later duplicate.
    seen, metrics = set(), []
    for row in metric_rows:
        if row["name"] in seen:
            continue
        seen.add(row["name"])
        metrics.append(row)

    return {
        "status": status,
        "threshold_pass": threshold_pass,
        "results": results,
        "metrics": metrics,
        # Derived decision layer (#299): the flags evaluate_curve already computed and
        # the cascade branch that produced the status. Records *why* the Call came out
        # as it did; the cascade logic itself is unchanged.
        "decision_reason": decision_reason,
        "flags": {
            "threshold_pass": bool(threshold_pass),
            "spike_only_crossings": bool(spike_only_crossings),
            "test_run": bool(curve.test_run),
            "typical_pass": bool(typical_pass),
            "biphasic_pass": bool(biphasic_pass),
            "baseline_fail": bool(baseline_fail),
            "mountain_shape_detected": bool(mountain_shape_detected),
            "rapid_rise_detected": bool(rapid_rise_detected),
            "late_ok": bool(late_ok),
            "late_confident": bool(late_confident),
            "signal_range_pass": bool(signal_range_pass),
        },
    }
