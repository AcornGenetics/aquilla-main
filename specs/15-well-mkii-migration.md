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

### 1b. Model identity — RECOMMENDATION: the device carries its own "birth certificate"

The cleanest answer that scales to any N and kills the flag smell:

**Each unit stores its own `PlateGeometry` + calibration record in on-board NVM/EEPROM, written once at QC.** Boot validates it against cheap probes (ADC ID, homing travel) and **fails loud** on mismatch.

- Scales to any well count — it's just data written at manufacture.
- Can't drift — written once, travels with the physical hardware.
- Isn't hand-edited text, isn't cloud-authored, isn't a fragile live probe.
- This is how real lab instruments identify themselves.

And here's the elegant bit: **if the ID encodes the shape** (EEPROM record, or enough strap bits for rows/cols), a brand-new 3×7 device works with **zero software change and zero registry edit** — the hardware describes itself, the code computes geometry from it. The registry becomes unnecessary; only calibration stays per-unit.

**If you have no NVM today:** keep a config file, but reframe it as *"the QC-generated birth certificate for this unit"* (calibration + shape, written by a QC tool, validated by detection) — **not** engineer-toggled behavior flags. That's a normal, defensible use of a file, and it's a drop-in path to the EEPROM version later.

This resolves the §1a "Device declares its model once" open question and supersedes the §17 declared-vs-detected-vs-shadow debate: **detected/QC-written record is the source of truth; any file is a stand-in for the EEPROM, not a behavior switch.**

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

> **⚠️ host_config.json is GENERATED, not the source of truth.** The repo `config_files/host_config.json` is only a *reference*. On a device the real file is written at deploy time by the deployment scripts — `scripts/deploy/deployment2.sh` (heredoc at `:394`, `cat > /opt/aquila/config/host_config.json`) and `scripts/deploy/deployment3_greengrass.sh`. So the Mk II `sn03` flags we merged into the repo file do **not** reach a device on their own: **the deployment scripts would need to be built to emit the new variables** (`well_15`/`two_adcs`/`updated4`/`motor_test`, `read_steps`) into the generated JSON. Noted as a to-do here rather than done, because the preferred direction is to stop defining geometry/identity in the deploy scripts at all and move to the detected/QC-written model (§1a/§1b) — TBD. Until then, treat repo `host_config.json` edits as documentation of intent, not device config.

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

> **Note (see §22):** `aq_curve` is **lit-only / baseline-subtracted** and does NOT use the dark samples, so the crosstalk below does **not** currently affect Cq on the device path. It only matters if a dark-subtracting analysis is (re)introduced or another path (internal-app/cloud) uses dark. Keep this in mind when weighing the options.

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
- [ ] **Evaluate a TMC5160-class motion controller** (option C, §19e): offloads step generation to hardware ramps + on-chip StallGuard → kills the Linux-timing jitter class, helps the ≤18 s scan budget, and can replace the homing-error → optics-QC coupling (§5). Board + firmware scope; the respin is the cheap moment.

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

## 19. Review of the engineers' Mk II draft

Reviewed 5 files from the engineers' Mk II branch (not merged here), diffed against current 4-well repo: `optics_read_plan.py`, `motor_class.py`, `state_run_assay.py`, `adc_class.py`, `host_config.json`. Verdict: **the hardware mechanisms are correct and worth keeping; the software structure is the flag-branching we're trying to avoid, and one file carries a real merge hazard.**

