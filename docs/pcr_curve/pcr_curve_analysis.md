# PCR Curve Analysis: Mathematical Approach

This document summarizes the math used by the PCR curve evaluator to classify FAM/ROX curves as detected, inconclusive, or undetected.

## Data preparation
- **Input**: Optics log rows are filtered by dye and well position.
- **Signal extraction**: For each cycle, the fluorescence signal is averaged after outlier rejection using a median-absolute-deviation filter (`m=2`).
- **Baseline correction**:
  1. Fit a line over the baseline window (`baseline_slice`, default cycles 5–15) using least-squares.
  2. Compute residuals across the full curve and keep baseline points within `2 * std(residuals)`.
  3. Refit the baseline line using the filtered baseline points.
  4. Subtract the fitted baseline line from the raw signal to obtain the corrected curve.

## Threshold definition
Threshold is computed on the **baseline-corrected** signal:

```
threshold = mean(baseline_window) + PCR_THRESHOLD_DELTA
```

- `PCR_THRESHOLD` can override the absolute threshold directly.
- `PCR_THRESHOLD_DELTA` defaults to the config value in `aq_curve/pcr_curve_config.py`.

## Key helper calculations
- **Sustained rise index**: first index where `min_consecutive` points are above the threshold.
- **Cq estimate**: the cycle index at sustained rise.
- **Threshold crossings**: number of transitions from below → above threshold.
- **Log-phase linearity**: `R²` for a linear fit to `log(y)` across the log-phase segment.

### Log-phase end detection
The log phase ends when the derivative falls below:

```
max_slope * PCR_LOG_PHASE_SLOPE_FLATTEN_FRACTION
```

with a minimum number of points (`PCR_LOG_PHASE_SLOPE_MIN_POINTS`).

## Curve quality checks
Each check is evaluated on the baseline-corrected curve unless noted.

### Threshold checks
- **Threshold crossing**: at least one crossing is required.
- **Threshold oscillation**: no more than one crossing.

### Baseline checks
- **Baseline length**: sustained rise occurs after `PCR_MIN_BASELINE_CYCLES`.
- **Baseline stability**: baseline standard deviation ≤ `PCR_BASELINE_STD_MAX` and slope ≤ `PCR_BASELINE_SLOPE_MAX`.

### Kinetics checks
- **Cycle location (Cq)**: `PCR_CQ_MIN ≤ Cq ≤ PCR_CQ_MAX`.
- **Log-phase linearity**: `R² ≥ PCR_LOG_PHASE_R2_MIN` on log-transformed data.
- **Stable slope**: coefficient of variation of log-phase slopes ≤ `PCR_LOG_PHASE_SLOPE_CV_MAX`.
- **Monotonic rise**: no post-threshold drop worse than `PCR_MAX_DROP`.
- **Sustained increase**: enough positive deltas after rise (`PCR_MIN_RISE_CYCLES`).
- **Sigmoidal profile**: amplitude fraction ≥ `PCR_MIN_PEAK_FRACTION` and positive overall slope.
- **Single transition**: number of strong derivative peaks ≤ `PCR_MAX_TRANSITIONS`.
- **Smooth features**: max diff ≤ `PCR_SPIKE_MULTIPLIER * median_diff` (or ≤ `PCR_MAX_DIFF` if median is 0).
- **No late drift**: slope of last `PCR_LATE_CYCLES` ≤ `PCR_LATE_DRIFT_MAX`.
- **Signal range (raw)**: peak amplitude fraction ≥ `PCR_SIGNAL_RANGE_PEAK_FRACTION` or fold-change ≥ `PCR_MIN_FOLD`.
- **Negative drop**: minimum corrected signal in the last `PCR_NEGATIVE_DROP_WINDOW` cycles ≥ `PCR_NEGATIVE_DROP_MIN`.

### Biphasic checks
For multiplex assays, a curve may show two growth phases (double-sigmoid). The biphasic path uses a separate, conservative set of checks:

- **Biphasic peaks**: the smoothed derivative has two strong, separated peaks or a peak–dip–rise pattern.
- **Baseline stability**: same baseline length/stability checks as typical curves.
- **Signal range**: raw signal meets the same minimum range requirements.
- **Smooth features**: limits on abrupt spikes remain enforced.
- **Sustained increase**: post-threshold rise persists for the minimum rise cycles.
- **Stable slope (biphasic)**: log-phase slope CV ≤ `BIPHASIC_LOG_PHASE_SLOPE_CV_MAX`.

## Final classification
- **Undetected**: threshold crossing fails.
- **Inconclusive**: threshold fails but the curve drops below `PCR_NEGATIVE_DROP_MIN` (default `-0.2`) in the last `PCR_NEGATIVE_DROP_WINDOW` cycles (default `20`).
- **Detected**: threshold passes and either the typical checks or biphasic checks pass.
- **Inconclusive**: threshold passes, but both check suites fail.

## Implementation references
- Data preparation and baseline: `aquila-main/aq_curve/curve.py`
- Thresholding and checks: `aquila-main/aq_curve/evaluator.py`
- Helper math utilities: `aquila-main/aq_curve/pcr_curve_helpers.py`
- Config constants: `aquila-main/aq_curve/pcr_curve_config.py`
