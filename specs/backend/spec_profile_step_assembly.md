# Backend Spec: Profile Step Assembly (`stages → steps`) — issue #198 (A1)

**Status:** Draft
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-25
**GitHub issue:** #198
**Source file(s):** `aquila_web/profile_assembly.py` (new), `unit_tests/test_profile_assembly.py` (new)
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018
**Builds on:** `specs/backend/spec_stages_contract_foundation.md` (#197 — the `stages` contract)

---

## 1. Overview

A pure function that expands a structured `stages` object (the #197 contract) into the complete runnable `steps` array, weaving the fixed Boilerplate together with the user's Stages. No HTTP, no disk, no hardware imports — pure `dict → list`.

```python
def assemble_steps(stages: dict) -> list[dict]: ...
```

Lives in a standalone module so it is unit-testable without importing the FastAPI app (no RPi/serial stubbing). Wiring into `POST /profiles` is **A3 (#201)**; range validation is **A2 (#199)**. A1 assumes well-formed input and does not validate.

---

## 2. Input

The `stages` object (canonical fixture `tests/fixtures/sample_stages.json`):
`incubation`/`denaturation`/`finalHold` = `{enabled, temp, time}` (optional Stages); `amplification` = `{cycles, subStages:[{name,temp,time}]}` (always present, 2–3 sub-stages). `temp` °C, `time` seconds.

---

## 3. Output: assembled `steps`, in order

1. **Head (always):**
   - `{"disable": 0, "duration": 1, "description": "Record equilibration without power."}`
   - `{"ramp_rate": 1.6}`
   - `{"pcr_fanon": 1}`
   - `{"enable": 0, "duration": 1, "description": "Turn on and record temperature for a little bit"}`
   - `{"optics": ""}`
   - `{"setpoint": 25, "duration": 1, "description": "Presetting temperature"}`
2. **Incubation** (only if `enabled`): `{"setpoint": temp, "duration": time, "description": "Incubation"}`
3. **Initial Denaturation** (only if `enabled`): `{"setpoint": temp, "duration": time, "description": "Initial Denaturation"}`
4. **Amplification** (always):
   - `{"ramp_rate": 1.75}`
   - `{"repeat": [ <sub-stage steps> ], "cycles": <cycles>}`
   - Each sub-stage → `{"setpoint": temp, "duration": time, "description": <name>}`.
   - The **extension-bearing** sub-stage (the 2nd when there are 2, the 3rd when there are 3) is split around the optics read:
     `{"setpoint": temp, "duration": time-10, "description": <name>}`, `{"optics": ""}`, `{"setpoint": temp, "duration": 10, "description": <name>}`.
5. **Final Temp Hold** (only if `enabled`): `{"setpoint": temp, "duration": time, "description": "Final Temp Hold"}` — after Amplification, before tail.
6. **Tail (always):**
   - `{"ramp_rate": 1.6}`
   - `{"setpoint": 40, "duration": 20, "description": "Initial cooling"}`
   - `{"setpoint": 25, "duration": 10, "description": "Restoring setpoint to RT"}`
   - `{"disable": 0, "duration": 5, "description": "Turn off and record temperature for a little bit"}`
   - `{"pcr_fanoff": 0}`

Disabled Stages emit nothing. Constants (1.6 / 1.75 / 25 °C / 10 s offset) are fixed per ADR-018.

---

## 7. Validation Rules

None here — A1 assumes valid input. Range/shape validation is A2 (#199), enforced on `POST` in A3 (#201).

---

## 8. Unit Tests

`unit_tests/test_profile_assembly.py` (marked `unit`), importing `aquila_web.profile_assembly` directly. Behaviors: head emitted; tail emitted; amplification ramp 1.75 + repeat with cycles; sub-stage → setpoint with name description; optics split on extension sub-stage (2- and 3-sub-stage cases); incubation/denaturation/final-hold emitted when enabled; disabled stages omitted; full end-to-end ordering.

Run: `pytest unit_tests/test_profile_assembly.py -v`

---

## Out of Scope (other issues)

- Validation — A2 (#199). Wiring into `POST /profiles` + `structured` list flag — A3 (#201). UI — B1/B2/B3.

---

## 9. Open Questions

- [ ] None — assembly rules fixed in ADR-018 / the PRD.
