# PCR Curve Specification

## Purpose
Define acceptance criteria for PCR amplification curves used in analysis and QC.

## Expected Shape
- **Sigmoidal profile:** clear baseline, exponential rise, linear midsection, and plateau.
- **Single transition:** one dominant rise (no secondary peaks or oscillations).

## Baseline & Threshold
- **Baseline stability:** baseline standard deviation and slope stay within configured limits.
- **Threshold crossing:** curve must cross the configured fluorescence threshold at least once.
- **Baseline length:** sustained rise begins after `PCR_MIN_BASELINE_CYCLES`.

## Growth & Smoothness
- **Monotonic rise:** no post-threshold drop worse than `PCR_MAX_DROP`.
- **Smooth features:** max derivative stays within `PCR_SPIKE_MULTIPLIER` of the median.
- **Sustained increase:** rise persists for at least `PCR_MIN_RISE_CYCLES`.

## Fit Quality
- **High linearity in log phase:** `R² ≥ PCR_LOG_PHASE_R2_MIN` on log-transformed data.
- **Stable slope:** slope coefficient of variation ≤ `PCR_LOG_PHASE_SLOPE_CV_MAX`.

## Late Stability
- **No late drift:** last `PCR_LATE_CYCLES` slope ≤ `PCR_LATE_DRIFT_MAX`.

## Additional QC Checks
- **Signal range:** raw peak meets `PCR_SIGNAL_RANGE_PEAK_FRACTION` or `PCR_MIN_FOLD`.
- **Sigmoidal profile:** amplitude fraction ≥ `PCR_MIN_PEAK_FRACTION` and positive slope.
- **Single transition:** strong slope peaks ≤ `PCR_MAX_TRANSITIONS`.
- **Cycle location:** `PCR_CQ_MIN ≤ Cq ≤ PCR_CQ_MAX`.
- **Threshold oscillation:** threshold crossings ≤ 1.

## Result Classification
- **Not detected:** sample never crosses the threshold.
- **Detected:** sample crosses the threshold and meets all acceptance criteria.
- **Inconclusive:** sample crosses the threshold but fails one or more criteria.

## Rejection Criteria
- Multiple rises, erratic spikes, or oscillations.
- Threshold crossing without sustained amplification.
- Poor R² or rapidly changing slope during the rise.
- Excessive late-cycle drift.
