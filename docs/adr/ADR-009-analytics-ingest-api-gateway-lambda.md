# ADR-009: Analytics Ingest via API Gateway + Lambda, not IoT Core

**Status:** Accepted
**Date:** 2026-06-08
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

Aquilla devices (Sentri) are Raspberry Pis deployed in the field, occasionally offline. We need to collect `run_complete` events from the fleet and store them in a queryable database to compute inconclusive rate by protocol.

Fleet size: <10 now, ~100 within 12 months. At 20 runs/day per device, peak volume is ~2,000 events/day at full scale.

Devices already have:
- A local SQLite event queue (`aquila_web/local_db.py`) with offline accumulation and `synced_at` tracking
- A sync module (`aquila_web/sync.py`) that batch-POSTs JSON to a configurable `AQ_SYNC_ENDPOINT`
- An asyncio background task pattern (`_background_update_poller`) for periodic work

AWS IoT Core is the conventional choice for IoT device telemetry. API Gateway + Lambda is the conventional web-API choice.

---

## Decision

**We will use AWS API Gateway + Lambda as the analytics ingest endpoint, backed by RDS PostgreSQL.**

- `AQ_SYNC_ENDPOINT` points to an API Gateway URL
- `sync.py` POSTs batches of `run_complete` events unchanged — no client-side changes needed
- A Lambda function receives the batch, validates the fleet API key, and upserts rows into RDS PostgreSQL
- RDS PostgreSQL holds three tables: `devices`, `runs`, `run_results` (one row per Well × Channel per Run)
- Analytics queries run directly against RDS via psql (raw SQL access)

Auth: shared fleet API key sent as `x-api-key` header, validated by API Gateway's built-in usage plan. Key stored as `AQ_SYNC_API_KEY` on each device. Rotated via Tailscale SSH fleet script.

Sync schedule: 15-minute asyncio background task in the FastAPI app, plus a trigger on WiFi reconnect.

---

## Consequences

### Positive
- No new device-side infrastructure — `sync.py` already speaks plain HTTP POST
- API Gateway + Lambda requires zero server management vs. running an EC2 ingest server
- RDS PostgreSQL is directly queryable with psql; no BI tool or data pipeline needed for v1
- Lambda's `ON CONFLICT DO NOTHING` idempotency (already in `cloud_db.py`) handles duplicate syncs safely
- Cost at 100 devices × 20 runs/day is negligible (Lambda free tier covers it; `db.t4g.micro` ~$15/month)

### Negative
- Shared fleet API key means a compromised device exposes the ingest endpoint for the whole fleet (mitigated: analytics data only, no commands flow back)
- Key rotation requires a fleet script touching all online devices; offline devices get the new key on next connection
- No real-time streaming — 15-minute sync interval means analytics lag by up to 15 minutes

### Neutral / Tradeoffs
- IoT Core would give per-device certificates and bi-directional messaging, but bi-directional is not needed for analytics-only data flow
- IoT Core → Kinesis → S3 is the right architecture at 500+ devices; this decision should be revisited at that threshold

---

## Alternatives Considered

### Option A: AWS IoT Core + Kinesis
**Why rejected:** Significant setup overhead (device certificate provisioning, IoT policies, Kinesis shards, Glue/Athena for querying) that isn't justified at <100 devices. Revisit at 500+ devices.

### Option B: Direct RDS connection from device
**Why rejected:** Exposes database credentials on every device, requires VPC peering or public RDS endpoint, and doesn't handle offline accumulation.

### Option C: S3 + Athena (data lake)
**Why rejected:** Athena query latency and setup cost aren't worth it at this volume. Flat RDS table with a `run_timestamp` index handles years of data at this scale.

---

## Revisit Conditions

- Fleet exceeds 500 Sentri devices → evaluate IoT Core + Kinesis
- Need for real-time alerting (< 1 minute latency) → add EventBridge or SNS trigger from Lambda
- Per-device audit trail becomes a compliance requirement → migrate to per-device API keys or mTLS

---

## References

- Related ADRs: ADR-002 (Watchtower fleet updates), ADR-001 (hostname-keyed device config)
- `aquila_web/sync.py` — existing sync client
- `aquila_web/local_db.py` — local SQLite event queue
- `aquila_web/cloud_db.py` — existing psycopg PostgreSQL integration
- `CONTEXT.md` — analytics domain glossary
