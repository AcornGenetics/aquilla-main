# PCR Curve Analysis: Mathematical Approach

This document summarizes the math used by the PCR curve evaluator to classify FAM/ROX curves as detected, inconclusive, or undetected.

---

## Data preparation
- **Input**: Optics log rows are filtered by dye and well position.
- **Signal extraction**: For each cycle, the fluorescence signal is averaged after outlier rejection using a median-absolute-deviation filter (`m=2`).
- **Baseline correction**:
  1. Fit a line over the baseline window (`baseline_slice`, default cycles 5–15) using least-squares.
  2. Compute residuals across the full curve and keep baseline points within `2 * std(residuals)`.
  3. Refit the baseline line using the filtered baseline points.
  4. Subtract the fitted baseline line from the raw signal to obtain the corrected curve.

---

## Threshold definition
Computed on the **baseline-corrected** signal:

```
signal_range = max(peak(y_corrected) − baseline_mean, 0)
threshold    = baseline_mean + PCR_THRESHOLD_FRACTION × signal_range
```

- `PCR_THRESHOLD` (env var) overrides the computed value with an absolute threshold directly.
- `PCR_THRESHOLD_FRACTION` (default **0.1**) sets how far above baseline — as a fraction of the total signal range — the threshold sits.

---

## Key derived values

| Value | How it is calculated |
|---|---|
| **baseline_mean** | Mean of `y_corrected[baseline_start:baseline_end]` |
| **signal_range** | `max(max(y_corrected) − baseline_mean, 0)` |
| **threshold** | `baseline_mean + PCR_THRESHOLD_FRACTION × signal_range` |
| **sustained_rise_index** | First index where `PCR_SUSTAINED_CYCLES` (default 3) consecutive points are ≥ threshold |
| **Cq** | Cycle number at the sustained_rise_index |
| **threshold_crossings** | Count of below→above transitions in `y_corrected` |
| **log_phase_end** | First index after sustained rise where derivative drops below `max_slope × PCR_LOG_PHASE_SLOPE_FLATTEN_FRACTION`, with at least `PCR_LOG_PHASE_SLOPE_MIN_POINTS` points in the segment |
| **R²** | Coefficient of determination for a linear fit to `log(y_corrected)` over the log-phase segment |
| **slope_CV** | `std(slopes) / abs(mean(slopes))` where slopes are point-to-point on `log(y_corrected)` in the log-phase |
| **amplitude_fraction** | `(max(y_corrected) − baseline_mean) / max(y_corrected)` |
| **fold_change** | `max(y_raw) / mean(y_raw[baseline])` |

---

## Config constants

All constants can be overridden per-device via environment variables. Defaults are defined in `aq_curve/pcr_curve_config.py`.

### Threshold & baseline

| Constant | Default | Meaning |
|---|---|---|
| `PCR_THRESHOLD_FRACTION` | 0.1 | Fraction of signal range above baseline used to set threshold |
| `PCR_SUSTAINED_CYCLES` | 3 | Consecutive cycles above threshold required to count as a sustained rise |
| `PCR_MIN_BASELINE_CYCLES` | 3 | Minimum cycle index at which sustained rise must occur (hard floor of 7 enforced in code) |
| `PCR_BASELINE_STD_MAX` | 5.0 | Maximum allowed standard deviation of the baseline window |
| `PCR_BASELINE_SLOPE_MAX` | 0.5 | Maximum allowed absolute slope of the baseline window |

### Cq / cycle location

| Constant | Default | Meaning |
|---|---|---|
| `PCR_CQ_MIN` | 7 | Earliest acceptable Cq cycle |
| `PCR_CQ_MAX` | 40 | Latest acceptable Cq cycle (typical-path cycle-location check) |
| `PCR_CQ_HARD_MAX` | 36 | Hard negative cutoff — any Cq strictly greater is Not Detected, overriding the late-Cq-confident path |

### Log-phase

| Constant | Default | Meaning |
|---|---|---|
| `PCR_LOG_PHASE_R2_MIN` | 0.78 | Minimum R² for log-linear fit over the log phase |
| `PCR_LOG_PHASE_SLOPE_CV_MAX` | 1.0 | Maximum coefficient of variation of log-phase slopes |
| `PCR_LOG_PHASE_SLOPE_FLATTEN_FRACTION` | 0.5 | Derivative must fall below this fraction of max slope to mark log-phase end |
| `PCR_LOG_PHASE_SLOPE_MIN_POINTS` | 5 | Minimum number of points required in the log-phase segment |

### Rise / shape

| Constant | Default | Meaning |
|---|---|---|
| `PCR_MAX_DROP` | 5.0 | Maximum allowed downward step (in signal units) after sustained rise |
| `PCR_MIN_RISE_CYCLES` | 3 | Minimum number of positive-delta cycles required after sustained rise |
| `PCR_MIN_PEAK_FRACTION` | 0.3 | Minimum amplitude fraction `(max − baseline) / max` for sigmoidal check |
| `PCR_SIGNAL_RANGE_PEAK_FRACTION` | 0.13 | Minimum amplitude fraction on raw signal for signal range check |
| `PCR_MIN_FOLD` | 0.015 | Minimum fold-change `max / baseline_mean` on raw signal (alternative to peak fraction) |

