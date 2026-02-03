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


def get_baseline_values(ydata, baseline_slice):
    start, end = baseline_slice
    return ydata[start:end]


def get_threshold(ydata, baseline_slice):
    baseline_values = get_baseline_values(ydata, baseline_slice)
    baseline_mean = float(np.mean(baseline_values))
    threshold_value = os.getenv("PCR_THRESHOLD")
    if threshold_value is not None:
        threshold = float(threshold_value)
    else:
        delta_value = os.getenv("PCR_THRESHOLD_DELTA")
        if delta_value is None:
            delta_value = config.get_float("PCR_THRESHOLD_DELTA")
        threshold = baseline_mean + float(delta_value)
    return threshold, baseline_mean


def sustained_rise_index(ydata, threshold, min_consecutive):
    count = 0
    for idx, val in enumerate(ydata):
        if val >= threshold:
            count += 1
            if count >= min_consecutive:
                return idx - min_consecutive + 1
        else:
            count = 0
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


def get_log_phase_indices(ydata, threshold, plateau_fraction, min_consecutive):
    start = sustained_rise_index(ydata, threshold, min_consecutive)
    if start is None:
        return None
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


def compute_cq(xdata, ydata, threshold, min_consecutive):
    start = sustained_rise_index(ydata, threshold, min_consecutive)
    if start is None:
        return None
    return float(xdata[start])
