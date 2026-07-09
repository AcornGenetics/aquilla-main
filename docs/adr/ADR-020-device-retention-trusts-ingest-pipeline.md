# ADR-020: Device retention trusts the ingest pipeline (S3 as source of truth), not warehouse acknowledgement

**Status:** Accepted
**Date:** 2026-07-09
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

Each Sentri keeps a local SQLite database (`data/db/app.db`) that is a **thin
outbox**: a single `events` table into which the app enqueues typed JSON Events
(`run_complete`, `optics_readings`, `call_evidence`) as a Run completes. The
background Sync task flushes pending Events to the Ingest Endpoint every 15
minutes (and on WiFi reconnect) and stamps `synced_at` on each row.

Two facts forced a retention decision:

- **`synced_at` is set on the ingest HTTP `2xx`, not on warehouse landing.**
  The Ingest Endpoint is only the front door of an asynchronous pipeline
  (ingest Lambda → SQS → archiver Lambda → **S3** → loader/ETL Lambda →
  analytics warehouse; ADR-015). A `2xx` means "accepted into the pipeline,"
  which is returned long before the loader writes the fact to Postgres. The
  device has **no signal** that a row reached the warehouse.
- **The cleanup was never wired up.** `cleanup_synced_events` existed but had no
  caller, so synced rows accumulated on the SD card indefinitely. Adding a real
  retention policy meant first deciding what "safe to delete" means.

Live options ranged from "delete as soon as ingest accepts" to "only delete once
the warehouse confirms the row landed." The relevant durability fact is that the
pipeline **archives every raw Event to S3** before loading, with DLQ retry on the
loader — so S3, not the device, is the replayable record of what was sent.

Doing nothing was not viable: the device DB grows without bound, and the
retention semantics stay ambiguous.

---

## Decision

**We will treat the ingest `2xx` as a durable hand-off and let device retention
trust the pipeline — the S3 archive is the source of truth for replay, not the
device SQLite.**

Concretely:

- `synced_at` continues to mean **"accepted by the Ingest Endpoint (`2xx`),"**
  i.e. durably handed to SQS + archived to S3. It does **not** mean "present in
  the Postgres warehouse."
- `cleanup_synced_events` runs **after** the flush inside the existing 15-minute
  Sync loop, deleting only rows that are **both** synced **and** older than
  **30 days** (`WHERE synced_at IS NOT NULL AND synced_at < now − 30d`).
- Pending (un-synced) and quarantined rows are **never** auto-deleted — an
  offline Sentri retains everything until it flushes; quarantined rows persist
  for diagnosis.
- We will **not** build a device↔warehouse acknowledgement channel. The device
  never asks acorn-analytics "did my rows load?"

The 30-day window is a **safety buffer**, not the correctness mechanism.
Correctness — the guarantee that a sent Event can always be recovered — lives in
the S3 archive and the pipeline's DLQ retry.

This is reversible in code (retention window and caller are trivial to change),
but the *data* it deletes is not recoverable from the device once gone.

---

## Consequences

### Positive
- **No new API surface or coupling.** No confirmation endpoint, no per-device
  polling of the warehouse across the fleet.
- **Bounded local storage.** The SD card no longer accumulates synced Events
  forever; the outbox stays a buffer.
- **Undelivered data is never lost.** Only synced rows are eligible; pending and
  quarantined rows are retained until delivered or explicitly resolved.
- **Generous recovery window.** 30 days is ample time for any transient loader
  failure to be noticed and resolved (via S3 replay) before the device copy ages
  out.

### Negative
- **A deleted device row is not a warehouse guarantee.** In a pathological
  failure where an Event is accepted (`2xx`) but never loads to Postgres and the
  issue is unresolved for 30 days, the device copy is gone — recovery then
  depends entirely on the S3 archive, not the device.
- **`synced_at` is a mild misnomer:** it records ingest acceptance, not warehouse
  arrival. Documented in the Device Event Contract and CONTEXT.md to prevent
  misreading.

### Neutral / Tradeoffs
- Retention is a housekeeping buffer, decoupled from correctness. Anyone
  reasoning about "is this data safe?" must look at S3, not the device DB.

---

## Alternatives Considered

### Option A: True warehouse acknowledgement (device confirms landing before delete)
The device would ask acorn-analytics which `run_timestamp`s have loaded and mark
only those confirmed, deleting later.
**Why rejected:** duplicates a durability guarantee the S3 archive + DLQ already
provide, while adding a new confirmation endpoint, device↔warehouse coupling, and
per-device polling that is costly to operate across a growing fleet.

### Option B: Delete immediately on `2xx`
Drop each row as soon as it syncs.
**Why rejected:** leaves no buffer for a transient pipeline issue and no local
window for diagnosis; a same-day loader outage would have no device-side fallback.

### Option C: Never delete (keep forever)
**Why rejected:** unbounded SD-card growth on a field device; the outbox is meant
to be a buffer, not an archive.

---

## Revisit Conditions

- If the S3 raw-Event archive is removed or stops being the replay source of
  truth, the trust assumption collapses and this must be reopened.
- If the pipeline loses its DLQ/retry durability between ingest and warehouse.
- If a real incident shows 30 days is too short (or needlessly long) for the
  fleet's recovery patterns.
- If on-device querying of historical Events becomes a product requirement (the
  thin-outbox premise itself would change — see the retired
  `local-db-schema.md` relational design).

---

## References

- Related ADRs: ADR-015 (ingest moves to acorn-analytics Lambda pipeline),
  ADR-013 (ingest moves to Sentri Analytics Platform, mTLS)
- Glossary: CONTEXT.md — **Event**, **Sync**, **Ingest Endpoint**
- Code: `aquila_web/local_db.py` (`cleanup_synced_events`, `mark_event_synced`),
  `aquila_web/sync.py`, `aquila_web/main.py` (Sync loop)
- Doc: `docs/local-db-schema.md` (Device Event Contract)
