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
    if len(log_segment) < 2:
        return True
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


def check_negative_drop(curve_data, curve):
    _, y_corrected, _ = curve_data
    min_allowed = config.get_float("PCR_NEGATIVE_DROP_MIN")
    window = config.get_int("PCR_NEGATIVE_DROP_WINDOW")
    if window is None or window <= 0:
        window = len(y_corrected)
    window = min(window, len(y_corrected))
    tail = y_corrected[-window:] if window else y_corrected
    if len(tail) == 0:
        return True
    return float(np.min(tail)) >= min_allowed


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
    if len(rise_deriv) < 2:
        return True
    max_deriv = float(np.max(rise_deriv))
    if max_deriv <= 0:
        return True
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
    slope_cv = _compute_stable_slope_cv(curve_data, curve)
    if slope_cv is None:
        return False
    max_cv = config.get_float("PCR_LOG_PHASE_SLOPE_CV_MAX")
    return slope_cv <= max_cv


def check_biphasic_stable_slope(curve_data, curve):
    slope_cv = _compute_stable_slope_cv(curve_data, curve)
    if slope_cv is None:
        return False
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
    start = sustained_rise_index(y_corrected, threshold, min_consecutive)
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
        check_negative_drop,
        check_sigmoidal_profile,
        check_signal_range,
        check_single_transition,
        check_smooth_features,
        check_stable_slope,
        check_sustained_increase,
        check_threshold_oscillation,
    ]
    return {check.__name__: _run_check(check, curve_data, curve) for check in checks}


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
    return {
        f"biphasic_{check.__name__}": _run_check(check, curve_data, curve)
        for check in checks
    }


def evaluate_curve(curve, log_name, dye, well):
    curve_data = get_curve_data(curve, log_name, dye, well)
    results = {
        "check_threshold_crossing": _run_check(
            check_threshold_crossing,
            curve_data,
            curve,
        )
    }
    typical_results = check_signal_basics(curve_data, curve)
    results.update(typical_results)
    biphasic_results = check_biphasic_basics(curve_data, curve)
    results.update(biphasic_results)
    threshold_pass = results["check_threshold_crossing"]
    negative_drop_ok = results.get("check_negative_drop", True)
    baseline_fail = any(
        not typical_results.get(name, False)
        for name in ("check_baseline_length", "check_baseline_stability")
    )
    other_fail = any(
        not passed
        for name, passed in typical_results.items()
    )
    typical_pass = not curve.test_run and threshold_pass and not (baseline_fail or other_fail)
    biphasic_pass = (
        not curve.test_run
        and threshold_pass
        and all(biphasic_results.values())
    )
    if not threshold_pass:
        status = "inconclusive" if not negative_drop_ok else "undetected"
    elif typical_pass or biphasic_pass:
        status = "detected"
    else:
        status = "inconclusive"
    return {
        "status": status,
        "threshold_pass": threshold_pass,
        "results": results,
    }
