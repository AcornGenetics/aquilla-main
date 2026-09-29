# Mk II 15-Well — Implementation Plan

**Target:** 3.5 weeks (~18 working days). **This schedule is TIGHT.**
**Scope note:** the GUI work (Phase G) is a **stretch and may NOT be included in this effort** — the core deliverable (a working 15-well instrument end-to-end on the backend) does **not** depend on it. If time is short, GUI is the first thing dropped.
**Full engineering detail / rationale:** see the running tracker `specs/15-well-mkii-migration.md` (section refs like "§1a" below point there).

---

## MVP milestone (~day 10 / end of week 2)
**Motor moves correctly through the 3×5 serpentine AND the optics file records all 15 tubes correctly.** Everything after (parse → analysis) builds on this working model.

## Two non-negotiable guardrails (every phase)
1. **Reactive, never hardcoded.** No literal well counts, no `[1,2,3,4]`, no `if well_15 / elif updated4`, no int-vs-tuple type-sniffing. Everything derives from one `PlateGeometry`. A new well count = new geometry *data*, **zero code change**.
2. **4-well never regresses.** SENTRI runs the *same* code as the degenerate `rows=1` geometry; verify byte-identical optics + identical calls at each phase.

## Critical path
**A → B → C / D → E → F → H.** Phase C's motor-bench work and Phase G (GUI, if in scope) can run in parallel with a second dev. **Dropping GUI relieves most of the schedule pressure.**

---

## Phase A — Configuration & hardware identity (Days 1–2)
*Priority #1: the model (4-well vs 15-well) is a **declared value written at device birth**, living in the hardware code layer — NOT a physical pin, and NOT a surface/mutable config file.*

**Goal:** `aq_lib.detect_model() → PlateGeometry`, resolved from a durable birth-written record and validated against live hardware, fail-loud on mismatch.

**Model-identity design — the software "birth certificate":**
- **What:** a minimal hardware-identity record — `{ "model": "mk2" }` — read by `aq_lib` to pick the `PlateGeometry` from the code registry. Geometry *data* lives in code; the record only names which profile.
- **When (birth):** written **once at enrollment/provisioning** (e.g. `provision --model mk2`) — the moment the physical unit is first set up. Not set per-run, not by operators.
- **Where (durable, not surface):** a **root-owned file on the persistent data volume**, *outside* the deploy-regenerated `host_config.json` path, so `deployment2.sh` never rewrites it and it survives reimage/OTA. Changing it = deliberate **re-provisioning**, not a JSON edit.
- **Validated in hardware code:** `detect_model()` reads the record → model → geometry, then **cross-checks against live hardware** — 2nd-ADC ID probe (`REG_ID=0x05`, is the dual-ADC board present?) and homing travel (does the plate match?). Mismatch → **halt and log**, never default.
- **Tamper-resistance dial:** **Tier 1 (this effort)** = root-owned persistent birth file. **Tier 2 (follow-up)** = sign the record / bind the model into the device certificate at enrollment (via `acorn-ca`) so it's cryptographically un-changeable. Design Tier 1 so Tier 2 layers on without rework.

**Tasks:**
- Define `PlateGeometry` value object (§1a): `rows, cols, axis_stops, drawer_rows, sensor_gap, channels`; `well_count` / `tube_ids` derived. Immutable.
- Model registry in `aq_lib`: `sentri` = 1×4, `mk2` = 3×5.
- Add the birth-record write to the **enrollment/provisioning** path (`provision --model …`) → root-owned persistent file.
- Implement `aq_lib.detect_model()`: read birth record → model → geometry; validate via ADC-ID probe + homing travel; fail loud on mismatch.
- Wire geometry as the single source of truth injected everywhere.

**Problems:**
- Provisioning/enroll flow must write the birth record — coordinate with the enrollment path early.
- The persistent location must survive reimage/OTA **and** sit off the deploy-regenerated config path.
- Homing-travel cross-check needs a calibrated threshold (soft signal).
- **Board ≠ plate** (§1b): a Mk II board can sit in a 4-well chassis — this is exactly why the model is *declared at birth* (authoritative) and hardware is only a *cross-check*, not the source.

**Exit:** the model comes from the birth record (not host_config); `aq_lib` resolves geometry from it; the live-hardware cross-check fails loud on mismatch; changing the model requires re-provisioning.

---

