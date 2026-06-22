# PRD: Sentri Analytics Pipeline — Device-Side Data Collection

> **Revision 2 — 2026-06-10**
> AWS ingest architecture updated from single-Lambda to three-Lambda + SQS + S3 pattern.
> See _AWS Ingest Architecture_ section for details. All other sections unchanged.

## Problem Statement

Sentri runs PCR assays on Sentri devices deployed in the field. There is currently no way to observe how those devices are performing across the fleet. When a protocol produces a high rate of inconclusive results — meaning the analysis engine cannot determine Detected or Not Detected — there is no signal to investigate whether the issue is with the protocol configuration, a specific device, or a systemic problem. Run results exist only locally on each Sentri and are not collected or queryable in aggregate.

## Solution

Build an offline-first analytics data pipeline that collects a structured `run_complete` event from each Sentri after every assay, queues it locally in the existing SQLite event store, and syncs it periodically to an AWS-hosted ingest endpoint. On the cloud side, a Lambda function writes structured run and result records into a PostgreSQL database that can be queried directly with SQL.

The first analytics capability enabled by this pipeline is **inconclusive rate by protocol**: the fraction of Well × Channel Calls with outcome `Inconclusive`, grouped by Protocol name, queryable across the fleet.

## User Stories

1. As a fleet operator, I want inconclusive rates aggregated by protocol, so that I can identify which assay protocols are producing unreliable results across all Sentri devices.
2. As a fleet operator, I want inconclusive rates broken down per Sentri device, so that I can detect whether a single device is performing worse than the rest of the fleet.
3. As a fleet operator, I want run data to be collected even when a Sentri is temporarily offline, so that I don't lose analytics history during connectivity gaps.
4. As a fleet operator, I want the pipeline to retry failed syncs automatically, so that I don't have to manually intervene when a device loses internet mid-sync.
5. As a fleet operator, I want each run's Cq values stored alongside the Call outcome, so that I can detect subtle reagent degradation or optical drift before it causes inconclusive calls.
6. As a fleet operator, I want to identify which Sentri device produced each run result, so that I can correlate performance with device age, location, or firmware version.
7. As a fleet operator, I want run timestamps in the cloud database, so that I can query trends over time (e.g., is the inconclusive rate increasing this month?).
8. As a fleet operator, I want the analytics pipeline to not interfere with assay execution, so that a sync failure or cloud outage never blocks a run.
9. As a fleet operator, I want the sync to happen automatically in the background, so that I don't need to manually trigger data uploads from each device.
10. As a fleet operator, I want the sync to attempt upload after a WiFi reconnect, so that events collected during an offline period are flushed promptly when connectivity is restored.
11. As a fleet operator, I want each device's identity to be stable across reimages and hostname changes, so that analytics history is not fragmented when a device is reconfigured.
12. As a fleet operator, I want the cloud endpoint to be protected so that only authenticated Sentri devices can write run data.
13. As a fleet operator, I want to be able to rotate the fleet authentication key without taking devices offline, so that key management doesn't disrupt operations.
14. As a fleet operator, I want duplicate events (from a retry after a partial sync) to be ignored safely, so that run counts in the database are accurate.
15. As a fleet operator, I want the number of calls per run and the protocol name stored together, so that I can compute inconclusive rate with a single SQL query without joining multiple sources.
16. As a fleet operator, I want ROX Unavailable calls excluded from the inconclusive rate denominator, so that the metric reflects real analytical failures rather than hardware configuration choices.
17. As a fleet operator, I want run abort events distinguished from completed runs, so that I can separately track abort rates without them skewing the inconclusive rate.
18. As a data analyst, I want to query run results with plain SQL against a PostgreSQL database, so that I can write ad-hoc analytics without learning a specialized query interface.
19. As a data analyst, I want one row per Well × Channel pair per Run in the results table, so that I can slice by well, channel, device, or protocol independently.
20. As a data analyst, I want the device's human-readable name (dock name) available in the database alongside its hardware serial, so that query results are interpretable without a lookup table.

