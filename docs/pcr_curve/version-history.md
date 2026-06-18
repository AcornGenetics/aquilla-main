# PCR Analysis — Version History

A history of how PCR curve detection evolved, traced through six representative
commits. Each "version" is a milestone where the detection behavior changed
meaningfully (some intermediate commits only tuned config or check internals).

## Version key

| Ver | Date | Commit | One-line |
|-----|------|--------|----------|
| v1 | 2026-02-02 | `a52acaa` | Original import — endpoint-based boolean detection |
| v2 | 2026-03-07 | `6855d8b` | Multi-check evaluator; 3-way status (detected / undetected / inconclusive) |
| v3 | 2026-04-17 | `98896fd` | Threshold model tuned (0.2 fraction); inconclusive band loosened |
| v4 | 2026-05-19 | `baae1e7` | Mountain-shape gate + late-Cq tier; baseline minimum w/ threshold fraction |
| v5 | 2026-06-03 | `082c615` (+`c80b2bb`) | Rapid-terminal-rise → undetected, spike suppression, late-confident override; ROX-unavailable profiles |
| v6 | 2026-06-18 | `9e7340d` | Shape checks re-anchored at the dip trough (ignore baseline artifact) |

> Notes:
> - v1's first repo commit is `515e4cb` "Initial commit" (same day); `a52acaa`
>   "aquilla-main import" brought in the PCR code.
> - v5 is a same-day cluster (2026-06-03): `c80b2bb` ("PCR analysis v4") added the
>   rapid/fast-late-rise→undetected logic, and `082c615` added ROX-unavailable.
>   The tree at `082c615` contains both.

---

## Detection decision logic by version

### v1 — endpoint-based boolean (`a52acaa`)
No evaluator, no curve shape, no "Inconclusive." Just the **last data point** vs a
fixed threshold:

```python
def is_detected(run_id, well):
    curve1 = get_curve(run_id, "fam", well)   # baseline-corrected
    curve2 = get_curve(run_id, "rox", well)
    z1, z2 = matrix_mul(cross_talk_matrix[well-1], (curve1[-1], curve2[-1]))  # final cycle only
    th = thresholds[well-1]
    return (z1 >= th[0], z2 >= th[1])          # (fam_detected, rox_detected) booleans
```

### v2 — multi-check evaluator, 3-way status (`6855d8b`)
```python
typical_pass  = not curve.test_run and threshold_pass and not (baseline_fail or other_fail)
biphasic_pass = not curve.test_run and threshold_pass and all(biphasic_results.values())

if not threshold_pass:
    status = "undetected"
elif typical_pass or biphasic_pass:
    status = "detected"
else:
    status = "inconclusive"
```

### v3 — decision tree identical to v2 (`98896fd`)
The change here was config (`0.2` threshold fraction) + check internals, not the
decision tree. `evaluate_curve` is byte-for-byte identical to v2.

### v4 — mountain-shape gate + late-Cq tier (`baae1e7`)
```python
mountain_shape_detected = not (check_no_mountain_shape and check_end_above_midpoint)
...
if not threshold_pass or not signal_range_pass:
    status = "undetected"
elif mountain_shape_detected:                       # NEW
    status = "undetected"
elif cq is not None and cq >= late_threshold:       # NEW late-Cq tier
    late_ok = check_late_cq_tier(...)
    status = "detected" if (late_ok and (typical_pass or biphasic_pass)) else "inconclusive"
elif typical_pass or biphasic_pass:
    status = "detected"
else:
    status = "inconclusive"
```

### v5 — rapid-rise→undetected, spike suppression, late-confident override (`082c615`)
```python
rapid_rise_detected = not check_no_rapid_terminal_rise          # NEW "fast late rise"
if threshold_pass and _spike_only_crossings(y, threshold_val):  # NEW spike suppression
    threshold_pass = False

# late-Cq confidence evaluated UP-FRONT to override strict shape checks
late_confident = (late_ok and threshold_pass and not baseline_fail
                  and not rapid_rise_detected and check_threshold_oscillation)

if late_confident:                                   # NEW override
    status = "detected"
elif not threshold_pass or not signal_range_pass:
    status = "undetected"
elif mountain_shape_detected or rapid_rise_detected: # rapid rise → UNDETECTED
    status = "undetected"
elif cq is None and not check_sustained_increase:    # NEW noise/spike guard
    status = "undetected"
elif cq is not None and cq >= late_threshold:
    status = "detected" if (late_ok and (typical_pass or biphasic_pass)) else "inconclusive"
elif typical_pass or biphasic_pass:
    status = "detected"
else:
    status = "inconclusive"
```