## Phase B — Reactive foundation + remediate the engineers' code (Days 3–6)
*Priorities #2 (reactive refactor) and #3 (fix Nick/Jake's changes) — together, because making their code reactive IS the remediation.*

**Goal:** one geometry-driven code path; all hardcoded literals and structural debt gone.

**Tasks:**
- **Unified `read_plan(geo)`** (§1a) replacing `OPTICS_READ_PLAN` + the `if well_15 / elif updated4` branch in `optics_read_tasks`. Generates the serpentine 3×5 (or 1×4) as data. `READS_PER_CYCLE` derived (kill hardcoded `21`).
- **Executor: one `drawer_to` task type** — delete the int-vs-tuple sniffing in `Axis`/`Drawer.goto_position`; positions are always structured coords from geometry.
- Replace every literal: `curve.py:341 _WELLS`, `notebook_evaluator` well-maps, `plot_utils:66 range(4)`, `motor_class` `range(6)` + `append(0)` pad, `main.py _build_results range(1,5)` / `_normalize_tube_names` cap-4. Delete dead `DEFAULT_CURVE_WELLS`.
- **Reconcile the sensor-offset bug:** unify `curve.py` `dpos = ±1` with the 2-position gap into one `geo.sensor_gap`.
- Fold in cheap remediations: collapse redundant flags (`well_15`/`two_adcs`/`updated4`) into the model; derive constants.

**Problems:**
- Keep 4-well byte-identical during the refactor (regression-test each literal removal).
- The sensor-offset unification is subtle — test against a known 4-well optics file.

**Exit:** 4-well runs unchanged through the new geometry path; no `well_15`/`elif`/type-sniff remain; a 15-well geometry produces the full 21-stop serpentine plan.

---

## Phase C — Motor: 15-well motion working, calibrated, tested (Days 5–8)
*Priority #4a. Can start once B's `read_plan` lands.*

**Goal:** the instrument physically steps the 3×5 serpentine and homes reliably within the scan budget.

**Tasks:**
- Drive motion from `read_plan(geo)`: axis across columns, drawer between the 3 rows.
- **Motion backend:** ship **pigpiod in-container → `localhost`** now for the working model (removes the hardcoded `172.18.0.1` network hop, keeps the proven waveform code). Run the **lgpio timing benchmark** in parallel (using existing `steps_to_flag` / `residual` logging) to decide the durable backend; leave a motion-controller IC for the respin.
- **Real 5-well axis calibration:** measure the 7 stops/row on the bench; put them in `geo.axis_stops`; remove `append(0)`; validate `len(axis_stops) == cols + sensor_gap`.
- Drawer 3-row moves (±9 mm / 320 steps) + homing; handle the degenerate `move_wo_home_flag(0)` on repeat gotos.
- **Homing-error → QC hook:** log per-move stall telemetry so downstream can disqualify samples.
- **Measure scan time** at 15 wells; confirm ≤18 s.

**Problems:**
- Physical calibration needs bench + the real 3×5 hardware.
- Scan-time budget is tight.
- Container pigpiod needs elevated device access — confirm fleet policy.

**Exit:** a dry 15-well run steps every tube in serpentine order, homes clean, scan-time ≤18 s.

---

## Phase D — Optics file: record all 15 tubes correctly + define the format (Days 8–10) → **MVP**
*Priority #4b. This + Phase C = the working model.*

**Goal:** a 15-well run writes an optics file with all 15 tubes, each unambiguously identified.

**Tasks:**
- **Rewrite the writer:** replace the 4-well `for k in range(6)` in `out_data` with an N-well emit driven by geometry — the current code drops **11 of 15 tubes**. Prefer a **native dual-ADC writer** over padding to the legacy shape.
- **Define + stamp the 15-well file format:** each line carries a real **tube id (`1A`–`5C`)** — add the row/drawer dimension the current `position` column lacks.
- **Fix deferred-write on cancel/crash (RISK C):** flush incrementally or via a `finally` / signal handler so an interrupted run still writes partial data.
- Overhang handling: mark ROX/FAM-valid stops in the plan so the writer selects real-tube samples by construction.
- **Dark samples:** analysis ignores them (§22) — decide now to either stop *writing* the LED-off block (save scan time/space) or stop only the `y0` averaging. Confirm no other consumer first.

**Problems:**
- Format must serve both the writer and the parser (Phase E) — **freeze it before coding either.**
- Native-vs-legacy-shape decision; cancel-flush correctness.

