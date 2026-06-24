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

**Notation** — symbols used across the versions below. Each version then defines
the *new* symbols it introduces in a `where:` list under its own formula.

| Symbol          | What it means |
|:---------------:|:--------------|
| $y$             | baseline-corrected fluorescence curve (vector over cycles); $y_{-1}$ = final cycle |
| $q$             | estimated Cq (quantification cycle); $\varnothing$ if none could be fit |
| $D$             | status $\in \{\textsf{U}, \textsf{I}, \textsf{D}\}$ = Undetected / Inconclusive / Detected |
| $\tau,\ \phi$   | threshold value / threshold fraction |

> **Note:** cases are evaluated **top-to-bottom** — the first branch whose
> condition holds wins.

### v1 — endpoint-based boolean (`a52acaa`)
No evaluator, no curve shape, no "Inconclusive." Just the **last data point** vs a
fixed threshold:

$$
\mathbf{z} = M_w \begin{pmatrix} y^{\text{fam}}_{-1} \\[2pt] y^{\text{rox}}_{-1} \end{pmatrix},
\qquad
D = \big(\,\mathbb{1}[z_1 \ge \tau_1],\ \mathbb{1}[z_2 \ge \tau_2]\,\big)
$$

where:

<div align="center">

| Symbol                                       | What it means |
|:--------------------------------------------:|:--------------|
| $M_w$                                        | cross-talk (color-compensation) matrix for well $w$ — un-mixes the FAM/ROX channels that bleed into each other |
| $y^{\text{fam}}_{-1},\ y^{\text{rox}}_{-1}$  | the **final-cycle** value of each channel's baseline-corrected curve |
| $\mathbf{z} = (z_1, z_2)$                    | the cross-talk-corrected FAM / ROX signals |
| $\tau_1,\ \tau_2$                            | per-channel fixed thresholds |
| $\mathbb{1}[\cdot]$                          | indicator: 1 if the condition holds, else 0 |

</div>

A pure boolean per channel over the **final cycle only** — no $\{\textsf{U},\textsf{I},\textsf{D}\}$
state, just `(fam_detected, rox_detected)`. The cross-talk matrix $M_w$ is specific to v1;
from v2 on, the pipeline works on a single baseline-corrected curve per channel and $M_w$
no longer appears.

```python
def is_detected(run_id, well):
    curve1 = get_curve(run_id, "fam", well)   # baseline-corrected
    curve2 = get_curve(run_id, "rox", well)
    z1, z2 = matrix_mul(cross_talk_matrix[well-1], (curve1[-1], curve2[-1]))  # final cycle only
    th = thresholds[well-1]
    return (z1 >= th[0], z2 >= th[1])          # (fam_detected, rox_detected) booleans
```

### v2 — multi-check evaluator, 3-way status (`6855d8b`)

$$
P_\text{typ} = \neg\text{test} \wedge T \wedge \neg(B \vee F),
\qquad
P_\text{bi} = \neg\text{test} \wedge T \wedge (b_1 \wedge \cdots \wedge b_n)
$$

$$
D = \begin{cases}
\textsf{U} & \neg T \\
\textsf{D} & T \wedge (P_\text{typ} \vee P_\text{bi}) \\
\textsf{I} & \text{otherwise}
\end{cases}
$$

where:

<div align="center">

| Symbol                        | What it means |
|:-----------------------------:|:--------------|
| $T$                           | `threshold_pass` — curve crosses the threshold |
| $P_\text{typ},\ P_\text{bi}$  | `typical_pass`, `biphasic_pass` |
| $B,\ F$                       | `baseline_fail`, `other_fail` |
| $b_1,\dots,b_n$               | the individual biphasic sub-check results (all must pass) |

</div>

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

$$
D_{v3} = D_{v2}\big|_{\phi:\,0.5 \to 0.2}
$$

The change here was config (`0.2` threshold fraction) + check internals, not the
decision tree. `evaluate_curve` is byte-for-byte identical to v2 — only the
predicate $T$ is recomputed with the looser threshold fraction $\phi = 0.2$.

### v4 — mountain-shape gate + late-Cq tier (`baae1e7`)

