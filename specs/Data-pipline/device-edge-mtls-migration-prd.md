# PRD: Sentri Analytics Pipeline — Device-Edge mTLS Migration & Aurora Connectivity

> **⚠️ Largely superseded by the six-repo split (2026-06).** The cloud-side scope of this
> PRD has moved out of aquilla-main: **ingest → `acorn-analytics`** (ADR-015, serverless
> Lambda pipeline) and the **device CA → `acorn-ca`** (ADR-014). The old SAM ingest stack,
> its handlers, the warehouse schema, and the predecessor `analytics-pipeline-prd.md` have
> been **deleted from this repo** (#250). What remains live here is the **device side**:
> on-device enrollment (shipped — `aq_lib/device_csr|enroll|verify`) and the **automatic
> certificate renewal + offline re-enrollment** scope (user stories 12–14, 27–30), the next
> aquilla-main slice. Kept for that remaining scope and as the migration's narrative record.

> **Revision 1 — 2026-06-17** *(pre-split)*
> Supersedes the predecessor's *Authentication and Key Rotation* and *AWS Ingest Architecture*
> sections: device auth switches from the shared Fleet API Key to per-device mTLS Device
> Certificates. See **ADR-013** (ingest moves off this repo; auth → mTLS) and **ADR-014**
> (device PKI: self-managed KMS-backed CA, short-lived certs). Glossary in `CONTEXT.md`.

## Problem Statement

Today every Sentri authenticates to the Ingest Endpoint with a single shared Fleet API Key sent as an `x-api-key` header. As built this key is not even enforced (HTTP APIs have no usage plans, no authorizer is defined, and the handler never inspects the header — see issue #174), so `/ingest` is effectively open. Worse, a shared fleet key is the wrong identity model for a field fleet of physical instruments: a single stolen Pi exposes ingest for the whole fleet, and the key can only be rotated fleet-wide.

In parallel, ingest ownership is moving off this repo's SAM stack and onto the Sentri Analytics Platform, whose system design authenticates devices with per-device mTLS client certificates at a managed gateway. This repo must change the **device edge** to speak mTLS, provision and renew per-device certificates, open the **Aurora** path for the new platform compute, and retire the old SAM ingest stack — without which the fleet cannot move to the new, authenticated platform.

## Solution

From the operator's and fleet's perspective:

- Each Sentri presents its own **Device Certificate** (mTLS) on every Sync instead of a shared key. The certificate's Subject CN is the **Device ID** (the Pi hardware serial), so the platform derives device identity cryptographically and a stolen certificate cannot impersonate a different Sentri.
- A Sentri generates its own keypair on-device and enrolls during deployment; its private key never leaves the Pi. Certificates are short-lived and the Sentri renews them automatically before expiry, authenticating the renewal with its current still-valid certificate. Revoking a compromised Sentri is simply ceasing to renew it — it self-expires.
- The shared Fleet API Key and the `x-api-key` header are removed entirely.
- The Aurora cluster (owned by this repo) admits the new platform's app VPC over peering so the platform's compute can read/write, with a dedicated least-privilege role rather than the master credential.
- Because nothing is in production yet (one Sentri syncing, disposable data), the fleet cuts over to the new Ingest Endpoint big-bang once the platform edge exists, and the old SAM ingest stack is then deleted — preserving the Aurora cluster.

## User Stories

1. As a fleet operator, I want each Sentri to authenticate with its own Device Certificate, so that a single stolen Pi does not expose ingest for the entire fleet.
2. As a fleet operator, I want the shared Fleet API Key removed from every Sentri, so that there is no shared secret left to leak or rotate fleet-wide.
3. As the Sentri Analytics Platform, I want device identity to come from the certificate's CN (the Device ID), so that I can trust the device identity without relying on the request body.
4. As the Sentri Analytics Platform, I want a request whose body `device_id` disagrees with the certificate CN to be rejectable, so that a device cannot claim to be a different Sentri.
5. As a Sentri, I want to send my client certificate and key on every Sync POST, so that I pass the mTLS handshake at the new Ingest Endpoint.
6. As a Sentri, I want to no longer send an `x-api-key` header, so that I stop depending on the retired shared-key model.
7. As the backfill tool, I want to authenticate with the same Device Certificate as live Sync, so that historical Event uploads use the same identity model.
8. As a Sentri, I want to generate my own keypair and a CSR with `CN=<Device ID>` during deployment, so that my private key never leaves the device.
9. As a fleet operator, I want initial enrollment (CSR signing) to be authenticated by my own credentials at provisioning time, so that the Pi never holds a credential that could mint certificates.
10. As a Sentri, I want my certificate and private key stored `chmod 600`, so that they are not world-readable on the device.
11. As a Sentri, I want a background task that checks my certificate's expiry, so that I renew before it lapses and never lose the ability to Sync.
12. As a Sentri, I want to renew by submitting a new CSR authenticated with my current valid certificate, so that renewal needs no operator presence and no stored credential.
13. As a Sentri, I want the new certificate swapped in atomically, so that a renewal interrupted mid-write never leaves me with a broken certificate.
14. As a fleet operator, I want a manual renewal trigger endpoint, so that I can force a renewal for diagnostics without waiting for the scheduled task.
15. As a fleet operator, I want a re-enrollment path for a Sentri whose certificate expired while it was offline beyond the certificate lifetime, so that the rare offline-too-long device can rejoin.
16. As a fleet operator, I want to repoint a Sentri's Ingest Endpoint to the new platform's regional custom domain, so that the fleet sends to the new platform at cutover.
17. As a fleet operator, I want to cut the whole fleet over at once (big-bang), so that the old open `x-api-key` endpoint is closed quickly rather than lingering during a phased rollout.
18. As an analytics consumer, I want `dock_name` to remain platform-owned registry metadata, so that a stolen or reimaged Sentri cannot mislabel its own location.
19. As a Sentri, I want my Event payload shape unchanged (still keyed on `device_id`), so that the migration is auth-only and introduces no new device-side fields.
20. As the Sentri Analytics Platform, I want the Aurora cluster to accept connections from my app VPC CIDR over peering, so that my compute can reach the database.
21. As the owner of the Aurora VPC, I want the return route to the platform app VPC codified in the SAM template, so that replies traverse the peering connection and a redeploy does not revert it.
22. As the owner of the Aurora cluster, I want the existing console-added connectivity (peering, route, security-group ingress) brought into the template, so that the next deploy does not silently break ingress.
23. As a security-conscious operator, I want the platform to connect with a dedicated read/least-privilege role rather than the master credential, so that credential rotation is decoupled from the ingest pipeline and the access contract is enforced at the database.
24. As the owner of this repo, I want the old SAM ingest stack (API Gateway, Lambdas, SQS, S3) decommissioned after cutover, so that there is one ingest implementation, not two.
25. As the owner of this repo, I want the Aurora cluster explicitly preserved during decommission, so that the new platform's pre-existing-database assumption holds.
26. As a developer, I want the device auth change covered by the existing Sync test seam, so that "certificate sent, no api-key" is verified automatically.
27. As a developer, I want the renewal decision logic unit-tested, so that "renew when within N days of expiry" is verified without hardware.
28. As a developer, I want the atomic certificate swap covered by an integration test, so that an interrupted renewal cannot corrupt the active certificate.
29. As a fleet operator, I want certificate renewal to rely on daily connectivity, so that short-lived certificates are practical given Sentris are online every day.
30. As an auditor, I want revocation to be achievable by ceasing renewal, so that revoking a stolen Sentri does not require CRL/OCSP infrastructure the gateway lacks.

## Implementation Decisions

### Identity model (per ADR-013, ADR-014)
- The Device Certificate Subject CN is the **Device ID** (Pi hardware serial from `/proc/cpuinfo`, already the stable analytics identity). The platform derives device identity from the certificate; the Event body continues to carry `device_id` only as a **cross-check** — a body/CN mismatch is a rejected request.
- The Event/`run_complete` payload shape is **unchanged**. `dock_name` is **not** a device-emitted field; it is platform-owned registry metadata (`device_sites`) joined server-side by `device_id`. No payload contract change is owed by this repo.

### Device sync auth
- The Sync client drops the `x-api-key` header and presents the client certificate and key on the POST (a `cert=(client_cert, client_key)` style request). The `AQ_SYNC_API_KEY` env var and Fleet API Key are removed.
- The backfill tool makes the same auth change at its request-building boundary.
- New device configuration: certificate path, key path, and renewal endpoint env vars; `AQ_SYNC_ENDPOINT` is repointed to the platform's regional custom domain at cutover.

### Enrollment, renewal, rotation
- On-device keypair generation + CSR (`CN=Device ID`); the private key never leaves the Pi; certificate and key stored `chmod 600`. Initial enrollment is operator-authenticated at deployment time.
- Certificates are short-lived; renewal is automatic. Renewal is implemented as a **Python background task in the FastAPI app**, mirroring the existing background Sync task, plus a manual-trigger endpoint **`POST /sync/cert/renew`** mirroring `POST /sync/flush`. Renewal authenticates with the current valid certificate, submits a new CSR, and swaps the certificate **atomically** (write-to-temp + rename).
- A re-enrollment path in the fleet update tooling covers the rare "offline beyond certificate lifetime" Sentri.
- Revocation model is **revocation-by-non-renewal**: ceasing to renew a Sentri lets its certificate self-expire, avoiding the gateway's missing CRL/OCSP support. One CA serves the single prod fleet (no dev-fleet CA).

### Aurora connectivity (`infra/template.yaml`)
- Codify the existing (currently console-added, drifted) peering connection, route to the platform app VPC CIDR, and `DBSecurityGroup` ingress, so a redeploy does not revert them.
- Add the Aurora-side return route over the peering connection to the platform app VPC CIDR (peering routes are not symmetric).
- Add `DBSecurityGroup` ingress on 5432 for the platform app VPC **CIDR** (cross-VPC security-group references over peering are brittle); keep the existing Lambda ingress untouched until decommission.
- Parameterize the app VPC CIDR and peering id so the values come from the platform's CDK outputs (cross-stack handshake).
- Provision a dedicated `sentri_readonly` role (LOGIN; CONNECT on the database; USAGE on schema; SELECT on `devices`, `runs`, `run_results`; and full CRUD on `device_sites`, which the platform owns) via the existing `schema_runner` migration path, instead of sharing the master credential.

### Cutover and decommission
- **Big-bang greenfield cutover:** with one Sentri syncing and disposable data, provision certificates fleet-wide, repoint the fleet to the new Ingest Endpoint at once, then delete the old SAM ingest stack (API Gateway + Lambdas + SQS + S3). No parallel-run, no dual-write, no idempotency-as-blocker.
- The Aurora cluster is **excluded from teardown** and preserved.

## Testing Decisions

Good tests here assert external behavior at the highest available seam — what the device sends on the wire and what configuration resources exist — not internal call sequences. Mock the network boundary (`requests.post`) and the filesystem (`tmp_path`) rather than asserting implementation details.

- **Device sync auth — existing seam (`POST /sync/flush` → `aquila_web.sync`).** Prior art: `tests/unit/test_background_sync.py`, which monkeypatches `aquila_web.sync.requests.post` and captures call kwargs. Replace the existing `TestApiKeyHeader` class (asserts `x-api-key` is sent) with tests asserting the client certificate tuple is passed and **no** `x-api-key` header is present. Keep the existing "no endpoint → synced 0" and "network error swallowed, events stay pending" behaviors green.
- **Backfill auth.** Unit test at the backfill request-building boundary: mock `requests.post`, assert the certificate is passed and no api-key header is set.
- **Renewal decision logic.** Pure-logic unit test (in `unit_tests/`): given a certificate expiry and a threshold, the function decides whether to renew. Prior art for pure-logic units: `unit_tests/test_optics_history.py`, `tests/unit/test_device_id.py`.
- **Renewal swap + endpoint.** Integration test via `POST /sync/cert/renew` with `tmp_path` certificates and the renewal POST mocked: a successful renewal swaps the active certificate atomically; a failed renewal leaves the existing certificate intact. Prior art: `tests/integration/test_seams.py` (TestClient + `tmp_path` seam tests).
- **Enrollment / provisioning.** Host-dependent (on-device keygen, install, deployment scripts) — mark `@pytest.mark.hardware` with a documented "why not CI" note per the repo testing rules. Extract any pure logic (e.g. CSR subject construction = `CN=Device ID`) into Python and unit-test it.
- **Aurora connectivity.** Light infra assertion: parse `infra/template.yaml` and assert the return route, the app-VPC-CIDR `DBSecurityGroup` ingress rule, and the `sentri_readonly` provisioning exist. Note the existing `tests/infra/` handler tests (`aurora_loader`, `ingest_handler`, `s3_archiver`) retire with the decommissioned SAM stack. Real validation is `sam deploy` plus the acceptance check: from a platform app-VPC instance, `psql` connects over TLS and a `SELECT` against `runs` returns.

## Out of Scope

These are **Sentri Analytics Platform** (`Acorn/sentri-analytics`) deliverables and **preconditions for cutover**, not work in this repo:

- The mTLS API Gateway (HTTP API), regional custom domain, ACM certificate, and the S3 truststore.
- The Certificate Authority itself (a self-managed, KMS-backed CA per ADR-014) and the signing/renewal endpoint the device calls.
- VPC Link, internal ALB, Auto Scaling group / launch template, VPC endpoints, the rate-limit store, and the Node `/ingest` application.
- AMI bake, CI/CD pipeline, and platform-side migrations.
- The analytics read/query surface and the `device_sites` / `dock_name` registry.

Also out of scope: data migration of any kind (existing ingest data is disposable); changing the Event payload schema (auth-only migration); any dev-fleet certificate isolation (one prod fleet, one CA — the dev platform environment uses simulation-mode traffic, not hardware).

## Further Notes

- Anchored by **ADR-013** (ingest moves to the Sentri Analytics Platform; device auth → mTLS) and **ADR-014** (device PKI: self-managed KMS-backed CA, short-lived certificates, on-device keygen, revocation-by-non-renewal). Glossary terms (Sentri, Device ID, Device Certificate, Ingest Endpoint, Sentri Analytics Platform, Fleet API Key *(retired)*, Sync, Event) are defined in `CONTEXT.md`.
- **Sequencing:** every in-scope item except the big-bang cutover can be built and tested now against mocks. Cutover requires the platform-side gateway + truststore + signing/renewal endpoint to exist first; confirm that before repointing the fleet.
- The short-lived-certificate posture depends on Sentris being **online daily** (assumption confirmed). A Sentri offline beyond its certificate lifetime drops to manual re-enrollment — accepted as rare.
- ADR-014's chosen PKI eliminates the ~$400/mo ACM Private CA cost and sidesteps the gateway's missing revocation checking; long-lived certificates + a deny-list remain the documented fallback if auto-renewal proves operationally fragile.
- The Aurora connectivity work is independent of the PKI/auth work and can proceed on a separate track.
