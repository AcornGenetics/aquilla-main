# PRD: Homing Telemetry — dedicated Homing Sample log → outbox → acorn-analytics → dashboard

**Status:** Ready for agent
**Author:** Nicole Cornell
**Date:** 2026-07-15
**Related:** ADR-021 (homing telemetry dumb-sampler), ADR-020 (device retention), ADR-015 (acorn-analytics ingest pipeline), ADR-008 (call_evidence per-Call telemetry)
**Glossary:** CONTEXT.md — **Homing Sample**, **Event**, **Sync**, **Ingest Endpoint**, **Sentri**, **Fleet**

---

## Problem Statement

We cannot tell, from off the bench, whether a Sentri's mechanics are healthy.
When a **Drawer** or **Axis** **misses a homing** (fails to reach its physical
home reference) or begins **homing consistently in a different place**
(mechanical drift — lost steps, a slipping belt, a shifting flag), the only trace
is a handful of lines — `"Caught home flag after N steps"`, `"Did not reach
home."`, `"Position Error N"` — buried in `logger.log` among every other
subsystem's output. That file is noisy, unrotated, never leaves the device, and
is only readable by SSHing into one Sentri at a time. There is no way to see
homing health across the **Fleet**, no history to spot slow drift before it
becomes a misaligned **Well** and a corrupted **Call**, and no alert when a unit
starts missing.

## Solution

Every homing operation emits a **Homing Sample** — a structured JSON-line record
of how the motor returned home — to a dedicated, rotated log file on the Pi,
separate from `logger.log`. A backend parser loads those Samples into the local
outbox exactly-once, and the existing **Sync** ships them to **acorn-analytics**.
The Sentri is a **dumb sampler**: it records points and never judges them.
acorn-analytics lands the Samples in a warehouse fact and derives the trends —
miss-rate and drift — and **acorn-internal-app** surfaces per-Sentri homing
health across the Fleet, so a human sees "sn06's drawer is drifting" days before
it fails, and can `tail` the on-device log for forensics when they do.

---

## User Stories

1. As a hardware reliability engineer, I want each homing operation recorded with
   how many steps it took to reach the home flag, so that I can see a Sentri's
   mechanical baseline.
2. As a hardware reliability engineer, I want a Homing Sample to record whether
   the home sensor actually confirmed arrival, so that I can distinguish a clean
   homing from a **missed** one.
3. As a hardware reliability engineer, I want the residual position error at the
   moment of homing captured before it is zeroed, so that I can quantify accumulated
   drift.
4. As a hardware reliability engineer, I want both the **Drawer** and the **Axis**
   instrumented and each Sample tagged by motor, so that I can tell carousel drift
   (which misaligns Wells) from drawer drift.
5. As a field engineer, I want the homing log to live in its own file on the Pi,
   so that `tail`-ing it over SSH shows only homing activity, not the firehose of
   `logger.log`.
6. As a field engineer, I want the homing log kept out of `logger.log` entirely,
   so that neither file pollutes the other.
7. As a field engineer, I want the homing log in JSON-lines, so that I can both
   read it by eye and pipe it to `jq` on the device.
8. As a field engineer, I want the homing log rotated at a bounded size, so that
   it never fills the SD card the way the unrotated `logger.log` can.
9. As the Sentri, I want writing a Homing Sample to be a local file append with no
   network or database call, so that emitting telemetry never stalls drawer or
   carousel motion mid-Run.
10. As a data engineer, I want the backend to parse the homing log and enqueue each
    Sample as a `homing_sample` **Event**, so that homing data rides the same
    outbox → Sync path as `run_complete`.
11. As a data engineer, I want each Sample carried by a unique id so re-parsing the
    log inserts it at most once, so that a parser restart or a log rotation never
    double-counts or drops a Sample.
12. As a data engineer, I want the parser to read both the active log and its most
    recent rotation, so that Samples written just before a rotation are not lost.
13. As a data engineer, I want malformed log lines skipped rather than fatal, so
    that one bad line never blocks the whole batch.
14. As an offline Sentri, I want Samples buffered in the outbox until the next
    successful Sync, so that homing history from a disconnected unit is not lost.
15. As a fleet operator, I want `homing_sample` Events accepted by the **Ingest
    Endpoint** over mTLS like any other Event, so that no new device credential or
    endpoint is required.
16. As acorn-analytics, I want each Homing Sample landed as a row in a homing fact
    table keyed by **Device ID**, so that homing is queryable per Sentri and across
    the Fleet.
17. As a data analyst, I want each fact row to carry motor, steps-to-flag, residual,
    reached/missed, and the device timestamp, so that I can compute both miss-rate
    and a drift series.
