# 15-Well (Mk II) Migration — Running Change Tracker

**Status:** LIVING DOC — scoping / not yet started in this repo
**Owner:** _(unassigned)_
**Last updated:** 2026-09-25
**Design source:** `Mk II Design Rationale — Well Expansion Project Report` (Akulov, Turner; Project Head: Abbott; 09/20/26)
**Related design work:** AQU-4002 board notes, Well Expansion Project ELN (9/17)

---

## 0. Purpose & how to use this doc

A single running list of **everything that must change to take the Sentri from 4 wells to 15 wells (3×5 grid)**, across all repos. Each item has a checkbox, the concern it belongs to, and a `file:line` anchor where known. Update the checkboxes as work lands; add rows as new couplings surface.

**Two things this doc is NOT:**
- It is not the engineers' Mk II branch. The Mk II code described in the PDF (dual-ADC, `well_15`, `'both'` channel) was written by two engineers and, per the user, is "a complete mess that does not reflect what is best for the software." Treat the PDF as *design intent and hardware constraints*, not as the reference implementation.
- It is not merged here. **This checkout of `aquilla-main` is still pure 4-well SENTRI** — verified: no `two_adcs` / `well_15` / `'both'` / `read_ambient_temp` / `blink_num` markers exist in any `.py`, and `host_config.json` has none of the Mk II header flags. So most items below are net-new to this codebase.

---

## 1. Architecture decision (locked)

**One parameterized codebase, driven by per-device hardware config — NOT a fork / new repo.**

Rationale (see scoping analysis):
- The cloud warehouse (`acorn-analytics`) and both apps are already well-count-agnostic — forking gains nothing and doubles maintenance.
- A fork also forks the fleet/cert/profile/OTA machinery, doubling every future fix and every operational failure mode.
- One fleet + one warehouse requires a shared contract; 4-well and 15-well Sentris must coexist.

**Do NOT define "how many wells" as a per-device flag.** The `host_config.json` `well_15`/`two_adcs`/`updated4` flag pile (Figure 9) is rejected: it lets illegal states exist (`well_15:true` + `two_adcs:false`), authors a count that can drift from geometry, and forces `if well_15:` branching. Replace it with a geometry model (below).

### 1a. Design: geometry value object + model registry (REPLACES host_config flags)

**Core insight — 4-well and 15-well are the same shape:** both are a grid of `rows × cols`. SENTRI = `1×4` (one drawer row, axis sweeps 4 cols). Mk II = `3×5` (drawer indexes 3 rows, axis sweeps 5 cols). **4-well is the degenerate 1-row case of the identical traversal** — so there is nothing for an `if well_15:` to switch on; only *data* differs, never control flow.

- [ ] **`PlateGeometry` value object** = single source of truth (replaces every `[1,2,3,4]`/`range(6)`/`4`). Fields: `rows`, `cols`, `axis_stops` (MEASURED steps, len = `cols + sensor_gap` — keep calibrated, not computed; current deltas are irregular 355/355/350/360/340), `drawer_rows` (measured steps, len = `rows`), `sensor_gap` (FAM/ROX carriage-stop offset — **unifies the latent `±1` vs 2-position bug**), `channels`. `well_count` is a **derived property** (`rows*cols`), never authored.
- [ ] **Model registry**: `{"sentri": PlateGeometry(1×4,…), "mk2": PlateGeometry(3×5,…)}`. Geometry is a property of *which instrument this is*, not a per-device knob. Makes illegal states unrepresentable; a future 24-well = one registry entry, zero code changes.
- [ ] **Device declares its model once** (`"model": "mk2"`) instead of the flag pile. Storage location = OPEN QUESTION (§17: declared config field vs. hardware-detected vs. managed shadow).
- [ ] **Unified plan generator** (subsumes `optics_read_plan.OPTICS_READ_PLAN` + `optics_read_tasks`): `read_plan(geo)` yields the task stream for one pass — `for r in range(geo.rows): drawer_to(row); for stop: goto_position; capture(dyes_at_stop)`. SENTRI (`rows=1`) yields byte-identical today's 6-stop sweep; Mk II (`rows=3`) interleaves drawer moves. **The entire new control flow in `state_run_assay.py` is ONE new task case (`drawer_to` → `drawer.move_abs`)** — not an `if well_15`. `READS_PER_CYCLE` stays derived (`× geo.rows`).
- [ ] This **deletes the PDF's `well_15` "pad the row with a 0 to mimic 5 wells" hack** — padding only existed because they forced 4-well to pretend to be 15-well; with rows×cols both are first-class.
- [ ] Keep **4-well working unchanged**: absent `model` ⇒ `"sentri"` default.
- [ ] Kill dead constants (e.g. `DEFAULT_CURVE_WELLS` `aq_curve/pcr_curve_config.py:64`, defined but never consumed).

