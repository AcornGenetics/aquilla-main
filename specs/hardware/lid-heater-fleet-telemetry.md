# Hardware Spec: Lid-Heater Fleet Telemetry

**Status:** Draft
**Author:** Claude
**Last updated:** 2026-08-19
**Subsystem:** Lid
**Source file(s):** `aq_lib/lid_heater_log.py` (new), `aq_lib/lid_heater_window.py` (new), `aq_lib/regulate.py`, `aquila_web/lid_parser.py` (new)
**GitHub issue:** #452
**Related specs:** `specs/hardware/lid-worker-instrumentation.md` (the diagnostic logging this promotes to permanent telemetry)

---

## 1. Overview

Permanent fleet telemetry for the lid heater. Today the lid is checked by hand — an
operator confirms it "parks at roughly 0.32 V and holds for 300 s" — and everything the
diagnostic instrumentation (#157) exposes lives only in on-device log files nobody reads
until something has already gone wrong. This spec makes the lid heater's behaviour a
reported fact, so degradation is visible across the fleet before it costs a run.

Two principles govern every field below.

**The device reports facts only.** No pass/fail judgement is made on the device. Every
threshold — what counts as too cold, too wobbly, too slow to climb — lives centrally in
the Warehouse's read views, so changing a limit is a SQL change, not a fleet-wide
redeploy. This mirrors the Homing Sample rule (ADR-021): the device is a dumb sampler.

**Nothing depends on converting voltage to temperature.** The lid thermistor has no
established calibration, so this spec never claims a temperature or a heating *rate*.
Where a rate would be natural it reports **checkpoint-crossing times** instead, which
need only the assumption that voltage rises as the lid heats.

### The Sample Window

The lid sensor is read about once per second. Shipping every reading is both wasteful and
useless — a single reading cannot show steadiness. Instead the device summarises a
**Sample Window** into one **Lid Heater Sample**, and emits one Sample per window for as
long as the heater worker is alive.

A Run's windows are **not** all the same length, and that is deliberate. The lid takes
roughly three minutes to climb from cold to `cutoff_voltage`, so a uniform 300 s window
would make the first Sample of every Run half climb and half settled — its `mean_voltage`
a blend of "still warming" and "at temperature", which is a number that means nothing and
reads on a chart as a cold lid. Instead:

- **The Climb Window** is the first window of a Run. It opens at worker start and closes
  the moment the lid first reaches `cutoff_voltage` — or at 300 s, whichever comes first,
  so a lid that never gets there still reports. It carries the
  [[Checkpoint Crossing]] times, and its `at_cutoff_fraction` is ~0 by construction.
  If the lid is already at or above cutoff on the very first reading (a back-to-back Run
  on a warm machine), no Climb Window is emitted at all.
- **Settled Windows** follow, fixed at 300 s each, until the worker stops. Every Sample
  states its own `window_kind`, so the two are never told apart by inference. Their
  `mean_voltage` and `at_cutoff_fraction` are clean: every one of them describes a lid
  that is supposed to be holding temperature.
- **The final window of a Run is short**, closed by the worker stopping rather than by the
  clock.

Comparability survives because every Sample carries its own `window_seconds`; anything
aggregating across Samples weights by it rather than counting rows. Lining the Samples up
is how the climb, the settle, and (across months) the degradation become visible.

---

## 2. Hardware Components

| Component | Part / Model | Interface | Notes |
|-----------|-------------|-----------|-------|
| Lid heater element | resistive heater | GPIO 21 (BCM), active HIGH | Driven by `lid_heater_worker` duty loop; unchanged by this spec |
| Lid thermistor / ADC | ADS1115 @ `0x48` | I2C (`/dev/i2c-1`) | Module-level singleton `adc` in `regulate.py`; lockless, shared by all workers |

---

## 3. Operating Parameters

| Parameter | Min | Nominal | Max | Unit |
|-----------|-----|---------|-----|------|
| Settled Window (`window_seconds`) | — | 300 | — | s |
| Climb Window (`window_seconds`) | — | until cutoff reached | 300 | s |
| Sensor read cadence | — | 1 | — | reads/s |
| Expected readings per full window | — | 300 | — | count |
| Lid ADC floor (`floor_voltage`) | — | 0.20 | — | V |
| Lid ADC cutoff (`cutoff_voltage`) | — | 0.34 | — | V |
| Healthy settled voltage | — | ~0.32 | — | V |
| Climb checkpoint offsets below cutoff | — | 0.06 / 0.04 / 0.02 / 0 | — | V |
| ADC resolution floor (1 LSB @ `pga_fs_v=4.096`) | — | 0.000125 | — | V |
| Slow-read threshold | — | 5 | — | s |
| Teardown join timeout (existing) | — | 5 | — | s |

**Safety limits:** the sampler must not alter the duty loop, must not add blocking work
inside the worker, and must not change timing inside the 5 s teardown join window.
Summarising happens on window close, off the read path. Telemetry is additive only.

The **resolution floor** is the smallest step the ADS1115 can resolve at the gain the
worker hardcodes (`pga_fs_v=4.096`, `lid_temperature.ADS1115._lsb_size`). It is a code
constant, identical on every machine, so it is documented here and deliberately **not**
carried on the Sample. It matters when reading `max_voltage − min_voltage`: a spread near 0.000125 V
is the converter's graininess, not lid wobble. Measured converter noise is not reported —
separating it from real lid movement would need repeated reads of a stable input, which
the control loop does not do.

`floor_voltage` and `cutoff_voltage` are read from `config_files/lid_heater_config.json`
and **reported on every Sample**, because machines can be configured differently and
nothing downstream may assume 0.20/0.34.

The **checkpoint ladder is derived from that machine's own cutoff**, not hardcoded:
`[cutoff − 0.06, cutoff − 0.04, cutoff − 0.02, cutoff]`, rounded to 4 decimals, dropping any
checkpoint at or below `floor_voltage` rather than clamping it. At the configured 0.34 V this
is exactly 0.28 / 0.30 / 0.32 / 0.34. The ladder is deliberately anchored to the **end** of
the climb: where a climb starts is an accident of ambient temperature or leftover warmth from
a previous Run, whereas the last stretch up to cutoff is the same journey every time and is
where a weakening element shows first (ADR-022). The ladder actually used is reported on every
Sample.

---

## 4. Control Logic

The sampler wraps — and does not change — the existing worker loop:

```
worker start → open Climb Window (device_ts = now, run_timestamp = the Run's stamp)
  ├─ each read: accumulate voltage, min/max, read duration, retries, quiet state
  ├─ first crossing of each checkpoint on the way up → record elapsed seconds
  ├─ first reading >= cutoff_voltage (or 300 s elapsed) → close Climb Window, emit
  └─ thereafter: close at 300 s (or at worker exit) → emit → open next Settled Window
```

- **Start trigger:** the lid worker starting for a run (`state_run_assay.run`).
- **Stop trigger:** `lid_heater_stop_event` set in `hw_deinitialize`. The final, partial
  window is still emitted, with its true `window_seconds` (< 300).
- **Worker death:** after 10 consecutive failed reads the loop re-raises and the worker
  dies mid-Run. The open window MUST still be flushed from the worker's `finally` block —
  that Sample (high `read_retry_count`, short `window_seconds`) is the only record that
  the lid stopped being heated at all, and the Run continues without it.
- **Checkpoint crossings** are recorded once per Run, on the way up. They land on the
  Climb Window and are absent (`{}`) on every Settled Window. This is deliberate: it makes
  "how fast did this lid heat up today" one clean value per Run.
- **On failure:** a failed or stalled read is counted, not raised — the Sample is the
  record of the failure. Emission never raises into the worker.
- **Simulation mode:** `DEV_SIMULATE=1` runs never spawn the lid worker, so no Samples are
  emitted. By design.

---

## 5. Communication Protocol

The Sample follows the Homing Sample path exactly — no new endpoint is introduced. The
fleet ingests one mTLS endpoint and routes on `event_type`.

```
lid_heater_log.emit_lid_sample()  → JSON line → logs/lid_heater/lid_samples.log
  → aquila_web/lid_parser.import_lid_samples()
  → local_db.enqueue_event("lid_heater_sample", sample, dedup_key=sample_id)
  → aquila_web/sync.py  → mTLS ingest edge → SQS → archiver → loader
  → Warehouse: fact_lid_heater_sample
```

Offline devices queue in the SQLite outbox and ship on reconnect. Redelivery is
first-write-wins on `sample_id`.

### Payload contract — `event_type: "lid_heater_sample"`

**Identity.** Required; without these the Sample cannot be loaded or de-duplicated.

| Field | Type | Meaning |
|---|---|---|
| `sample_id` | string (UUID) | Generated on the device. The idempotency key — replay and redelivery are no-ops. |
| `device_id` | string | Stamped by ingest from the client-certificate CN. **Never trusted from the payload.** |
| `device_ts` | ISO-8601 UTC | When the window opened (device clock). |
| `run_timestamp` | ISO-8601 UTC | The Run this window fell inside — the canonical per-Run stamp from `state_run_assay.run()`, the same one `run_complete` carries. The cloud derives `run_id = uuid5(device_id : run_timestamp)`; the device never mints a `run_id`. Unlike a Homing Sample this is always available, because the lid worker cannot exist outside a Run (ADR-022). |
| `window_kind` | enum | `climb` \| `settled`. Which kind of window this Sample summarises. Explicit rather than inferred: a lid too cold to cross any checkpoint produces a Climb Window with empty `checkpoint_crossings`, which is otherwise indistinguishable from a Settled Window — and Lid Hold is drawn from Settled Windows only. |
| `window_seconds` | int | Length of the window these figures are drawn from. Windows are not uniform (Climb vs Settled vs final), so without it, averages across windows are not comparable. |

**Right now** — a snapshot of the lid at the instant the window closed.

| Field | Type | Meaning |
|---|---|---|
| `last_voltage` | float (V) | The latest reading from the lid sensor. The raw signal everything else derives from. |
| `last_reading_age_seconds` | float | Seconds since that reading was actually taken. A stopped controller looks perfectly healthy otherwise; freshness is what exposes it. |
| `cutoff_voltage` | float (V) | The stop-heating voltage this machine is configured with. |
| `floor_voltage` | float (V) | The sanity floor this machine is configured with. |
| `heater_state` | enum | `heating` \| `holding` \| `quiet` \| `not_heating`. Tells you *why* the heater is off, which the voltage alone cannot. |

**Over the window** — summarised across the stretch, not a single instant.

| Field | Type | Meaning |
|---|---|---|
| `mean_voltage` | float (V) | Mean reading across the window. The existing QC criterion — a healthy lid parks at ~0.32 V. |
| `min_voltage` | float (V) | Lowest reading in the window. |
| `max_voltage` | float (V) | Highest reading in the window. Together with `min_voltage` these carry the "consistent" half of the QC criterion, which an average by itself cannot measure — and they are raw facts, so the Warehouse derives the spread (`max − min`), "frozen" (`min = max`) and "below floor" (`min <= floor_voltage`) itself, with the floor comparison as a *central* threshold rather than a firmware constant. |
| `checkpoint_crossings` | object | Seconds from worker start to first reaching each checkpoint of the derived ladder, e.g. `{"0.28": 41.2, "0.30": 58.9, "0.32": 96.4, "0.34": 172.0}`. A missing key means that checkpoint was never reached. Captures the shape of the climb without claiming a heating rate. Keys are the actual voltages used, so a machine with a different cutoff is self-describing. |
| `at_cutoff_fraction` | float 0–1 | Share of the window spent at or above `cutoff_voltage`. Replaces the manual "holds for 300 s" check with something computed. ~0 on the Climb Window by construction; meaningful on Settled Windows. |
| `quiet_fraction` | float 0–1 | Share of the window the heater was held off because the machine was moving or imaging (`quiet_event`). The internal app may display this as "Muted"; `quiet` is the wire name, matching the code. Without it, nothing else here is interpretable during a live assay. |

**Trustworthiness** — signals about whether the numbers above are believable.

| Field | Type | Meaning |
|---|---|---|
| `live_worker_count` | int | Live heater control threads (`lid_worker_metrics.live_count()`). Should always be exactly 1. More means abandoned threads are stacking up and over-driving the heater. |
| `slowest_read_seconds` | float | Longest single sensor read in the window. |
| `slow_read_count` | int | Reads exceeding 5 s. Five seconds is the teardown join timeout, so a read past it is the known trigger for the thread leak (see §7). |
| `read_retry_count` | int | Failed reads that had to be retried. A storm of these stretches the control loop and quietly weakens heating. |
| `reading_count` | int | Readings actually received in the window. |
| `expected_reading_count` | int | Readings expected (≈ `window_seconds` at 1/s). A shortfall means the controller stalled. |

No field on this Sample is a verdict. Two conditions the docx named as flags — sensor below
the floor, and a frozen reading — are deliberately **not** shipped as booleans: `min_voltage`
and `max_voltage` let the Warehouse decide both, so the device never judges and the floor
stays changeable centrally. What min/max cannot say is *how long* a dip lasted; if that
distinction is ever needed, add `below_floor_fraction` rather than a boolean.

---

## 6. Calibration

Not applicable, and deliberately so. No factory or field calibration is introduced, and
no voltage→temperature conversion exists anywhere in this path.

This is why `checkpoint_crossings` replaces a heating rate. A rate in volts per second
would only be meaningful if the sensor responded proportionally to temperature, which is
not established. Crossing times need only that voltage rises as the lid heats.

Configured bounds continue to live in `config_files/lid_heater_config.json` (unchanged)
and are echoed onto every Sample.

---

## 7. Failure Modes

| Failure | Symptom in the Sample | Cause | Recovery |
|---|---|---|---|
| Lid-thread leak | `live_worker_count` > 1, climbing across runs | A read stalls > 5 s → teardown join times out → the abandoned worker is revived by the next run's shared-event `clear()` | Power-cycle. Root-cause fix (per-run Event + ADC lock) deferred |
| I2C bus contention | `slowest_read_seconds` and `read_retry_count` rising together | Multiple leaked workers hitting the lockless `adc` singleton | As above |
| Stalled controller | `last_reading_age_seconds` large, `reading_count` ≪ `expected_reading_count` | Control loop wedged; voltage may still look plausible | Investigate; power-cycle |
| Disconnected / broken sensor | `min_voltage` <= `floor_voltage` | Sensor unplugged or failed open | Service the lid harness |
| Dead sensor holding a value | `min_voltage` = `max_voltage` | Sensor or ADC returning its last known value | Service; do **not** read the steady value as healthy |
| Degrading heater | `checkpoint_crossings` lengthening run-over-run | Element or contact degradation | Trend alert; schedule service before it fails a run |
| Under-heating | `mean_voltage` below expectation, `at_cutoff_fraction` low | Weak element, or heavy `quiet_fraction` competing with the assay | Correlate with `quiet_fraction` before concluding |

---

## 8. Known Limitations

- Voltage is not temperature. Everything here is a voltage proxy; no field may be
  presented to an operator as °C.
- `checkpoint_crossings` is populated only on the Climb Window. A Run that starts with an
  already-warm lid records few or no crossings, and may emit no Climb Window at all —
  expected, not a fault.
- Samples are **not** uniform in length: the Climb Window ends on an event, the final
  window of a Run ends on the worker stopping. Downstream aggregates must weight by
  `window_seconds` rather than counting Samples.
- The 5 s `slow_read_count` cutoff is also a firmware constant, but a legitimate one: it is
  the teardown join timeout, which lives in device code regardless.
- `live_worker_count` tracks lid workers only; executor and stop-monitor threads are
  covered separately (`snapshot_resources.py`, #160).
- No Samples exist for idle machines — the lid worker only runs during a Run. A lid that
  fails while idle is invisible until the next run starts.
- **The window length and the checkpoint list are firmware constants.** The facts-only
  principle in §1 holds for *thresholds* — what counts as too cold or too slow is a SQL
  change in the Warehouse. It does **not** hold for *definitions*: changing
  `window_seconds` from 300, changing the Climb Window's closing rule, or changing the
  checkpoint **offsets**, requires a fleet-wide
  deploy, and silently changes what historical Samples mean. Any such change must be
  treated as a new generation of the data, not an edit to the old.
- Summarising on the device is lossy by construction — the individual readings are
  discarded once a window closes and cannot be recovered. This was chosen over shipping
  raw readings because a raw series would land as a blob (as `fact_run_optics` does):
  readable one Run at a time by code, but never projected into rows, so no fleet-wide
  question could be asked of it. If the definitions above turn out to churn, shipping a
  raw per-Run blob alongside the Samples is the escape hatch (ADR-022).
- Telemetry observes; it does not fix. A confirmed leak still needs the remediation work.

---

## 9. Testing in Simulation Mode

The window-summarising core is deliberately hardware-free and unit-testable; only the
wiring into the worker is Pi-only.

- **Unit (any machine):** `aq_lib/lid_heater_window.py` — accumulate/close/emit, checkpoint
  first-crossing-only semantics, partial final window, `expected_reading_count` arithmetic,
  min/max tracking, empty-window safety.
  Test file: `tests/unit/test_lid_heater_window.py`, marked `-m unit`.
- **Unit (any machine):** `aquila_web/lid_parser.py` — malformed line skipping, dedup on
  `sample_id`, oldest-file-first ordering. Test file: `tests/unit/test_lid_parser.py`.
- **Cannot be simulated:** the accumulation calls inside `lid_heater_worker` (imports
  `RPi.GPIO` + I2C). Test file: `tests/unit/hardware/test_lid_heater_telemetry.py`, marked
  `@pytest.mark.hardware`; run on device with `-m hardware`.
- `DEV_SIMULATE=1` emits no Samples at all — an integration test must not assert on them.

Run units: `pytest tests/unit/test_lid_heater_window.py tests/unit/test_lid_parser.py -v`

---

## 10. Related

- Prior art: `specs/hardware/lid-worker-instrumentation.md` (#157) — the diagnostic logging
  this promotes to permanent telemetry; `live=N` becomes `live_worker_count`.
- Decision: `docs/adr/ADR-022-lid-telemetry-windowed-on-device-and-run-scoped.md` — why this
  summarises on-device and carries `run_timestamp`, diverging from ADR-021.
- Parent study: `specs/analysis/sentri-self-cancel-study.md` (H1, the thread leak).
- Pattern followed: Homing Sample — `aq_lib/homing_log.py`, `aquila_web/homing_parser.py`,
  ADR-021 (device is a dumb sampler; the Warehouse never judges a Sample).
- Source (new): `aq_lib/lid_heater_log.py`, `aq_lib/lid_heater_window.py`,
  `aquila_web/lid_parser.py`. Source (touched): `aq_lib/regulate.py`.

### Downstream, outside this repo

This spec covers the device only. Two further pieces of work consume it:

1. **acorn-analytics** (issues #93 fact/loader, #94 views) — `lib/lid-heater/contract.ts`, a `lid_heater_sample` case in
   `lib/loader/load-event.ts`, migration `fact_lid_heater_sample`, and the governed read
   views where every threshold in this document actually lives. Three views are needed:
   **Lid Hold** (share of Settled Windows at cutoff, weighted by `window_seconds`),
   **Lid Climb** (Checkpoint Crossing times per Run, trended), and **Leaked Controllers** —
   with governed thin-data floors: no Lid Hold band below 20 Settled Windows (the floor is on
   windows, the score's denominator, not on Runs), no Lid Climb trend below 5 Runs carrying a
   Climb Window —
   Critical when the latest Sample reports `live_worker_count` >= 3, or when
   `live_worker_count` > 1 in >= 2 of the device's last 8 Runs. The leak rule reads the
   latest Samples, never all-time, so a power cycle clears it without an acknowledgement.
2. **acorn-internal-app** (issue #337) — the mirrored migrations, and a new **Thermal** metric category
   (the app's fourth, alongside Optics & LEDs, Inconclusive and Mechanical) carrying two
   metrics: **Lid Hold** (share of Settled Windows at cutoff — the computed replacement for
   the manual bench check, the lagging indicator) and **Lid Climb** (Checkpoint Crossing
   times per Run, trended — the leading indicator, since a lid slows before it goes cold).
   The trust fields are **not** a third metric; they surface as a data-quality caveat badge
   on the Thermal detail page. Terms are defined in `acorn-internal-app/CONTEXT.md`.

---

## 11. Open Questions

None outstanding. Every question raised in design was resolved into §1–§10 or into ADR-022.