$$
\begin{aligned}
K &= \neg(\text{no\_mtn} \wedge \text{end\_above\_mid}) \\[10pt]
D &= \begin{cases}
\textsf{U} & \neg T \vee \neg S \\
\textsf{U} & K \\
\textsf{D} & (q \neq \varnothing) \wedge (q \ge \theta_\text{late}) \wedge L \wedge (P_\text{typ} \vee P_\text{bi}) \\
\textsf{I} & (q \neq \varnothing) \wedge (q \ge \theta_\text{late}) \\
\textsf{D} & P_\text{typ} \vee P_\text{bi} \\
\textsf{I} & \text{otherwise}
\end{cases}
\end{aligned}
$$

where:

<div align="center">

| Symbol                | What it means |
|:---------------------:|:--------------|
| $S$                   | `signal_range_pass` |
| $K$                   | `mountain_shape_detected` |
| $L$                   | `late_cq_tier` ok |
| $\theta_\text{late}$  | late-Cq threshold |

</div>

New vs v2: the $\neg S$ signal-range gate, the mountain branch $K$, and the
late-Cq tier (the two $q \ge \theta_\text{late}$ rows — $\textsf{D}$ only if $L$
also holds, otherwise $\textsf{I}$).

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

$$
T' = T \wedge \neg\,\text{spike\_only}(y, \tau),
\qquad
R = \neg\,\text{no\_rapid\_rise}
$$

$$
C = L \wedge T' \wedge \neg B \wedge \neg R \wedge O
$$

$$
D = \begin{cases}
\textsf{D} & C \\
\textsf{U} & \neg T' \vee \neg S \\
\textsf{U} & K \vee R \\
\textsf{U} & (q = \varnothing) \wedge \neg U \\
\textsf{D} & (q \neq \varnothing) \wedge (q \ge \theta_\text{late}) \wedge L \wedge (P_\text{typ} \vee P_\text{bi}) \\
\textsf{I} & (q \neq \varnothing) \wedge (q \ge \theta_\text{late}) \\
\textsf{D} & P_\text{typ} \vee P_\text{bi} \\
\textsf{I} & \text{otherwise}
\end{cases}
$$

where:

<div align="center">

| Symbol  | What it means |
|:-------:|:--------------|
| $T'$    | $T$ with spike-only crossings suppressed |
| $R$     | `rapid_terminal_rise_detected` |
| $C$     | `late_confident` — up-front override |
| $U$     | `sustained_increase` |
| $O$     | `threshold_oscillation` ok |

</div>

New vs v4: $T \to T'$ (spike-only crossings suppressed), the up-front
$C$ override that can short-circuit straight to $\textsf{D}$, rapid rise $R$
folded into the undetected gate ($K \vee R$), and the no-Cq / no-sustained-increase
guard ($(q = \varnothing) \wedge \neg U$).

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

### v6 — same tree as v5, re-anchored at the dip trough (`9e7340d`)

The `diff` of `evaluate_curve` v5→v6 is empty, so the decision tree below is
identical to v5's — reproduced in full for reference. The only change is in the
*check functions*: a new `trough_index()` and a `floor=` parameter so the
shape predicates are evaluated on $y[\,t^\star{:}\,]$ instead of $y[\,0{:}\,]$.

$$
T' = T \wedge \neg\,\text{spike\_only}(y, \tau),
\qquad
R = \neg\,\text{no\_rapid\_rise}
$$

$$
C = L \wedge T' \wedge \neg B \wedge \neg R \wedge O
$$

$$
D = \begin{cases}
\textsf{D} & C \\
\textsf{U} & \neg T' \vee \neg S \\
\textsf{U} & K \vee R \\
\textsf{U} & (q = \varnothing) \wedge \neg U \\
\textsf{D} & (q \neq \varnothing) \wedge (q \ge \theta_\text{late}) \wedge L \wedge (P_\text{typ} \vee P_\text{bi}) \\
\textsf{I} & (q \neq \varnothing) \wedge (q \ge \theta_\text{late}) \\
\textsf{D} & P_\text{typ} \vee P_\text{bi} \\
\textsf{I} & \text{otherwise}
\end{cases}
$$