18. As a data analyst, I want acorn-analytics to derive a per-Sentri, per-motor
    steps-to-flag baseline and flag when recent homings deviate from it, so that
    "homing consistently in a different place" is a computed signal, not a manual
    eyeball.
19. As a data analyst, I want acorn-analytics to compute a rolling miss-rate per
    Sentri per motor, so that a unit that starts missing is detectable.
20. As a data analyst, I want homing correlated to its **Run** (or to "idle") by
    timestamp downstream, so that I can ask whether misses cluster inside Runs
    without the device having to know about Runs.
21. As a dashboard user (acorn-internal-app), I want a per-Sentri homing panel
    showing steps-to-flag over time per motor, so that I can see drift as a trend
    line.
22. As a dashboard user, I want the panel to show current miss-rate and time since
    last successful homing, so that I can judge a unit's health at a glance.
23. As a dashboard user, I want a Fleet-level view that ranks or flags Sentris by
    drift and miss-rate, so that I can triage which units need attention first.
24. As a dashboard user, I want a visual alert badge when a Sentri crosses a drift
    or miss threshold, so that a degrading unit surfaces without me querying for it.
25. As a support engineer, I want to correlate a customer's bad Run with that
    Sentri's homing history at that time, so that I can attribute a failure to
    mechanical drift versus assay chemistry.
26. As a release manager, I want homing health visible per **Ring**, so that a
    mechanical regression introduced by a build shows up before it reaches prod.
27. As an on-call responder, I want a missed-homing spike on a prod Sentri to be
    visible in the dashboard within one Sync interval, so that I hear about a
    stuck drawer without a customer call.

---

## Implementation Decisions

### Device — aquila-app (`aq_lib`)

- **Dedicated logger.** Add a fourth `logging.config.dictConfig` alongside the
  existing three. Logger `aquila.homing` with `propagate: False` and its own
  `RotatingFileHandler` → `logs/homing/homing.log`, JSON-lines formatter. The
  `logs/` directory is already a host bind-mount shared by aquila-app and
  aquila-backend, so no new volume is needed.
- **Sample emission is woven into `Motor.home()`**, the shared base-class method
  inherited by both `Drawer` and `Axis`, so one hook covers both motors. The
  emitter runs after the homing move completes and captures `residual` **before**
  `reset_position()` zeroes it.
- **Homing Sample shape** (one JSON object per homing):
  `id` (unique per device — a UUID; no shared counter state required), `ts`
  (device clock, UTC), `motor` (`"drawer" | "axis"`), `steps_to_flag` (steps to
  reach the home flag), `residual` (position error pre-zero), `reached_home`
  (the home-sensor reading after the move; `false` = a missed homing).
- **No Run reference on the device.** `motor_class` stays decoupled from the
  state machine; Run/idle attribution is done downstream by timestamp.
- **No network or DB in the motor path.** The only per-homing cost is the file
  append.

### Device → outbox — aquila-backend (`aquila_web`)

- **Parser.** A backend component reads `logs/homing/homing.log` (and its most
  recent rotation `homing.log.1`), parses each JSON line to a Sample, and calls
  `enqueue_event("homing_sample", payload)` for each. It runs on a cadence
  decoupled from Runs (homing also happens idle).
- **Exactly-once is data-intrinsic.** Add an **additive, nullable
  `dedup_key TEXT` column with a `UNIQUE` index** to the `events` table; the
  parser writes the Sample `id` as the `dedup_key` and inserts with
  `INSERT OR IGNORE`. Existing Events leave it `NULL` (SQLite permits multiple
  NULLs under a UNIQUE index), so the change is backward-compatible and needs no
  data migration. Schema version bumps via the existing `PRAGMA user_version`
  mechanism.
- **Sync is unchanged.** `homing_sample` flushes through the existing batch
  Sync; retention follows ADR-020 (delete only synced rows older than 30 days).

### Upstream — acorn-analytics (separate repo; contract defined here)

- **Ingest is event-type agnostic.** The `homing_sample` batch is authenticated
  by the same Device Certificate (mTLS), archived to S3, and passed through the
  ingest Lambda → SQS → archiver → S3 → loader/ETL path exactly like existing
  Event types. No new endpoint or auth.
- **New warehouse fact: `homing_sample`.** The loader/ETL maps each Sample to a
  fact row keyed by **Device ID** (derived from the cert CN, not the body):
  `device_id`, `sample_id` (the dedup key — idempotent load), `motor`,
  `steps_to_flag`, `residual`, `reached_home`, `device_ts`, `ingested_at`.