### Smoothness / transitions

| Constant | Default | Meaning |
|---|---|---|
| `PCR_SPIKE_MULTIPLIER` | 80.0 | Max allowed cycle-to-cycle delta as a multiple of the median delta (used by `check_smooth_features`) |
| `PCR_SPIKE_CROSSING_MULTIPLIER` | 40.0 | Max allowed crossing-point delta as a multiple of the median delta (used by spike-only crossing detection) |
| `PCR_MAX_DIFF` | 30.0 | Absolute max allowed delta when median delta is zero |
| `PCR_MAX_TRANSITIONS` | 3 | Maximum number of distinct strong-derivative peaks allowed |
| `PCR_PEAK_FRACTION` | 0.3 | Fraction of max derivative used as the peak detection threshold |
| `PCR_TRANSITION_DIP_TOLERANCE` | 0.05 | A dip between peaks that stays within this fraction of peak_threshold is treated as the same transition, not a new one |

### Rapid terminal rise

| Constant | Default | Meaning |
|---|---|---|
| `PCR_RAPID_RISE_MAX_REMAINING` | 5 | If the sustained rise starts with fewer than this many cycles remaining, the rise is considered "terminal" |
| `PCR_RAPID_RISE_FRACTION` | 0.65 | Maximum fraction of the total signal range that can be covered in the first 3 post-rise cycles before the rise is classified as rapid |

### Late drift / negative drop

| Constant | Default | Meaning |
|---|---|---|
| `PCR_LATE_CYCLES` | 3 | Number of end cycles used to measure late drift |
| `PCR_LATE_DRIFT_MAX` | 0.85 | Maximum allowed slope over the last `PCR_LATE_CYCLES` cycles |
| `PCR_NEGATIVE_DROP_MIN` | -0.2 | Minimum corrected signal value in last `PCR_NEGATIVE_DROP_WINDOW` cycles (stub — not yet enforced) |
| `PCR_NEGATIVE_DROP_WINDOW` | 20 | Number of end cycles to inspect for negative drop (stub — not yet enforced) |

### Biphasic

| Constant | Default | Meaning |
|---|---|---|
| `BIPHASIC_SMOOTH_WINDOW` | 3 | Moving-average window applied before derivative analysis |
| `BIPHASIC_PEAK_FRACTION` | 0.35 | Fraction of max derivative required to count a derivative group as a peak |
| `BIPHASIC_SECOND_PEAK_FRACTION` | 0.2 | Minimum height of the second peak relative to the overall max derivative |
| `BIPHASIC_MIN_PEAK_SEPARATION` | 4 | Minimum cycle separation between two peaks |
| `BIPHASIC_DIP_FRACTION` | 0.5 | Valley between peaks must fall below this fraction of max derivative to confirm biphasic pattern |
| `BIPHASIC_LOG_PHASE_SLOPE_CV_MAX` | 1.0 | Max slope CV for biphasic log-phase (same formula as typical) |
| `BIPHASIC_MIN_RISE_CYCLES` | 1 | Minimum rise cycles after dip for the peak–dip–rise detection path |
| `BIPHASIC_MIN_TOTAL_CYCLES` | 8 | Minimum number of cycles after sustained rise for biphasic analysis to proceed |

---

## Curve quality checks

Each check returns `True` (pass) or `False` (fail). All operate on the baseline-corrected signal unless noted.

### Threshold checks
- **`check_threshold_crossing`**: at least one below→above crossing exists.
- **`check_threshold_oscillation`**: no more than one crossing (curve does not oscillate across threshold).

### Baseline checks
- **`check_baseline_length`**: sustained rise index ≥ `PCR_MIN_BASELINE_CYCLES`. A hard floor of 7 is applied regardless of config.
- **`check_baseline_stability`**: `std(baseline_window) ≤ PCR_BASELINE_STD_MAX` and `|slope(baseline_window)| ≤ PCR_BASELINE_SLOPE_MAX`.