And in `curve.py` — **profiles not using ROX**:
```python
_ROX_UNAVAILABLE = "ROX Unavailable"
if rox_unavailable:
    rox_status = {w: _ROX_UNAVAILABLE for w in _WELLS}   # ROX greyed out per-profile
# + FAM-undetected + late ROX Cq -> suppress ROX as Not Detected
```

### v6 — decision tree identical to v5 (`9e7340d`)
`diff` of `evaluate_curve` v5→v6 is empty. The change is entirely in the check
functions: `trough_index()` + a `floor=` parameter so `check_log_phase_linearity`,
`check_stable_slope`, and `check_sigmoidal_profile` anchor the rise at the dip
trough instead of index 0.

### Where the rules actually changed

| Transition | What changed in the decision logic |
|---|---|
| v1 → v2 | Endpoint boolean → multi-check evaluator; **Inconclusive** introduced |
| v2 → v3 | *No tree change* — config (0.2 threshold) + check internals |
| v3 → v4 | + mountain-shape gate, + late-Cq tier branch |
| v4 → v5 | + rapid-terminal-rise→undetected, + spike-only-crossing suppression, + late-confident up-front override, + no-Cq/no-sustained-increase guard, + ROX-unavailable profiles & late-ROX suppression |
| v5 → v6 | *No tree change* — checks re-anchored at dip trough |

---

## Checks added at each stage

| Stage | Checks added | Count |
|---|---|---|
| v1 | *(none — no check framework; single endpoint boolean)* | 0 |
| v2 | `threshold_crossing`, `threshold_oscillation`, `baseline_length`, `baseline_stability`, `cycle_location`, `log_phase_linearity`, `monotonic_rise`, `no_late_drift`, `negative_drop` (stub), `sigmoidal_profile`, `signal_range`, `single_transition`, `smooth_features`, `stable_slope`, `sustained_increase`, `biphasic_peaks`, `biphasic_stable_slope` | 17 |
| v3 | *(none — config + check-body tuning only)* | 0 |
| v4 | `no_mountain_shape`, `end_above_midpoint`, `late_cq_tier` | +3 |
| v5 | `no_rapid_terminal_rise` | +1 |
| v6 | *(none — checks re-anchored at dip trough)* | 0 |

Total roster size: 0 → 17 → 17 → 20 → 21 → 21.

---

## Config value evolution

### v2 → v3 (threshold model tuning)
| Key | Before → After |
|---|---|
| `PCR_LOG_PHASE_SLOPE_CV_MAX` | 0.9 → **1.0** |
| `PCR_MAX_TRANSITIONS` | 2 → **3** |
| `PCR_THRESHOLD_DELTA` | 0.5 → **0.2** |
| `PCR_TRANSITION_DIP_TOLERANCE` | *(new)* 0.05 |

### v3 → v4 (largest change — late-Cq tier, mountain, absolute signal)
| Key | Change |
|---|---|
| `PCR_THRESHOLD_DELTA` → `PCR_THRESHOLD_FRACTION` | **renamed**, 0.2 → **0.25** |
| `PCR_LOG_PHASE_R2_MIN` | 0.78 → **0.85** |
| `PCR_LATE_CYCLES` | 3 → **8** |
| `PCR_LATE_DRIFT_MAX` | 0.85 → **0.50** |
| `PCR_MAX_TRANSITIONS` | 3 → **2** (reverted past v3) |
| `PCR_MIN_PEAK_FRACTION` | 0.3 → **0.35** |
| `PCR_NEGATIVE_DROP_MIN` | −0.2 → **−0.15** |
| `BIPHASIC_SECOND_PEAK_FRACTION` | 0.2 → **0.25** |
| *New:* `PCR_LATE_CQ_THRESHOLD`=35, `PCR_LATE_R2_MIN`=0.92, `PCR_LATE_CQCONF_MIN`=0.70, `PCR_LATE_FOLD_MIN`=5.0, `PCR_LOG_PHASE_R2_MID`=0.83, `PCR_LOG_PHASE_MIN_SLOPE`=0.10, `PCR_END_MIDPOINT_FRACTION`=0.50, `PCR_MAX_DROP_RELATIVE`=0.15, `PCR_MIN_ABS_SIGNAL`=0.25, `PCR_MOUNTAIN_DROP_RATIO`=0.35, `PCR_POST_RISE_SLOPE_MIN`=0.03 | |