## Implementation Decisions

### Device Identity

Each Sentri uses its Raspberry Pi hardware serial number (read from `/proc/cpuinfo` at startup) as its canonical Device ID. This is injected as the `AQ_SYNC_DEVICE_ID` environment variable and stored on every event. The hardware serial survives reimages and is globally unique. The existing hostname-based config key (`sn01`, `sn02`, etc.) continues to be used for hardware configuration lookup only and is not the analytics identifier. A human-readable `dock_name` (from `host_config.json`) is registered in a cloud-side `devices` table alongside the hardware serial.

### Event Schema

One `run_complete` event is emitted per completed Run. The payload is a JSON object containing:
- `protocol`: the Protocol title string (the `title` field from the profile JSON)
- `run_name`: the run label
- `run_timestamp`: ISO-8601 UTC datetime when the run completed
- `duration_seconds`: integer run duration
- `aborted`: boolean; `true` if the run was stopped before completion
- `calls`: an array of 8 objects, each with `{ well: int, channel: "fam"|"rox", call: "Detected"|"Not Detected"|"Inconclusive"|"ROX Unavailable", cq: float|null }`

Aborted runs emit the event with `aborted: true` and empty `calls`. They are stored but excluded from inconclusive rate calculations.

### Enqueue Point

The event is enqueued inside the FastAPI `/history/append` endpoint handler, which is already called by the assay loop after every run (completed or aborted). At that point the handler has the protocol name, run name, and results file path. It loads the results JSON, transforms it into the `calls` array, and calls `enqueue_event('run_complete', payload)`. No changes to `state_run_assay.py` or the assay loop are required.

### Local Queue

The existing SQLite event queue (`local_db.py`) is used without schema changes. Events accumulate with `synced_at = NULL` and are retained for 7 days after successful sync. The queue handles offline accumulation transparently — the assay loop is unaffected by connectivity state.

### Sync Schedule

