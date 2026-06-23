# ADR-009: Analytics Ingest via API Gateway + Lambda, not IoT Core

**Status:** Superseded by ADR-013 (2026-06-17) — ingest moves to the sentri-analytics platform and device auth switches to mTLS. The shared-API-key model and SAM ingest stack described below are retired; see ADR-013.
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

## Addendum (2026-06-16): API key is not enforced as currently deployed

**Status of this addendum:** Known gap — documented, not yet fixed.

### What was found

The decision above specifies a shared fleet API key "validated by API Gateway's
built-in usage plan." That validation does **not** happen with the stack as
written. The device sends the key, but nothing on the server checks it:

1. `infra/template.yaml` deploys an **HTTP API** (`AWS::Serverless::HttpApi`,
   resource `IngestApi`). API keys and usage plans are a **REST API**
   (`AWS::ApiGateway::RestApi`) feature only — HTTP APIs have no concept of an
   API key or usage plan, so the manually-created `sentri-fleet-key` and its
   usage plan (see `docs/aws-deployment-guide.md`) cannot be attached to this
   endpoint and have no effect.
2. The template defines **no authorizer** — the auth section is comments only.
3. The ingest Lambda (`infra/handlers/ingest_handler.py`) never reads the
   `x-api-key` header; it forwards any body with `device_id` + `events` to SQS.

**Consequence:** the `/ingest` endpoint is effectively open. The "No API key →
403" smoke test in the deployment guide does not hold as deployed — an
unauthenticated POST returns `200`. The key is sent by `aquila_web/sync.py` and
`scripts/backfill_history.py` but discarded by the gateway and Lambda.

### Why the key still exists

`sentri-fleet-key` is a real artifact of this ADR's auth design, not leftover
scaffolding. The ADR and deployment guide were written to the REST-API
usage-plan model; the template was implemented as the cheaper/simpler HTTP API,
and the docs were never reconciled with that change. The device side was wired
correctly to *send* the key, which masked that the server never *checks* it.

### Remediation options

Pick one. Listed cheapest-to-implement first.

- **Option 1 — Validate in the Lambda (no infra change).** Store the expected
  key in SSM Parameter Store (SecureString) or Secrets Manager, read it in
  `ingest_handler.handler`, and compare against `event["headers"]["x-api-key"]`
  (HTTP API lowercases header names); return `403` on mismatch. Fastest fix,
  keeps the HTTP API. Downside: auth lives in app code, no usage-plan throttling
  or per-key metering.
- **Option 2 — Lambda authorizer on the HTTP API.** Add a request authorizer
  that checks the header before the ingest function runs. Keeps the HTTP API,
  centralizes auth, still no usage-plan metering.
- **Option 3 — Switch to a REST API with a usage plan.** Matches the original
  ADR wording exactly and makes `sentri-fleet-key` real. Most infra change.
  Details below.

### Option 3 in detail: migrating to a REST API with usage plans

What changes in `infra/template.yaml`:

1. **Swap the API resource type.** Replace `IngestApi`
   (`AWS::Serverless::HttpApi`) with `AWS::Serverless::Api` (REST API). On it,
   set `Auth.ApiKeyRequired: true` (globally or per-method via
   `DefinitionBody`), which makes API Gateway reject any request missing a valid
   key with `403` before the Lambda runs.
2. **Define the API key and usage plan in the template** (so it is no longer a
   manual console step). Add:
   - `AWS::ApiGateway::ApiKey` (`sentri-fleet-key`) with `Enabled: true`.
   - `AWS::ApiGateway::UsagePlan` referencing the API + stage, with optional
     `Throttle` / `Quota` limits (e.g. rate-limit the fleet).
   - `AWS::ApiGateway::UsagePlanKey` binding the key to the plan.
   Output the key id (and retrieve the value via
   `aws apigateway get-api-key --include-value`) so it can be pushed to devices
   as `AQ_SYNC_API_KEY`.
3. **Update the event source on `IngestHandlerFunction`.** Change the
   `IngestPost` event from `Type: HttpApi` to `Type: Api`, point `RestApiId` at
   the new resource, keep `Method: POST` / `Path: /ingest`, and set
   `Auth.ApiKeyRequired: true` on the method.
4. **Stage name.** REST APIs require an explicit `StageName` (e.g. `!Ref
   Environment`); keep it consistent so the `IngestEndpoint` output URL still
   ends in `/prod/ingest`.

What does **not** change:

- **The device.** `aquila_web/sync.py` already sends `x-api-key`; the REST API
  reads exactly that header. No device-side code change, no re-flash.
- **The ingest endpoint shape.** Still `POST /ingest` returning
  `{"queued": N}`. The `IngestEndpoint` stack output keeps the same format
  (`https://<id>.execute-api.<region>.amazonaws.com/<stage>/ingest`), though the
  `<id>` changes because it is a new API resource.
- **The Lambda body handling.** `ingest_handler.py` can stay as-is — API Gateway
  rejects bad keys before invoking it, so no in-handler key check is needed.
- **Downstream** SQS → S3 → Aurora is untouched.

Caveats:

- Replacing the API resource type forces a **new API id** (the old HTTP API is
  deleted, a new REST API created), so `AQ_SYNC_ENDPOINT` must be re-pushed to
  the fleet after migration.
- Note the URL difference: REST APIs use
  `…/execute-api.…/<stage>/<resource>` and the stage is part of the path the
  same way; confirm the deployed URL from stack outputs before updating devices.
- After this change the deployment guide's "No API key → 403" smoke test becomes
  accurate and should be kept as a post-deploy verification step.

This migration is the only option that makes the ADR's stated auth mechanism
("validated by API Gateway's built-in usage plan") literally true. If the
simpler Option 1 or 2 is chosen instead, update the Decision section's "Auth:"
line to match what is actually enforced.

---

## References

- Related ADRs: ADR-002 (Watchtower fleet updates), ADR-001 (hostname-keyed device config)
- `aquila_web/sync.py` — existing sync client
- `aquila_web/local_db.py` — local SQLite event queue
- `aquila_web/cloud_db.py` — existing psycopg PostgreSQL integration
- `CONTEXT.md` — analytics domain glossary