### v4 → v5 (rapid-rise, spike suppression, threshold loosened)
| Key | Change |
|---|---|
| `PCR_THRESHOLD_FRACTION` | 0.25 → **0.1** (much more sensitive) |
| `PCR_LOG_PHASE_R2_MIN` | 0.85 → **0.8** (loosened) |
| `PCR_LATE_DRIFT_MAX` | 0.50 → **5.0** (effectively disables the drift gate) |
| `PCR_NEGATIVE_DROP_MIN` | −0.15 → **−0.25** |
| *New:* `PCR_RAPID_RISE_FRACTION`=0.65, `PCR_RAPID_RISE_MAX_REMAINING`=5, `PCR_SPIKE_CROSSING_MULTIPLIER`=40.0, `PCR_LATE_NEGATIVE_DRIFT_MIN`=0.30, `PCR_LATE_PER_CYCLE_FOLD_MIN`=1.5, `PCR_MOUNTAIN_DROP_RATIO_LATE`=0.25 | |

### v5 → v6
No config changes.

**Notable trajectories:** the detection threshold loosened steadily
(`THRESHOLD_DELTA` 0.5 → 0.2, renamed to `THRESHOLD_FRACTION` 0.25 → 0.1) and
log-phase R² zig-zagged (0.78 → 0.85 → 0.8) as the false-positive vs
false-negative balance was tuned.

---

## Per-check evolution

### `threshold_crossing`
- v2–v6: Unchanged. `count_threshold_crossings(y) >= 1`. The gate that, if failed, forces Undetected.

### `threshold_oscillation`
- v2–v4: `count_threshold_crossings(whole curve) <= 1` — counted crossings over the entire trace.
- v5: Rewritten to scan only **post-rise** (`y[rise_index:]`), still `<= 1`. Stops pre-rise baseline noise from counting.
- v6: Tolerance loosened to `<= 2`.

### `baseline_length`
- v2–v6: Unchanged. Requires the rise to start at/after `PCR_MIN_BASELINE_CYCLES` (with a floor of 7).

### `baseline_stability`
- v2–v6: Unchanged. Baseline std ≤ `PCR_BASELINE_STD_MAX` and |slope| ≤ `PCR_BASELINE_SLOPE_MAX`.

### `cycle_location`
- v2–v6: Unchanged. Cq within `[PCR_CQ_MIN, PCR_CQ_MAX]` = [7, 40].

### `log_phase_linearity`
- v2: Single bar — `r² >= PCR_LOG_PHASE_R2_MIN` for the log-phase segment.
- v4: **Tiered** — picks the R² bar by Cq: late (`>= PCR_LATE_CQ_THRESHOLD` → `PCR_LATE_R2_MIN` 0.92), mid (`>= 30` → `PCR_LOG_PHASE_R2_MID` 0.83), else normal (`PCR_LOG_PHASE_R2_MIN`).
- v6: Same tiers, but the rise is now anchored with `floor=trough_index(y)` so the dip artifact can't mis-anchor the fit.

