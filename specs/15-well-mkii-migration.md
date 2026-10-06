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

- [ ] **`PlateGeometry` value object = PURELY LOGICAL** (grilled 2026-09-30): the single source of truth for *shape*, holding **no measured/physical values**. Fields: `rows`, `cols`, `sensor_gap` (FAM/ROX carriage-stop offset — **unifies the latent `±1` vs 2-position bug**), `channels`; `well_count` (`rows*cols`), `tube_ids`, and the serpentine scan order are **derived**. **The MEASURED motor steps (`axis.positions`, `drawer.read_steps`, `home_steps`, `step_multiplier`) stay in `host_config.json`, read by the MOTOR — NOT in `PlateGeometry`, NOT read by `geometry()`.** (Earlier drafts put `axis_stops`/`drawer_rows` in geometry — dropped; that coupled geometry to host_config for no reason.)
- [ ] **Registry keyed by WELL COUNT (int)**: `GEOMETRIES = {4: PlateGeometry(rows=1, cols=4, …), 15: PlateGeometry(rows=3, cols=5, …)}`, invariant `GEOMETRIES[n].well_count == n` asserted at load. Makes illegal states unrepresentable; a future 24-well = one registry entry, zero code changes. Assumption: one canonical layout per well count.
- [ ] **`geometry()` accessor** (`aq_lib/geometry.py`): reads ONLY `device_identity.json` (`{"wells": 15}`), validates `wells ∈ GEOMETRIES` (halt+log on unknown), returns the cached logical `PlateGeometry`. Zero `host_config` dependency. Storage of the well count = the immutable `device_identity.json` (§1b) — RESOLVED.
- [ ] **Physical mapping stays in the motor**: `read_plan(geo)` emits LOGICAL stops ("col 3, row B"); the motor translates each to steps via its existing `host_config` positions (unchanged). **Consistency assert** at motor load: `len(config.axis.positions) == geo.cols + geo.sensor_gap` — a 15-well unit with a 6-position host_config fails loud instead of misbehaving. (One assert, no new file, no calibration migration.)
- [ ] **Unified plan generator** (subsumes `optics_read_plan.OPTICS_READ_PLAN` + `optics_read_tasks`): `read_plan(geo)` yields the task stream for one pass — `for r in range(geo.rows): drawer_to(row); for stop: goto_position; capture(dyes_at_stop)`. SENTRI (`rows=1`) yields byte-identical today's 6-stop sweep; Mk II (`rows=3`) interleaves drawer moves. **The entire new control flow in `state_run_assay.py` is ONE new task case (`drawer_to` → `drawer.move_abs`)** — not an `if well_15`. `READS_PER_CYCLE` stays derived (`× geo.rows`).
- [ ] This **deletes the PDF's `well_15` "pad the row with a 0 to mimic 5 wells" hack** — padding only existed because they forced 4-well to pretend to be 15-well; with rows×cols both are first-class.
- [ ] Keep **4-well working unchanged**: absent `device_identity.json` ⇒ default `wells: 4`.
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

> **DECISION (2026-09-29, grilled) — immutable well-count file, deploy-written, NO acorn-ca.** Resolved design (supersedes the strap/EEPROM and the cert-binding framing above):
> - **Rejected:** GPIO strap / EEPROM (no physical add); inferring from the board (**"Mk II board ⇒ 3×5 plate" is NOT safe**); binding into the Device Certificate (**explicitly NOT attached to `acorn-ca`** — the model record is fully independent of the cert/enroll/renew path).
> - **The record:** `/opt/aquila/config/device_identity.json` = `{ "wells": 15, "schema": 1, "provisioned_utc": "…" }`. Value is the **well count `4` or `15`** (integer) — self-describing, matches how the units are talked about. It only *names* the geometry; the geometry data lives in the `aq_lib` code registry keyed by well count (`GEOMETRIES[15] → PlateGeometry(rows=3, cols=5, …)`), with the invariant `GEOMETRIES[n].well_count == n`.
> - **Assumption:** one canonical layout per well count (4→1×4, 15→3×5). Revisit only if a same-count/different-layout build ever appears.
> - **Written by the Greengrass deploy script**, host-side as root, **write-once**: `if [ ! -e ]` guard → write → `chattr +i` (immutable). A separate filename from `host_config.json`/`device.env` (both deploy-regenerated), so regeneration never touches it; the immutable bit blocks stray scripts/OTA/fat-finger edits.
> - **Read by `aq_lib.geometry()`** (container-side, plain file read via the `/opt/aquila/config` bind-mount — host sets the immutable bit, container only reads, so no container capability needed). Maps `wells` → `PlateGeometry`. **Input validation only, NO hardware cross-check** (decision 2026-09-29): unknown well count (typo/malformed) → halt+log; otherwise trust the flag. A valid-but-wrong flag (15 on a 4-well unit) is NOT software-caught → motor misbehaves on first run; backstop is careful provisioning + one-command re-provision. Removed the ADC-ID/homing check to drop the hardware + calibration dependency.
> - **Recovery (bench):** `sudo chattr -i … && sudo rm …` → re-provision with the correct well count. Deliberate, one command — hard to change, but recoverable.
> - **Lifecycle:** survives OTA/container swap (persistent volume); a full SD reimage wipes it → re-provision (a reimage is a re-birth). Deploy script must not `rm -rf` the config dir (immutable file would error).
> - See §26 Phase A. Candidate ADR (hard-to-reverse, trade-off-driven: immutable file chosen over OTP-permanence and over cert-binding).

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

Layout **will visually break at 15** (fixed 4-col grid). Best fix: replace the 3 hand-authored 4-tube HTML blocks with a JS render-loop driven by well count, and switch the grid to `auto-fit`. **Full GUI redesign (3×5 plate grid, `1A–5C` labels, tap→larger edit panel, controls marking) is in §25.**
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

