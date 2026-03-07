# PCR Curve Specification

## Purpose
Define acceptance criteria for PCR amplification curves used in analysis and QC.

## Expected Shape
- **Sigmoidal profile:** clear baseline, exponential rise, linear midsection, and plateau.
- **Single transition:** one dominant rise (no secondary peaks or oscillations).
- **Biphasic allowance:** some multiplex assays may show two distinct growth phases; these are evaluated with a separate biphasic detector.

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
- **Negative drop:** minimum corrected signal in the last `PCR_NEGATIVE_DROP_WINDOW` cycles ≥ `PCR_NEGATIVE_DROP_MIN`.

## Additional QC Checks
- **Signal range:** raw peak meets `PCR_SIGNAL_RANGE_PEAK_FRACTION` or `PCR_MIN_FOLD`.
- **Sigmoidal profile:** amplitude fraction ≥ `PCR_MIN_PEAK_FRACTION` and positive slope.
- **Single transition:** strong slope peaks ≤ `PCR_MAX_TRANSITIONS`.
- **Cycle location:** `PCR_CQ_MIN ≤ Cq ≤ PCR_CQ_MAX`.
- **Threshold oscillation:** threshold crossings ≤ 1.

## Biphasic Acceptance
- **Two growth phases:** derivative shows two separated peaks or a peak–dip–rise pattern.
- **Baseline stability:** same baseline requirements as typical curves.
- **Signal range:** raw signal meets `PCR_SIGNAL_RANGE_PEAK_FRACTION` or `PCR_MIN_FOLD`.
- **Smooth features:** spike limits remain enforced.
- **Sustained increase:** rise persists for `PCR_MIN_RISE_CYCLES`.
- **Stable slope (biphasic):** log-phase slope CV ≤ `BIPHASIC_LOG_PHASE_SLOPE_CV_MAX`.

## Result Classification
- **Not detected:** sample never crosses the threshold.
- **Inconclusive:** threshold fails but the curve drops below `PCR_NEGATIVE_DROP_MIN` (default `-0.2`) in the last `PCR_NEGATIVE_DROP_WINDOW` cycles (default `20`).
- **Detected:** sample crosses the threshold and meets typical or biphasic criteria.
- **Inconclusive:** sample crosses the threshold but fails both check suites.

## Rejection Criteria
- Multiple rises, erratic spikes, or oscillations.
- Threshold crossing without sustained amplification.
- Poor R² or rapidly changing slope during the rise.
- Excessive late-cycle drift.
