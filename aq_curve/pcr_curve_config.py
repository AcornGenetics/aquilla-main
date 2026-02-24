import os

DEFAULTS = {
    "PCR_BASELINE_SLOPE_MAX": 0.5,
    "PCR_BASELINE_STD_MAX": 5.0,
    "PCR_CQ_MAX": 38,
    "PCR_CQ_MIN": 5,
    "PCR_LATE_CYCLES": 3,
    "PCR_LATE_DRIFT_MAX": 0.85,
    "PCR_LOG_PHASE_R2_MIN": 0.85,
    "PCR_LOG_PHASE_SLOPE_CV_MAX": 0.8,
    "PCR_LOG_PHASE_SLOPE_FLATTEN_FRACTION": 0.5,
    "PCR_LOG_PHASE_SLOPE_MIN_POINTS": 5,
    "PCR_MIN_FOLD": 1.2,
    "PCR_THRESHOLD_DELTA": 0.5,
    "PCR_MAX_DIFF": 30.0,
    "PCR_MAX_DROP": 5.0,
    "PCR_MIN_PEAK_FRACTION": 0.3,
    "PCR_MIN_BASELINE_CYCLES": 3,
    "PCR_SIGNAL_RANGE_PEAK_FRACTION": 0.15,
    "PCR_MIN_RISE_CYCLES": 3,
    "PCR_PEAK_FRACTION": 0.3,
    "PCR_MAX_TRANSITIONS": 2,
    "PCR_SPIKE_MULTIPLIER": 60.0,
    "PCR_SUSTAINED_CYCLES": 3,
}

DEFAULT_CURVE_DYES = ["fam", "rox"]
DEFAULT_CURVE_WELLS = [1, 2, 3, 4]


def _get_value(name, default=None):
    value = os.getenv(name)
    if value is not None:
        return value
    if default is not None:
        return default
    return DEFAULTS.get(name)


def get_float(name, default=None):
    value = _get_value(name, default)
    if value is None:
        return None
    return float(value)


def get_int(name, default=None):
    value = _get_value(name, default)
    if value is None:
        return None
    return int(value)


def get_list(name):
    value = os.getenv(name)
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]