**Keep the dual-ADC `'both'` channel as a SEPARATE axis** — it's an optics *capability*, not geometry. `read_plan` decides *where* to read; the optics strategy decides *how* to sample channels at a stop (sequential 1-ADC vs simultaneous 2-ADC). Model capability as its own small enum on the instrument (same registry pattern). Folding it into geometry reintroduces branching.

---

## 2. BIG RISK AREAS (the three flagged by the team)

These three carry the most design risk. Everything in §5–§7 elaborates them.

### 🔴 RISK A — New positioning / motion software (4 across → 3 rows × 5)
The 3×5 grid (9 mm center-to-center) makes motion **2-dimensional**: the **axis motor** steps across 5 wells in a row; the **drawer motor** steps between the 3 rows (±9 mm). Wells are in neat rows (not offset) specifically so only one motor moves at a time per scan step. This replaces the current 1-D `axis.positions` sweep entirely.
- Motion is driven by an **optical path** = ordered `(position, channel)` pairs stored in `host_config.json`.
- Mk II motor driving changed to **pigpio precise hardware-timed pulses** (not Linux `sleep`) to avoid step-skipping at ≥30 mm/s; scan-time budget is tight (must fit in ≤18 s of the 38 s anneal/extension; all-optimizations Mk II = 16.7 s, unoptimized = ~55 s and FAILS).
- **Homing/step tracking feeds analysis:** steps-to-home and homing errors are logged and used to **disqualify optics samples** downstream of a motor stall (see Figure 5 — a stall between positions 4→5 corrupts all wells after it in the optical path). This is a genuinely new coupling between motion telemetry and curve QC.

### 🔴 RISK B — LED flashing & dual-ADC simultaneous read (`'both'` channel)
Mk II adds a second ADC (upgraded AQU-4002 board) so FAM and ROX are read **at the same time** via a new `'both'` channel, using **out-of-phase flashing** (ROX LED on while FAM LED off, and vice versa).
- Gated by `two_adcs` (board has 2 ADCs) and `updated4` (dual ADCs flashed out of phase); both **always `false` on SENTRI** → legacy single-ADC path must be preserved.
- Flash structure changes: legacy flashes each LED **3×/sec** and writes immediately; `'both'` flashes **2×**, records 28 samples @ 60 Hz (~0.47 s), buffers internally.
- **Fast-settling filter** (sinc4+sinc1) lets the ADC discard 2 settling samples instead of 5 → 7 samples per half-flash instead of 10 (~30 % scan-time save). `blink_num` selects 7-vs-10.
- **Crosstalk is real and position-dependent** (see §12) — not cosmetic.

### 🔴 RISK C — Optics file write / "download from there" (deferred write)
The `'both'` channel does **not** write the optics file live. It buffers all wells in memory and only at **end-of-run** reconstructs a legacy-format optics file (padding 7→10 samples, synthesizing a 3rd flash as the average, so SENTRI analysis can still "digest" it).
- **Interrupting a run with the new code yields NO optics data at all** (legacy code preserved whatever was scanned). This is a regression the PDF explicitly flags as "not inherent… can be improved later."
- `out_data` returns without writing unless `both_channel_was_used` is set → legacy rox/fam runs produce no reconstruction.
- Reconstructed files are fingerprintable (every row shares one timestamp; samples 8/9/10 of each 10-block are byte-identical) — matters for anyone parsing raw optics files downstream / for "downloading the optics file."