where:

<div align="center">

| Symbol      | What it means |
|:-----------:|:--------------|
| $T'$        | $T$ with spike-only crossings suppressed |
| $R$         | `rapid_terminal_rise_detected` |
| $C$         | `late_confident` — up-front override |
| $U$         | `sustained_increase` |
| $O$         | `threshold_oscillation` ok |
| $t^\star$   | dip-trough index `argmin(y)` — the **new v6 rise anchor** (was index 0) |

</div>

```python
rapid_rise_detected = not check_no_rapid_terminal_rise          # carried over from v5
if threshold_pass and _spike_only_crossings(y, threshold_val):  # spike suppression
    threshold_pass = False

# late-Cq confidence evaluated UP-FRONT to override strict shape checks
late_confident = (late_ok and threshold_pass and not baseline_fail
                  and not rapid_rise_detected and check_threshold_oscillation)

if late_confident:
    status = "detected"
elif not threshold_pass or not signal_range_pass:
    status = "undetected"
elif mountain_shape_detected or rapid_rise_detected:
    status = "undetected"
elif cq is None and not check_sustained_increase:
    status = "undetected"
elif cq is not None and cq >= late_threshold:
    status = "detected" if (late_ok and (typical_pass or biphasic_pass)) else "inconclusive"
elif typical_pass or biphasic_pass:
    status = "detected"
else:
    status = "inconclusive"
```

`evaluate_curve` is byte-for-byte the v5 body above. The actual v6 change lives in
the check functions: `trough_index()` + a `floor=` parameter so
`check_log_phase_linearity`, `check_stable_slope`, and `check_sigmoidal_profile`
anchor the rise at the dip trough $t^\star$ instead of index 0, so the baseline
dip can't mis-anchor the fit.

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

---

## Current Checks (as of v6)
Every check is a boolean: **`True` = looks like real amplification**. They feed the
predicates in the decision tree above — most roll up into `typical_pass` ($P_\text{typ}$),
the biphasic ones into `biphasic_pass` ($P_\text{bi}$), and a few act as standalone
gates ($T$, $S$, $K$, $R$, $L$). Source: `sentri_curve/evaluator.py`.

### Building blocks (referenced by every test)
- **`get_threshold(y, baseline)` → $\tau$** — the detection threshold, derived from the
  baseline region plus the threshold fraction $\phi$. Everything compares against $\tau$.
- **`trough_index(y)` → $t^\star$** — `argmin(y)`, the lowest point (baseline dip). Used
  as the rise anchor in v6 so a baseline hump can't fool the shape fits.
- **`sustained_rise_index(y, τ, k)`** — first cycle where $y$ stays above $\tau$ for $k$
  consecutive cycles (the "rise start"); `None` if it never does. v6 passes `floor=`$t^\star$.
- **`compute_cq(x, y, τ, k)` → $q$** — Cq by linear interpolation of the cycle where $y$
  crosses $\tau$, after skipping the first 7 cycles; `None` if there's no sustained rise.

### Category 1 — Threshold & location gates
- **`threshold_crossing`** — passes if `count_crossings(y, τ) ≥ 1`. The hard gate ($T$):
  zero crossings ⇒ Undetected.
- **`threshold_oscillation`** ($O$) — counts crossings **after the rise start** only
  (`y[rise:]`); passes if `≤ 2`. Rejects curves that wiggle across $\tau$.
- **`cycle_location`** — $q$ exists and `7 ≤ q ≤ 40` (`PCR_CQ_MIN`/`MAX`).
- **`signal_range`** ($S$) — relative **and** absolute amplitude must hold:
  `(peak−baseline)/peak ≥ min_peak_fraction` **or** `peak/baseline ≥ min_fold`,
  **and** `max(y) ≥ PCR_MIN_ABS_SIGNAL` (0.25).

### Category 2 — Baseline quality
- **`baseline_length`** — rise starts late enough: `rise_index ≥ PCR_MIN_BASELINE_CYCLES`
  (floored at 7). Enough flat baseline before takeoff.
