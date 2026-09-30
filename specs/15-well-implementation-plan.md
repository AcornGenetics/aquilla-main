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

**Goal:** `aq_lib.geometry() → PlateGeometry`, resolved from the immutable birth-written well-count record. Input validation only (unknown count → halt+log); no hardware cross-check.

**Model-identity design — immutable well-count file (grilled 2026-09-29):**
- **The record:** `/opt/aquila/config/device_identity.json` = `{ "wells": 15, "schema": 1, "provisioned_utc": "…" }`. Value is the **well count `4` or `15`** (integer) — self-describing. It only *names* the geometry; the geometry data lives in the `aq_lib` code registry keyed by well count.
- **Registry keyed by well count:** `GEOMETRIES = { 4: PlateGeometry(rows=1, cols=4, …), 15: PlateGeometry(rows=3, cols=5, …) }`, with the load-time invariant `GEOMETRIES[n].well_count == n`. Assumption: one canonical layout per well count (revisit only if a same-count/different-layout build appears).
- **Written by the Greengrass deploy script**, host-side as root, **write-once**: `if [ ! -e ] → write → chattr +i` (immutable). Separate filename from `host_config.json`/`device.env` (both deploy-regenerated), so regeneration never touches it; the immutable bit blocks stray scripts / OTA / fat-finger edits. `DEVICE_MODEL`/well-count is the one human input at provisioning (default 4).
- **Read by `aq_lib.geometry()`** — container-side, plain file read via the `/opt/aquila/config` bind-mount (host sets the immutable bit; container only reads → no container capability needed). Maps `wells` → `PlateGeometry`. **Input validation only, NO hardware cross-check** (decision 2026-09-29): if `wells` is not a known geometry (e.g. a typo like `5`/`150`, or a malformed file) → halt+log; otherwise trust the flag and return the geometry.
- **Trusted flag, accepted trade:** a *valid-but-wrong* flag (`wells: 15` on a physical 4-well unit, or vice-versa) is **not** software-caught → the motor drives to positions that don't exist on the first run. Backstop = careful once-at-build provisioning + one-command re-provision. No ADC-ID probe, no homing-travel check (removes the calibration dependency and the hardware coupling).
- **Recovery (bench):** `sudo chattr -i … && sudo rm …` → re-provision. Deliberate, one command — hard to change, recoverable.
- **Lifecycle:** survives OTA/container swap (persistent volume); a full SD reimage wipes it → re-provision. Deploy script must not `rm -rf` the config dir (immutable file errors).
- **NOT attached to `acorn-ca`** — fully independent of the Device Certificate and the enroll/renew path. (OTP and cert-binding both considered and rejected: OTP is permanently un-recoverable; cert-binding couples to acorn-ca.)

**Tasks:**
- Define `PlateGeometry` value object (§1a) — **purely logical**: `rows, cols, sensor_gap, channels`; `well_count` / `tube_ids` / scan-order derived. **No measured steps** — those stay in `host_config.json`, read by the motor. Immutable.
- `GEOMETRIES` registry in `aq_lib` keyed by well count: `4` = 1×4, `15` = 3×5; assert `well_count == n` at load.
- Add the write-once + `chattr +i` identity-file write to the **Greengrass deploy script** (`deployment3_greengrass.sh` / `deployment2.sh`).
- Implement `aq_lib/geometry.py` `geometry()`: read `device_identity.json` → `wells` → cached logical `PlateGeometry`; validate `wells ∈ GEOMETRIES` (halt+log on unknown); **reads nothing from host_config**; NO hardware cross-check.
- Motor keeps reading measured positions from `host_config` (unchanged); add the consistency assert `len(config.axis.positions) == geo.cols + geo.sensor_gap` (fail loud if host_config doesn't match the geometry).
- Wire `geometry()` as the single source of truth for shape everywhere.

**Problems:**
- Deploy script must write the identity file write-once and set `chattr +i`; must not later `rm -rf` the config dir.
- **Trusted flag:** a valid-but-wrong well count isn't software-caught (see design note) — relies on careful provisioning; accepted trade for removing the hardware/calibration dependency.
- **Board ≠ plate** (§1b): a Mk II board can sit in a 4-well chassis — reinforces that the well count is *declared* (authoritative), not inferred from hardware.

**Exit:** the well count comes from the immutable `device_identity.json` (not host_config); `aq_lib` resolves geometry from it; an unknown well count fails loud; changing it requires `chattr -i` + re-provision.

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
- **Motion backend (DECIDED — fleet is Pi 4B):** keep **pigpio** (DMA `wave_chain` = best stepper timing on Pi 4B; `lgpio.tx_wave` is software-timed and would be a *downgrade* here). Fix only the **deployment**: run `pigpiod -l` (localhost-only) **inside the app container** started by `entrypoint.sh`; `motor_class.py` `pigpio.pi()` → localhost (drop the hardcoded `172.18.0.1`); `apt-get install -y pigpio` in `Dockerfile.api`; disable host pigpiod (one DMA owner). **Bench-test SPI(optics)+pigpio(motor) DMA coexistence.** lgpio = Pi-5/fallback only; TMC5160 = respin. Full analysis + sources in tracker §19e.
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
| Identity file not written by deploy script | A | Add write-once + `chattr +i` to the Greengrass deploy script |
| Well count mis-provisioned (valid-but-wrong flag) | A | Accepted trade (no hardware check); careful once-at-build provisioning + one-command re-provision; motor misbehaves on first run if wrong |
| 5-well physical calibration slips | C | Bench early; it gates D's tube ids |
| Scan-time > 18 s at 15 wells | C | Measure early; backend + fewer flashes are levers |
| Optics format churn (writer↔parser) | D/E | Freeze the file format before coding either |
| Control-QC is new design, not a port | F | Timebox; ship per-tube calls first |
| 3.5 weeks is tight | overall | GUI (G) is the declared drop; protect A→D (the MVP) |

## Definition of done
- 4-well and 15-well both run through **one** geometry-driven path; no hardcoded counts or `elif` mode branches anywhere.
- 15-well: correct serpentine motion, correct 15-tube optics file, correct parse / analysis / Cq, correct synced `run_complete` event.
- Well count resolved from the immutable `device_identity.json`; unknown count fails loud (no hardware cross-check — trusted flag).
- (GUI only if scope allowed.)