### 19a. Mechanisms to KEEP (proven, match the PDF)
- **pigpio hardware-waveform motion** (`motor_class.move_wo_home_flag` → `wave_create`/`wave_chain`). Real anti-step-skip speedup vs the Python per-step bit-bang. Keep. (Caveat: talks to the daemon over a network socket `pigpio.pi("172.18.0.1", 8888)` — see cons.)
- **Serpentine 3×5 sweep** (`OPTICS_READ_PLAN_15`): 3 drawer rows × 7 axis stops, alternating direction per row to minimize travel. Good idea — but should be *generated from geometry*, not a hand-built literal.
- **Out-of-phase `"both"` capture** (`adc_class.capture_blink` "both" branch): dual-ADC, ROX-on/FAM-off ↔ FAM-on/ROX-off, reads both ADCs per sample, RDY-polled, `−123` sentinel.
- **Fast-settling filter** (`blink_num=7` vs 10) — the ~30% scan-time saving.
- **RDY-register polling** on every read (both legacy and dual paths) — more correct than the old blind read.
- **Deferred legacy-format reconstruction** (`mask_data` + `out_data`): pads 7→10, synth 3rd blink, swaps FAM phase, re-emits rox-then-fam per well so existing `aq_curve` still parses. Mechanism fine; lifecycle risky (see cons).
- **`read_ambient_temp()`** (w14): ADC1 → channel 4, restores to ROX.

### 19b. Structure to REWRITE (the flag-branching we rejected — see §1a/§1b)
- Behavior branches on `well_15` / `updated4` / `two_adcs` string flags across `optics_read_plan.py`, `state_run_assay.py`, `adc_class.py`. → replace with `PlateGeometry` + capability enum.
- `optics_read_tasks()` `if well_15 … elif updated4 …` plan selection → one `read_plan(geo)`.
- **Motor int-vs-tuple type-sniffing** (`Drawer.goto_position` no-ops on an int; `Axis.goto_position` unpacks `N[0]`) is `if well_15` in disguise → positions should always be structured coordinates from geometry.
- **Magic numbers:** hardcoded `21` (`expected_lines`, `out_data`, `state_run_assay`), `320` (row pitch), `self.positions.append(0)` "pad to imitate a 5th well." → derive from geometry.
- **Redundant flags:** `two_adcs` and `updated4` both really mean "this is a Mk II board" — illegal states possible (§1a). Collapse into one detected model/capability.
- **Single-device test config:** `host_config.json` trimmed to just `sn03` with string-typed flags (`"false"`/`"true"`).