- **Derived signals (warehouse queries / materialized aggregates):**
  - *Miss-rate* — rolling fraction of Samples with `reached_home = false`, per
    Sentri per motor.
  - *Drift* — a per-Sentri, per-motor `steps_to_flag` baseline (e.g. historical
    median) and the deviation of a recent window from it; "homing consistently in
    a different place" is a sustained deviation, not a single outlier.
  - *Run correlation* — a timestamp join from Sample `device_ts` to Run
    start/end facts, labelling each Sample in-Run or idle.
- **Retention/volume.** Homing is high-frequency (many per Run × Fleet); the fact
  table is the highest-volume in the warehouse. Aggregation/rollup and a
  retention window for raw Samples are an acorn-analytics concern (see Revisit
  Conditions in ADR-021).

### Dashboard — acorn-internal-app (separate repo; behavior defined here)

- **Per-Sentri homing panel** on the device detail view: a steps-to-flag time
  series per motor (the drift line), current rolling miss-rate, and time since
  last `reached_home = true`.
- **Fleet homing-health view:** Sentris ranked/flagged by drift magnitude and
  miss-rate, filterable by **Ring**, so a mechanical regression is visible before
  full rollout.
- **Alert badge** when a Sentri crosses a drift or miss threshold, driven by the
  acorn-analytics derived signals (threshold owned by the dashboard/analytics,
  never the device).

---

## Testing Decisions

Good tests here assert **external behavior** — the JSON a homing produces, the
rows the outbox ends up with — never private helpers or log wording.

### Seam 1 — the emitted Homing Sample (aquila-app)

- **Harness:** the existing `tests/unit/hardware/test_motor.py` pattern —
  `MockGPIO` with `simulate_home_flag(pin, value)` (`tests/unit/conftest.py`)
  drives the home sensor, so `steps_to_flag` and `reached_home` are fully
  controllable with no hardware.
- **What we test:** run real `Motor.home()` on a mocked `Drawer`/`Axis` and
  **observe the JSON line the `aquila.homing` logger emits** — assert
  `steps_to_flag` equals the step the flag fired, `reached_home` reflects the
  sensor, `residual` is the pre-`reset_position` value, and `motor` is tagged
  correctly. A **miss** = the flag never fires → `reached_home: false`. This
  covers the full `home()` → Sample integration at the highest seam.

### Seam 2 — the parser → outbox (aquila-backend)

- **Prior art:** `tests/unit/test_run_complete_event.py`,
  `test_optics_readings_event.py`, `test_local_db_quarantine.py`,
  `test_retention.py`, `test_background_sync.py` — the established way to exercise
  `enqueue_event` against a real temp SQLite.
- **What we test:** feed the parser homing-log lines and assert the outbox rows —
  **idempotency** (parsing the same lines twice yields exactly one row per `id`
  via the `dedup_key` UNIQUE + `INSERT OR IGNORE`), **rotation** (Samples in
  `homing.log.1` are also loaded), **skip-malformed** (a bad line is dropped, the
  rest load), and that existing Event types with `NULL dedup_key` are unaffected
  by the schema change.

### Contract

- A test asserting the `homing_sample` payload matches the **Device Event
  Contract** (`docs/local-db-schema.md`), mirroring how the other Event types are
  contract-checked.

### Upstream (cross-repo — noted, not built here)

- acorn-analytics: a loader unit test that a Sample maps to the fact row and that
  re-loading the same `sample_id` is idempotent.
- acorn-internal-app: a component test that the homing panel renders a drift
  series and a miss/alert state from fixture analytics data.

---

## Out of Scope

- **On-device drift detection or alarms.** The device never judges a Sample; all
  trend/threshold logic lives in acorn-analytics (ADR-021).
- **Per-homing HTTP or direct SQLite writes from the motor process.** Rejected in
  ADR-021; the file-parse seam is the mechanism.
- **Changes to Sync, the Ingest Endpoint auth, or retention semantics** beyond
  adding a new Event type (retention follows ADR-020 as-is).
- **The acorn-analytics and acorn-internal-app implementations themselves.** This
  PRD defines their contract and behavior; the code lands in those repos.
- **Backfill of historical homing data** — telemetry starts at deploy; there is no
  pre-existing structured homing history to import.

## Further Notes

- Homing is the **first non-Run-scoped Event**; CONTEXT.md's **Event** entry is
  already updated to reflect that a Run is no longer the sole unit of emission.
- The `optics_readings` Event (a raw log shipped whole, ADR-0007) is prior art for
  "a log becomes pipeline data," but homing differs deliberately: it is
  per-operation structured Samples, not one captured file per Run.
- Rotation size should follow the compose convention (~10 MB × 3) unless homing
  volume argues otherwise.
- The single biggest downstream risk is **Event volume**; if it becomes a
  warehouse cost problem, the revisit path is parser-side batching/aggregation,
  per ADR-021's Revisit Conditions — the device stays a full-fidelity sampler.
