# ADR-021: Homing telemetry is a dumb-sampler JSON-lines log on the Pi, parsed into the outbox; acorn-analytics owns drift detection

**Status:** Accepted
**Date:** 2026-07-15
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

We want to know when a Sentri **misses a homing** (the drawer/carousel fails to
reach its home reference) and when it is **homing consistently in a different
place** (mechanical drift over time). Today this signal exists only as scattered
lines in `logs/logger.log` — `motor_class.py` logs `"Caught home flag after %d
steps"`, `"Did not reach home."`, and `"Position Error %d"` through the shared
`aquila` logger, drowned among every other subsystem's output and never sent
upstream.

The constraints that shaped the decision:

- **Homing is high-frequency and sub-Run.** `home()` lives on `Motor` (inherited
  by both `Drawer` and `Axis`) and fires on every `Drawer.open()`,
  `Drawer.read()`, and every optics re-home pass — many times per Run — and also
  when the Sentri is **idle** (ready-screen drawer open/close), so it is **not**
  Run-scoped and cannot ride the `run_complete` cadence.
- **`home()` runs inside the motor-control loop.** Any per-homing network or DB
  I/O risks stalling drawer motion mid-run.
- **Two-container split.** `motor_class` runs in **aquila-app**; the SQLite
  outbox (`enqueue_event`) is owned by **aquila-backend**. `app.db` is mounted
  **only** on backend, so the motor process cannot write SQLite directly. The
  `logs/` directory (`/opt/aquila/logs`) **is** bind-mounted on **both**
  containers.
- **"Drift" is a trend, not a point fact.** Deciding a Sentri homes
  "consistently" somewhere new requires history across many homings — judgement
  that belongs where the fleet time series already lives (acorn-analytics),
  not on a stateless field device.
- The pipeline ingests **Events** (SQLite → Sync → Ingest Endpoint), not log
  files. To reach the warehouse, homing data must become an Event.

Doing nothing leaves homing health invisible to the fleet and unqueryable.

---

## Decision

**We will emit a [[Homing Sample]] on every `home()` as a JSON-line in a
dedicated, non-propagating homing log on the Pi, have a backend parser load those
lines into the events outbox exactly-once, and let acorn-analytics derive all
drift/miss judgement — the Sentri is a dumb sampler.**

Concretely:

- **On-device log.** A fourth `logging.config.dictConfig` alongside the existing
  three: a logger `aquila.homing` with **`propagate: False`** and its **own**
  `RotatingFileHandler` → `logs/homing/homing.log`, using a **JSON-lines**
  formatter. `propagate: False` keeps homing out of `logger.log` and everything
  else out of the homing log.
- **Sample shape.** One object per homing: `id` (unique per-device), `ts`,
  `motor` (`"drawer" | "axis"`), `steps_to_flag`, `residual` (the position error
  captured *before* `reset_position()` zeroes it), `reached_home` (the `HME_PIN`
  home sensor after the move; `false` = a missed homing). The write is a local
  file append only — no network, no DB — so it never blocks the motor loop.
- **No run reference on the device.** `motor_class` stays decoupled from the
  state machine; a Sample carries only `ts` + `motor`. acorn-analytics correlates
  each homing to its Run (or to "idle") by timestamp downstream.
- **Parser → outbox.** A parser in **aquila-backend** reads the shared
  `homing.log` (+ rotated `homing.log.1`) and inserts each Sample via
  `enqueue_event` as a new `homing_sample` Event. Exactly-once is a property of
  the **data**: each Sample's unique `id` backs an `INSERT OR IGNORE`, so a
  parser restart or a log rotation can re-scan freely without double-inserting or
  skipping.
- **Upstream.** Existing **Sync** flushes `homing_sample` Events unchanged;
  acorn-analytics owns miss-rate and drift-trend detection and adds the warehouse
  fact.

Reversible in code (formats, parser, thresholds), but the `homing_sample` Event
type and its warehouse fact are a cross-repo contract that is costly to change
once acorn-analytics depends on it.

---

## Consequences

### Positive
- **Homing health is visible and queryable across the fleet** without polluting
  `logger.log`; the dedicated file is a stable `tail`-able artifact on the Pi.
- **The motor loop never blocks** — the only per-homing work is a local append.
- **No data loss when a Sentri is unhealthy.** Samples are durable on disk before
  the parser runs; the outbox + Sync provide offline buffering.
- **Zero new HTTP surface** between app and backend — the shared `logs/` mount is
  the seam.
- **The device stays stateless** — no rolling baseline, no on-device thresholds to
  drift out of calibration.

### Negative
- **A parse hop is a new moving part** (a background reader + its unique-id dedup)
  that must survive rotation and restarts.
- **Event volume rises materially** — many homings per Run × the fleet — a
  warehouse cost the dumb-sampler choice accepts in exchange for full fidelity.
- **Drift is only visible after Sync** (≤15 min offline lag); there is no
  immediate on-device alarm.

### Neutral / Tradeoffs
- Homing becomes the first **non-Run-scoped** Event, softening "a Run is the unit
  of event emission" (CONTEXT.md **Event** updated accordingly).
- Run/idle attribution moves entirely downstream and depends on warehouse clock
  correlation.

---

## Alternatives Considered

### Option A: Synchronous per-homing POST to the backend (like `emit_run_complete`)
**Why rejected:** a network call inside every `home()` can stall the drawer if the
backend is slow, and it is one Event per homing with no offline buffer.

### Option B: Device computes a rolling baseline and flags drift on-device
**Why rejected:** puts stateful window logic + a persisted baseline on every field
device to reproduce a trend query the warehouse can already run over the series.

### Option C: Anomaly-only / periodic-baseline Events (device decides what to send)
**Why rejected:** superseded in the interview by "log the point every time and let
acorn-analytics make sense of it" — full fidelity beats device-side sampling
judgement.

### Option D: Byte-offset checkpoint for the parser
**Why rejected:** rotation/truncation handling is fiddly (inode detection, finish-
old-then-reset) and a single mistake silently skips a Sample; a per-sample unique
id + `INSERT OR IGNORE` makes correctness data-intrinsic instead.

### Option E: Direct SQLite write from the motor process
**Why rejected:** `app.db` is mounted only on aquila-backend; this needs a shared
DB volume and breaks single-writer ownership of the outbox.

---

## Revisit Conditions

- If homing Event volume becomes a warehouse cost problem, revisit the
  full-fidelity choice (batch/aggregate at the parser, or sample on-device).
- If immediate on-device homing alarms become a product requirement, the
  dumb-sampler premise changes and some judgement moves back to the device.
- If run/idle attribution by timestamp proves unreliable, add an explicit run
  reference (recoupling `motor_class` or setting a shared run-context).
- If `logs/` stops being a shared bind-mount across app and backend, the
  HTTP-free parser seam collapses.

---

## References

- Related ADRs: ADR-020 (device retention trusts the ingest pipeline),
  ADR-015 (ingest moves to acorn-analytics Lambda pipeline), ADR-0007
  (optics_readings raw-log-as-Event precedent)
- Glossary: CONTEXT.md — **Homing Sample**, **Event**, **Sync**
- Code: `aq_lib/motor_class.py` (`Motor.home`, `move_w_home_flag`, `isHome`,
  `reset_position`), `aq_lib/utils.py` (logging configs),
  `aquila_web/local_db.py` (`enqueue_event`)
- Doc: `docs/local-db-schema.md` (Device Event Contract — add `homing_sample`)
