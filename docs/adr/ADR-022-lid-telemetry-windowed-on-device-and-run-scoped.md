# ADR-022: Lid-heater telemetry is summarised on-device into Sample Windows and carries the Run's timestamp

**Status:** Proposed
**Date:** 2026-08-19
**Author:** Claude
**Deciders:** Nana Vajapattana

---

## Context

Lid-heater health is checked by hand today: an operator confirms the lid "parks at roughly
0.32 V and holds for 300 s". Everything else the subsystem knows — read stalls, retries,
leaked worker threads (ADR-021's sibling problem, `specs/hardware/lid-worker-instrumentation.md`)
— exists only in on-device log files nobody reads until a Run has already failed. We want lid
degradation visible across the [[Fleet]] before it costs a Run.

The obvious path is to copy [[Homing Sample]] wholesale (ADR-021), which established the fleet's
telemetry pattern: **the Sentri is a dumb sampler** — it emits one raw record per real-world
event, carries **no Run reference**, and lets acorn-analytics own every judgement. Two facts
about the lid heater make a literal copy the wrong move.

**The lid produces a continuous signal, not discrete events.** `lid_heater_worker` reads the
ADS1115 roughly once per second for the whole of a Run. There is no "one homing" to emit a row
for. The candidates are therefore: ship every reading, or summarise.

**The lid worker is created by the state machine.** `state_run_assay.run()` captures one
canonical `run_timestamp` (line 176) and starts the lid worker (line 230); `hw_deinitialize`
stops it. Unlike `motor_class.home()` — which also fires when the Sentri is idle, and which
ADR-021 deliberately kept ignorant of the state machine — the lid worker **cannot exist outside
a Run**, and the Run's identity is already in scope at the moment the worker is spawned.

Constraints carried over from ADR-021 and unchanged here: the assay process (`application.py`,
the aquila-app container) is separate from the process owning the SQLite outbox
(`aquila_web`, the aquila-backend container), with `logs/` bind-mounted on both; and no network
or DB I/O may happen inside the control loop.

Doing nothing leaves the manual QC check as the only signal, and the known thread leak
invisible until a machine is in front of an engineer.

---

## Decision

**We will emit a [[Lid Heater Sample]] per [[Sample Window]] — a summary computed on the
device — and it will carry the Run's `run_timestamp`, deliberately diverging from ADR-021 on
both points.**

Concretely:

- **Summarised, not raw.** Each Sample reports mean/min/max voltage, share of window at cutoff,
  share Quiet, [[Checkpoint Crossing]] times, and the loop-health counters (live workers, slowest
  read, slow reads, retries, readings received vs expected) for one window. The individual
  readings are discarded.
- **Two window kinds.** One [[Climb Window]] per Run, closing when the lid first reaches
  `cutoff_voltage` (or at 300 s), then repeated 300 s [[Settled Window]]s. Uniform windows were
  rejected because the lid's ~3-minute climb would make the first Sample of every Run a
  meaningless blend of warming and settled. Every Sample carries its own `window_seconds`.
- **The checkpoint ladder is derived from the machine's own cutoff**, not hardcoded:
  `[cutoff − 0.06, cutoff − 0.04, cutoff − 0.02, cutoff]`, rounded to 4 decimals, with any
  checkpoint at or below `floor_voltage` dropped rather than clamped. The ladder actually used
  is reported on every Sample, exactly as `cutoff_voltage` and `floor_voltage` are, so nothing
  downstream assumes 0.34. At today's configured cutoff this reproduces the original
  0.28/0.30/0.32/0.34 ladder exactly.
- **Run-scoped.** Every Sample carries the `run_timestamp` from `state_run_assay.run()` — the
  same stamp `run_complete`, `optics_readings` and `call_evidence` share. The device still does
  **not** mint a `run_id`; the cloud derives `uuid5(device_id : run_timestamp)` as it always has.
- **Judgement stays central.** No Sample field is a verdict. "Below floor" and "frozen reading",
  which the source proposal wanted as device-set booleans, are instead derivable in the Warehouse
  from `min_voltage`/`max_voltage`, so their cutoffs remain SQL-side. ADR-021's dumb-sampler
  principle is preserved *for judgement*; it is what "dumb" means for *shape* that changes.
- **Transport unchanged.** JSON lines to a dedicated lid log → backend parser → `enqueue_event`
  with `dedup_key` = the Sample id → existing Sync. The parser runs in `_run_sync_cycle()` beside
  the homing import, on the 15-minute sync cadence, failures swallowed.

Reversible in code (window rules, field set, thresholds). **Not** cheaply reversible once
acorn-analytics depends on it: the `lid_heater_sample` event type and `fact_lid_heater_sample`
are a cross-repo contract, exactly as ADR-021 said of its own.

---

## Consequences

### Positive
- Lid degradation becomes a fleet-wide trend rather than a per-machine manual check.
- A cold or wobbly lid can be joined straight to the Run it spoiled, with no timestamp
  reconstruction — the correlation ADR-021 pushed downstream for homing is free here.
- The known thread leak becomes visible in production data (`live_worker_count` > 1) instead of
  only in logs on a bench.
- Settled Windows give an honest "is this lid holding temperature" number, uncontaminated by
  the climb.

### Negative
- **`window_seconds`, the Climb Window's closing rule, and the checkpoint offsets are firmware
  constants.** Changing any of them needs a fleet-wide deploy *and* silently changes what
  historical Samples mean; such a change must be treated as a new generation of the data.
- Summarising is lossy — the individual readings cannot be recovered later, so a question
  nobody thought to ask cannot be answered retroactively. (Shipping a raw per-Run blob
  *alongside* the Samples remains available as an escape hatch; it would be readable per-Run
  like the optics log, not queryable across the fleet.)
- A second telemetry shape now exists (summary rows alongside per-event rows), so "how does a
  Sentri report telemetry?" no longer has one answer.

### Neutral / Tradeoffs
- Samples are not uniform in length, so downstream aggregation must weight by `window_seconds`
  rather than count rows.
- Changing a machine's `cutoff_voltage` slides its checkpoint ladder with it, which is the
  point — but it also splits that device's Lid Climb history into two incomparable eras. Like
  a window-length change, it must be treated as a new generation of the data.
- Lid health is invisible while a Sentri is idle, because the worker only exists during a Run.
  This is acceptable: an unheated idle lid is not a fault, and the cost is that a failure is
  learned at the start of the next Run rather than before it.

---

## Alternatives Considered

### Option A: Ship every raw reading, let the Warehouse summarise
**Why rejected:** volume is not the problem (~tens of KB gzipped per Run) — queryability is. A
raw series would land like `fact_run_optics`: a blob that ADR-0007 stores rather than
re-analyses. Such a blob is not unreadable — acorn-internal-app's qPCR Analysis context pulls it
per-Run via `getOpticsLog` at compute time — but it is readable **one Run at a time, by code**,
and there is no projection of it into rows. Fleet-wide questions ("which lids are climbing
slower than they did in June?") need a queryable fact, which is what a summarised Sample is.

### Option B: Copy ADR-021 literally — no `run_timestamp`, correlate by timestamp downstream
**Why rejected:** it discards a fact the device holds. ADR-021's reason was that `home()` also
fires when idle and must stay decoupled from the state machine; neither applies to a worker the
state machine itself spawns.

### Option C: Uniform 300 s windows throughout
**Why rejected:** the ~3-minute climb would sit inside the first window, making one Sample in
twelve a blend of warming and settled — an average that means nothing and reads as a cold lid.

### Option D: Time the whole climb, or express the checkpoints as percentages of floor→cutoff
**Why rejected:** we are deliberately timing the **end** of the climb, not all of it. Where the
climb *starts* is an accident of the run — ambient room temperature, or leftover warmth from a
previous Run — so a time measured from the bottom mostly reports the starting conditions rather
than the heater's condition. The final stretch up to cutoff is the same journey on every Run,
and it is where a weakening element shows first, because that is where the heater works hardest
against the lid's heat loss. Fixed offsets below cutoff say exactly that ("the last 0.06 V of
the climb, sampled every 0.02 V"); a percentage of the floor→cutoff span would match today's
ladder only by coincidence, and would slide the measured stretch around if a machine's floor
were ever reconfigured. Percentages would become the better rule only if machines' cutoffs and
floors came to differ widely enough that a fixed 0.06 V meant a materially different share of
the climb on different machines — not the case today.

### Option E: Device-set `below_floor` / `reading_frozen` booleans (as originally proposed)
**Why rejected:** it moves a threshold onto the device for no gain. `min_voltage`/`max_voltage`
carry the same information and leave both cutoffs changeable in SQL.

---

## Revisit Conditions

- If the window rules or checkpoint ladder need changing more than once, the on-device summary
  is the wrong boundary — revisit Option A, shipping a raw per-Run blob alongside the Samples.
- If an ETL to unpack blob facts (`fact_run_optics` and friends) is ever built, Option A becomes
  viable and this decision should be re-examined.
- If Sentris in the field come to run materially different `cutoff_voltage` / `floor_voltage`
  configurations, revisit the fixed-offset checkpoint ladder in favour of percentages of the
  floor→cutoff span (Option D).
- If the lid heater is ever driven outside a Run (idle pre-warming, a service mode), the
  Run-scoped assumption breaks and Samples need an "idle" representation.
- If a third continuous-signal subsystem wants telemetry, generalise the Sample Window pattern
  rather than copying it a third time.

---

## References

- Related ADRs: `ADR-021-homing-telemetry-dumb-sampler-file-parsed-to-outbox.md` (the pattern this
  diverges from), ADR-0007 (optics stored not re-analyzed), ADR-0008 (device decides, warehouse
  never re-scores)
- Spec: `specs/hardware/lid-heater-fleet-telemetry.md`
- Prior instrumentation: `specs/hardware/lid-worker-instrumentation.md` (#157)
- Issues: aquilla-main #452 (emit), acorn-analytics #93 (fact + loader) and #94 (governed
  views), acorn-internal-app #337 (Thermal category)
