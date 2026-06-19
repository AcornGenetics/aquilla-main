# Bounded Context: Aquilla Analytics

This glossary defines canonical terms for the analytics domain. Terms here take precedence over informal usage in conversations and documentation.

---

## Glossary

**Sentri**
A single physical Aquilla PCR instrument — a Raspberry Pi running the Aquilla software stack in Docker. "Device" and "Sentri" are synonymous; prefer "Sentri" in analytics contexts to avoid ambiguity with AWS/cloud "devices."

**Fleet**
The collection of all deployed Sentri units. Analytics queries span the fleet; device-level queries scope to a single Sentri. There is one prod fleet; there is no separate physical "dev fleet."

**Sentri Analytics Platform**
The separate system (repo `Acorn/sentri-analytics`) that owns cloud ingest and the analytics/query surface over Aurora — the mTLS gateway, compute tier, and read APIs. Distinct from a Sentri (the physical instrument). Beware the name collision: AWS resource names such as `SentriVPC` and the `sentri/db` secret belong to this platform/infrastructure, not to an individual Sentri.
_Avoid_: calling the platform "Sentri" unqualified.

**Device ID**
The Raspberry Pi hardware serial number (from `/proc/cpuinfo`), used as the stable, globally unique identifier for a Sentri in analytics data. Survives reimages. Stored as `AQ_SYNC_DEVICE_ID` env var. Mapped to a human-readable `dock_name` in the AWS device registry. Do not confuse with the hostname-based config key (`sn01`, `sn02`) used for hardware configuration in `host_config.json`. The Device ID is also the canonical transport identity: it is the Subject CN of the Sentri's Device Certificate, so the platform derives Device ID from the cert rather than trusting the request body.

**Device Certificate**
The per-Sentri mTLS client certificate (and private key) presented on every Sync. Its Subject CN is the Device ID, cryptographically binding the transport identity to the data-model identity. Validated at the Ingest Endpoint against a signing-CA truststore. Replaces the Fleet API Key. Revoked per-device (the stolen-Pi threat model) rather than fleet-wide. Stored `chmod 600` on the Pi.

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

**Well Verdict**
The single aggregated outcome for a Well, derived from its two Channel Calls for display in the History detail view. One of: `Detected`, `Inconclusive`, `Not Detected`. Resolved by precedence **Detected > Inconclusive > Not Detected** — a Well is Detected if *any* Channel is Detected, else Inconclusive if any Channel is Inconclusive, else Not Detected. A `ROX Unavailable` Call is excluded from the verdict (the Well Verdict then comes from FAM alone). Distinct from a Call: a Call is per Channel; a Well Verdict is per Well. The Well Verdict drives the pill color and the Detected/Inconclusive KPI counts (a Well counts toward exactly one bucket — its verdict), while the pill *text* still names both Channels' individual Calls. Note: the Well Verdict does **not** drive [[QC Status]] — QC is evaluated on the underlying Channel Calls, so an Inconclusive Channel still flags QC even when the Well Verdict is Detected. (Earlier the precedence was Inconclusive > Detected; see ADR for the reversal.)

**QC Status**
A run-level Pass / Review badge on the History detail view, derived from the Channel Calls (not the Well Verdict). `Review` if *any* Channel on *any* Well has an `Inconclusive` Call (excluding `ROX Unavailable`); otherwise `Pass`. It is channel-sensitive by design: because the Well Verdict precedence is Detected-wins, a Detected Well can still contain an Inconclusive Channel, and QC must surface that rather than let a Detected verdict mask it. There is no `Fail` state. UI-only — not stored or synced.

**Cq (Cycle Quantification)**
The fractional PCR cycle at which a Well's fluorescence crosses the detection threshold. `null` when the Call is Not Detected or Inconclusive. Stored as a float rounded to 2 decimal places.

**Inconclusive Rate**
The fraction of Calls with outcome `Inconclusive`, grouped by Protocol. The primary analytics metric for v1. Denominator excludes `ROX Unavailable` calls.

**Event**
A structured JSON record enqueued in the local SQLite database (`data/db/app.db`) when a Run completes. Event type: `run_complete`. Payload contains: protocol name, run name, run timestamp, duration, and all 8 Well × Channel Calls with Cq values. Events queue offline and flush on the next successful Sync.

**Sync**
The background process (asyncio task in the FastAPI app, 15-minute interval) that batches pending Events from the local SQLite queue and POSTs them to the AWS Ingest Endpoint. Also triggered on WiFi reconnect. On success, marks events `synced_at` in SQLite. Events accumulate indefinitely if offline.

**Ingest Endpoint**
The authenticated cloud entry point that receives Event batches from Sentri devices, hosted by the Sentri Analytics Platform. Devices authenticate with their Device Certificate (mTLS) — there is no API key. Reached at a regional custom domain (API Gateway), which forwards through the platform's compute tier to write to Aurora. The device-side URL is stored as `AQ_SYNC_ENDPOINT`. (Superseded the earlier API Gateway + Lambda + RDS + `x-api-key` design; see ADR-013.)

**Fleet API Key** _(retired)_
A shared secret (`AQ_SYNC_API_KEY`) formerly sent as `x-api-key` on every Sync. Retired in favor of per-device Device Certificate (mTLS) auth: a shared fleet key is the wrong identity model for a field fleet — a single stolen Pi exposed the whole fleet, and the key could only be rotated fleet-wide. See ADR-013. Listed here only to mark the term obsolete.
