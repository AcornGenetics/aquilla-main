# ADR-013: Ingest moves to the sentri-analytics platform; device auth switches to mTLS

**Status:** Accepted — supersedes ADR-009; **amended by ADR-015** (its "ingest served by the ASG application" sub-decision is superseded — ingest now runs as a serverless Lambda pipeline in `acorn-analytics`; the mTLS/cert-CN decisions below remain in force)
**Date:** 2026-06-17
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

ADR-009 placed the analytics ingest endpoint in this repo as a SAM stack —
API Gateway (HTTP API) + Lambda + SQS + S3 + Aurora — with devices
authenticating via a shared fleet API key sent as an `x-api-key` header.

Two problems emerged:

1. **The API key is not enforceable as built** (see the 2026-06-16 addendum to
   ADR-009 and issue #174). HTTP APIs do not support API keys or usage plans,
   no authorizer was defined, and `ingest_handler.py` never inspects the header
   — so `/ingest` is effectively open.
2. **A shared fleet key is the wrong identity model for a field fleet.** A
   single stolen Raspberry Pi exposes the ingest endpoint for the whole fleet,
   and the key can only be rotated fleet-wide. ADR-009 itself flagged migrating
   to per-device credentials as a revisit condition.

In parallel, the analytics read layer (`Acorn/sentri-analytics`) has produced a
full platform **system design** (`sentri-analytics-system-design.md`) that
defines a self-healing, mTLS-authenticated ingest + analytics platform:
API Gateway HTTP API (regional custom domain, **mTLS truststore in S3**) →
VPC Link → internal ALB → Auto Scaling group running the Node application →
Aurora over a peered VPC. Under that design the **ingest endpoint is served by
the ASG application**, device identity comes from an **mTLS client
certificate**, and per-device rate limiting protects the backend.

That design and this repo's SAM ingest stack are two implementations of the same
ingest path. They cannot both own it. This ADR records the decision to retire
this repo's implementation and define what remains aquilla-main's
responsibility.

If we did nothing: we would keep an open, unauthenticated ingest endpoint and
two conflicting ingest architectures.

---

## Decision

**We will retire this repo's SAM ingest stack and move ingest ownership to the
sentri-analytics platform, and we will replace the shared API key with
per-device mTLS client certificates.**

Concretely, this splits the work as follows.

### What aquilla-main remains responsible for (the device edge)

1. **Device auth → mTLS.** `aquila_web/sync.py` must present a client
   certificate on the ingest POST (`requests.post(..., cert=(client_cert,
   client_key), ...)`) and **drop the `x-api-key` header** (currently
   `aquila_web/sync.py:30-32`). Same change for `scripts/backfill_history.py`.
2. **Per-device cert provisioning + secure storage on the Pi.** Each device gets
   its own client cert + private key, stored `chmod 600`, wired into the request.
   This is deployment / host-config work (`scripts/deploy/deployment2.sh`,
   `config_files/`, `host_config.json`).
3. **Cert rotation / revocation on the device.** The device must support
   re-provisioning a cert, and the fleet script must be able to push a new one.
   This is the critical-path "device cert rollout" in the platform migration
   runbook; the threat model is a stolen Pi.
4. **Repoint `AQ_SYNC_ENDPOINT`** to the new API Gateway regional custom domain
   at cutover.
5. **Own the `run_complete` payload contract** — the JSON shape the platform
   parses. The payload remains keyed on `device_id` (the Pi serial). Note:
   `dock_name` is **not** a device-side field — it is platform-owned metadata in
   the AWS device registry (`device_sites`), joined server-side from `device_id`.
   The device must not emit it; a stolen or reimaged Pi must not be able to
   mislabel its own location. (This corrects an earlier draft of this ADR that
   said the device should emit `dock_name`.)
6. **Decommission the SAM ingest stack.** `aquila-main/infra/template.yaml`
   (API Gateway + Lambdas + SQS + S3 + Aurora) is superseded by the
   sentri-analytics platform and is torn down at the runbook's decommission
   phase. **The Aurora cluster is the exception** — the platform design treats
   Aurora as pre-existing in its own VPC reached via peering, so the cluster
   must be preserved (and excluded from the SAM teardown), not deleted with the
   rest of the stack.

### What moves to sentri-analytics (out of scope for this repo)

The API Gateway edge + mTLS truststore, VPC Link, internal ALB, ASG/launch
template, VPC endpoints, rate-limit store, the Node `/ingest` endpoint (reading
cert identity and writing to Aurora), AMI bake, CI/CD, and migrations. See
`sentri-analytics-system-design.md`.

This is **largely irreversible** once the SAM stack is decommissioned: rollback
during migration is repointing the fleet endpoint, not redeploying Lambdas.

---

## Consequences

### Positive
- Strong per-device identity: a compromised Pi is revoked individually via
  truststore rotation, not a fleet-wide key change.
- The "open endpoint" gap from ADR-009 / issue #174 is closed at the gateway —
  unauthenticated requests fail the mTLS handshake before reaching the app.
- One ingest implementation, not two conflicting stacks.
- Ingest and analytics converge on one operated platform (ASG app), removing the
  SAM Lambda/SQS/S3 pipeline this repo had to maintain.

### Negative
- **PKI is now a hard requirement.** Issuing, distributing, rotating, and
  revoking per-device certs is real operational work that did not exist with a
  shared key. Cert provisioning becomes part of device deployment.
- Device-side change touches every physical Pi (cert rollout is the migration
  critical path); offline devices get certs on next connection.
- This repo loses direct control of the ingest endpoint; a contract change now
  requires cross-repo coordination with sentri-analytics.

### Neutral / Tradeoffs
- The payload/schema contract is unchanged in shape — only the transport auth
  and the hosting move. `dock_name` is platform-owned registry metadata, not a
  device field, so it imposes no payload change on this repo.
- The `device_id` (RPi hardware serial) remains the stable identity in the data
  model; the mTLS cert is the transport identity layered on top.

---

## Alternatives Considered

### Option A: Keep the SAM stack, fix the API key (issue #174 as filed)
**Why rejected:** Migrating the HTTP API to a REST API with usage-plan API keys
still leaves a shared fleet secret (wrong identity model for a field fleet) and
maintains a second ingest stack that conflicts with the sentri-analytics
platform design, which explicitly rejects API keys and REST API.

### Option B: In-Lambda API key validation
**Why rejected:** Closes the open-endpoint gap but keeps the shared-key model and
the duplicate stack; superseded by the platform's mTLS edge.

### Option C: AWS IoT Core per-device certificates
**Why rejected:** Same reasoning as ADR-009 — IoT Core's provisioning and
streaming overhead isn't justified at <100 devices, and mTLS at the API Gateway
gives per-device identity without it.

---

## Revisit Conditions

- Per-device cert management proves too heavy operationally → evaluate a managed
  device-identity service (IoT Core provisioning) or an automated ACM Private CA
  workflow.
- The sentri-analytics platform design is abandoned or materially changed →
  re-open the ingest ownership and auth decision.
- Fleet exceeds the scale assumptions in `sentri-analytics-system-design.md` →
  revisit the ASG-app-as-ingest choice vs. a dedicated streaming path.

---

## References

- Supersedes: ADR-009 (analytics ingest via API Gateway + Lambda; shared API key)
- Related ADRs: ADR-001 (hostname-keyed device config), ADR-002 (Watchtower fleet updates)
- Issue: #174 (API-key enforcement — to be reframed/closed in light of this ADR)
- `sentri-analytics-system-design.md` — the target platform design (sentri-analytics)
- `aquila_web/sync.py` — device sync client (x-api-key → mTLS)
- `scripts/backfill_history.py` — backfill client (same auth change)
- `scripts/deploy/deployment2.sh`, `config_files/`, `host_config.json` — cert provisioning
- `infra/template.yaml` — SAM ingest stack to be decommissioned (preserve Aurora)