---

## 3. Geometry source of truth  (see §1a for the design decision)

Current committed block is 4-well only: `axis.positions: [320, 675, 1030, 1380, 1740, 2080]` (6 stops = 4 wells + 2-position FAM/ROX sensor offset), `adc: {famP:0,famN:1,roxP:2,roxN:3}`, no Mk II keys. **Do not extend it with `well_15`/`two_adcs`/`updated4` flags** — use the model registry instead.

- [ ] Implement `PlateGeometry` value object + `GEOMETRIES` registry (§1a). SENTRI entry reuses today's measured `axis.positions`; Mk II entry adds the 3-row drawer positions + 7 axis stops.
- [ ] Add a per-device `model` identifier (`"sentri"`/`"mk2"`); resolve → `PlateGeometry`. Storage decided in §17.
- [ ] Migrate current per-device `axis.positions` / drawer `read_steps` into the SENTRI registry entry (or have the registry read measured stops from the device's calibrated config, keeping calibration per-device while count/shape come from the model). **Decide: are stop positions per-model or per-device-calibrated?** — likely per-device calibration of a per-model *shape*.
- [ ] **Travel-budget check:** 5 axis stops/row is within range, but confirm `axis.home_steps` (2500) and drawer `read_steps`/`home_steps` cover the 3-row ±9 mm sweep.
- [ ] Model the **second ADC** as an optics *capability* on the instrument (separate enum), not geometry — its channel map + selection line.
- [ ] Backward-compat: absent `model` ⇒ `"sentri"`.

---

## 4. Well-count literals to replace (introduce `NUM_WELLS` / derive from config)

- [ ] `aq_curve/curve.py:341` — `_WELLS = [1, 2, 3, 4]` (the live well loop)
- [ ] `aq_curve/curve.py:160-165` — dye→position offset `dpos = +1 (fam)/-1 (rox)`; reconcile with the 2-position sensor gap used elsewhere (**latent inconsistency**, see below)
- [ ] `aq_curve/notebook_evaluator.py:59-63` — `positions=[2,3,4,5]`/`well_map={2:1,3:2,4:3,5:4}` (fam) and `[0,1,2,3]`/`{0:1,1:2,2:3,3:4}` (rox)
- [ ] `aq_curve/plot_utils.py:66` — `for index in range(4)`
- [ ] `aq_curve/pcr_curve_config.py:64` — `DEFAULT_CURVE_WELLS = [1,2,3,4]` (**dead — delete**)
- [ ] `aq_lib/motor_class.py:194` — fallback `self.positions = [w0 + dw*i for i in range(6)]`; `:192-193` defaults; `:197-199` `goto_position` indexing
- [ ] `aq_lib/optics_read_plan.py:12-19` — `OPTICS_READ_PLAN` (6 positions; rox 0–3, fam 2–5). `READS_PER_CYCLE` (:22) already **derives** from the plan — good, keep that pattern.
- [ ] `scripts/tools/diagnostic_sweep.py:427` — `--well choices=[1,2,3,4]`
- [ ] **Latent bug to fix during migration:** `curve.py` encodes the FAM/ROX sensor offset as `±1` while `optics_read_plan`/`notebook_evaluator` use a 2-position gap. Any geometry change must unify these.

---

## 5. Positioning & motion  (RISK A)  — `aquilla-main/aq_lib`, `state_run_assay.py`

- [ ] **Unify via `read_plan(geo)`** (§1a): one row-major traversal, `rows=1` (SENTRI) / `rows=3` (Mk II). NO `if well_15:` branch. The plan generator replaces the hardcoded `OPTICS_READ_PLAN`.
- [ ] `state_run_assay.py` executor: add exactly ONE new task case — `drawer_to` → `drawer.move_abs(...)`. Existing `goto_position`/`home`/`capture` cases unchanged.
- [ ] `aq_lib/motor_class.py` — generalize `positions`/`goto_position` to N stops from geometry; remove `range(6)` fallback. Drawer gains row-indexing moves (generalize the current single `.read()` position).
- [ ] The Mk II row sweep (drawer down 9 mm → scan; original read position → scan; drawer +9 mm → scan → home) falls out of `read_plan` iterating `geo.drawer_rows` — do NOT hand-code it as a separate function.
- [ ] Adopt **pigpio hardware-timed pulses** (replace Linux `sleep` delays) to hit ≥30 mm/s without step-skipping. Verify against the **≤18 s scan budget**.
- [ ] `state_run_assay.py` — it currently drives optics via `optics_read_plan.optics_read_tasks()` / `count_optics_passes()` (both derived), so it scales *if* the plan + geometry scale. Verify the executor/message-queue task flow (Figure 8) still holds with row moves interleaved.
- [ ] **Homing-error → optics QC coupling (NEW):** log steps-to-home + homing errors per move; propagate to analysis so samples downstream of a stall in the optical path are disqualified. Decide policy: blanket "bad homing disqualifies the whole cycle" vs. per-well "discard downstream wells only" (PDF leaves this open).
- [ ] `config_files/host_config.json` drawer/axis position + travel-budget updates (see §3).

## 6. Optics: LED flashing & dual-ADC  (RISK B)  — `aq_lib/adc_class.py`, `aq_lib/optics_read_plan.py`

- [ ] Add second-ADC support to `adc_class.py`: two ADCs share 3 signal lines, each with its own **selection line** (dormant vs active); code selectively talks to each and reads different channels concurrently. Preserve **backward-compat single-ADC mode** when `two_adcs=false`.
- [ ] Implement the `'both'` channel (simultaneous FAM+ROX) with **out-of-phase flashing** (ROX on ↔ FAM off). Gate on `two_adcs`/`updated4`.
- [ ] Fast-settling filter (sinc4+sinc1) config + `blink_num` selecting 7-vs-10 samples per half-flash. Wire the ~30 % scan-time saving.
- [ ] Robust ADC-ready handling: poll 1-byte RDY register (bit 7, active-low), sentinel `-123` on failure. **Known weakness to fix, not copy:** 7 poll attempts cover only ~42 % of a 60 SPS period (16.7 ms) → a healthy sample can fall through to substitution; PDF suggests raising capture-path count to 20 (matching `read_ambient_temp`) at a scan-speed cost. Decide.
- [ ] `mask_data` repair (bounded by `i % blink_num`, never crosses well/LED-phase boundary). Mk II V2 wants a `null` argument to "unfreeze" the ADC — **blocked on analysis accepting null** (see §8). Track that dependency.
- [ ] Optics geometry: `OPTICS_READ_PLAN` grows from 6 positions to the 3×5 layout (× 2 dyes) — but `'both'` changes the flash/position semantics; redesign the plan around simultaneous reads rather than sequential rox-then-fam passes.

## 7. Optics file write / download  (RISK C)  — optics output path (`out_data`, `mask_data`)

- [ ] Fix the **deferred-write regression**: interrupting a `'both'`-channel run currently writes no optics file. Design incremental/flush-on-cancel so an aborted run still yields partial data (matches legacy behavior). High priority — cancel is a common, supported flow (see `specs/analysis/scan-cancel-*`).
- [ ] `out_data` currently returns nothing unless `both_channel_was_used` — ensure the legacy rox/fam path still writes, and the reconstruction path is correct.
- [ ] Augmentation/padding to legacy format (7→10 via mean-of-last-4; synth 3rd flash = average of 2; 28→40, block→60). Verify the reconstructed file is analysis-compatible AND document the fingerprint (shared per-run timestamp; samples 8/9/10 byte-identical) for anyone parsing raw optics files.
- [ ] Confirm "how we download the optics file from there" — end-to-end path from device buffer → optics file → sync/upload. Verify against the event contract & any raw-optics consumers.

## 8. Curve analysis  — `aquilla-main/aq_curve`

- [ ] Generalize well loop + position↔well maps to N wells (see §4 literals).
- [ ] Accept the new optics-file layout (dual-ADC augmented format) as input — validate it "digests" identically to legacy.
- [ ] **Unblock the ADC `null`-sample path:** upgrade analysis to accept `null`/missing samples so `mask_data` can stop substituting stale values. This gates the §6 ADC fix.
- [ ] Ingest **homing-error metadata** to exclude compromised samples (see §5 QC coupling).
- [ ] Account for / correct the position-dependent **FAM crosstalk** (§12) if it exceeds tolerance.

## 9. Temperature acquisition  — `aq_lib/adc_class.py`, `state_run_assay.py`

- [ ] `read_ambient_temp()` switches ADC #1 from ROX to the temp input, takes readings, switches back. With dual ADCs + `'both'`, confirm which ADC owns temp and that channel-switching doesn't collide with simultaneous optics reads. `print_temp()` logs to docker logs + `/opt/aquila/logs/logger.log`.
- [ ] Verify the Figure-8 call flow (thermal_engine → `read_wells()` queues scan+move+`{"temp":1}` → executor thread) still holds under row moves + dual-ADC.

## 10. Device backend / API & event contract  — `aquilla-main/aquila_web/main.py`, `docs/local-db-schema.md`

- [ ] `main.py:338` `DEFAULT_TUBE_NAMES` (length 4) → derive from well count
- [ ] `main.py:450-460` `_normalize_tube_names` — **hard-caps names to exactly 4** (truncates/pads). Primary server-side gate; make width = well count.
- [ ] `main.py:462-471` `_tube_names_by_well` — keyed wells "1".."4" (#296)
- [ ] `main.py:604-612` `_build_results` — `for row in range(1,3)` (2 ch) × `for col in range(1,5)` (4 wells) = the fixed 8-call matrix → parameterize the well dimension
- [ ] `main.py:655` `_CHANNEL={"1":"fam","2":"rox"}` (2 channels — orthogonal, stays)
- [ ] `main.py:1092-1095`, `1119`, `1139`, `848`, `1217-1226` (`GET/POST /tube_names`), `1329-1337` — tube-name paths through the length-4 clamp
- [ ] `docs/local-db-schema.md:63-64` — contract prose promises "Wells 1–4" and "8 calls"; update. **No explicit version field** in `run_complete`; design is additive-by-`event_type`, so 15-well events are just longer `calls[]` / bigger `tube_names` — no hard version bump required, but update the doc so downstream doesn't assume 4.
- [ ] Tests encoding the contract: `tests/unit/test_run_complete_event.py:136-179` asserts exactly 4 tube-name keys.

## 11. Device UI  — `aquilla-main/aquila_web/static`

Layout **will visually break at 15** (fixed 4-col grid). Best fix: replace the 3 hand-authored 4-tube HTML blocks with a JS render-loop driven by well count, and switch the grid to `auto-fit`.
- [ ] `static/run.html:102-131`, `static/ready.html:43-72`, `static/complete.html:38-66` — four literal `results-tube` blocks (data-tube 1-4, "Tube 1".."Tube 4", FAM/ROX half-dots) → render dynamically
- [ ] `static/styles.css:1515-1520` `grid-template-columns: repeat(4, …)`; `:1908-1910` (820px breakpoint, still 4); `:2161-2164` (dead `flex-wrap` on a grid) → `repeat(auto-fit, minmax(…))`
- [ ] `static/script.js:49` `DEFAULT_TUBE_NAMES` len 4; `:1105-1106` `Array(4)`; `:1115` `for col=1..4`; `:1447-1462` `/tube_names` fetch bound to len-4 fallback
- [ ] `static/history.js:2,33-35` (loop `≤4`, channels "1"/"2"); `static/history_detail.js:10,79-90,177` (two loops `≤4`, channels "1"/"2")
- [ ] Note: `.results-tube` querySelector loops (script.js `:409,967,1088,1133`) adapt automatically once the DOM has N tubes.

## 12. Data-quality / crosstalk  (analysis correctness)

- [ ] **Out-of-phase flashing ⇒ no true dark read** (one LED always on). Measured raised FAM dark level 0.36–0.41 mV at carriage positions 2–3, ~0 at 4–5 (ROX LED leaking into FAM detector; ROX unaffected).
- [ ] Effect is **position-dependent, not a constant offset** → LED-on-minus-off does NOT cancel it. In the 2026-09-17 comparison: FAM Ct split along that boundary — wells 1–2 came up 0.2–0.4 cycles *early*, wells 3–4 came up 0.9–1.6 cycles *late*; FAM Ct stdev ~doubled (0.322→0.688). ROX unchanged.
- [ ] Decide: correct in analysis, change optics, or accept + document tolerance. **Do not repeat the PDF's earlier "no effect on analysis" claim without qualification.**

## 13. Cloud analytics  — `acorn-analytics`  (LOW EFFORT — already scales)

Warehouse is **normalized** (`(run_id, well, channel)` grain, `well SMALLINT` with the `-- 1-4` only a comment, variable-length `calls[]`, loader iterates with no count check). **No DDL migration, no loader change, no version bump** to ingest 15 wells.
- [ ] `db/migrations/002_facts.sql:30` (+ `007`/`008` call-evidence) — update the `-- 1-4` comments only
- [ ] `lib/loader/transform.ts:10-15,28-31,104-113` — already generic; refresh doc comments
- [ ] Extend example fixtures/tests to cover wells 5–15 (`tests/migrations/views.test.ts`, `inconclusive-flagged-run.test.ts`)

## 14. Apps  — `acorn-app`, `acorn-internal-app`  (MOSTLY DATA-DRIVEN)

**acorn-app** (customer dashboard — beer-QC mock): rendering already adapts; `4` lives in fixtures only.
- [ ] `src/mock/generate.ts:20-59` — `buildGrid` "4-well" loop + hardcoded control wells 3 (PC) & 4 (NTC); `src/mock/types.ts:46` `// 1..4` comment
- [ ] `src/app/runs/[runId]/page.tsx` already derives wells from data — no change

**acorn-internal-app**: mostly data-driven (`well_count = count(distinct well)`); one real bottleneck.
- [ ] `compute/qpcr/curves.py:12-15` — `_WELL_MAP` position→well table (4 wells/dye) → extend to 15 (**the one genuine code change**)
- [ ] `src/app/analysis/ResultsView.tsx:331-341` — `MAX_WELLS_PER_RUN = 4` (layout min-height; overflows at 15) → cosmetic
- [ ] Stale comments: `src/types/index.ts:244` ("4×2=8"), `src/analysis/results-graph.ts:166`

## 15. QC tooling  — `qaqc-cli`  (MOST HARDWARE-COUPLED)

Several constants mirror physical hardware (4 thermocouples, 6 optics stops), so these are hardware-shaped, not display tweaks.
- [ ] `qaqc_cli/analysis/thermal/hold_test.py:33-34` `WELLS=("tc1".."tc4")`, `WELL_LABEL`; `:141-152` DAQ parser reads exactly 4 thermocouple columns (`parts[2..5]`, `len<6` guard) — **structural: needs more DAQ columns for more thermocouples**; `:376,384,404,503,592` "Well 1..4" headers
- [ ] `qaqc_cli/analysis/thermal/recipe_test.py:25,171,183,310`; `recipe_test_plot.py:66-67,96-97,193` (`0.7/4`, `linspace(...,4)`, 4-color palette); `hold_test_plot.py:35` (4 colors)
- [ ] `qaqc_cli/analysis/optics/adc_scan.py:21-29` `_SENSOR_MAPPING` (6 stops→wells 1-4/dye); `:73-80` `expected_wells`; `raster_plot.py:24,38` `_MAX_WELLS=4`
- [ ] `qaqc_cli/commands/motor.py:24-25` `_AXIS_POSITIONS=range(0,6)`, `_WELLS=range(1,5)`
- [ ] `qaqc_cli/analysis/optics/dilutions.py` — `parse_wells` already well-agnostic; only docstring says "4"

## 16. Electrical / firmware context (affects flags & timing, not app code)

Not software tasks, but they set the config flags and constraints above:
- Pi, photodiode board, cables/connectors **unchanged**.
- AQU-4001: 12 V regulator LM73605→**LM73606** (+1 A on 12 V rail; lid heater up to 60 W).
- AQU-4002: **dual-ADC** board, same shape/connectors, backward compatible (2nd ADC on previously-unused connection; shared 3 signal lines + per-ADC selection line).
- 150 W PSU (peak 169.5 W during ramp); **lid heater must be OFF during heat/cool ramps** — confirm the control code enforces this.
- Larger 53×35 mm TEC + heatsink; PID (Kp/Ti/Td/PW) carried over from SENTRI as first approximation → **may need retuning for the 3.21× bigger heatblock**.

---

## 17. Cross-cutting open questions

- [ ] **Model identity — DIRECTION: self-detect (detect-and-validate), not a declared flag.** Two senses, do NOT conflate:
  - *Capability (dual-ADC board)* — reliably probeable TODAY: `adc_class.py` already has `REG_ID = 0x05`; open the 2nd ADC's chip-select and read the AD7124 ID register (present → valid ID, absent → floating `0x00`/`0xFF`). No hardware change.
  - *Geometry (1×4 vs 3×5 plate)* — NOT directly countable (no per-well sensor). Infer from homing travel (`motor_class.py`/`homing_log.py` already log `steps_to_flag`) — a 3-row/5-col build homes over longer travel. Softer signal; needs thresholds/calibration.
  - **Danger:** signals can disagree (PDF allows a Mk II *board* in a SENTRI backward-compat build → dual-ADC present but 4-well mechanics). Board ≠ plate. Misdetecting geometry = axis sweeps wrong span → mechanical crash. Detection MUST fail-loud on ambiguity, never default.
  - **Recommended:** add a dedicated **build ID** on the Mk II board respin (GPIO strap pins / I²C EEPROM / ID resistor) → one unambiguous read resolves the model. Interim (no HW change): ADC-ID probe + homing-travel classification, with any declared `model` demoted to a cross-check detection must match.
- [ ] **Geometry delivery (secondary to detection):** if any declared fallback is kept, `host_config.json` (image-baked, hostname-keyed) vs. managed per-device profile (IoT shadow, `acorn-fleet` ADR-0002). How do 4-well and 15-well devices coexist in one fleet/ring?
- [ ] **Optical path schema:** exact JSON shape for `(position, channel)` pairs incl. `'both'`, drawer rows, and per-channel delays.
- [ ] **ADC readiness policy:** 7 vs 20 capture-path attempts (scan-time vs. correctness).
- [ ] **Homing-error QC policy:** blanket-cycle-disqualify vs. per-well downstream discard.
- [ ] **Crosstalk handling:** correct in analysis vs. accept-with-tolerance.
- [ ] **`null` sample rollout order:** analysis must accept `null` before the ADC can stop substituting — sequence this.
- [ ] **Contract/version:** keep additive (no version field) or introduce an explicit schema version now that call-count varies?

## 18. Testing (to expand)

- [ ] Device unit tests: parameterize `test_run_complete_event.py` off well count
- [ ] Optics reconstruction: golden-file test that dual-ADC augmented output digests identically to legacy in `aq_curve`
- [ ] Cancel-mid-run: assert partial optics data is written (RISK C regression guard)
- [ ] Motor/scan-time budget test (≤18 s) at 15 wells
- [ ] Analytics: fixtures for wells 5–15
- [ ] End-to-end: 15-well run → event → warehouse → app render

---

### Changelog
- 2026-09-25 — Doc created from Mk II Design Rationale + cross-repo scoping sweep. Confirmed this checkout is still 4-well; no Mk II code merged here.
