import os

DEFAULTS = {
    "PCR_BASELINE_SLOPE_MAX": 0.5,
    "PCR_BASELINE_STD_MAX": 5.0,
    "PCR_CQ_MAX": 40,
    "PCR_CQ_MIN": 7,
    "PCR_END_MIDPOINT_FRACTION": 0.50,
    "PCR_LATE_CQ_THRESHOLD": 35,
    "PCR_LATE_CYCLES": 8,
    "PCR_LATE_DRIFT_MAX": 0.50,
    "PCR_LATE_FOLD_MIN": 5.0,
    "PCR_LATE_R2_MIN": 0.92,
    "PCR_LATE_CQCONF_MIN": 0.70,
    "PCR_LOG_PHASE_MIN_SLOPE": 0.10,
    "PCR_LOG_PHASE_R2_MIN": 0.85,
    "PCR_LOG_PHASE_R2_MID": 0.83,
    "PCR_LOG_PHASE_SLOPE_CV_MAX": 1.0,
    "PCR_LOG_PHASE_SLOPE_FLATTEN_FRACTION": 0.5,
    "PCR_LOG_PHASE_SLOPE_MIN_POINTS": 5,
    "PCR_MAX_DIFF": 30.0,
    "PCR_MAX_DROP": 5.0,
    "PCR_MAX_DROP_RELATIVE": 0.15,
    "PCR_MAX_TRANSITIONS": 2,
    "PCR_MIN_BASELINE_CYCLES": 3,
    "PCR_MIN_ABS_SIGNAL": 0.25,
    "PCR_MIN_FOLD": 0.015,
    "PCR_MIN_PEAK_FRACTION": 0.35,
    "PCR_MIN_RISE_CYCLES": 3,
    "PCR_MOUNTAIN_DROP_RATIO": 0.35,
    "PCR_NEGATIVE_DROP_MIN": -0.15,
    "PCR_NEGATIVE_DROP_WINDOW": 20,
    "PCR_PEAK_FRACTION": 0.3,
    "PCR_POST_RISE_SLOPE_MIN": 0.03,
    "PCR_SIGNAL_RANGE_PEAK_FRACTION": 0.13,
    "PCR_SPIKE_MULTIPLIER": 80.0,
    "PCR_SUSTAINED_CYCLES": 3,
    "PCR_THRESHOLD_FRACTION": 0.25,
    "PCR_TRANSITION_DIP_TOLERANCE": 0.05,
    "BIPHASIC_DIP_FRACTION": 0.5,
    "BIPHASIC_LOG_PHASE_SLOPE_CV_MAX": 1.0,
    "BIPHASIC_MIN_PEAK_SEPARATION": 4,
    "BIPHASIC_MIN_RISE_CYCLES": 1,
    "BIPHASIC_MIN_TOTAL_CYCLES": 8,
    "BIPHASIC_PEAK_FRACTION": 0.35,
    "BIPHASIC_SECOND_PEAK_FRACTION": 0.25,
    "BIPHASIC_SMOOTH_WINDOW": 3,
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
