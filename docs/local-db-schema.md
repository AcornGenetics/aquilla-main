# Device Event Contract

The on-device SQLite database (`data/db/app.db`, WAL mode) is a **thin outbox**,
not a relational store. It holds one table, `events`, into which the Sentri
enqueues structured JSON [Events](../CONTEXT.md#glossary) as a Run completes;
[Sync](../CONTEXT.md#glossary) flushes them to the cloud and they are pruned once
safely synced (retention policy: ADR-020). All querying and analytics happen
**downstream in the warehouse** (`acorn-analytics`), never on the device.

> This replaces an earlier draft that described a 22-table relational schema. That
> schema was never built and, under the outbox architecture (ADR-015), never will
> be. If you want to *inspect* device data, look at the warehouse facts below.

---

## The `events` table

One append-only queue. One row per Event.

```sql
CREATE TABLE events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type        TEXT NOT NULL,   -- run_complete | optics_readings | call_evidence | homing_sample
    payload           TEXT NOT NULL,   -- the Event body, as a JSON string
    device_id         TEXT,            -- Sentri Device ID (Pi serial)
    created_at        TEXT NOT NULL,   -- when enqueued (UTC ISO-8601)
    synced_at         TEXT,            -- when the Ingest Endpoint accepted it; NULL = pending
    quarantined_at    TEXT,            -- set only if the Event can't be synced even alone
    quarantine_reason TEXT,
    dedup_key         TEXT             -- optional idempotency key; UNIQUE index, NULL for most Events
);
CREATE UNIQUE INDEX idx_events_dedup_key ON events(dedup_key);
```

- **`synced_at`** means *"accepted by the Ingest Endpoint (HTTP 2xx)"* — i.e.
  durably handed to the pipeline — **not** "present in the warehouse." The S3
  archive is the source of truth; see **ADR-020**.
- **Pending** = `synced_at IS NULL`. **Quarantined** = `quarantined_at IS NOT NULL`
  (retained for diagnosis, never synced, never auto-pruned — the #289 size guard).
- **`dedup_key`** is an optional idempotency key backing `INSERT OR IGNORE`, so a
  parser that re-reads its source never double-enqueues (#326). Most Events leave
  it `NULL` (many NULLs coexist under the UNIQUE index); `homing_sample` sets it
  to the Sample `id`.
- Retention (prune synced Events past a window) lives in **ADR-020**, not here.

---

## Event types

Each Event's `payload` is JSON. Adding a new kind of Event = a new `event_type`
value + a new section here + a matching warehouse transform.

### `run_complete`

Emitted once per [Run](../CONTEXT.md#glossary) at completion.

| Field | Meaning |
|---|---|
| `run_name` | Operator-facing Run name |
| `profile` | [Protocol](../CONTEXT.md#glossary) name |
| `result` | Detected/summary string for the Run |
| `run_timestamp` | Run identity; shared by the Run's other Events |
| `tube_names` | Per-Well labels, keyed to Wells 1–4 (default "Tube 1".."Tube 4") |
| `calls` | All 8 Well × Channel [Calls](../CONTEXT.md#glossary) with Cq values |

**→ warehouse:** `fact_run` (+ `fact_run_result`, one row per Well × Channel Call).

### `optics_readings`

The raw optics log the Run consumed, captured whole (ADR-0007 — stored, not
re-analyzed). Shares the Run's `run_timestamp`. Emitted only when a log exists.

| Field | Meaning |
|---|---|
| `run_timestamp` | Run identity |
| `filename` | Source optics log filename |
| `sha256` | Digest of the raw (pre-compression) bytes |
| `raw_bytes` | Uncompressed size |
| `line_count` / `expected_lines` | Rows captured vs. expected |
| `complete` | `line_count == expected_lines` |
| `aborted` | Whether the Run aborted mid-read |
| `chunk_index` / `chunk_count` | Set when a large log is split across Events for Sync |
| `data_b64` | base64 of the gzipped raw log |

**→ warehouse:** `fact_run_optics` (the whole blob, per ADR-0007).

### `call_evidence`

Per-Call QC telemetry from `aq_curve` — read-only provenance for a Call already
decided on-device (ADR-0008; the warehouse never re-scores). Shares the Run's
`run_timestamp`. Emitted only when the Run evaluated at least one Call.

| Field | Meaning |
|---|---|
| `run_timestamp` | Run identity |
| `algo_version` | Analysis algorithm version (provenance) |
| `evidence` | Array, one record per evaluated Well × Channel Call |

Each `evidence` record carries: `well`, `channel`, `raw_status`, `call`,
`decision_reason`, a `flags` object, and a `metrics` array (one row per named
Metric/Check: `name`, `value`, `threshold`, `passed`).

**→ warehouse:** `fact_call_evidence` (summary, one row per Call) +
`fact_call_evidence_metric` (long, one row per Metric name).

### `homing_sample`

One [Homing Sample](../CONTEXT.md#glossary) per motor homing operation (ADR-021).
**Not** Run-scoped: homing recurs within and between Runs, so a Sample carries no
`run_timestamp` — the warehouse correlates it to a Run (or "idle") by timestamp.
The device is a dumb sampler; drift and miss-rate are derived downstream.

Written by `motor_class` as JSON lines to the dedicated homing log (#325), then
loaded into this table by the backend parser (#326) with `dedup_key` = the
Sample `id`, so re-parsing the log (or a rotation) is idempotent.

| Field | Meaning |
|---|---|
| `id` | Unique per-Sample id (UUID); also the `dedup_key` |
| `ts` | When the homing occurred (device UTC ISO-8601) |
| `motor` | `"drawer"` or `"axis"` |
| `steps_to_flag` | Steps taken to reach the home flag |
| `residual` | Position error at homing, before it is zeroed |
| `reached_home` | Home sensor after the move; `false` = a missed homing |

**→ warehouse:** `fact_homing_sample` (one row per Sample; miss-rate and drift are
derived views — acorn-analytics, issues #327–#328).

---

## Related

- **ADR-015** — ingest/warehouse is `acorn-analytics`; the device is a thin outbox.
- **ADR-020** — device retention trusts the pipeline (S3 as source of truth).
- **ADR-0007 / ADR-0008** (in `acorn-analytics`) — optics stored whole; Call Evidence.
- Glossary: `CONTEXT.md` — Event, Sync, Ingest Endpoint, Run, Call, Cq.