A new asyncio background task in the FastAPI app calls `sync_pending_events()` on a 15-minute interval, following the existing `_background_update_poller` pattern. A separate trigger fires on WiFi reconnect (detected via the kiosk control service's `/wifi/status` endpoint). Sync failures are silent — events remain in the queue and retry on the next interval.

### AWS Ingest Architecture

#### Pipeline overview

```
Sentri Device
  └─→ API Gateway  (HTTP API, POST /ingest, x-api-key auth)
        └─→ Lambda 1 — ingest-handler  (no VPC)
              - validates payload structure
              - sends event batch to SQS
              - returns 200 {"queued": N} immediately
              └─→ SQS: sentri-event-queue  (standard queue)
                    - visibility timeout: 60 s
                    - DLQ: sentri-event-dlq (maxReceiveCount: 3)
                    └─→ Lambda 2 — s3-archiver  (no VPC)
                          - triggered by SQS (batch size: 10)
                          - writes one JSON file per event to S3
                          - path: s3://sentri-raw-events/{YYYY-MM-DD}/{device_id}/{event_id}.json
                          └─→ S3: sentri-raw-events bucket
                                - ObjectCreated notification → Lambda 3
                                └─→ Lambda 3 — aurora-loader  (IN VPC, private subnet)
                                      - reads raw JSON from S3
                                      - upserts into Aurora PostgreSQL:
                                        devices / runs / run_results
                                      - ON CONFLICT DO NOTHING idempotency
                                      └─→ Aurora PostgreSQL (Provisioned, private subnet)
```

#### Why three Lambdas

- **Resilience**: S3 is the durable buffer. If Aurora is down, events are already archived in S3 and Lambda 3 retries independently via S3 event notifications.
- **Replayability**: Any time window can be replayed by re-triggering Lambda 3 against the S3 prefix — no data is ever lost.
- **Simplicity per Lambda**: each function has one job (validate+queue / archive / load), making each independently testable and deployable.

#### Networking and cost

| Component | VPC | Reason |
|---|---|---|
| Lambda 1 (ingest-handler) | No | Only writes to SQS — public AWS endpoint |
| Lambda 2 (s3-archiver) | No | Reads SQS, writes S3 — both public |
| Lambda 3 (aurora-loader) | **Yes, private subnet** | Needs Aurora which is in private subnet |
| Aurora PostgreSQL | Private subnet | Never exposed to public internet |
| S3 bucket | — | Lambda 3 accesses via free VPC Gateway Endpoint |

No NAT Gateway required. VPC Gateway Endpoint for S3 is free. Estimated monthly cost: Aurora `db.t4g.medium` ≈ $55/mo; Lambda + SQS + S3 at this volume ≈ $0 (free tier covers it).

#### Components

- **API Gateway**: HTTP API, single `POST /ingest` route, usage plan validates `x-api-key`
- **SQS**: Standard queue with Dead-Letter Queue (messages that fail 3× go to DLQ for investigation)
- **S3**: `sentri-raw-events` bucket, versioning enabled, lifecycle: transition to Glacier after 90 days
- **Aurora PostgreSQL**: Provisioned `db.t4g.medium`, single-AZ, three tables (see schema below)
- **Query access**: Raw SQL via psql; no BI tool for v1

IoT Core was evaluated and rejected: the connection management overhead and per-device certificate provisioning are not justified at <100 devices. See ADR-009.

### PostgreSQL Schema

Three tables:

**`devices`** — one row per physical Sentri:
- `device_id` (TEXT PK) — RPi hardware serial
- `dock_name` (TEXT) — human-readable label from `host_config.json`
- `registered_at` (TIMESTAMPTZ)

**`runs`** — one row per Run:
- `run_id` (UUID PK, generated by Lambda)
- `device_id` (TEXT FK → devices)
- `protocol` (TEXT)
- `run_name` (TEXT)
- `run_timestamp` (TIMESTAMPTZ) — indexed
- `duration_seconds` (INTEGER)
- `aborted` (BOOLEAN)
- `received_at` (TIMESTAMPTZ)

**`run_results`** — one row per Well × Channel per Run:
- `result_id` (BIGSERIAL PK)
- `run_id` (UUID FK → runs)
- `device_id` (TEXT)
- `protocol` (TEXT) — denormalized for query convenience
- `well` (SMALLINT, 1–4)
- `channel` (TEXT, `fam` or `rox`)
- `call` (TEXT)
- `cq` (NUMERIC(6,2), nullable)
- `run_timestamp` (TIMESTAMPTZ) — denormalized, indexed

Unique constraint on `(run_id, well, channel)` for idempotency.

### Authentication and Key Rotation

A single shared Fleet API Key is stored as `AQ_SYNC_API_KEY` on each Sentri. It is sent as an `x-api-key` HTTP header on every sync request. Rotation procedure: generate a new key in API Gateway, push `AQ_SYNC_API_KEY` to all reachable devices via a Tailscale SSH fleet script, wait 24 hours for offline devices to reconnect and receive the update, then retire the old key in API Gateway.

### Inconclusive Rate Query

The primary analytics query:

```sql
SELECT
    protocol,
    COUNT(*) FILTER (WHERE call = 'Inconclusive') AS inconclusive_count,
    COUNT(*) FILTER (WHERE call != 'ROX Unavailable') AS eligible_count,
    ROUND(
        COUNT(*) FILTER (WHERE call = 'Inconclusive')::numeric /
        NULLIF(COUNT(*) FILTER (WHERE call != 'ROX Unavailable'), 0),
        4
    ) AS inconclusive_rate
FROM run_results
WHERE aborted = false  -- joined from runs
GROUP BY protocol
ORDER BY inconclusive_rate DESC;
```

## Testing Decisions

**What makes a good test here:** Tests should assert observable external behavior — what ends up in the SQLite queue and what gets sent over the wire — not implementation details like which internal function was called. Tests should not mock the SQLite database; use a real in-memory or temp-file SQLite. The sync HTTP call should be mocked.

### Modules to test

**`/history/append` endpoint — enqueue behavior (contract test)**
Test that after a successful POST to `/history/append` with a valid results file, the SQLite event queue contains exactly one `run_complete` event with the correct `protocol`, correct number of `calls` entries (8), and correct `call` values matching the results file. Test the aborted case produces an event with `aborted: true` and empty `calls`. Prior art: `tests/contract/` using the FastAPI test client via `httpx`.

**`sync_pending_events()` — sync behavior (unit test)**
Test that pending events are POSTed to the configured endpoint with the correct shape (`device_id` at top level, `events` array), that events are marked `synced_at` on HTTP 200, and that events remain unsynced on HTTP 500 or connection error. Use `responses` or `httpx` mock transport for the HTTP call.

**`local_db` queue — idempotency (unit test)**
Test that `cleanup_synced_events()` removes events older than the retention window and leaves recent ones. Test that `mark_event_synced` with an empty list is a no-op.

**Lambda 1: ingest-handler — queue behavior (unit test)**
Test that a valid payload sends messages to SQS and returns `{"queued": N}`. Test that a malformed payload returns 400 without touching SQS. Mock the SQS client.

**Lambda 2: s3-archiver — archive behavior (unit test)**
Test that each SQS message produces one S3 object at the correct path (`{date}/{device_id}/{event_id}.json`). Mock the S3 client. Test that a batch of N messages produces N S3 objects.

**Lambda 3: aurora-loader — upsert behavior (unit test)**
Test that a valid S3 event loads rows into `devices`, `runs`, and `run_results`. Test that a duplicate S3 event (same `run_id`, `well`, `channel`) does not duplicate rows. Test that an aborted run inserts a `runs` row with `aborted = true` and zero `run_results` rows. Mock the Aurora/psycopg connection.

**Device ID extraction (unit test)**
Test that the RPi serial extraction from `/proc/cpuinfo` returns the expected string, and that a missing file falls back gracefully (e.g., returns hostname).

## Out of Scope

- **Operator identity / login**: No user authentication on the Sentri; runs are attributed to a device, not a named operator. Operator-level analytics is a future phase.
- **Device utilization metrics**: CPU, RAM, disk, and temperature telemetry are not collected in v1. See `docs/local-db-schema.md` for the future schema.
- **Real-time alerting**: No CloudWatch alarms or SNS notifications in v1. Monitoring is pull-based (run a SQL query).
- **BI tool or dashboard**: Raw SQL access via psql only for v1.
- **Per-device API keys**: Shared fleet key only for v1. Per-device keys or mTLS are a future security hardening option.
- **Raw fluorescence data**: The optics log files (per-cycle RFU readings) are not synced. Only the final calls and Cq values are collected.
- **IoT Core**: Explicitly out of scope until fleet exceeds 500 devices (see ADR-009).
- **S3 as analytics source (Athena)**: S3 stores raw event archives for replay and durability but is not queried directly in v1. Athena is a future option if query volume outgrows Aurora.
- **Sync from the assay loop process**: All event emission happens in the FastAPI web process. The assay loop (`state_run_assay.py`) is not modified.

## Further Notes

- The existing `cloud_db.py` module contains a partial PostgreSQL integration (`psycopg`, bulk insert with `ON CONFLICT DO NOTHING`). Lambda 3 (aurora-loader) adopts this idempotency pattern directly.
- The existing `AQ_SYNC_ENDPOINT`, `AQ_SYNC_DEVICE_ID`, `AQ_SYNC_BATCH_SIZE`, and `AQ_SYNC_TIMEOUT_SECONDS` env vars are the complete device-side configuration surface. The new `AQ_SYNC_API_KEY` is the only addition.
- Devices that have never synced will have a backlog in SQLite. On first successful sync after pipeline deployment, the Lambda should handle potentially large initial batches gracefully (the existing 100-event batch size cap in `sync.py` limits per-request size).
- See `CONTEXT.md` for the canonical analytics domain glossary.
- See `docs/adr/ADR-009-analytics-ingest-api-gateway-lambda.md` for the architecture decision record covering the API Gateway + Lambda choice.
