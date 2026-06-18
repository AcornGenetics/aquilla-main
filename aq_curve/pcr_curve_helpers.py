import os
import numpy as np
from aq_curve import pcr_curve_config as config


DEFAULT_LOG = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "tests",
        "fixtures",
        "sample_test.dat",
    )
)


def resolve_log_path():
    custom_path = os.getenv("PCR_CURVE_LOG")
    if custom_path:
        return custom_path
    return DEFAULT_LOG


def get_curve_data(curve, log_name, dye, well):
    xdata, _, y1 = curve.extract_data(log_name, dye, well)
    xdata = np.array(xdata)
    y1 = np.array(y1)
    coeffs = curve.baseline(xdata, y1)
    y_corrected = y1 - coeffs[0] * xdata - coeffs[1]
    return xdata, y_corrected, y1


def _clamp_baseline_slice(baseline_slice, length):
    if length <= 0:
        return 0, 0
    start, end = baseline_slice
    start = max(0, min(start, length - 1))
    end = max(start + 1, min(end, length))
    return start, end


def get_baseline_values(ydata, baseline_slice):
    start, end = _clamp_baseline_slice(baseline_slice, len(ydata))
    return ydata[start:end]


def get_threshold(ydata, baseline_slice):
    baseline_values = get_baseline_values(ydata, baseline_slice)
    if len(baseline_values) == 0:
        baseline_mean = 0.0
    else:
        baseline_mean = float(np.mean(baseline_values))
    threshold_value = os.getenv("PCR_THRESHOLD")
    if threshold_value is not None:
        threshold = float(threshold_value)
    else:
        fraction_value = os.getenv("PCR_THRESHOLD_FRACTION")
        if fraction_value is None:
            fraction_value = config.get_float("PCR_THRESHOLD_FRACTION")
        fraction = float(fraction_value)
        signal_range = max(float(np.max(ydata)) - baseline_mean, 0.0) if len(ydata) > 0 else 0.0
        threshold = baseline_mean + fraction * signal_range
    return threshold, baseline_mean


def trough_index(ydata):
    """Index where the initial downward dip bottoms out (curve minimum).

    Everything before this is the optical baseline artifact (initial hump /
    descent); the genuine amplification begins at or after the trough.
    """
    if len(ydata) == 0:
        return 0
    return int(np.argmin(ydata))


def sustained_rise_index(ydata, threshold, min_consecutive, floor=0):
    """First index of a sustained run of >= min_consecutive points above
    threshold. ``floor`` skips the leading dip artifact: scanning starts at
    ``floor`` so a hump before the trough cannot anchor the rise at index 0.
    """
    floor = max(0, floor)
    count = 0
    for idx in range(floor, len(ydata)):
        if ydata[idx] >= threshold:
            count += 1
            if count >= min_consecutive:
                return idx - min_consecutive + 1
        else:
            count = 0
    if count > 0:
        return len(ydata) - count
    return None


def count_threshold_crossings(ydata, threshold):
    above = ydata >= threshold
    crossings = int(above[0])
    crossings += int(np.sum((~above[:-1]) & (above[1:])))
    return crossings


def get_plateau_start_index(ydata, plateau_fraction):
    target = np.max(ydata) * plateau_fraction
    indices = np.where(ydata >= target)[0]
    return int(indices[0]) if len(indices) else None


def get_log_phase_indices(ydata, threshold, plateau_fraction, min_consecutive, min_slope_fraction=0.10):
    start = sustained_rise_index(ydata, threshold, min_consecutive)
    if start is None:
        return None
    diffs = np.diff(ydata)
    rise_diffs = diffs[start:]
    if len(rise_diffs) > 0:
        max_slope = float(np.max(rise_diffs))
        if max_slope > 0:
            min_slope = max_slope * min_slope_fraction
            for offset, d in enumerate(rise_diffs):
                if d >= min_slope:
                    start = start + offset
                    break
    plateau_start = get_plateau_start_index(ydata, plateau_fraction)
    if plateau_start is None:
        plateau_start = len(ydata) - 1
    if plateau_start - start < 3:
        return None
    return start, plateau_start


def compute_r2(xdata, ydata):
    coeffs = np.polyfit(xdata, ydata, 1)
    pred = coeffs[0] * xdata + coeffs[1]
    ss_res = np.sum((ydata - pred) ** 2)
    ss_tot = np.sum((ydata - np.mean(ydata)) ** 2)
    if ss_tot == 0:
        return 0.0
    return 1 - ss_res / ss_tot


def interpolate_ct(xdata, ydata, threshold, start_idx):
    """Linearly interpolate the exact threshold crossing before start_idx."""
    if start_idx == 0:
        return float(xdata[0])
    x0, x1 = float(xdata[start_idx - 1]), float(xdata[start_idx])
    y0, y1 = float(ydata[start_idx - 1]), float(ydata[start_idx])
    if y1 <= y0:
        return x0
    return x0 + (threshold - y0) / (y1 - y0) * (x1 - x0)


def compute_cq(xdata, ydata, threshold, min_consecutive, skip_cycles=7):
    if skip_cycles:
        mask = xdata > skip_cycles
        xdata = xdata[mask]
        ydata = ydata[mask]
        if len(xdata) == 0:
            return None
    start = sustained_rise_index(ydata, threshold, min_consecutive)
    if start is None:
        return None
    return interpolate_ct(xdata, ydata, threshold, start)
