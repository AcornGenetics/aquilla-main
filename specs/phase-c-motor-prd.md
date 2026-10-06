# PRD — Phase C: 15-Well Motion (Working, Calibrated, Tested) + Thermal/Power Coordination companion

**Status:** Draft PRD (not an issue — tracked as a spec)
**Date:** 2026-10-06
**Depends on:** Phase B `read_plan(geo)` (landed on `feat/15well`: #514, #521–#525)
**Related:** `specs/15-well-mkii-migration.md` (§3 geometry source, §5 motion, §19e backend, §21b calibration), ADR-023 (optics read path), #519 (Meerstetter current-latch)

**Sliced into issues:**
- Slice 1 (#526) — per-row axis calibration (accept-both schema + row-aware axis) · AFK
- Slice 2 (#527) — lid heater quiet during a TEC ramp (thermal/power) · AFK
- Slice 3 (#528) — homing-error → QC telemetry (structure RDY/stale + correlation key) · AFK
- Slice 4 (#529) — motion backend: in-container pigpiod → localhost · normal
- Slice 5 (#530) — on-device bench validation: calibrate, scan-time ≤18s, power budget · HITL (blocked by #526, #527, #529)

---

## Problem Statement

The 15-well (Mk II) instrument must physically step the 3×5 plate in serpentine
order, read every tube, and home reliably — all inside a tight **≤ 18 s scan-time
budget**. Today the *software* can generate the geometry-driven motion (Phase B),
but the instrument has never been driven and calibrated for 15 wells: the axis
stop positions are 4-well placeholders, the motion backend still uses a hardcoded
container network hop, and there is no confirmation the real hardware hits the
scan budget or homes cleanly across 3 rows.

Separately but concurrently, a **device power-budget** constraint surfaced: the
lid heater and the Meerstetter TEC can draw peak power at the same time, exceeding
the budget. The lid heater must not draw power (it cannot pull ~0.315 V) **while
the TEC is ramping**. This is a thermal-control fix that *accompanies* the motion
work (more wells → more TEC load → tighter budget) but is its own concern.

## Solution

**Phase C (Motor):** drive the axis and drawer from `read_plan(geo)` on real
3×5 hardware; calibrate the 7 axis stops per row and the 3 drawer rows on the
bench; settle the motion backend (in-container pigpiod → localhost now; lgpio
benchmark to decide the durable backend); log per-move stall telemetry for a
downstream QC hook; and measure the scan time to confirm ≤ 18 s.

**Thermal/Power Coordination (companion phase):** drive the *existing* lid-heater
"quiet" gate from the thermal ramp in addition to the optics path, so the lid
heater energizes only when **neither** the optics path **nor** the TEC ramp wants
it quiet. The device stays within its power budget during ramps.

---

## User Stories

### Phase C — Motion

1. As a **run operator**, I want a dry 15-well run to step every tube in
   serpentine order, so that all 15 tubes are read in one pass.
2. As a **run operator**, I want the axis and drawer to home cleanly between
   passes, so that position error does not accumulate across cycles.
3. As a **run operator**, I want a 15-well pass to complete in ≤ 18 s, so that
   the total run time stays acceptable.
4. As a **field operator**, I want a 4-well device to move exactly as it does
   today, so that the 15-well work never regresses fielded units.
5. As a **provisioning engineer**, I want each device's 7-stop-per-row axis
   calibration and 3 drawer-row positions stored in `host_config`, so that the
   motion matches that physical unit.
6. As a **provisioning engineer**, I want the host_config to accept **either** a
   shared 7-stop list (one X-calibration reused across rows) **or** per-row stops
   (`{A,B,C}`, 7 each), so that I can start shared and move to per-row only if the
   bench shows the carriage X drifts between rows — with no code change.
7. As a **firmware engineer**, I want a `host_config` whose axis-stop count does
   not match the provisioned geometry to fail loud at motor load, so that a
   mis-calibrated device never drives to carriage stops that don't exist.
8. As a **firmware engineer**, I want the axis to select the correct row's stops
   when per-row calibration is present, so that per-row warp is handled.
9. As a **firmware engineer**, I want a repeat goto to the same physical stop
   (the serpentine row boundary) to be a safe no-op, so that the move is correct
   whether stops are shared (0-step move) or per-row (a real move).
10. As a **firmware engineer**, I want the motion backend to run pigpiod
    in-container and connect to localhost, so that the hardcoded `172.18.0.1`
    network hop is removed while the proven waveform code is unchanged.
12. As an **analysis/QC consumer**, I want per-move stall telemetry (steps to
    flag, residual, reached-home) logged structured, so that samples downstream
    of a stall can be disqualified.
13. As a **future engineer**, I want a motion-controller IC left for the respin,
    so that the current software backend is explicitly interim.
14. As a **test engineer**, I want the geometry-driven task generation and the
    host_config resolvers covered at the unit seam, so that motion *logic*
    regresses in CI even though the physical motion can't.

### Companion — Thermal/Power Coordination

15. As a **device owner**, I want the lid heater to stay off while the TEC is
    ramping, so that the device never exceeds its power budget.
16. As a **firmware engineer**, I want the lid heater to energize only when no
    quiet source (optics path or TEC ramp) is requesting quiet, so that one
    source releasing the gate can't turn the heater on while another still needs
    it off.
17. As a **firmware engineer**, I want the TEC ramp (both heating and the
    40→25 cooldown) to hold the lid heater quiet for its duration, so that both
    peak-current directions are covered.
18. As a **run operator**, I want a cancelled/aborted run to release the lid-heater
    quiet gate, so that the heater is never left stuck off after a stop.
19. As a **device owner**, I want the lid to stay warm enough through the worst-case
    ramp that condensation does not form, so that runs stay valid.

---

## Implementation Decisions

### Motion driven from geometry (largely already landed)
- Motion is generated by `read_plan(geo)` → `optics_read_tasks`: `drawer_to(row)`
  on row change, `goto_position(stop)` on axis-stop change, captures per channel.
  The executor already dispatches these (Phase B).
- The `append(0)` pad and the `−1` stop origin are already removed; the
  `len(axis_stops) == cols + sensor_gap` consistency assert
  (`assert_axis_positions_match`) is already in place.
- The degenerate `move_wo_home_flag(0)` is already guarded (returns immediately).

### Host_config calibration schema — **accept both forms**
- `axis.stops` accepts **either**:
  - a **flat list** of `cols + sensor_gap` steps (shared across rows; the 4-well
    and 15-well-separable case — 4-well stays byte-identical), **or**
  - a **per-row object** `{"A":[…], "B":[…], "C":[…]}`, 7 each, one per plate row.
- The `axis_stops(axis_config, geo)` resolver returns the flat list for the shared
  form and a per-row structure for the dict form; validation applies in both
  (each list `== cols + sensor_gap`; the per-row form has exactly `geo.rows` rows;
  fail loud otherwise). `drawer_rows` already resolves the 3 `{A,B,C}` positions.
- The motor normalizes: `goto_position(stop, row)` uses the current row's stops
  when per-row, else the shared list (row ignored). The executor threads the row.
- Consequence: the Phase B "skip the redundant goto at a serpentine row boundary"
  optimization is **replaced** by "always emit the goto; the motor no-ops a
  0-step move" — correct for shared (0-move) and per-row (real move to the new
  row's stop).

### Motion backend (§19e)
- **Decided:** run `pigpiod` in-container and connect to **localhost**, removing
  the hardcoded `172.18.0.1`. Waveform code unchanged. Container pigpiod needs
  elevated device access — **confirm fleet policy** (ops/infra). This is THE
  backend — the lgpio benchmark is dropped. A motion-controller IC is left for
  the respin (future hardware, not this phase).

### Homing-error → QC hook
- Per-move stall telemetry already lands structured in the **homing log**
  (`homing.log`, ADR-021 → outbox). **No new `motor.log`** — homing is already
  the motor-stall telemetry.
- The QC coupling correlates **homing position errors** against the **ADC
  RDY/stale-frame** signal (Slice 3 counters, now reaching disk via the Slice 1
  logger fix) to disqualify suspect tubes. Correlation happens **downstream in the
  outbox/warehouse** (join by run + position/time), not by co-locating files. The
  RDY/stale signal may need a structured home (not `logger.log`) for this — decided
  when the hook is built.

### Thermal/Power Coordination (companion)
- **Combinator — "quiet if either source asks."** The lid heater has one quiet
  source today (the optics path, via `lid_heater_quiet_event`). Add a second
  (the TEC ramp). The lid worker energizes only when **none** are set. Ship the
  minimal form — **two `Event`s OR'd** in the worker's quiet check — with a
  **refcount gate** (`acquire`/`release`, quiet while count > 0) noted as the
  scale-up for a 3rd source.
- **Trigger.** `thermal_engine` sets a `ramp_quiet_event` at the start of a
  `"ramp"` action and clears it when the ramp completes:
  - **v1 (ship first):** quiet for the whole `"ramp"` action (clear at the
    transition to `"hold"`). Deterministic; no current monitoring.
  - **v2 (power-optimal):** release early once TEC current drops below the budget
    threshold — `meer.log()` already reads `Cur1/Cur2`; ties to the #519 note
    "under 6 A on the 40→25 cooldown." The worst-case-ramp lid-cooling bench check
    decides whether v2 is needed.
  - `"ramp"` covers **both** heating and cooldown (`change_setpoint` to any value).
- **Abort safety.** The ramp set/clear is `finally`-guarded so a stop mid-ramp
  releases the gate — the lid heater is never stuck off.
- **Wiring.** `state_run_assay` creates `ramp_quiet_event` and passes it to both
  `lid_heater_worker` (second quiet source) and `thermal_engine`.

---

## Testing Decisions

Good tests assert **external behavior** at the highest existing seam, not internal
structure. Physical motion/calibration/scan-time cannot run in CI and are
bench/HITL; the *logic* around them is unit-testable.

- **Host_config resolvers (unit)** — `tests/unit/test_plate_positions.py`:
  `axis_stops` accepts the shared flat form (4-well byte-identical) **and** the
  per-row `{A,B,C}` form; fails loud on a count/label mismatch in either. Prior
  art: the existing `axis_stops`/`drawer_rows` fail-loud tests.
- **Geometry-driven task generation (unit)** — `tests/unit/test_optics_read_plan.py`:
  motion emits `drawer_to` on row change and `goto_position` on axis change;
  4-well byte-identical; 15-well serpentine. (Extends Phase B tests.)
- **Combinator (unit, highest seam)** — `tests/unit/hardware/test_lid_heater.py` /
  `test_lid_worker_instrumentation.py`: the lid worker energizes only when **no**
  quiet source is set; with two sources, OFF if **either** is set, ON only when
  **both** clear, including the overlap case (A clears while B still set → stays
  OFF). Prior art: the existing quiet-gate behavior tests.
- **Ramp trigger + abort (unit)** — `tests/unit/hardware/test_thermal_engine.py`:
  a `"ramp"` action holds the ramp-quiet signal for the ramp and releases it after;
  a `"hold"`/`"disable"`/`"enable"` does not assert it; a stop mid-ramp releases it
  (the `finally`). Prior art: the existing fake-meer thermal-engine tests.
- **Hardware/bench (not CI, documented `@pytest.mark.hardware` where applicable):**
  the SPI/pigpio motion, physical calibration, scan-time, and power-budget
  measurement.

Run the full suite (`pytest tests unit_tests -v`); all existing optics/geometry/
lid/thermal tests must stay green; 4-well must stay byte-identical.

---

## Out of Scope

- **Physical bench calibration values** themselves (the measured 7 stops/row and 3
  drawer positions) — produced on the bench, dropped into `host_config`.
- **The scan-time and power-budget measurements** — bench/HITL; this PRD delivers
  the software to drive and validate them.
- **Building the full homing-QC disqualification** in analysis — this PRD logs the
  telemetry structured and defines the correlation; the downstream
  outbox/warehouse join and sample-disqualification is a separate (analytics) piece.
- **Confirming the 0.315 V figure / exact power budget** — a bench power
  measurement; this PRD implements the coordination mechanism.
- **The 15-well optics `both` output format / analysis acceptance** — tracked
  separately (#524, acorn-analytics#102).

---

## Further Notes

- **Branch homes.** Phase C motion is part of the 15-well migration (`feat/15well`,
  where `read_plan`/geometry live). The thermal/power companion belongs to the
  Meerstetter/thermal family (the #519 line, `feat/greengrass-migration`) — the
  7.6 A cap (#519) fixed over-current *latching*; this fixes total-device *power
  budget*, same subsystem. Decide the merge/branch strategy when scheduling.
- **Why the thermal fix "accompanies" motion** (the colleague's point): more wells
  = more TEC load = tighter budget, so it surfaces with the 15-well expansion — but
  the fix is device-wide thermal control, not 15-well-specific code.
- **Exit criteria (Phase C motion):** a dry 15-well run steps every tube in
  serpentine order, homes cleanly, and scans in ≤ 18 s.
- **Exit criteria (thermal companion):** the lid heater is provably off throughout
  a TEC ramp, releases on abort, and the lid stays warm enough through the
  worst-case ramp to avoid condensation (bench-confirmed).