### `monotonic_rise`
- v2–v6: Body unchanged — no drop in `y[rise_index:]` exceeds `PCR_MAX_DROP_RELATIVE × signal_range`. Still anchors at index 0 (not part of the v6 trough fix — known limitation; see PR #179).

### `no_late_drift`
- v2–v6: Body unchanged: slope over last `PCR_LATE_CYCLES` ≤ `PCR_LATE_DRIFT_MAX`. **Effectively neutralized at v5** when `PCR_LATE_DRIFT_MAX` went 0.50 → 5.0.

### `negative_drop`
- v2–v3: **Stub** — `return True` (no-op placeholder).
- v4: Implemented — rejects curves that drop below `PCR_NEGATIVE_DROP_MIN × signal_range` in the last `PCR_NEGATIVE_DROP_WINDOW` cycles. Unchanged v4–v6 (only the threshold value moved).

### `sigmoidal_profile`
- v2: Amplitude gate + `slope > 0` (any positive post-rise slope passed).
- v3/v4: Tightened to `slope >= PCR_POST_RISE_SLOPE_MIN × signal_range` (proportional slope floor).
- v6: Rise anchored at `floor=trough`, and the slope is fit over the **log-phase window `[start:end]`** instead of `[start:]` through the plateau (PR #179).

### `signal_range`
- v2–v3: Relative only — `amplitude_fraction >= min_peak_fraction OR fold_change >= PCR_MIN_FOLD`.
- v4: Added an **absolute** floor — `AND max(y) >= PCR_MIN_ABS_SIGNAL` (0.25). Unchanged v4–v6.

### `single_transition`
- v2–v6: Body stable — counts derivative sign transitions, `<= PCR_MAX_TRANSITIONS` (the limit moved 2→3→2 in config).

### `smooth_features`
- v2–v6: Unchanged. Rejects isolated spikes via `PCR_SPIKE_MULTIPLIER` (80×).

### `stable_slope`
- v2–v5: Log-phase slope CV ≤ `PCR_LOG_PHASE_SLOPE_CV_MAX` (0.9 at v2, 1.0 from v3).
- v6: CV computed on a trough-floored window (via `_compute_stable_slope_cv`).

### `sustained_increase`
- v2–v6: Unchanged. Confirms a real sustained rise after threshold (guards against single-spike crossings).

### `no_mountain_shape` *(added v4)*
- v4–v6: Rejects rise-then-fall "mountain" artifacts via `PCR_MOUNTAIN_DROP_RATIO` (v5 added a separate late-curve ratio `PCR_MOUNTAIN_DROP_RATIO_LATE`).

### `end_above_midpoint` *(added v4)*
- v4–v6: Final value must sit above `PCR_END_MIDPOINT_FRACTION` (0.50) of the range — pairs with mountain detection.

### `late_cq_tier` *(added v4)*
- v4: Confidence test for late risers (fold growth, R², per-cycle fold) gating the late-Cq branch.
- v5: Promoted into the `late_confident` up-front override in `evaluate_curve`, with extra gates (`PCR_LATE_NEGATIVE_DRIFT_MIN`, `PCR_LATE_PER_CYCLE_FOLD_MIN`).

### `no_rapid_terminal_rise` *(added v5)*
- v5–v6: The "fast late rise → Undetected" check. Fails when the rise starts with `< PCR_RAPID_RISE_MAX_REMAINING` (5) cycles left **and** the first 3 post-rise cycles cover `>= PCR_RAPID_RISE_FRACTION` (0.65) of the range.

### `biphasic_peaks` / `biphasic_stable_slope`
- v2–v6: The biphasic alternate path. `biphasic_peaks` body stable; `biphasic_stable_slope` shares `_compute_stable_slope_cv`, so it inherited the v6 trough-floor change.

---

## Known limitation (as of v6)

The v6 trough-floor fix was applied to `check_log_phase_linearity`,
`check_stable_slope`, and `check_sigmoidal_profile` only. Other
`sustained_rise_index`-based checks still anchor at index 0 and remain vulnerable
to the same baseline-hump artifact:
`check_monotonic_rise`, `check_threshold_oscillation`, `check_no_mountain_shape`,
`check_end_above_midpoint`, `check_single_transition`,
`check_no_rapid_terminal_rise`, `check_baseline_length`, `check_biphasic_peaks`,
`check_sustained_increase`. `compute_cq` keeps its own `skip_cycles=7` and is
intentionally isolated.
