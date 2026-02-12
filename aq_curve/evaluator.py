import numpy as np
from aq_curve import pcr_curve_config as config
from aq_curve.pcr_curve_helpers import (
    compute_cq,
    compute_r2,
    count_threshold_crossings,
    get_curve_data,
    get_threshold,
    sustained_rise_index,
)


def check_threshold_crossing(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    crossings = count_threshold_crossings(y_corrected, threshold)
    return crossings >= 1


def check_threshold_oscillation(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    crossings = count_threshold_crossings(y_corrected, threshold)
    return crossings <= 1


def check_baseline_length(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    min_baseline_cycles = config.get_int("PCR_MIN_BASELINE_CYCLES")
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    return start is not None and start >= min_baseline_cycles


def check_baseline_stability(curve_data, curve):
    xdata, y_corrected, _ = curve_data
    start, end = curve.baseline_slice
    baseline_values = y_corrected[start:end]
    max_std = config.get_float("PCR_BASELINE_STD_MAX")
    if float(np.std(baseline_values)) > max_std:
        return False
    slope = np.polyfit(xdata[start:end], baseline_values, 1)[0]
    max_slope = config.get_float("PCR_BASELINE_SLOPE_MAX")
    return abs(float(slope)) <= max_slope


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
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False
    end = _find_log_phase_end(y_corrected, start)
    x_segment = xdata[start:end + 1]
    y_segment = y_corrected[start:end + 1]
    mask = y_segment > 0
    x_segment = x_segment[mask]
    log_segment = np.log(y_segment[mask])
    if len(log_segment) < 3:
        return False
    r2 = compute_r2(x_segment, log_segment)
    min_r2 = config.get_float("PCR_LOG_PHASE_R2_MIN")
    return r2 >= min_r2


def check_monotonic_rise(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    max_drop = config.get_float("PCR_MAX_DROP")
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
    max_drift = config.get_float("PCR_LATE_DRIFT_MAX")
    return float(slope) <= max_drift


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
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False
    slope = np.polyfit(
        xdata[start:],
        y_corrected[start:],
        1,
    )[0]
    return slope > 0


def check_signal_range(curve_data, curve):
    _, _, y_raw = curve_data
    start, end = curve.baseline_slice
    baseline_values = y_raw[start:end]
    baseline_mean = float(np.mean(baseline_values))
    if baseline_mean <= 0:
        return False
    peak = float(np.max(y_raw))
    min_peak_fraction = config.get_float("PCR_SIGNAL_RANGE_PEAK_FRACTION")
    min_fold = config.get_float("PCR_MIN_FOLD")
    if peak <= 0:
        return False
    amplitude_fraction = (peak - baseline_mean) / peak
    fold_change = peak / baseline_mean
    return amplitude_fraction >= min_peak_fraction or fold_change >= min_fold


def check_single_transition(curve_data, curve):
    _, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False
    deriv = np.diff(y_corrected)
    rise_deriv = deriv[start:]
    max_deriv = float(np.max(rise_deriv))
    if max_deriv <= 0:
        return False
    peak_fraction = config.get_float("PCR_PEAK_FRACTION")
    peak_indices = np.where(rise_deriv >= max_deriv * peak_fraction)[0]
    transitions = 0
    last_index = None
    for idx in peak_indices:
        if last_index is None or idx > last_index + 1:
            transitions += 1
        last_index = idx
    max_transitions = config.get_int("PCR_MAX_TRANSITIONS")
    return transitions <= max_transitions


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
    xdata, y_corrected, _ = curve_data
    threshold, _ = get_threshold(y_corrected, curve.baseline_slice)
    min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
    if start is None:
        return False
    end = _find_log_phase_end(y_corrected, start)
    x_segment = xdata[start:end + 1]
    y_segment = y_corrected[start:end + 1]
    mask = y_segment > 0
    x_segment = x_segment[mask]
    log_segment = np.log(y_segment[mask])
    if len(log_segment) < 3:
        return False
    slopes = np.diff(log_segment) / np.diff(x_segment)
    mean_slope = float(np.mean(slopes))
    if mean_slope == 0:
        return False
    slope_cv = float(np.std(slopes)) / abs(mean_slope)
    max_cv = config.get_float("PCR_LOG_PHASE_SLOPE_CV_MAX")
    return slope_cv <= max_cv


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
    threshold = max_slope * flatten_fraction
    end = len(y_corrected) - 1
    for idx in range(start, len(diffs)):
        if idx - start >= min_points and diffs[idx] < threshold:
            end = idx
            break
    if end <= start:
        end = min(start + min_points, len(y_corrected) - 1)
    return end


def _run_check(check, curve_data, curve):
    try:
        return bool(check(curve_data, curve))
    except Exception:
        return False


def check_signal_basics(curve_data, curve):
    checks = [
        check_baseline_length,
        check_baseline_stability,
        check_cycle_location,
        check_log_phase_linearity,
        check_monotonic_rise,
        check_no_late_drift,
        check_sigmoidal_profile,
        check_signal_range,
        check_single_transition,
        check_smooth_features,
        check_stable_slope,
        check_sustained_increase,
        check_threshold_oscillation,
    ]
    return {check.__name__: _run_check(check, curve_data, curve) for check in checks}


def evaluate_curve(curve, log_name, dye, well):
    curve_data = get_curve_data(curve, log_name, dye, well)
    results = {
        "check_threshold_crossing": _run_check(
            check_threshold_crossing,
            curve_data,
            curve,
        )
    }
    results.update(check_signal_basics(curve_data, curve))
    threshold_pass = results["check_threshold_crossing"]
    baseline_fail = any(
        not results.get(name, False)
        for name in ("check_baseline_length", "check_baseline_stability")
    )
    other_fail = any(
        not passed
        for name, passed in results.items()
        if name != "check_threshold_crossing"
    )
    if curve.test_run or baseline_fail:
        status = "inconclusive"
    elif not threshold_pass:
        status = "undetected"
    elif other_fail:
        status = "inconclusive"
    else:
        status = "detected"
    return {
        "status": status,
        "threshold_pass": threshold_pass,
        "results": results,
    }