- [x] **Model identity — RESOLVED (2026-09-29): declared immutable well-count file, NO hardware self-detect. See §1b + §26 Phase A.** (The self-detect exploration below is superseded — the well count is a trusted provisioned flag, not inferred from ADC-ID/homing.) Original notes kept for context:
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
- [ ] **2 — hardcoded pigpiod `172.18.0.1:8888` / motion GPIO backend:** RESOLVED — see **§19e**. Fleet is Pi 4B, so **keep pigpio** (best DMA timing there) and fix only the deployment: `pigpiod -l` in-container (localhost), client → `localhost`, `pigpio` added to the image, host pigpiod disabled. lgpio = Pi-5/fallback; TMC5160 = respin.
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

### 19e. Motion GPIO backend — DECISION: pigpio on Pi 4B, deployment fixed

**What the real problem is (and isn't).** The original inaccuracy was **software-timed pulsing on a non-realtime OS** (`RPi.GPIO` + `time.sleep()` at the mercy of the Linux scheduler) — NOT the container. That jitter is identical in a container or bare-metal. The container boundary is an **artifact of the pigpio fix**: DMA needs privileged `/dev/mem`, which is awkward in-container, so `pigpiod` runs on the host and the container reaches it over a socket.

**Where the container boundary genuinely DOES hurt accuracy (the subtle part):**
- Fast move `move_wo_home_flag` uses `wave_chain`: the whole waveform is uploaded once and the host's **DMA clocks every pulse precisely** — the network hop carries one "play this" command, so per-pulse timing is DMA-accurate regardless of where the client runs. Location is irrelevant to accuracy here.
- **Homing move `move_w_home_flag` can't pre-build a wave** (it polls the home flag every step), so it does a `pi.write()` **per step** — each a **network round-trip to the host daemon**. That per-step socket latency is a real timing/speed penalty on the homing path. Running in-process removes it.

So accuracy depends on the **timing method**, not on where the code runs. An in-container backend can be fully accurate if its timing mechanism is good.

**Library choice — settled by the hardware: the fleet runs Raspberry Pi 4B.** (2026-09-29.)

**What online reviews / the library authors actually say (sourced):**
- **`RPi.GPIO`** — worst for steppers: software `time.sleep()` timing, forum reports of *missed pulses* and *runaway* motion. No hardware waveforms. (Why the team already left it.)
- **`pigpio` `wave_chain`** — the community **gold standard** for stepper timing: **DMA, zero CPU, the hardware counts the pulses**, so OS scheduling can't jitter it. **Works on Pi ≤4 (i.e. our 4B). Does NOT work on Pi 5** (RP1 chip).
- **`lgpio` `tx_wave`** — per the author's own docs (`joan2937/lg`) this is a **"software timed wave"**, explicitly *"not 100% precise… will jitter"*. It is the *only* option on Pi 5, but on Pi 4B it is a **timing downgrade** vs pigpio's DMA. (Note: the `rpi-lgpio` RPi.GPIO-compat shim is software-PWM and twitches — do not confuse with native lgpio.)

**Timing ranking:** `pigpio DMA wave_chain` **>** `lgpio tx_wave (software)` **>** `RPi.GPIO`.

### DECISION (Pi 4B): keep pigpio, fix only the DEPLOYMENT
On Pi 4B, pigpio's DMA is the best timing available and we already have the wave code (the ramp file). The library was never the problem — the **deployment** was (daemon over TCP to the docker-gateway `172.18.0.1`, an unauthenticated root daemon reachable by other containers / LAN / tailnet — §19e security note above). Fix that without touching the motion code:

1. **Run `pigpiod` INSIDE the `aquila-app` container** (already `privileged` + mounts `/dev/gpiomem`, so it can host the DMA daemon) — not on the host.
2. **Bind localhost only:** start `pigpiod -l` (refuses non-loopback connections → closes the network exposure).
3. **Client → localhost:** `motor_class.py` `pigpio.pi()` (drop the hardcoded `"172.18.0.1", 8888`).
4. **Start pigpiod before the app** in `entrypoint.sh`, and wait until ready:
   `pigpiod -l; until pigs t >/dev/null 2>&1; do sleep 0.1; done; exec "$@"`
5. **Disable host pigpiod** (`systemctl disable --now pigpiod`) — only ONE pigpiod may run (it grabs the DMA channels); two instances conflict.
6. **Add `pigpio` to the image:** `apt-get install -y pigpio` in `Dockerfile.api` (the `python:3.11-slim-bookworm` base doesn't ship the daemon).

**Result:** best-in-class DMA timing kept; no gateway IP; no network-reachable root daemon; calibration one-shots (`compose run --rm app …`) bring up their own localhost pigpiod.

**Gotchas to verify on the bench (Phase C):**
- **DMA-channel contention with SPI:** the ADC uses `spidev` (DMA) and pigpio uses DMA — a clash can corrupt either. pigpiod can pick channels (`-d`/`-e`). **Test optics (SPI) + motor (pigpio) running simultaneously.** Most likely thing to bite.
- **`privileged` stays** (pre-existing, needed for `/dev/gpiomem`/SPI/I²C/DMA). A later hardening pass could try `--device` + `SYS_RAWIO`; don't couple it to this.

### Not chosen (and why)
| Option | Verdict on Pi 4B |
|---|---|
| **lgpio (in-process)** | **Fallback / Pi-5-migration only.** Cleaner deploy (no daemon, `--device /dev/gpiochip0`, no `/dev/mem`), but `tx_wave` is **software-timed → worse jitter** than pigpio DMA on 4B, so not worth the timing regression here. Becomes mandatory if the fleet ever moves to Pi 5 (pigpio is dead there). Base-image caveat: `lgpio` doesn't `pip`/`apt` cleanly on `python:3.11-slim`. |
| **Motion IC / MCU (TMC5160)** | **Respin destination.** Hardware ramp/step generation + StallGuard (could replace the homing-error QC hack, §5). Best long-term, but board + firmware scope — not this effort. |

**Tasks (Phase C):**
- [ ] `pigpiod -l` in `entrypoint.sh` (start + readiness wait) before the app CMD.
- [ ] `motor_class.py`: `pigpio.pi()` → localhost; remove the hardcoded `172.18.0.1`.
- [ ] `Dockerfile.api`: `apt-get install -y pigpio`.
- [ ] Disable host pigpiod in setup scripts.
- [ ] **Bench test:** SPI (optics) + pigpio (motor) DMA coexistence, no corruption.
- [ ] lgpio/TMC5160 recorded as fallback/respin only — NOT on the critical path.

**Sources:** RPi forums (PIGPIO stepper control t=289203, t=151592; Understanding PIGPIO t=294804; Pi5 hardware-timed wave p=2321568), `joan2937/lg` lgpio.h / tx_wave example ("software timed wave"), gpiozero Docker Pi5 discussion #1117, RPi-GPIO-in-docker-without-privileged forum t=374456.

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

### 21f. Decisions locked (2026-10-05) — dual-ADC `both` ground truth + padding-removal split

Ground truth confirmed (resolves the Risk-B unknowns from ADR-023 for 15-well):
- **15-well hardware is dual-ADC; the `both` capture is SIMULTANEOUS** (both ADCs sample the same instant).
- **Tube mapping is verified:** sensor gap = **2 carriage stops** (= 1 tube physically between the ROX and FAM photodiodes); FAM column = ROX column − 2. This confirms the capture-side `sensor_gap = 2` and makes `aq_curve/curve.py`'s `dpos = ±1` (offset of 1) the **stale half** of the §4 latent inconsistency — fix it to gap = 2 on the analysis side.
- **Overhang (§21c):** `read_plan(geo)` already marks ROX-/FAM-valid stops via its per-stop `dyes` tuple; the writer must select real-tube samples from that, not the `rox_well_one`/`fam_well_one` index math.

Samples-per-half-flash + the padding-removal split (resolves §21a reshape + the §21d format question):
- **15-well writes the honest 7 samples/half-flash** (fast-settling); **do NOT pad 7→10**. 4-well stays 10 (separate path, byte-identical).
- **Split across the device↔analysis seam:**
  - **Device — `aq_lib/adc_class.py` (remove padding):** drop the `10 − blink_num` pad, the `i%40`/`i+20` fake-3rd-blink, and the `%20`/`%10` FAM-swap literals; drive rows-per-capture from one samples-per-half-flash value instead of the hardcoded `10/20/40/60`. Write all N tubes (fixes §21a) selecting valid samples from the plan's per-stop dyes (fixes §21c).
  - **Analysis — BOTH `aq_curve` (on-device Cq, `curve.py`/`results_to_json`) AND `acorn-analytics` (cloud):** augment both to parse the unpadded 7-sample 15-well layout and stamp/read an explicit 15-well **tube id** (§21d); regenerate the ADR-0007 golden fixture + expected hash for the new format.
- **Completeness constant moves with it:** `SAMPLES_PER_BLINK = 60` (`aquila_web/optics_readings.py:15`) must derive per mode/geometry (like the new `reads_per_cycle(geo)`), feeding `expected_lines`/`complete`.

Still OPEN (format specifics needed before authoring the full contract):
- [ ] **Blinks per capture for 15-well:** keep a synthesized 3rd blink (3 blinks) or write the real 2? Sets rows-per-capture = `blinks × 2 × 7`.
- [ ] **Tube-id label format (§21d):** `A1…C5` vs flat `1–15` on the optics line.
- [ ] Resulting `SAMPLES_PER_BLINK`/rows-per-capture value for 15-well, from the two above.

**Summary:** capture works; **write-out (21a) is the blocker**, **calibration (21b) makes the current stops physically wrong**, and **overhang (21c) is implicit tech debt.** Ground truth is now in (§21f); the remaining work is the padding-removal split (device + both analysis tools) once the two open format specifics are set.

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

## 23. Plotting & analysis per tube — what stays the same / changes

**Headline: the per-tube qPCR math does NOT change.** `results_to_json` runs the same pipeline once per well; everything inside `resolve_status`/`resolve_cq` operates on **one tube's curve in isolation**. Verified: **no cross-tube logic** (nothing reads neighboring wells), and `baseline_slice = (5, 15)` is cycle-based → **well-count-independent**. So for 15 wells you run the identical math 15×.

```python
_WELLS = [1, 2, 3, 4]                                          # curve.py:341 — the only "4"
fam_status = {w: resolve_status(0, "fam", w) for w in _WELLS}
```

### 23a. UNCHANGED — the qPCR math
`baseline` fit, `get_threshold`, `compute_cq`, the `evaluate_curve` detection cascade, spike-only rejection, ROX-unavailable/suppression, well-verdict precedence — all per-curve, untouched by well count.

### 23b. MECHANICAL — scaling (loop/list bumps)
- [ ] `_WELLS = [1,2,3,4]` (`curve.py:341`) → N from geometry; drives the results dict.
- [ ] `plot_utils.py:66` `range(4)` → N.
- [ ] results dict (channel `"1"`/`"2"` × well) simply grows to N keys — downstream event/UI consume more entries.
- [ ] per-well `thresholds` / `cross_talk_matrix` → N (§21e; currently dead path).

### 23c. REAL WORK — not just a loop bump
- [ ] **Tube identity from the file (blocked on §21d):** `extract_data`'s `position = well + dpos` must locate each of 15 tubes; needs the 15-well optics-file tube id. Without it, tubes 5–15 can't be found.
- [ ] **Plot layout redesign:** `generate_optics_plot` draws **all wells on ONE axis** (`fig, ax = plt.subplots`) — 8 lines today, **30 lines at 15 wells = unreadable**. Move to a **3×5 small-multiples grid** (one mini-plot per tube, laid out like the physical plate). Also update the device History/results UI plot (§11).

### 23d. NEW DESIGN DECISION — control-aware run QC
`aq_curve` is currently **control-agnostic** — every tube is analyzed independently, with no notion of a positive control (PC) or no-template control (NTC). But the **entire rationale for 15 wells** (PDF) is dedicated PC + NTC without eating 50% of capacity. So we likely want a **control-aware QC layer**:
- NTC must be **Not Detected**, PC must be **Detected** — else flag/invalidate the run.
- [ ] **Decide:** where are control positions defined — per-protocol? a per-plate map? Does a failed control **invalidate the whole run** or just annotate it? Does this QC live **on-device** (`aq_curve`) or in the **app/cloud**?
- This is the **only analysis item that's a new capability**, not a scaling chore — and it shapes the plot layout (mark control tubes) and the event/results schema. Recommend tackling this design first.

Cross-ref: §21d (tube identity in file), §21e (per-well calibration arrays), §11 (device UI plot), §8 (curve analysis), §22 (lit-only math).

## 24. Open verification items by category (mechanisms exist — confirm they work)

The mechanisms mostly exist; these are the under-examined *verification* and *un-ported* gaps per category.

**Motor**
- [ ] Backend decision undecided (§19e A/B/C) — run the lgpio timing benchmark.
- [ ] Homing-error → optics-QC coupling (§5) — confirm stall telemetry is actually wired to disqualify samples in the new motion.
- [ ] Scan-time ≤18 s at 15 wells — never measured with real motion.
- [ ] 5-well axis calibration (§21b); degenerate `move_wo_home_flag(0)` on repeat drawer gotos.

**Recording data**
- [ ] 🔴 **`run_complete` EVENT is still 4-well** — `aquila_web/main.py` `_build_results = range(1,5)`, `_normalize_tube_names` **hard-capped at 4**, tube_names keyed 1–4 (§10). Even after the optics file records 15 tubes, the event that syncs to the cloud is 4-well. **Least-examined gap; squarely in "recording data."**
- [ ] Optics file writer + format (§21a/§21d); deferred-write/cancel (§7); dark cleanup (§22).
- [ ] `call_evidence` / `optics_readings` events scale to 15 wells.

**New ADC**
- [ ] Self-detect/validate not built (§1b); RDY 7-vs-20 policy (§19c #9); CS-toggle robustness (#6).
- [ ] Temperature acquisition on dual-ADC verified (§9); single-ADC backward-compat verified.

---

## 25. Device GUI (kiosk) redesign for 15 wells

**Constraint:** the device is a **768×1024 portrait touch kiosk**, 44px minimum touch targets (viewport `width=768,height=1024`; kiosk notes in `styles.css`). **Current UI:** each tube is a `.results-tube` = FAM/ROX status dot + a text input (`"Tube 1"`…), **4 hand-authored blocks** in a `repeat(4,…)` row, copy-pasted across `run.html` / `ready.html` / `complete.html` + the History views (`history.js`, `history_detail.js`). Code-location checklist is in §11; this section is the design.

### 25a. Layout — 3×5 grid mirroring the physical plate
The results grid becomes a **3×5 grid laid out to match how tubes are physically loaded** (so "back-left tube" = "back-left on screen"). 5 columns across 768px ≈ ~150px/cell; 3 rows fit within 1024px without scrolling.

```
         1      2      3      4      5
       ┌─────────────────────────────────┐
   A   │ 1A     2A     3A     4A     5A   │
       │ ◐      ◐      ◐      ◐      ◐    │   row A (drawer -1)
       │ name   name   name   name   name│
   B   │ 1B     2B     3B     4B     5B   │
       │ ◐      ◐      ◐      ◐      ◐    │   row B (drawer 0)
       │ name   name   name   name   name│
   C   │ 1C     2C     3C     4C     5C   │
       │ ◐      ◐      ◐      ◐      ◐    │   row C (drawer +1)
       │ name   name   name   PC     NTC │   ← controls marked
       └─────────────────────────────────┘
```

### 25b. Labeling scheme (operator-facing) — `1A` … `5C`
- **Columns numbered 1–5** across the top; **rows lettered A–C** down the side.
- Each tube is labeled **column-then-row**: **`1A`** (col 1, row A) … **`5C`** (col 5, row C). Operators read/press these.
- ⚠️ **Canonicalize:** the motion/optics sections (§20, §21d) used `A1–C5` (row-then-column) as internal shorthand. **Pick ONE scheme and use it everywhere** — recommend adopting the operator's `1A–5C` (col-then-row) as canonical so UI, file tube-ids, and docs agree. [Decision needed.]

### 25c. Naming UX — tap a tube → LARGER edit panel
15 tiny inline inputs on a touch kiosk is painful. Instead: the grid shows **compact labels**, and **tapping a tube opens a larger edit panel/tab** — a big, touch-friendly field + on-screen keyboard to rename just that one tube. Avoids 15 keyboard sessions crammed into 150px cells.

```
tap  3B  →   ┌──────────────────────────────┐
             │  Edit  3B                     │
             │  ┌────────────────────────┐   │
             │  │ Sample name…           │   │  ← large field
             │  └────────────────────────┘   │
             │  [   on-screen keyboard    ]   │
             │  [ Cancel ]          [ Save ]  │
             └──────────────────────────────┘
```
- Controls (PC/NTC) can **auto-label** so operators only name samples (ties §23d).
- Optional: plate templates / batch naming so 15 names aren't retyped every run.

### 25d. Status dots
FAM/ROX half-dot per tube, live over WebSocket during the run. The existing `querySelectorAll(".results-tube")` update loops in `script.js` **adapt automatically** once N tubes render — no per-dot rewrite.

### 25e. Enabling refactor — render dynamically (do this FIRST)
Replace the 4 hand-authored `.results-tube` blocks (×3 files) with a **JS loop that renders N tubes from geometry**, and change CSS `repeat(4,…)` → a geometry-driven grid. One template → 4-well *or* 15-well (§11/§1a). This is the foundation everything else builds on; low-risk.

### 25f. Controls marking + counts
Mark PC/NTC visually (badge/color) and **exclude them from the Detected/Inconclusive counts** (which shift from `/4` to `/(sample count)`). Depends on the §23d control-aware decision.

### 25g. History views
`history_detail.js` builds a per-tube Cq table → **N rows** instead of 4; give it the same dynamic-render treatment; may need vertical scroll.

### 25h. Optional (v1?) — live scan indicator
Since the serpentine visits tubes in a known order (§20), the UI could **highlight the currently-scanning tube** (1A→2A→…→5A→5B→…). New, optional, satisfying on a kiosk.

### Decisions to make
- **Grid orientation:** which physical corner is `1A` (must match the loading orientation).
- **Labeling:** adopt `1A–5C` everywhere and reconcile the internal `A1–C5` shorthand (§25b).
- **Naming UX:** tap → larger edit panel (chosen); all 15 named vs. controls auto-named.
- **Live scan highlight:** build in v1 or defer.

**Sequencing:** dynamic-render refactor (25e) → larger naming panel (25c) → controls marking (25f, once §23d lands) → optional scan indicator (25h).

---

## 26. IMPLEMENTATION PLAN (target: 3.5 weeks)

**Timeline:** ~18 working days. **MVP milestone (~day 10 / end of week 2):** *motor moves correctly through the 3×5 serpentine AND the optics file records all 15 tubes correctly.* Everything after that (parse → analysis → GUI) builds on that working model. GUI (Phase G) and control-QC (Phase F) are the compressible/at-risk items if the schedule slips.

**Two non-negotiable guardrails (apply to every phase):**
1. **Reactive, never hardcoded.** No `NUM_WELLS`-as-literal, no `[1,2,3,4]`, no `if well_15 / elif updated4`, no int-vs-tuple type-sniffing. Everything derives from one `PlateGeometry`. A new well count = new geometry data, **zero code change**.
2. **4-well never regresses.** SENTRI runs through the *same* code as the degenerate `rows=1` geometry; verify byte-identical optics + identical calls at each phase.

**Critical path:** A → B → C/D → E → F. G (GUI) and the motor bench work in C can parallelize if a second dev is available.

---

### Phase A — Configuration & hardware identity (Days 1–2)
*Your priority #1: the model is a **declared value written at device birth**, in the hardware code layer — NOT a physical pin, NOT a surface/mutable config file. (Decision 2026-09-28: "Mk II board ⇒ 3×5 plate" is NOT a safe assumption, so the model is declared, not inferred from the board.)*

**Goal:** `aq_lib.geometry() → PlateGeometry`, resolved from the immutable birth-written well-count record. Input validation only (unknown count → halt+log); no hardware cross-check.

**Model-identity design — immutable well-count file (grilled 2026-09-29; full detail in §1b):**
- **The record:** `/opt/aquila/config/device_identity.json` = `{ "wells": 15, "schema": 1, "provisioned_utc": "…" }`. Value = **well count `4`/`15`** (int). Names the geometry; geometry data is in the `aq_lib` registry keyed by well count (`GEOMETRIES[n].well_count == n` invariant).
- **Written by the Greengrass deploy script**, host-side, **write-once + `chattr +i`** (immutable). Separate file from `host_config.json`/`device.env`. NOT attached to `acorn-ca`/cert.
- **Read by `aq_lib.geometry()`** (plain read via bind-mount) → geometry. Input validation only (unknown well count → halt+log); NO hardware cross-check — trusted flag.
- **Recovery:** `chattr -i` + re-provision. Survives OTA; SD reimage → re-provision.

**Tasks:**
- `PlateGeometry` value object (§1a) — **purely logical**: `rows, cols, sensor_gap, channels`; `well_count`/`tube_ids`/scan-order derived. NO measured steps (those stay in host_config). Immutable.
- `GEOMETRIES` registry in `aq_lib` keyed by well count: `4` = 1×4, `15` = 3×5; assert `well_count == n` at load.
- Write the identity file (write-once + `chattr +i`) in the **Greengrass deploy script**.
- `aq_lib/geometry.py` `geometry()`: read `device_identity.json` → `wells` → cached logical `PlateGeometry`; validate `wells ∈ GEOMETRIES` (halt+log); reads NOTHING from host_config.
- Motor keeps reading measured positions from `host_config` (unchanged); add the consistency assert `len(config.axis.positions) == geo.cols + geo.sensor_gap`.
- Wire `geometry()` as the single source of truth for shape everywhere.

**Problems:** deploy script must write the identity file write-once + `chattr +i` and not later `rm -rf` the config dir; a valid-but-wrong well count is a trusted-flag risk (not software-caught — accepted trade). **Board ≠ plate** (§1b) reinforces declaring the well count rather than inferring it.

**Exit:** well count comes from the immutable `device_identity.json` (not host_config); `aq_lib` resolves geometry from it; an unknown well count fails loud; changing it requires `chattr -i` + re-provision.

---

### Phase B — Reactive foundation + remediate the engineers' code (Days 3–6)
*Your priorities #2 (reactive refactor) and #3 (fix Nick/Jake's changes) — done together, because making their code reactive IS the remediation.*

**Goal:** one geometry-driven code path; all §4 literals and §19 structural debt gone.

**Tasks:**
- **Unified `read_plan(geo)`** (§1a) replacing `OPTICS_READ_PLAN` + the `if well_15/elif updated4` branch in `optics_read_tasks`. Generates the serpentine 3×5 (or 1×4) as data. `READS_PER_CYCLE` derived (kill the hardcoded `21`, §21a/#13).
- **Executor: one `drawer_to` task type** (§19b#3) — delete the int-vs-tuple sniffing in `Axis`/`Drawer.goto_position`; positions are always structured coords from geometry.
- Replace every literal (§4): `curve.py:341 _WELLS`, `notebook_evaluator` well_maps, `plot_utils:66 range(4)`, `motor_class` `range(6)` + `append(0)` pad, `main.py _build_results range(1,5)` / `_normalize_tube_names` cap-4. Delete dead `DEFAULT_CURVE_WELLS`.
- **Reconcile the sensor-offset bug** (§4): unify `curve.py` `dpos=±1` with the 2-position gap into one `geo.sensor_gap`.
- Fold in the cheap §19d remediations while here: collapse redundant flags into the model (#14), derive constants (#13).

**Problems:** keep 4-well byte-identical during the refactor (regression-test each literal removal); the sensor-offset unification is subtle — test against a known 4-well optics file.

**Exit:** 4-well runs unchanged through the new geometry path; no `well_15`/`elif`/type-sniff remain; a 15-well geometry produces the full 21-stop serpentine plan.

---

### Phase C — Motor: 15-well motion working, calibrated, tested (Days 5–8, can start once B's read_plan lands)
*Your priority #4a.*

**Goal:** the instrument physically steps the 3×5 serpentine and homes reliably within the scan budget.

**Tasks:**
- Drive motion from `read_plan(geo)`: axis across columns, drawer between the 3 rows.
- **Motion backend (§19e):** ship **A (pigpiod in-container → `localhost`)** now for the working model — removes the hardcoded `172.18.0.1` network hop, keeps the proven waveform code. Run the **lgpio (B) timing benchmark** in parallel (using existing `steps_to_flag`/`residual` logging) to decide the durable backend; keep C (motion IC) for the respin.
- **Real 5-well axis calibration (§21b):** measure the 7 stops/row on the bench; put them in `geo.axis_stops`; remove `append(0)`; validate `len(axis_stops)==cols+sensor_gap`.
- Drawer 3-row moves (±9 mm / 320 steps) + homing; handle the degenerate `move_wo_home_flag(0)` on repeat gotos.
- **Homing-error → QC hook (§5):** log per-move stall telemetry so downstream can disqualify samples.
- **Measure scan time** at 15 wells; confirm ≤18 s (§ scan budget).

**Problems:** physical calibration needs bench + the real 3×5 hardware; scan-time budget is tight; container pigpiod needs elevated device access (fleet policy — confirm).

**Exit:** a dry 15-well run steps every tube in serpentine order, homes clean, scan-time ≤18 s.

---

### Phase D — Optics file: record all 15 tubes correctly + define the format (Days 8–10) → **MVP**
*Your priority #4b. This + Phase C = the working model.*

**Goal:** a 15-well run writes an optics file with all 15 tubes, each unambiguously identified.

**Tasks:**
- **Rewrite the writer (§21a):** replace the 4-well `for k in range(6)` in `out_data` with an N-well emit driven by geometry — the current code drops 11 of 15 tubes. Prefer a **native dual-ADC writer** (#12) over padding to the legacy shape.
- **Define + stamp the 15-well file format (§21d):** each line carries a real **tube id (`1A`–`5C`, per §25b)** — add the row/drawer dimension the current `position` column lacks.
- **Fix deferred-write on cancel/crash (§7, RISK C):** flush incrementally or via a `finally`/signal handler so an interrupted run still writes partial data.
- Overhang handling (§21c): mark ROX/FAM-valid stops in the plan so the writer selects real-tube samples by construction.
- **Dark samples:** given §22 (analysis ignores them), decide now — simplest is stop *writing* the LED-off block to save scan time/space, or keep logging but stop the `y0` averaging. (Confirm no other consumer first — §22 checklist.)

**Problems:** format design must serve both the writer and the parser (Phase E); native-vs-legacy-shape decision; cancel-flush correctness.

**Exit / MVP:** run a 15-well profile → motor sweeps correctly → optics file contains 15 correctly-labelled tubes with sane values; canceling mid-run still writes what was captured.

---

### Phase E — Parse the optics file (Days 11–12)
*Your priority #5.*

**Goal:** `extract_data` reads the new 15-well format and locates every tube.

**Tasks:**
- Update `extract_data` (`curve.py`) to read the tube id (§23c) instead of the 4-well `position = well + dpos` math; drive tube enumeration from geometry.
- Golden-file test: the parser round-trips the writer's output; a 4-well file still parses identically.

**Problems:** parser/writer format lock-step; keep the 4-well path working.

**Exit:** parsing a 15-well optics file yields 15 per-tube, per-dye curves.

---

### Phase F — Analysis on 15-well + control QC + event path (Days 12–15)
*Your priority #6.*

**Goal:** calls, Cq, and the synced event all correct for 15 tubes.

**Tasks:**
- Scale the per-tube loop (§23b): `_WELLS`→N, results dict, `plot range`→N. **Per-tube qPCR math is unchanged (§23a)** — no touching baseline/threshold/Cq.
- Per-well calibration arrays → N (§21e) if reactivated.
- **`run_complete` EVENT (§24, §10):** `main.py _build_results`/`_normalize_tube_names`/tube_names → N, so the cloud receives 15-well data. (Warehouse already scales — §13.)
- **NEW: control-aware QC (§23d)** — define control positions (per-protocol / plate map), enforce NTC=Not-Detected & PC=Detected, decide run-invalidate vs annotate, on-device vs app. *This is the one genuine new feature — timebox it; if it slips, ship per-tube calls first and layer control-QC after.*

**Problems:** control-QC is a design decision, not a port — get the "where are controls defined" answer early; event/tube_names cap-4 is the least-examined gap.

**Exit:** a 15-well run produces 15×2 calls + Cq, a valid `run_complete` event, and (if in scope) control-based run QC.

---

### Phase G — GUI for 15-well (Days 14–17, parallelizable)
*Your priority #7. Full design in §25.*

**Goal:** the kiosk shows and names 15 tubes usably on 768×1024.

**Tasks:**
- **Dynamic-render refactor first (§25e):** replace the 4 hand-authored `.results-tube` blocks (×3 files) with a JS loop from geometry; CSS `repeat(4)` → geometry-driven grid.
- **3×5 plate-mirroring grid** (§25a) with **`1A`–`5C` labels** (§25b — and canonicalize vs the internal `A1–C5`).
- **Tap-a-tube → larger edit panel** for naming (§25c); controls auto-labelled.
- Status dots scale (§25d); controls marking + count exclusion (§25f); history table → N rows (§25g); optional live scan indicator (§25h).

**Problems:** touch layout at 150px cells; naming UX; keep 4-well rendering identical.

**Exit:** operator can load, name, run, and read 15 tubes on the kiosk; 4-well UI unchanged.

---

### Phase H — Integration, 4-well regression, buffer (Days 17–18)
- End-to-end: 15-well run → motor → optics file → parse → analysis → event → GUI → history.
- Full 4-well regression (same code, `rows=1`) — byte-identical optics + identical calls.
- Schedule buffer for slippage (calibration, control-QC, GUI most likely).

---

### Risk register (top items)
| Risk | Phase | Mitigation |
|---|---|---|
| Identity file not written by deploy script | A | Add write-once + `chattr +i` to the Greengrass deploy script |
| Well count mis-provisioned (valid-but-wrong flag) | A | Accepted trade (no hardware check); careful once-at-build provisioning + one-command re-provision |
| 5-well physical calibration slips | C | Bench early; it gates D's tube ids |
| Scan-time > 18 s at 15 wells | C | Measure early; lgpio/backend + fewer flashes are levers |
| Optics format churn (writer↔parser) | D/E | Freeze the §21d format before coding either |
| Control-QC is new design, not a port | F | Timebox; ship per-tube calls first |
| 3.5 wks is tight for GUI + control-QC | F/G | Both are the declared compressible items |

### Definition of done
- 4-well and 15-well both run through **one** geometry-driven path; no hardcoded counts or `elif` mode branches anywhere.
- 15-well: correct serpentine motion, correct 15-tube optics file, correct parse/analysis/Cq, correct synced event, usable kiosk UI.
- Well count resolved from the immutable `device_identity.json`; unknown count fails loud (no hardware cross-check — trusted flag).

## 27. Colleague's 2026-09-30 source files — review, locked decisions, and re-scope

**Tracking issue:** [#517](https://github.com/AcornGenetics/aquilla-main/issues/517). This section is the written-up review the issue references.

### 27.0 Source + constraint
A colleague's newer Aquila device files (authoritative set, dated **2026-09-30 17:46** in `~/Downloads`): `adc_class (1).py`, `motor_class (2).py`, `thermal_parser.py`, `utils.py`. (The `~/Downloads/aquilla-main/` copies are stale March baselines — ignore.)

**Hard constraint — cherry-pick only, never wholesale-replace:** the colleague's `motor_class` is **pre-geometry** (hardcodes positions + a 320-step row pitch, drops the `geometry()` imports). Wholesale-replacing it would destroy the Slice 1–5 geometry spine. Already on this branch (not new from him): `home()`+`emit_homing_sample`, `count_optics_passes()`.

### 27.1 Locked decisions (confirmed 2026-10-01) — what to take / adapt / skip

| Slice | File | Decision |
|---|---|---|
| **1** | `utils.py` | **Take** the `aquila_logger` logging block (prereq so ADC-health logs reach disk). Trim its dangling `adc_class_12well.py` reference (no such file here). |
| **2** | `thermal_parser.py` | **Take** 2 bug fixes: top-level `duration = 0` init (fixes `UnboundLocalError` when optics is the first step of a repeat block) + `if len(args)==6` guard on the carry-forward unpack (fixes `ValueError` when a `ramp_rate`/`pcr_fanoff` step sits in a repeat block). **Skip** the abandoned setpoint step-limiting (`MAX_SETPOINT_STEP=0`; author measured no effect). |
| **3** | `adc_class.py` (Tier 1) | **Take all** — `ADC_RDY_*` constants + RDY polling before each read, `_check_frame` stale-frame detection, health counters (`n_retries`/`n_failed_reads`/`n_stale_frames`/`n_unrepairable`, incl. the `n_unrepairable` init fix), `read_ambient_temp` RDY + `ROX_enabled=True` fix. Diagnostics only, no read-path impact. |
| **4** | `adc_class.py` (Tier 2) | **Taken (`e7510c6`):** `clean_up` `raise e`→`raise` (a latent `NameError` in our branch today) and the **half-period-aware `-123` repair** (only interpolates within the same LED half-period → never averages a good sample with `-123` into a fake ≈−60 mV reading; byte-identical when no `-123` present, so ADR-0007 hash contract unaffected — verified). **HELD: the single-dye `append([a,b,c])` carry-forward.** On review our single-dye path never appends to `data_both`, so there is **no latent TypeError here** (the bug was in the colleague's ancestor, not ours). Porting it changes single-dye file output on failed reads and is coupled to the Tier 3 `out_data` `data_both` reset to stay safe against mixed 3-/11-element rows — so it is NOT a self-contained Tier 2 fix. Deferred to the Variant C / Phase B (#514) bundle and re-reviewed as an output-affecting change. |
| **5** | `motor_class.py` | **Taken (`f4553e3`).** Ramp grafted onto `move_wo_home_flag` (ramp-up / cruise / ramp-down; only the cruise block uses the `//8` chain, ramp legs are standalone waves, so pulse-count + multiple-of-8 invariants hold; `finally` wave cleanup). New pure helpers `_ramp_profile`/`_ramp_pulses`/`move_time_estimate`/`_resolve_pulse_delay`; SINGLE/SCAN `motor_test`; `ramp_test` auto-tuner gated by `config.info["ramp_test"]` (inert in prod). **Method** `pulse_delay` defaults flipped to `None` (required by the tuner) but **geometry call sites keep explicit args**, so production cruise speed is unchanged — the ramp only softens start/stop; `Axis`/`Drawer` geometry `__init__`/`goto_row`/`goto_position`/`axis_stops`/`drawer_rows` untouched. **ON-DEVICE FOLLOW-UP:** subclass ramp constants (Axis `ramp_steps=16`, Drawer `40`, cruise fallbacks) are the colleague's hardware values — run `ramp_test` on a real 15-well axis + drawer and paste the recommended constants. **Flagged:** `ramp_test`/`motor_test` use the generic bench `test_positions=[320,640,960,1280]`; to tune at the real geometry distances, set `self.test_positions` from `self.positions`/`self.rows` inside the geometry `__init__` (small, otherwise-out-of-scope addition — tuner is bench-only so it doesn't block). |
| **6** | optics writer | **Variant C** — explicitly **rejected** the colleague's keep-everything incremental writer (no RAM win, restructures our 15-well read path). Instead: continuous RAW safety log during a run + mask on **ANY** stop (complete/cancel/crash); masking reads the raw back **pass-by-pass** (~2-pass bounded RAM). Build a re-mask recovery tool for leftover raw logs. |

**Verify-before-porting flags:** `print_temp`/duplicate-temp-line (we have no `print_temp` — confirm where temperature is logged first); fam `j==0` fallback — his `2.1` vs our `2.0` (confirm intent, don't silently change output).

### 27.2 Re-scope against the merged geometry spine (Slices 1–5: #506–#509, #511)
The scope above predates the geometry merge. Reconciling against the current branch:

- **Slices 1–4 are unaffected** — `utils.py`, `thermal_parser.py`, `adc_class.py` were barely touched by the geometry work; verified still-needed on the branch (`thermal_parser` still sets `duration` inside each branch with no top-level init; no `ADC_RDY`/`_check_frame`; the `-123` path is still the old non-half-period version). Port as scoped.
- **Slice 5 graft target MOVED (approach unchanged).** `motor_class` is now geometry-driven: `Axis.__init__` → `self.positions = axis_stops(config.axis, geometry())`, `Drawer` has `self.rows = drawer_rows(...)` + `goto_row()`. The ramp grafts into the `Motor` base **move methods only**; the geometry `__init__`/`goto_row`/`axis_stops`/`drawer_rows` stay untouched. **New coupling:** the `Drawer` already has hand-tuned pulse_delays (`0.00007`, "verify full travel on sn01-03") — the ramp must reconcile with/supersede these, and the on-device `ramp_test` must now be run against the real 15-well `geometry()` axis stops **and** the 3 drawer-row moves (not just the axis, and not the colleague's hardware constants).
- **Slice 6 (Variant C) now sequences AFTER Phase B (#514).** Both the `updated4` and `well_15` capture-mode flags are still live (`state_run_assay.py:54–76`), and `read_wells` still passes `updated4` (`:178`). #514 deletes those forks → one executor path, so Variant C grafts onto a single clean path instead of being redone. `out_data()`'s sole caller is the executor `quit` branch (`state_run_assay.py:154`); "mask on any stop" = wiring `clean_up`/finally on the cancel path (verify `clean_up` fires on cancel).
- **`aq_curve/notebook_evaluator.py` was DELETED** (unused; see §4 literal list) — its `positions=[2,3,4,5]`/`well_map` well-count site is now moot, one fewer to reconcile.

### 27.3 Revised order
The geometry motor path is merged but **never driven on real hardware** — so Slice 5 is the highest-leverage item (it's both a #517 deliverable and what makes the geometry motion reliable enough to bench-test).
1. **Slice 1** (logger) — prereq, trivial.
2. **Slices 2, 3, 4** (thermal_parser + ADC diagnostics/fixes) — low-risk, independent, mechanical; land to get ADC health logging before any bench run.
3. **Slice 5** (motor ramp) onto the geometry base → **bench `ramp_test` on a real 15-well device** for our axis *and* drawer-row constants. Unlocks testing the whole geometry spine.
4. **#514 (Phase B, one read path)** → **then Slice 6 (Variant C)** on the collapsed path.

### 27.4 Must-respect gotchas
- Optics output file is a **FROZEN hashed contract** (ADR-0007 / acorn-analytics#45): `aquila_web/optics_readings.py` hashes the whole file + counts rows (`SAMPLES_PER_BLINK=60`). Output must stay **byte-identical**; "ring-mask == batch-mask" is a hard unit-test gate. The RAW safety log must be a **separate** file the uploader never scans.
- `capture_blink` is shared with `scripts/tools/melt_curve.py` — raw-streaming must gate on run context so melt_curve isn't broken.
- Land as incremental `Slice N` commits (match branch style), each with tests (`unit_tests/` for pure logic: mask parity + ramp-profile math; `@pytest.mark.hardware` for pigpio/SPI). Add an ADR alongside ADR-023 for the Variant C crash-safe writer.

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
- 2026-09-28 — Added §23 (plotting & analysis: per-tube qPCR math unchanged; scaling is loop/list bumps + plot small-multiples + §21d tube identity; NEW control-aware QC design decision) and §24 (open verification items by category — incl. the still-4-well `run_complete` event).
- 2026-09-28 — Added §25 (device kiosk GUI redesign: 768×1024 portrait, 3×5 plate-mirroring grid, `1A–5C` col-row labels, tap→larger edit panel for naming, dynamic-render refactor, controls marking, history table, optional live scan indicator). Flagged the A1–C5 vs 1A–5C labeling reconciliation.
- 2026-09-28 — Added §26 IMPLEMENTATION PLAN (3.5 wks, ~18 days): Phases A(config/hardware identity) → B(reactive refactor + remediate) → C(motor) → D(optics file) = **MVP ~day 10** → E(parse) → F(analysis + control-QC + event) → G(GUI) → H(integration). Guardrails: reactive/no-hardcode, 4-well never regresses. Risk register + DoD.
- 2026-09-29 — RESOLVED §19e motion backend: fleet is **Pi 4B**, so **keep pigpio** (DMA wave_chain = best stepper timing; lgpio tx_wave is software-timed/worse on 4B, mandatory only on Pi5). Fix deployment: `pigpiod -l` in-container + client→localhost + `pigpio` in image + disable host daemon; bench-test SPI/pigpio DMA coexistence. lgpio=Pi5/fallback, TMC5160=respin. Reviews sourced. Updated §19d#2, plan Phase C.
- 2026-10-04 — Added §27 (colleague's 2026-09-30 source-file review + locked decisions, #517), reconstructing the write-up the issue references (it had never been committed). Re-scoped it against the merged geometry spine (Slices 1–5): Slices 1–4 unaffected; Slice 5 ramp graft target moved onto the geometry-driven `motor_class` (base move methods only) with `ramp_test` tuning now coupled to `geometry()` axis stops + 3 drawer rows; Slice 6 (Variant C) re-sequenced to AFTER Phase B (#514); `notebook_evaluator.py` deleted so its well-count literal site is moot.