**Exit / MVP:** a 15-well profile → motor sweeps correctly → optics file contains 15 correctly-labelled tubes with sane values; canceling mid-run still writes what was captured.

---

## Phase E — Parse the optics file (Days 11–12)
*Priority #5.*

**Goal:** `extract_data` reads the new 15-well format and locates every tube.

**Tasks:**
- Update `extract_data` (`curve.py`) to read the tube id instead of the 4-well `position = well + dpos` math; drive tube enumeration from geometry.
- Golden-file test: the parser round-trips the writer's output; a 4-well file still parses identically.

**Problems:** parser/writer format lock-step; keep the 4-well path working.

**Exit:** parsing a 15-well optics file yields 15 per-tube, per-dye curves.

---

## Phase F — Analysis on 15-well + control QC + event path (Days 12–15)
*Priority #6.*

**Goal:** calls, Cq, and the synced event all correct for 15 tubes.

**Tasks:**
- Scale the per-tube loop: `_WELLS`→N, results dict, `plot range`→N. **Per-tube qPCR math is UNCHANGED** — do not touch baseline / threshold / Cq (all per-curve, well-count-independent).
- Per-well calibration arrays (`cross_talk_matrix`, `thresholds`) → N if/when reactivated (currently on a dead path).
- **`run_complete` EVENT:** `main.py _build_results` / `_normalize_tube_names` / tube_names → N, so the cloud receives 15-well data. (The warehouse already scales.)
- **NEW: control-aware QC** — define control positions (per-protocol / plate map), enforce NTC = Not-Detected & PC = Detected, decide run-invalidate vs annotate, on-device vs app. **This is the one genuine new feature — timebox it; if it slips, ship per-tube calls first and layer control-QC after.**

**Problems:**
- Control-QC is a design decision, not a port — get "where are controls defined" answered early.
- The `run_complete` event / tube_names cap-4 is the least-examined gap; don't forget it (optics file ≠ synced data).

**Exit:** a 15-well run produces 15×2 calls + Cq, a valid `run_complete` event, and (if in scope) control-based run QC.

---

## Phase G — GUI for 15-well  *(STRETCH — likely NOT in this effort)*
*Priority #7. Full design in tracker §25.*

> **This phase is out of scope if the schedule is tight.** The backend MVP and analysis do not depend on it. Included here only so the work is scoped if time allows or a second dev is free.

**Goal (if pursued):** the kiosk (768×1024 portrait touch) shows and names 15 tubes usably.

**Tasks:**
- Dynamic-render refactor: replace the 4 hand-authored `.results-tube` blocks (×3 files) with a JS loop from geometry; CSS `repeat(4)` → geometry-driven grid.
- 3×5 plate-mirroring grid with `1A`–`5C` labels (columns 1–5 × rows A–C).
- Tap-a-tube → larger edit panel for naming; controls auto-labelled.
- Status dots scale; controls marking + count exclusion; history table → N rows; optional live scan indicator.

**Problems:** touch layout at ~150px cells; naming UX; keep 4-well rendering identical.

**Exit:** operator can load, name, run, and read 15 tubes on the kiosk; 4-well UI unchanged.

---

## Phase H — Integration, 4-well regression, buffer (Days 17–18)
- End-to-end: 15-well run → motor → optics file → parse → analysis → event → (GUI/history if in scope).
- Full **4-well regression** (same code, `rows=1`): byte-identical optics + identical calls.
- Schedule buffer for slippage (calibration, control-QC, and — if attempted — GUI are the most likely).

---

## Risk register (top items)
| Risk | Phase | Mitigation |
|---|---|---|
| Hardware strap/EEPROM not ready | A | Coordinate day 1; interim ADC-ID + declared-model fallback |
| 5-well physical calibration slips | C | Bench early; it gates D's tube ids |
| Scan-time > 18 s at 15 wells | C | Measure early; backend + fewer flashes are levers |
| Optics format churn (writer↔parser) | D/E | Freeze the file format before coding either |
| Control-QC is new design, not a port | F | Timebox; ship per-tube calls first |
| 3.5 weeks is tight | overall | GUI (G) is the declared drop; protect A→D (the MVP) |

## Definition of done
- 4-well and 15-well both run through **one** geometry-driven path; no hardcoded counts or `elif` mode branches anywhere.
- 15-well: correct serpentine motion, correct 15-tube optics file, correct parse / analysis / Cq, correct synced `run_complete` event.
- Model resolved from a **hardware** signal, fail-loud.
- (GUI only if scope allowed.)
