# Bounded Context: Aquilla Analytics

This glossary defines canonical terms for the analytics domain. Terms here take precedence over informal usage in conversations and documentation.

---

## Glossary

**Sentri**
A single physical Aquilla PCR instrument — a Raspberry Pi running the Aquilla software stack in Docker. "Device" and "Sentri" are synonymous; prefer "Sentri" in analytics contexts to avoid ambiguity with AWS/cloud "devices."

**Fleet**
The collection of all deployed Sentri units. Analytics queries span the fleet; device-level queries scope to a single Sentri. There is one prod fleet; there is no separate physical "dev fleet."

**Sentri Analytics Platform** _(being split — see ADR-015)_
Historically "the separate system (repo `Acorn/sentri-analytics`) that owns cloud ingest and the analytics/query surface over Aurora." Under the six-repository split (`sentri-analytics/specs/six-repo-architecture.md`, ADR-015) this single "platform" is **decomposed**, so prefer the specific repo:
- **`acorn-analytics`** — owns cloud **ingest** (the serverless Lambda pipeline) and the **analytics warehouse**. This is what the device POSTs to.
- **`acorn-app`** — the user-facing dashboard + its own operational DB (the renamed `sentri-analytics` repo).
- **`acorn-infra`** — the shared AWS substrate (VPC, API Gateway, SQS, S3, IAM).
- **`acorn-ca`** — the standalone KMS-backed device CA + S3 truststore (ADR-014's standalone CA).
Distinct from a Sentri (the physical instrument). The name collision still holds: AWS resource names like `SentriVPC` and the `sentri/db` secret belong to platform infrastructure, not an individual Sentri.
_Avoid_: calling any of these "Sentri" unqualified; using "Sentri Analytics Platform" as if it were one repo.

**Device ID**
The Raspberry Pi hardware serial number (from `/proc/cpuinfo`), used as the stable, globally unique identifier for a Sentri in analytics data. Survives reimages. Stored as `AQ_SYNC_DEVICE_ID` env var. Mapped to a human-readable `dock_name` in the AWS device registry. Do not confuse with the hostname-based config key (`sn01`, `sn02`) used for hardware configuration in `host_config.json`. The Device ID is also the canonical transport identity: it is the Subject CN of the Sentri's Device Certificate, so the platform derives Device ID from the cert rather than trusting the request body.

**Device Certificate**
The per-Sentri mTLS client certificate (and private key) presented on every Sync. Its Subject CN is the Device ID, cryptographically binding the transport identity to the data-model identity. Validated at the Ingest Endpoint against a signing-CA truststore — the CA private key (KMS, non-extractable) and the S3 truststore are owned by **`acorn-ca`** (ADR-014's standalone CA, now its own service). This device keeps only the client-side keypair + the enrollment/renewal daemons. Replaces the Fleet API Key. Revoked per-device (the stolen-Pi threat model) rather than fleet-wide. Stored `chmod 600` on the Pi.

**Protocol**
A named PCR assay profile — a JSON file in `profiles/` that defines thermal steps, cycle count, and optical configuration. The `title` field in the JSON is the canonical protocol name. Protocols are the primary grouping dimension for analytics (e.g., "inconclusive rate by protocol").

**Run**
A single execution of a Protocol on a Sentri, producing results for up to 4 Wells. A Run has a start time, end time, and status (completed, aborted). A Run is the unit of event emission — one `run_complete` event per Run.

**Well**
One of 4 sample positions (numbered 1–4) in the Sentri carousel. Each Well is read independently.

**Channel**
One of 2 optical measurement channels: `fam` or `rox`. Channels are labels for optical hardware, not named biological targets. Each Well produces one Call per Channel per Run.

**Call**
The analytical outcome for a single Well × Channel pair within a Run. One of: `Detected`, `Not Detected`, `Inconclusive`, `ROX Unavailable`. A Run produces up to 8 Calls (4 wells × 2 channels).

**Cq (Cycle Quantification)**
The fractional PCR cycle at which a Well's fluorescence crosses the detection threshold. `null` when the Call is Not Detected or Inconclusive. Stored as a float rounded to 2 decimal places.

**Inconclusive Rate**
The fraction of Calls with outcome `Inconclusive`, grouped by Protocol. The primary analytics metric for v1. Denominator excludes `ROX Unavailable` calls.

**Event**
A structured JSON record enqueued in the local SQLite database (`data/db/app.db`) when a Run completes. Event type: `run_complete`. Payload contains: protocol name, run name, run timestamp, duration, and all 8 Well × Channel Calls with Cq values. Events queue offline and flush on the next successful Sync.

**Sync**
The background process (asyncio task in the FastAPI app, 15-minute interval) that batches pending Events from the local SQLite queue and POSTs them to the AWS Ingest Endpoint. Also triggered on WiFi reconnect. On success, marks events `synced_at` in SQLite. Events accumulate indefinitely if offline.

**Ingest Endpoint**
The authenticated cloud entry point that receives Event batches from Sentri devices, **owned by `acorn-analytics`** (ADR-015). Devices authenticate with their Device Certificate (mTLS) — there is no API key. Reached at a regional custom domain (API Gateway), which feeds a serverless pipeline (ingest Lambda → SQS → archiver Lambda → S3 → loader/ETL Lambda → analytics warehouse). The device-side URL is stored as `AQ_SYNC_ENDPOINT`. (Superseded the earlier API-key design — ADR-013; the hosting is a Lambda pipeline, not an ASG app — ADR-015.) The mTLS truststore/CA is owned by `acorn-ca` (ADR-014).

**Fleet API Key** _(retired)_
A shared secret (`AQ_SYNC_API_KEY`) formerly sent as `x-api-key` on every Sync. Retired in favor of per-device Device Certificate (mTLS) auth: a shared fleet key is the wrong identity model for a field fleet — a single stolen Pi exposed the whole fleet, and the key could only be rotated fleet-wide. See ADR-013. Listed here only to mark the term obsolete.
