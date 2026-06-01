# Analysis / Math Spec: [Algorithm or Pipeline Name]

**Status:** Draft | Review | Active | Deprecated
**Author:** [Name]
**Last updated:** YYYY-MM-DD
**GitHub issue:** #[number]
**Source file(s):** `aq_curve/[filename].py`

---

## 1. Purpose

What biological or physical quantity is being estimated?
What decision does this analysis support (e.g., positive/negative call, Cq value)?

---

## 2. Inputs

| Input | Type | Shape / Range | Source | Notes |
|-------|------|---------------|--------|-------|
| Raw fluorescence | `list[float]` | N cycles, > 0 | Hardware ADC | May contain noise spikes |
| Cycle numbers | `list[int]` | 1..N | Assay config | Usually 1-indexed |
| [other] | | | | |

---

## 3. Algorithm

Describe the algorithm step by step. Be explicit enough that a new engineer (or Claude) can implement it without asking questions.

### Step 1: [Name]

**Purpose:** [What this step produces]

**Method:** [Description + formula if applicable]

$$
\text{Equation in LaTeX if needed}
$$

**Implementation:** `aq_curve/[file].py`, function `[function_name]`, line ~[N]

**Edge cases:**
- What if input is empty?
- What if all values are identical?

---

### Step 2: [Name]

[Same format]

---

## 4. Outputs

| Output | Type | Range | Meaning |
|--------|------|-------|---------|
| `cq` | `float` | 0..40 | Quantification cycle |
| `is_positive` | `bool` | — | Call determination |
| `r_squared` | `float` | 0..1 | Curve fit quality |
| `[field]` | | | |

**When output is None / NaN:**
- [Describe when and why — e.g., "Cq is None when R² < 0.9 or no sigmoid detected"]

---

## 5. Thresholds and Parameters

| Parameter | Value | Configurable? | Effect if changed |
|-----------|-------|---------------|-------------------|
| `MIN_R_SQUARED` | 0.90 | No (hardcoded) | Fewer calls accepted |
| `CQ_THRESHOLD` | 35.0 | Yes (`config.json`) | Positive/negative cutoff |
| [param] | | | |

Source: `aq_curve/pcr_curve_config.py` (or wherever params live)

---

## 6. Validation Criteria

How do we know this analysis is correct?

- **Reference datasets:** [Where are the ground-truth datasets? `pcr_curve_tests/` ?]
- **Acceptance threshold:** [e.g., "Cq must match reference within ±0.3 cycles"]
- **Known failure modes:** [e.g., "Late amplification at cycle >38 may produce false Cq"]

---

## 7. Test Coverage

| Test | File | What it verifies |
|------|------|-----------------|
| Positive call | `tests/unit/test_[name].py` | Standard sigmoid input → positive |
| Negative call | `tests/unit/test_[name].py` | Flat trace → None cq |
| Noisy input | `tests/unit/test_[name].py` | Spike in cycle 5 → still correct |
| [other] | | |

Run: `pytest tests/unit/test_[name].py -v`

---

## 8. Numerical Stability

- Are there division-by-zero risks? [Where and how handled]
- Floating point precision: [any known issues]
- Dependency on scipy/numpy version: [note if version-sensitive]

---

## 9. References

- [Paper or method this is based on]
- Prior implementation notes: `docs/pcr_curve/`
- Related ADR: `docs/adr/ADR-008-pcr-analysis-post-run-pipeline.md`
