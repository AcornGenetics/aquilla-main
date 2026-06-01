import logging
from collections import defaultdict
from statistics import mean

import numpy as np

logger = logging.getLogger("aquila")

try:
    from scipy.signal import savgol_filter
except ImportError:  # pragma: no cover - optional dependency
    savgol_filter = None


DEFAULT_SKIP_READINGS = 5
DEFAULT_USE_READINGS = 5
DEFAULT_BASELINE_CYCLES = 14
DEFAULT_THRESHOLD_PCT = 0.20


def load_optics_log(filepath):
    rows = []
    with open(filepath, "r") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.strip().split()
            if len(parts) < 7:
                continue
            try:
                rows.append(
                    {
                        "time_s": float(parts[0]),
                        "hex": parts[1],
                        "voltage": float(parts[2]),
                        "led_state": int(parts[3]),
                        "dye": parts[4],
                        "cycle": int(parts[5]),
                        "position": int(parts[6]),
                    }
                )
            except (ValueError, IndexError):
                continue
    return rows


def extract_amplification_curves(
    rows,
    dye="fam",
    skip_readings=DEFAULT_SKIP_READINGS,
    use_readings=DEFAULT_USE_READINGS,
):
    filtered = [row for row in rows if row["dye"] == dye and row["cycle"] > 0]
    if not filtered:
        logger.warning("No data found for %s", dye)
        return {}

    if dye == "fam":
        positions = [2, 3, 4, 5]
        well_map = {2: 1, 3: 2, 4: 3, 5: 4}
    elif dye == "rox":
        positions = [0, 1, 2, 3]
        well_map = {0: 1, 1: 2, 2: 3, 3: 4}
    else:
        raise ValueError(f"Unknown dye: {dye}. Use 'fam' or 'rox'.")

    grouped = defaultdict(list)
    cycles = set()
    for row in filtered:
        cycles.add(row["cycle"])
        grouped[(row["position"], row["cycle"], row["led_state"])].append(row["voltage"])

    max_cycle = max(cycles) if cycles else 0
    curves = {}
    for pos in positions:
        well = well_map[pos]
        cycle_values = []
        led_on_values = []
        led_off_values = []

        for cycle in range(1, max_cycle + 1):
            led_on = grouped.get((pos, cycle, 1), [])
            led_off = grouped.get((pos, cycle, 0), [])

            if len(led_on) > skip_readings:
                led_on = led_on[skip_readings:skip_readings + use_readings]
            if len(led_off) > skip_readings:
                led_off = led_off[skip_readings:skip_readings + use_readings]

            if led_on and led_off:
                cycle_values.append(cycle)
                led_on_values.append(mean(led_on))
                led_off_values.append(mean(led_off))

        if cycle_values:
            curves[well] = {
                "cycles": np.array(cycle_values),
                "led_on": np.array(led_on_values),
                "led_off": np.array(led_off_values),
                "signal": np.array(led_on_values) - np.array(led_off_values),
            }

    return curves


def calculate_ct_threshold(
    cycles,
    signal,
    baseline_cycles=DEFAULT_BASELINE_CYCLES,
    threshold_pct=DEFAULT_THRESHOLD_PCT,
):
    if len(signal) < baseline_cycles + 5:
        return None

    baseline = float(np.mean(signal[2:baseline_cycles]))
    max_signal = float(np.max(signal))
    delta = max_signal - baseline
    if delta <= 0:
        return None

    threshold = baseline + threshold_pct * delta
    above = np.where(signal > threshold)[0]
    if len(above) == 0:
        return None

    idx = int(above[0])
    if idx > 0:
        x1, x2 = cycles[idx - 1], cycles[idx]
        y1, y2 = signal[idx - 1], signal[idx]
        if y2 != y1:
            return float(x1 + (threshold - y1) * (x2 - x1) / (y2 - y1))
    return float(cycles[idx])


def calculate_ct_second_derivative(cycles, signal):
    if len(signal) < 10:
        return None
    if savgol_filter is None:
        return None

    try:
        if len(signal) >= 7:
            smoothed = savgol_filter(signal, window_length=7, polyorder=3)
        else:
            smoothed = signal
        d1 = np.gradient(smoothed, cycles)
        d2 = np.gradient(d1, cycles)
        max_idx = int(np.argmax(d2))
        return float(cycles[max_idx])
    except Exception:
        return None


def analyze_curves(
    curves,
    dye,
    baseline_cycles=DEFAULT_BASELINE_CYCLES,
    threshold_pct=DEFAULT_THRESHOLD_PCT,
):
    results = []
    for well, data in curves.items():
        cycles = data["cycles"]
        signal = data["led_on"]

        n_baseline = min(baseline_cycles, len(signal))
        baseline = float(np.mean(signal[:n_baseline])) if n_baseline else 0.0
        baseline_std = float(np.std(signal[:n_baseline])) if n_baseline else 0.0
        endpoint = float(signal[-1]) if len(signal) else np.nan
        max_signal = float(np.max(signal)) if len(signal) else np.nan
        delta = endpoint - baseline

        ct_threshold = calculate_ct_threshold(cycles, signal, baseline_cycles, threshold_pct)
        ct_2nd_deriv = calculate_ct_second_derivative(cycles, signal)

        fold_change = max_signal / baseline if baseline > 0 else np.nan

        results.append(
            {
                "well": well,
                "dye": dye.upper(),
                "baseline": baseline,
                "baseline_std": baseline_std,
                "endpoint": endpoint,
                "max_signal": max_signal,
                "delta": delta,
                "fold_change": fold_change,
                "ct_threshold": ct_threshold,
                "ct_second_derivative": ct_2nd_deriv,
                "num_cycles": len(cycles),
            }
        )

    return results


def evaluate_curve_notebook(
    log_name,
    dye,
    well,
    baseline_cycles=DEFAULT_BASELINE_CYCLES,
    threshold_pct=DEFAULT_THRESHOLD_PCT,
    skip_readings=DEFAULT_SKIP_READINGS,
    use_readings=DEFAULT_USE_READINGS,
):
    rows = load_optics_log(log_name)
    curves = extract_amplification_curves(rows, dye, skip_readings, use_readings)
    curve = curves.get(well)
    if not curve:
        return {"status": "undetected", "reason": "no_data"}

    cycles = curve["cycles"]
    signal = curve["led_on"]
    ct_threshold = calculate_ct_threshold(cycles, signal, baseline_cycles, threshold_pct)
    ct_2nd_deriv = calculate_ct_second_derivative(cycles, signal)

    status = "detected" if ct_threshold is not None else "undetected"
    return {
        "status": status,
        "ct_threshold": ct_threshold,
        "ct_second_derivative": ct_2nd_deriv,
        "curve": curve,
    }
