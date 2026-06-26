# Backend Spec: Stages Validation (`validate_stages`) — issue #199 (A2)

**Status:** Draft
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-25
**GitHub issue:** #199
**Source file(s):** `aquila_web/profile_assembly.py`, `unit_tests/test_profile_assembly.py`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018
**Builds on:** `spec_stages_contract_foundation.md` (#197), `spec_profile_step_assembly.md` (#198)

---

## 1. Overview

A pure function that checks a structured `stages` object against the instrument's valid ranges and shape, returning the list of problems found. Lives in `aquila_web/profile_assembly.py` alongside `assemble_steps` (same bounded concern). No HTTP/disk/hardware imports.

```python
def validate_stages(stages: dict) -> list[str]: ...
```

Returns a list of human-readable error strings, each naming the offending field (e.g. `"incubation.temp: Invalid Value"`). **Empty list means valid.** Enforcement on `POST /profiles` (return 4xx; call `validate_stages` *before* `assemble_steps`) is **A3 (#201)**; the frontend does its own save-time display (B3). A2 is the backend defense-in-depth check only.

---

## 2. Rules

Validated only for **enabled** Stages (Amplification is always enabled). Disabled optional Stages are skipped entirely — their values never produce errors.

| Field | Rule | On failure |
|-------|------|-----------|
| any temp (incubation/denaturation/finalHold/each sub-stage) | numeric, `25 ≤ temp ≤ 100` | error |
| incubation/denaturation/finalHold time | numeric, `1 ≤ time ≤ 600` | error |
| extension-bearing sub-stage time (last sub-stage) | numeric, `11 ≤ time ≤ 600` | error — keeps the `assemble_steps` `(time-10)` split ≥ 1s |
| non-extension sub-stage time | numeric, `1 ≤ time ≤ 600` | error |
| `amplification.cycles` | integer, `1 ≤ cycles ≤ 50` | error |
| `amplification.subStages` | length 2 or 3 | error |
| any required numeric field | present and numeric (not blank / non-numeric) | error |

Constants per ADR-018. Non-numeric or missing values for enabled fields are errors (not exceptions).

**Non-finite guard (#219):** `_is_number` rejects `NaN`/`Infinity`, and `save_profile` serializes with `allow_nan=False` *before* writing — so a non-finite value anywhere (including a disabled stage that validation skips) fails as a 400 with nothing written, rather than persisting literal `NaN`/`Infinity` that 500s on every later read.

---

## 8. Unit Tests

`unit_tests/test_profile_assembly.py` (marked `unit`), importing `validate_stages` directly. Behaviors, one RED→GREEN each: valid stages → no errors; temp above 100 / below 25 → error; time above 600 / below 1 → error; extension sub-stage time < 11 → error (while a non-extension time of e.g. 5 is fine); cycles 0 / 51 / non-int → error; sub-stage count 1 or 4 → error; disabled stage with bad values → no error (skipped); non-numeric / missing value → error.

Run: `pytest unit_tests/test_profile_assembly.py -v`

---

## Also in this issue (carried from A1 review, PR #206)

- Tighten `assemble_steps`'s return annotation from `-> list` to `-> list[dict]` (same file, cosmetic).

## Out of Scope

- Enforcing validation on `POST` + returning 4xx, and calling `validate_stages` before `assemble_steps` — A3 (#201).
- Frontend save-time validation display — B3 (#203).

## 9. Open Questions

- [ ] Return shape chosen: `list[str]` of field-named messages — simplest for A3's 4xx; the frontend doesn't depend on it (B3 validates independently). Revisit if A3 wants structured `{field, message}` entries.