### Kinetics checks
- **`check_cycle_location`**: `PCR_CQ_MIN ≤ Cq ≤ PCR_CQ_MAX`.
- **`check_log_phase_linearity`**: `R² ≥ PCR_LOG_PHASE_R2_MIN` on log-transformed log-phase data.
- **`check_stable_slope`**: log-phase slope CV ≤ `PCR_LOG_PHASE_SLOPE_CV_MAX`.
- **`check_monotonic_rise`**: no cycle-to-cycle drop > `PCR_MAX_DROP` after sustained rise.
- **`check_sustained_increase`**: at least `PCR_MIN_RISE_CYCLES` positive deltas after rise. Falls back to using baseline_mean as threshold if the primary threshold-based check fails.
- **`check_sigmoidal_profile`**: amplitude fraction ≥ `PCR_MIN_PEAK_FRACTION` and post-rise slope > 0.
- **`check_single_transition`**: number of strong derivative peaks ≤ `PCR_MAX_TRANSITIONS`. Peaks within `PCR_TRANSITION_DIP_TOLERANCE` of the peak threshold are grouped as one transition.
- **`check_smooth_features`**: `max(|Δy|) ≤ PCR_SPIKE_MULTIPLIER × median(|Δy|)`. If median is 0, uses `PCR_MAX_DIFF` as absolute cap.
- **`check_no_late_drift`**: slope of last `PCR_LATE_CYCLES` cycles ≤ `PCR_LATE_DRIFT_MAX`.
- **`check_no_rapid_terminal_rise`**: returns `False` when the sustained rise is both **terminal** (starts with fewer than `PCR_RAPID_RISE_MAX_REMAINING` cycles remaining) and **rapid** (the first 3 post-rise cycles cover ≥ `PCR_RAPID_RISE_FRACTION` of the total signal range). True PCR amplification develops gradually over many cycles; a signal that shoots up only in the final few cycles is an artifact. A genuine slow late-Cq rise (barely emerging near run-end with a small per-cycle gain) passes because its 3-cycle fraction stays below the threshold.
- **`check_signal_range`** *(raw signal)*: `amplitude_fraction ≥ PCR_SIGNAL_RANGE_PEAK_FRACTION` OR `fold_change ≥ PCR_MIN_FOLD`.
- **`check_negative_drop`**: always passes — stub, not yet implemented.

### Biphasic checks
Run in parallel with typical checks. All operate on the post-rise segment.

- **`biphasic_check_biphasic_peaks`**: smoothed derivative has two strong separated peaks (separated by ≥ `BIPHASIC_MIN_PEAK_SEPARATION`, second peak ≥ `BIPHASIC_SECOND_PEAK_FRACTION × max_deriv`, valley ≤ `BIPHASIC_DIP_FRACTION × max_deriv`), or a peak–dip–rise pattern.
- **`biphasic_check_baseline_length`**: same as typical.
- **`biphasic_check_baseline_stability`**: same as typical.
- **`biphasic_check_signal_range`**: same as typical.
- **`biphasic_check_smooth_features`**: same as typical.
- **`biphasic_check_sustained_increase`**: same as typical but uses `BIPHASIC_MIN_RISE_CYCLES`.
- **`biphasic_check_negative_drop`**: stub, always passes.
- **`biphasic_check_biphasic_stable_slope`**: slope CV ≤ `BIPHASIC_LOG_PHASE_SLOPE_CV_MAX`.

---

## Final classification

```
compute Cq and evaluate late-Cq confidence upfront

if cq > PCR_CQ_HARD_MAX                                   →  "undetected"
elif late_confident                                      →  "detected"
elif threshold_crossing fails OR signal_range fails      →  "undetected"
elif mountain_shape OR rapid_terminal_rise               →  "undetected"
elif cq is None AND no sustained_increase                →  "undetected"
elif cq >= PCR_LATE_CQ_THRESHOLD:
    if late_ok AND (typical_pass OR biphasic_pass)       →  "detected"
    else                                                 →  "inconclusive"
elif typical_pass OR biphasic_pass                       →  "detected"
else                                                     →  "inconclusive"
```

Where:
- `cq > PCR_CQ_HARD_MAX` = hard negative cutoff: a crossing later than cycle `PCR_CQ_HARD_MAX` (36) is Not Detected regardless of shape or fold evidence — a genuine target does not first emerge this late, so a later crossing is non-specific. This is checked first and overrides the late-Cq-confident rescue.
- `typical_pass` = threshold passes AND no baseline check fails AND no other check fails AND not a test run
- `biphasic_pass` = threshold passes AND all biphasic checks pass AND not a test run
- `late_ok` = `check_late_cq_tier` passes (per-cycle fold ≥ `PCR_LATE_PER_CYCLE_FOLD_MIN`)
- `late_confident` = `late_ok` AND threshold passes AND baseline is clean AND no rapid terminal rise AND threshold oscillation passes — allows detection of genuine slow late-Cq signals even when absolute-signal checks (e.g. `check_signal_range`) are too strict for a barely-emerged curve
- `mountain_shape` = `check_no_mountain_shape` fails OR `check_end_above_midpoint` fails
- `rapid_terminal_rise` = `check_no_rapid_terminal_rise` fails

**Spike-only crossings**: before the status decision, if the threshold is crossed but every crossing is preceded by a spike-level jump (`|Δy| > PCR_SPIKE_CROSSING_MULTIPLIER × median(|Δy|)`), the threshold is treated as not genuinely crossed.

---

## Implementation references
- Data preparation and baseline: `aq_curve/curve.py`
- All check functions and `evaluate_curve`: `aq_curve/evaluator.py`
- Threshold, Cq, R², helper math: `aq_curve/pcr_curve_helpers.py`
- Config constants and env-var overrides: `aq_curve/pcr_curve_config.py`