- **`baseline_stability`** — over the baseline slice: `std(y) ≤ PCR_BASELINE_STD_MAX`
  **and** `|slope| ≤ PCR_BASELINE_SLOPE_MAX`. Quiet, level baseline.

### Category 3 — Rise-shape quality
- **`log_phase_linearity`** — fit a line to `log(y)` over the log-phase window `[rise:end]`;
  passes if `r² ≥` a Cq-tiered bar (late $q$ → 0.92, mid → 0.83, else 0.85). Confirms
  exponential growth. Anchored at $t^\star$ in v6.
- **`monotonic_rise`** — after the rise start, no single drop exceeds
  `PCR_MAX_DROP_RELATIVE × signal_range`. No big dips mid-climb.
- **`sigmoidal_profile`** — amplitude gate `(peak−baseline)/peak ≥ min_peak_fraction`
  **and** log-phase slope `≥ PCR_POST_RISE_SLOPE_MIN × signal_range`. A real S-curve that
  rises steeply enough.
- **`stable_slope`** — coefficient of variation of the log-phase slope
  `≤ PCR_LOG_PHASE_SLOPE_CV_MAX` (1.0). Steady, not jerky, growth.
- **`single_transition`** — counts distinct "bursts" in the derivative after the rise
  (runs above `PEAK_FRACTION × max_deriv`, with a dip tolerance); passes if
  `≤ PCR_MAX_TRANSITIONS` (2). One growth event, not several.
- **`smooth_features`** — largest jump `max|Δy| ≤ PCR_SPIKE_MULTIPLIER × median|Δy|` (80×).
  Rejects isolated single-point spikes.
- **`sustained_increase`** ($U$) — confirms a genuine sustained climb after threshold
  (≥ `PCR_MIN_RISE_CYCLES` consecutive rising cycles), trying $\tau$ then the baseline mean
  as the reference. Guards against single-spike crossings.

### Category 4 — End-of-curve drift & drop
- **`no_late_drift`** — slope over the last `PCR_LATE_CYCLES` (8) cycles
  `≥ −PCR_LATE_NEGATIVE_DRIFT_MIN`. Tail mustn't fall off. *(Effectively neutralized since
  the v5 config loosening.)*
- **`negative_drop`** — min of the last `PCR_NEGATIVE_DROP_WINDOW` cycles
  `≥ PCR_NEGATIVE_DROP_MIN × signal_range`. No collapse at the end.

### Category 5 — Mountain & terminal artifacts
- **`no_mountain_shape`** ($K$ when failed) — find the peak after the rise; with
  `drop_ratio = (peak−end)/peak`, **fails** if `drop_ratio >` `PCR_MOUNTAIN_DROP_RATIO`
  (or its late-Cq variant) **and** the peak sits >8 cycles before the end. Rejects
  rise-then-fall humps.
- **`end_above_midpoint`** — final value (mean of last 5) `≥ PCR_END_MIDPOINT_FRACTION`
  (0.50) `× midpoint signal`. Curve ends high, not sagging.
- **`no_rapid_terminal_rise`** ($R$ when failed) — if the rise begins with
  `< PCR_RAPID_RISE_MAX_REMAINING` (5) cycles left **and** the first 3 post-rise cycles
  cover `≥ PCR_RAPID_RISE_FRACTION` (0.65) of the range ⇒ fails. Too fast and too late to trust.

### Category 6 — Late-Cq confidence
- **`late_cq_tier`** ($L$) — around $q$, per-cycle fold growth
  `(y_after / base)^(1/Δcycles) ≥ PCR_LATE_PER_CYCLE_FOLD_MIN` (1.5). Confirms a late riser
  is still growing exponentially; gates the late-Cq branch and the v5 `late_confident` override.

### Category 7 — Biphasic alternate path
- **`biphasic_peaks`** — detects two genuine peaks separated by a valley (smoothed-derivative
  grouping; the second peak `≥ BIPHASIC_SECOND_PEAK_FRACTION` of the first). Admits valid
  two-step curves the single-transition path would reject.
- **`biphasic_stable_slope`** — the same slope-CV test as `stable_slope`, but against
  `BIPHASIC_LOG_PHASE_SLOPE_CV_MAX`.
