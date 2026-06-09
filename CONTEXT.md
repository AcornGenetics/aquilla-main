# Bounded Context: Aquilla Analytics

This glossary defines canonical terms for the analytics domain. Terms here take precedence over informal usage in conversations and documentation.

---

## Glossary

**Sentri**
A single physical Aquilla PCR instrument — a Raspberry Pi running the Aquilla software stack in Docker. "Device" and "Sentri" are synonymous; prefer "Sentri" in analytics contexts to avoid ambiguity with AWS/cloud "devices."

**Fleet**
The collection of all deployed Sentri units. Analytics queries span the fleet; device-level queries scope to a single Sentri.

**Device ID**
The Raspberry Pi hardware serial number (from `/proc/cpuinfo`), used as the stable, globally unique identifier for a Sentri in analytics data. Survives reimages. Stored as `AQ_SYNC_DEVICE_ID` env var. Mapped to a human-readable `dock_name` in the AWS device registry. Do not confuse with the hostname-based config key (`sn01`, `sn02`) used for hardware configuration in `host_config.json`.

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
The AWS API Gateway URL that receives Event batches from Sentri devices. Authenticates via `x-api-key` header (shared fleet API key stored as `AQ_SYNC_API_KEY` env var). Backed by a Lambda function that writes to RDS PostgreSQL.

**Fleet API Key**
A shared secret (`AQ_SYNC_API_KEY`) stored in each Sentri's environment, sent as `x-api-key` on every Sync request. Rotated via Tailscale SSH fleet script when compromised or on scheduled rotation. A single key covers the entire fleet.