### 19c. HAZARDS / correctness risks
- 🔴 **`state_run_assay.py` merge hazard:** the draft was branched from an OLDER base and DROPS features now on greengrass/main — `profile_sha256` run-provenance (#456), lid-heater sample logging (`configure_lid_sample_logger` + `run_timestamp` kwarg to lid worker, ADR-022). Merging as-is would silently REVERT them. Mk II changes must be ported ONTO current `state_run_assay.py`, never replace it.
- 🔴 **Deferred write = data loss on interrupt** (RISK C, §7): `out_data` only fires on `quit`; `"both"` buffers in `self.data_both` and writes nothing live. Cancel/crash mid-run → no optics file. Legacy path wrote incrementally.
- 🟠 **Network pigpio dependency:** motion now requires the pigpiod daemon reachable at a hardcoded docker-gateway IP:port. New runtime failure mode + a hardcoded address.
- 🟠 **`append(0)` mutates shared config state** (`config.axis["positions"]`) and relies on Python negative-indexing (`positions[-1]`) — fragile; the author's own comment flags it as temporary.
- 🟠 **Crosstalk unaddressed** (§12): `"both"` (one LED always on) has no true dark read; PDF measured position-dependent FAM Ct shift. Not handled in this draft.
- 🔴 **15-well output not actually implemented** (§21a): `out_data()` is still the 4-well writer — a "15-well" run writes only tubes B2–B5 and drops the other 11. See §21 for the full set of blocking gaps (writer, 5-well calibration, overhang).

### 19d. Remediation — fix per con

Numbering matches the decisions in the review. **Leverage:** three moves cover most of the list — #14 (geometry object) fixes 3/4/13/14; #12 (native dual-ADC reader) fixes 8/12 and de-risks 10; #11 (flush-on-exit) closes the one data-loss bug.

**Motion**
- [ ] **1 — pigpio waveform guards:** wrap waveform construction in one helper that enforces its own preconditions (`assert step_count % 8 == 0`; auto-chunk moves where `inner_count > 65000` into successive `wave_chain`s instead of erroring). Bit-bang fallback for tiny moves.
- [ ] **2 — hardcoded pigpiod `172.18.0.1:8888` / motion GPIO backend:** this is a bigger decision than a config injection — see **§19e** for the full A/B/C analysis. Short version: the network hop is an artifact of running the app in a container while `pigpiod` runs on the host; **preferred fix is B (lgpio, in-process) gated on a timing benchmark**, A (pigpiod in-container) as fallback, C (motion IC) on the respin.
- [ ] **3 — int/tuple type-sniffing:** emit two explicit task types from `read_plan(geo)` — `{"drawer_to": row}` and `{"goto_position": axis}`. Delete every `isinstance`/silent `return`. A 4-well plate (`rows=1`) emits NO `drawer_to` tasks, so the drawer stays put by construction.
- [ ] **4 — `append(0)` hack:** put the real measured first-column stop in `geo.axis_stops` (len = `cols + sensor_gap`); validate length at load and raise if short (the author's own TODO). Immutable geometry object; never mutate `config.axis["positions"]`.
- [ ] **5 — `motor_test()` in the driver:** move to `qaqc-cli`/`scripts/hardware/` as a standalone diagnostic importing `Motor`; drop the `motor_test` flag branch from `__init__`.

**Optics / ADC**
- [ ] **6 — verbose CS toggling:** a context manager (`with self._adc(i): ...`) asserts CS low on enter / high on exit even on exception. Every manual `GPIO.output(cs, …)` collapses into one place; leaked CS state becomes impossible.
- [ ] **7 — `"both"` crosstalk uncorrected:** either (a) subtract a per-position FAM dark calibration (offsets already measured, wells 1–2 vs 3–4) in analysis, or (b) take one true-dark read (both LEDs off) per pass. Add QC flagging runs where FAM Ct stdev exceeds the legacy baseline. (Decision → §12/§17.)
- [ ] **8 — `blink_num` couples filter/capture/padding:** derive `blink_num` from the filter choice in one spot; every consumer reads it (no bare 7/10); assert the filter register value ↔ `blink_num` so they can't desync. Fully dissolved by #12.
- [ ] **9 — RDY 7-vs-20 inconsistent, late healthy sample dropped:** one shared `read_when_ready(adc, timeout_ms)` that polls until RDY OR a deadline covering a full conversion period (~20 ms > 16.7 ms); use in both capture and temp. Resolves §17.
- [ ] **10 — `−123` sentinel fabricates data:** propagate `null`/NaN and teach `aq_curve` to skip nulls (PDF V2). SEQUENCE: analysis-accepts-null lands first, then the ADC stops substituting. Interim: add a "repaired" flag column so QC can see fabrication.

**Optics file**
- [ ] **11 — deferred write loses data on interrupt (RISK C):** flush incrementally (write each completed well/pass) OR register `out_data()` in a `finally`/signal handler so cancel AND crash both flush `data_both`. Make `out_data` idempotent + partial-safe. Add the cancel-mid-run regression test (§18).
- [ ] **12 — reconstruct-legacy-format fakes samples + format lock-in:** give `aq_curve` a native reader for the raw dual-ADC capture; keep legacy reconstruction only as a temporary shim behind a flag, then delete. Short-term: document the fingerprint (samples 8/9/10 byte-identical), never count padded rows as measurements in QC.
- [ ] **13 — hardcoded `21`/`6` in three files:** derive once (`reads_per_cycle = len(read_plan(geo))`), import everywhere `expected_lines`/`out_data`/`scan_num` need it, delete the literals. Extends the existing `READS_PER_CYCLE`-is-derived pattern.

**Root cause**
- [ ] **14 — config string flags / illegal states:** replace with `PlateGeometry` + optics-capability resolved from a detected/QC-written model (§1a/§1b). One `model` yields geometry AND capability; parse real booleans; absent → `sentri`. Deletes `well_15`/`two_adcs`/`updated4`, the redundancy, and the branching in every consumer — fixes #3/#13/#14 together.

**Migration approach:** cherry-pick the 19a mechanisms into the §1a/§1b architecture; do NOT merge these files wholesale (esp. `state_run_assay.py`).

### 19e. Motion GPIO backend — pigpio vs lgpio vs motion IC (decision)

**What the real problem is (and isn't).** The original inaccuracy was **software-timed pulsing on a non-realtime OS** (`RPi.GPIO` + `time.sleep()` at the mercy of the Linux scheduler) — NOT the container. That jitter is identical in a container or bare-metal. The container boundary is an **artifact of the pigpio fix**: DMA needs privileged `/dev/mem`, which is awkward in-container, so `pigpiod` runs on the host and the container reaches it over a socket.

**Where the container boundary genuinely DOES hurt accuracy (the subtle part):**
- Fast move `move_wo_home_flag` uses `wave_chain`: the whole waveform is uploaded once and the host's **DMA clocks every pulse precisely** — the network hop carries one "play this" command, so per-pulse timing is DMA-accurate regardless of where the client runs. Location is irrelevant to accuracy here.
- **Homing move `move_w_home_flag` can't pre-build a wave** (it polls the home flag every step), so it does a `pi.write()` **per step** — each a **network round-trip to the host daemon**. That per-step socket latency is a real timing/speed penalty on the homing path. Running in-process removes it.

So accuracy depends on the **timing method**, not on where the code runs. An in-container backend can be fully accurate if its timing mechanism is good.

**The three options:**

| | Runs | Privilege | Timing mechanism | Verdict |
|---|---|---|---|---|
| **A — pigpio, in-container** | in the container (co-located daemon) | needs `/dev/mem` + root → **privileged container** | DMA (gold standard) | Fallback. Keeps proven wave code; drops the network hop; cost is a privileged container (fleet/Greengrass policy question). |
| **B — lgpio, in-process** | in the container, in the app process; **no daemon, no socket** | needs only `/dev/gpiochip0` exposed + `gpio`-group access (like `/dev/spidev*` already) — **no `/dev/mem`/privileged** | kernel gpiochip chardev (NOT pigpio DMA) | **Preferred — gated on a timing benchmark.** Removes daemon, socket, AND per-step homing network latency, AND the privileged container. Risk: lgpio pulse precision at 30 mm/s must be proven. |
| **C — motion IC / MCU** | Pi sends high-level SPI moves; a TMC5160 (or RP2040) generates steps | plain SPI; no root, no DMA | dedicated hardware ramp/step generator | Respin destination. Kills the jitter class at the source; StallGuard can replace the homing-error QC hack; hardware ramps help the ≤18 s budget. Cost: board + firmware scope. |

**Recommendation:** ship **B if a quick benchmark passes**, else **A**; evaluate **C** for the Mk II respin.

- [ ] **Benchmark to decide B vs A:** prototype the step loop on `lgpio`, run at target speed (30 mm/s, 8–32 microsteps), and compare **step-skip rate / homing residual consistency** against the pigpio version. Instrumentation already exists (`steps_to_flag`/`residual` in `homing_log.py`). Pass → B; fail → A.
- [ ] **If A:** run `pigpiod` in-container (device mounts + caps), connect `localhost`/unix socket; confirm privileged-container is acceptable to fleet/Greengrass policy.
- [ ] **If B:** map `/dev/gpiochip0` into the container + `gpio`-group access; port the `wave_chain` fast path and the flag-polling homing path to lgpio's API.
- [ ] **C (respin):** add "evaluate TMC5160-class motion controller" to the §16 electrical/respin list; weigh StallGuard vs the homing-error QC coupling (§5).

---

## 20. How the 15-well scan moves & flashes (as-implemented walkthrough)

Grid, 3 rows × 5 columns:
```
A1 A2 A3 A4 A5
B1 B2 B3 B4 B5
C1 C2 C3 C4 C5
```
- **Rows = drawer motor** (front↔back, `read_steps + row*320`; 320 steps ≈ 9 mm). **Columns = axis motor** (left↔right, `positions[idx]`).
- **`OPTICS_READ_PLAN_15` = 3 rows × 7 axis stops = 21 stops**, each captures the `"both"` channel. Serpentine (minimizes axis travel — one motor moves at a time):
  - Row A: drawer `-1`, axis idx `-1→5` (L→R)
  - Row B: drawer ` 0`, axis idx `5→-1` (R→L)  ← reverses, no carriage-return
  - Row C: drawer `+1`, axis idx `-1→5` (L→R)
- **Why 7 stops for 5 tubes:** the FAM and ROX photodiodes sit **2 stops apart**. Each tube passes under ROX at one stop and under FAM two stops later, so a 7-stop sweep covers *both* channels of all 5 tubes; the 2 extra stops are the sensor overhang at the row ends. Axis idx `-1` = step 0 = the appended pad stop (`positions.append(0)`, §19b#4).
- **Executor calls BOTH motors every stop.** Position is a tuple `(axis, drawer)`: `Axis.goto_position` uses `[0]`, `Drawer.goto_position` uses `[1]`. In 4-well the position is a plain int → `Drawer.goto_position` returns immediately (no-op) → a single row. This int-vs-tuple no-op IS the 4-vs-15 switch (§19b#3). The drawer physically moves once per row (repeat gotos to the same absolute step are ~no-ops).
- **Flashing at each stop** (`capture_blink("both")`, `blink_num=7`): 28 samples @ 60 Hz (`4*blink_num`) — **ROX-on/FAM-off ×7, then FAM-on/ROX-off ×7, twice** → each LED flashes twice, out of phase (one LED always on, no true dark read → the §12 crosstalk). Both ADCs (ADC1=ROX, ADC2=FAM) are read *every* sample (RDY-polled, `−123` on miss) and buffered to `data_both`. **Nothing is written until `out_data()` fires on `quit`** (RISK C, §7).

**4-well vs 15-well — same machinery, three differences:** (1) plan selection `if well_15 … elif updated4 …`; (2) tuple positions + drawer moves vs int positions + drawer no-op; (3) `"both"` channel (dual-ADC, 21 stops, 3 rows) vs legacy sequential rox/fam passes (6 stops, 1 row). Everything downstream (executor loop, `read_wells`, task queue) is shared.

---

## 21. 🔴 BLOCKING GAPS — real 15-well output is NOT done yet

Three things in the draft are placeholders/broken. Until these are built, a "15-well" run does **not** produce usable 15-well data. These must be done.

### 21a. `out_data()` only reconstructs 4 wells — 11 of 15 tubes are dropped
The capture buffers all 21 stops × 3 rows correctly, but `out_data()`/`mask_data()` (`aq_lib/adc_class.py`) is still the **4-well writer**: its loop is `for k in range(6)` → 4 ROX + 4 FAM wells, with **no iteration over the 3 rows or 5 columns**. For 15-well it just sets `scan_num=21`, `rox_well_one=9`, `fam_well_one=7`, which offsets the 4-well window into the middle of the buffer → it writes only **Row B tubes B2–B5** and silently **drops B1, all of Row A, all of Row C.**
- [ ] **Rewrite the writer to emit all N wells** — iterate rows × columns from geometry (§1a), not a hardcoded `range(6)`. Ideally do this as the **native dual-ADC reader** (remediation #12, §12) rather than extending the legacy-4-well reconstruction, which cannot represent 15 wells cleanly. **This is the highest-priority correctness gap: today a "15-well" optics file is really a 4-well file.**
- Ties to RISK C (§7): even the 4 wells it does write only land at `quit` via `out_data()`.

### 21b. Axis stops are not real 5-well calibration (testing hack)
The axis reuses the **4-well** calibrated `positions` list plus a padded `0` stop (`self.positions.append(0)` in `motor_class.py`) "to imitate the first well while testing." So the 7 stops per row are **not the true 5-well pitch** — the logical ROX/FAM 2-offset is correct, but the physical stop positions are wrong for a real 5-column row.
- [ ] **Provide real measured 7-stop axis calibration per row** (5 wells + 2 sensor-offset stops) in geometry; validate `len(axis_stops) == cols + sensor_gap` at load and raise if short (the author's own TODO). Remove `positions.append(0)` and the negative-index pad (§19b#4, remediation #4).

### 21d. Optics file FORMAT must carry a 15-well tube identity (not yet specified)
The optics-file line is `<timestamp> <raw_hex> <value_mV> <led_on/off> <dye> <cycle> <position>`, where `position` is a **4-well carriage index** and the tube is derived as `position ∓ 1` (per dye). This **cannot name one of 15 tubes** — it has no row/drawer dimension. `out_data` currently stamps the 4-well `k` (0–5).
- [ ] **Define the 15-well optics file format:** carry an explicit **tube id** (row+column, e.g. `A1…C5`, or a flat 1–15) so every line is unambiguously attributable. Update the writer to stamp it and `curve.py extract_data` (its `position = well + dpos` mapping) to read it. Prefer doing this as part of the **native dual-ADC reader** (#12) rather than bolting a row onto the legacy `position`. This is the missing spec behind §21a.

### 21e. Per-well calibration arrays are hardcoded to 4 wells
`aq_curve/curve.py` holds per-well calibration as **4-entry lists** indexed `[well-1]`:
- `DEFAULT_CROSS_TALK_MATRIX` — 4 × 2×2 **spectral** crosstalk-correction matrices (`[[1,-0.1],[0,1]]` = `fam − 0.1·rox`; NOT the LED optical crosstalk). Applied via `_matrix_mul` (`:254`).
- `DEFAULT_THRESHOLDS` — 4 × `[0.2, 0.2]`.
- **Currently on a DEAD path:** both are used only by `is_detected` (`:276`), which is **not** the live detection route — `results_to_json` uses `evaluate_curve` (threshold-crossing, no matrix); the `is_detected` detection is commented out. `is_detected` survives as a public API (`main.py:25`) + a test.
- [ ] If/when reactivated (or for any per-well calibration), make these **N-entry, derived from geometry** — not fixed 4-length lists. Same for `thresholds`. Another per-well calibration artifact that must scale with well count (cf. §21b axis stops).

### 21c. Overhang bursts fire and are discarded (not modeled, just dropped)
At each row's edge stops the "missing" sensor still flashes both LEDs and samples both ADCs; that data isn't aligned to a real tube and is dropped in reconstruction. It works but is wasteful and implicit.
- [ ] **Make the overhang explicit in the plan/geometry** (mark which stops are ROX-valid / FAM-valid) so the writer selects real-tube samples by construction instead of index arithmetic — and so scan-time isn't spent on reads that are always thrown away. Fold into the §1a `read_plan(geo)` generation.

**Summary:** capture works; **write-out (21a) is the blocker**, **calibration (21b) makes the current stops physically wrong**, and **overhang (21c) is implicit tech debt.** None are "done."

---

## 22. Finding + decision: `aq_curve` is lit-only — stop averaging dark into `y0`

**Finding (verified in code):** `aq_curve`'s detection/Cq path is **lit-only, baseline-subtracted** — it does **not** use the dark (LED-off) samples.
- `extract_data` (`aq_curve/curve.py:186-187`) is the *only* place that reads the LED-off flag (`d[3]==0`), averaging it into `y0`.
- **Every** consumer drops `y0`: `get_curve` (`curve.py:261`) unpacks it and never uses it; `get_curve_data` (`pcr_curve_helpers.py:24`) explicitly discards it — `xdata, _, y1 = curve.extract_data(...)`.
- The production entry `results_to_json` → `resolve_status`/`resolve_cq` → `evaluate_curve`/`get_curve_data` all flow through those, so **calls and Cq are computed from `y1` (lit) with a fitted baseline** (`self.baseline(xdata, y1)`), never dark subtraction.
- True for **4-well and 15-well** (shared code). Consequence: the §12 crosstalk (contaminated 15-well dark) *and* the pristine legacy 4-well true-dark are **both moot for this path** — neither reaches Cq.

**Decision:** **Stop averaging dark samples into `y0`.** It's dead computation — remove the `y0` branch in `extract_data` and have consumers stop unpacking it.
- [ ] Remove the `y0` averaging + return from `extract_data` (`curve.py:173,186-187,196,198`); update `get_curve` (`:261`) and `get_curve_data` (`pcr_curve_helpers.py:24`) to a 2-tuple `(xdata, y1)`.

**Before it's fully safe, verify no OTHER analysis consumes dark (this only clears `aq_curve`):**
- [ ] `acorn-internal-app/compute/qpcr/curves.py` (the separate curve reimplementation, its own `_WELL_MAP`) — does it do on-minus-off?
- [ ] Cloud loader/ETL (`acorn-analytics`) and the offline `aq_curve/notebook_evaluator.py` (`:36` parses `led_state`).
- [ ] Reconcile with the **Mk II PDF's claim** that the analysis "subtracts LED On minus LED off" — that does NOT match `aq_curve`; confirm which implementation the PDF meant before trusting either.

**Bigger opportunity (separate, larger change):** if dark truly goes unused *everywhere*, stop **capturing** the LED-off samples at all → direct scan-time savings. That touches `adc_class.py` (the flash loop) and the optics file format / `mask_data` padding, so scope it on its own — the `y0` removal above is the safe, self-contained first step.

Cross-ref: §12 (crosstalk becomes a non-issue for the current path), §21 (output), §7 (RISK C).

---

### Changelog
- 2026-09-25 — Doc created from Mk II Design Rationale + cross-repo scoping sweep. Confirmed this checkout is still 4-well; no Mk II code merged here.
- 2026-09-25 — Added §1b (birth-certificate model identity) and §19 (review of the engineers' 5-file Mk II draft).
- 2026-09-28 — Added §19d (remediation: a concrete fix per con, with the 3-move leverage map).
- 2026-09-28 — Added §19e (motion GPIO backend decision: pigpio-A / lgpio-B / motion-IC-C, B preferred pending a timing benchmark) and the §16 TMC5160 evaluation item.
- 2026-09-28 — Landed the 5 Mk II files merged onto greengrass (3-way merge preserved #456/#454). Added §3 note (host_config is generated by deployment2.sh/deployment3_greengrass.sh — scripts must emit the new vars) and §20 (as-implemented move/flash walkthrough with the A1–C5 grid).
- 2026-09-28 — Added §21 (blocking gaps: 21a out_data writes only 4 of 15 tubes, 21b axis stops need real 5-well calibration, 21c overhang bursts implicit) + §19c hazard pointer. These must be built before 15-well output is real.
- 2026-09-28 — Added §22: verified `aq_curve` is lit-only/baseline-subtracted (dark `y0` computed in extract_data then dropped by all consumers). Decision: stop averaging dark into `y0` (dead code); verify no other path uses dark first. §12 flagged as moot for current path.
- 2026-09-28 — Added §21d (optics file format must carry a 15-well tube id — the missing spec behind §21a) and §21e (per-well `cross_talk_matrix`/`thresholds` are 4-hardcoded and on the dead `is_detected` path; spectral not LED crosstalk; make N-from-geometry if reactivated).
