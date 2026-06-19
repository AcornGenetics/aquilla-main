# PCR Curve Evaluator

## Overview
`sentri_curve/evaluator.py` centralizes the curve checks into reusable functions. The pytest tests now call these functions, and the runtime detection pipeline can reuse the same logic without invoking pytest.

## Key Functions
- `evaluate_curve(curve, log_name, dye, well)` returns a status (`detected`, `undetected`, or `inconclusive`) plus per-check results.
- `check_*` helpers implement each PCR curve check and return `True`/`False`.

## Detection Integration
`sentri_curve/curve.py` calls `evaluate_curve` inside `results_to_json`.

### Status decision (in order)
1. **`late_confident` → "detected"** — genuine slow late-Cq rise confirmed by per-cycle fold growth, clean baseline, stable oscillation, and no rapid terminal rise. This path fires before strict shape checks so that barely-emerged signals with Cq ≥ `PCR_LATE_CQ_THRESHOLD` are not incorrectly rejected by absolute-signal requirements.
2. **Threshold or signal-range fails → "undetected"**
3. **Mountain shape or rapid terminal rise → "undetected"** — the rapid-rise check flags signals that shoot up only in the final few cycles of the run (see below).
4. **No Cq and no sustained increase → "undetected"** — threshold was crossed by noise or a transient spike.
5. **Late Cq (Cq ≥ `PCR_LATE_CQ_THRESHOLD`) → "detected" or "inconclusive"** depending on `late_ok` and `typical_pass`/`biphasic_pass`.
6. **`typical_pass` or `biphasic_pass` → "detected"**
7. **Otherwise → "inconclusive"**

## Rapid Terminal Rise Check
`check_no_rapid_terminal_rise` catches optical artifacts that masquerade as late detections:

- **Rule:** returns `False` (fails) when the sustained rise starts with fewer than `PCR_RAPID_RISE_MAX_REMAINING` (default 5) cycles remaining **and** the first 3 post-rise cycles cover ≥ `PCR_RAPID_RISE_FRACTION` (default 0.65) of the total signal range.
- **Rationale:** true PCR exponential growth is gradual — a sigmoid requires many cycles to develop baseline, log phase, and plateau. A signal that rises steeply only at run-end has not had time to establish proper PCR kinetics.
- **Slow late-Cq exemption:** a genuine Cq ≈ 38–39 signal barely crosses threshold at run-end; its 3-cycle fraction stays below 0.65 because the absolute gain is small. Such curves pass `check_no_rapid_terminal_rise` and are detected via the `late_confident` path.

## Spike-Only Crossing Suppression
Before the status decision, `_spike_only_crossings` checks whether every threshold crossing was caused by an isolated spike (crossing delta > `PCR_SPIKE_CROSSING_MULTIPLIER` × median delta, default 40×). If so, the threshold is treated as not genuinely crossed, giving **"undetected"**.

Note: `PCR_SPIKE_CROSSING_MULTIPLIER` (40) is separate from `PCR_SPIKE_MULTIPLIER` (80) used by `check_smooth_features`, so that spike detection at the crossing point can be calibrated independently.
