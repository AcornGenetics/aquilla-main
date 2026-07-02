# Spec: Size-Aware Sync + Size Guard + Chunk Split

**Status:** Draft
**Author:** Jack Hu
**Last updated:** 2026-07-02
**GitHub issue:** #289
**Blocked by:** #288 (optics_readings capture) — runtime producer of the large payload
**Source file(s):** `aquila_web/sync.py`, `aquila_web/sync_batching.py` (new)

---

## 1. Problem

`sync_pending_events()` is size-blind. It pulls up to `AQ_SYNC_BATCH_SIZE` (default 100)
pending events, serialises **all of them into one JSON body**, and POSTs it in a single
request. Ingest on the platform side lands in **SQS, which rejects any message over
256 KB (262 144 bytes)**.

Issue #288 introduces a new, heavy event type — `optics_readings` — carrying a gzipped +
base64'd optics log up to ~230 KB. The moment such an event is bundled with other pending
events in one POST, the batch can exceed the SQS ceiling and the message is rejected:
**silent data loss** at the queue boundary.

Sizing reality: current logs are ≤230 KB base64 (under the ceiling), so the **chunk split
is a guard for future longer protocols, not an everyday path**. Batching and the size
guard, however, are needed as soon as #288 puts optics events on the outbox.

Source: PRD stories 18–20.

---

## 2. Solution

Three complementary defenses, none of which silently drops or truncates data:

| Mechanism | What it does | Everyday? |
|---|---|---|
| **Byte-capped batching** | Pack pending events into batches each ≤ the message cap; one POST per batch. A large optics event naturally lands **alone** in its own POST. | Yes — active every sync |
| **Size guard** | A single event that alone exceeds the hard limit is **quarantined**: left pending, never marked synced, never truncated; logged loudly. Healthy events keep flowing. | Backstop |
| **Chunk split** | A gzipped log above the inline limit is split into **ordered chunks sharing one `sha256`**, each chunk sized under the cap. Reassembled and integrity-checked server-side. | Future protocols |

**Design decisions (agreed):**
- Batching + guard are **wired live into `sync_pending_events()` now**. The batching logic
  is generic (it packs by serialised byte size, event-type-agnostic), so it does not depend
  on #288 landing.
- `split_log()` is built and unit-tested now as a **pure function with the signature #288
  will call**, but is **not** wired into a capture path that does not yet exist.
- The guard **quarantines one poison event and syncs the rest** (never aborts the whole
  flush). Rationale: aborting would let one oversized event block every other pending
  event from syncing — itself a silent failure. A backstop must not take the queue hostage.

---

## 3. New module: `aquila_web/sync_batching.py` (pure, no IO)

```python
MAX_MESSAGE_BYTES = 262_144          # SQS hard limit: 256 KiB

def event_size_bytes(event: dict) -> int: ...
    # Serialised UTF-8 byte length of one event as it appears in the POST body.

def envelope_overhead_bytes(device_id, max_events=1) -> int: ...
    # MEASURED size the {device_id, events:[...]} wrapper adds (empty wrapper +
    # one separator byte per extra event). Not a coarse fixed reserve — a
    # near-ceiling event is no longer needlessly quarantined.

def max_batch_bytes(device_id, message_ceiling=MAX_MESSAGE_BYTES, max_events=1) -> int: ...
    # message_ceiling - envelope_overhead_bytes(...). The precise per-POST cap.

DEFAULT_MAX_BATCH_BYTES = max_batch_bytes(None)  # default for the pure helpers

def partition_oversized(events, max_bytes=DEFAULT_MAX_BATCH_BYTES) -> tuple[list, list]: ...
    # (ok_events, oversized_events). The guard's partition step.

def batch_events(events, max_bytes) -> list[list[dict]]: ...
    # Greedily pack events (assumed each fits alone) into batches ≤ max_bytes,
    # preserving id order. An event that fits alone but not with the current
    # batch starts a new batch — so a large optics event lands alone.

def split_log(compressed: bytes, sha256: str,
              max_chunk_bytes=DEFAULT_MAX_BATCH_BYTES) -> list[dict]: ...
    # Split gzipped bytes into ordered chunk payloads, all sharing sha256.
    # Each chunk: {sha256, chunk_index, chunk_count, data(base64)}.
    # chunk_index 0..count-1; concatenating decoded chunk bytes == compressed.
    # Fits in one chunk -> single chunk with chunk_count == 1.
    # NOTE: consumed by #288's optics producer; not wired into Sync here.
```

**Quarantine persistence (`local_db.py`).** An oversized event is not left
pending — it is flagged so it drops out of the flushable set without being
dropped or truncated:

```python
# events table gains (additive migration for existing devices):
#   quarantined_at TEXT, quarantine_reason TEXT
get_pending_events(...)        # now excludes quarantined_at IS NOT NULL
mark_event_quarantined(ids, reason)  # set quarantined_at once
get_quarantined_events()       # retained rows, discoverable for follow-up
```

---

## 4. Data Models

### Chunk payload (output of `split_log`)

| Field | Type | Description |
|---|---|---|
| `sha256` | string (hex) | Integrity hash of the **whole** reassembled gzip blob; identical across all chunks |
| `chunk_index` | int | 0-based position in the ordered sequence |
| `chunk_count` | int | Total chunks for this blob |
| `data` | string (base64) | This chunk's slice of the gzipped bytes |

Reassembly (server-side, out of scope here): order by `chunk_index`, base64-decode and
concatenate `data`, verify `sha256` of the result.

---

## 5. Wiring into `sync.py`

`sync_pending_events()` changes from one-POST to per-batch:

```
pending = get_pending_events(batch_size)   # already excludes quarantined
cap = max_batch_bytes(device_id, ceiling, batch_size)   # precise, measured reserve
ok, oversized = partition_oversized(pending, cap)
if oversized:
    log each ERROR once, then mark_event_quarantined([ids], reason)
    # excluded from future flushes: no re-fetch/re-log spam, no slot occupied
for batch in batch_events(ok, cap):
    POST {device_id, events: batch}   # same envelope, same mTLS cert as today
    on success: mark_event_synced([e["id"] for e in batch])
    on RequestException: log, stop — remaining batches stay pending, return count so far
return total_synced
```

Unchanged: the mTLS `cert=(client_cert, client_key)` handshake (ADR-013), the
`AQ_SYNC_ENDPOINT` / `AQ_SYNC_BATCH_SIZE` / `AQ_SYNC_TIMEOUT_SECONDS` env vars, the
`{device_id, events}` envelope shape, and the "no endpoint → 0" / "network error swallowed,
events stay pending" behaviors.

---

## 6. Behaviors to test

### Pure logic — `unit_tests/test_sync_batching.py`
1. Small events pack into one batch (tracer bullet).
2. When total exceeds the cap, events split into multiple batches; **every** batch ≤ cap.
3. A single large event lands **alone** in its own batch (optics-sent-alone).
4. Id order is preserved across batches.
5. `partition_oversized` separates an event over the hard limit from the fittable rest.
6. `split_log`: a blob under the limit → one chunk, `chunk_count == 1`.
7. `split_log`: a blob over the limit → N ordered chunks, all sharing one `sha256`,
   each ≤ cap, and decode+concat reconstructs the original bytes exactly.

Plus `envelope_overhead_bytes` is the measured wrapper (< 100 B), one separator per extra
event; `max_batch_bytes` = ceiling − overhead.

### Quarantine seam — `unit_tests/test_local_db_quarantine.py`
Additive migration adds the columns to a legacy table without dropping rows and is
idempotent; a quarantined event leaves the pending set but its row is retained and
discoverable via `get_quarantined_events`.

### Flush integration — `tests/unit/test_background_sync.py` (extend)
8. Two events whose combined size exceeds the cap produce **two** POSTs, not one.
9. An oversized single event is quarantined: excluded from pending and the flush count,
   healthy events in the same flush still sync, its row retained (not dropped).
10. A network error on batch 2 leaves batch-2 events pending while batch-1 stays synced.
11. A quarantined event is **not** reprocessed on the next flush (no re-POST, no re-log).
12. An event just under the true ceiling still syncs (precise reserve, not the coarse 4 KB).

Existing green behaviors (cert presented, no api-key, no-endpoint→0, error-swallowed) must
stay passing.

---

## 7. Files touched

| File | Change |
|---|---|
| `aquila_web/sync_batching.py` | **New** — pure batching, guard partition, measured envelope reserve, `split_log` |
| `aquila_web/sync.py` | Per-batch POST loop; quarantine oversized; precise device-aware cap; per-batch mark-synced |
| `aquila_web/local_db.py` | Additive `quarantined_at`/`quarantine_reason` columns; `mark_event_quarantined`/`get_quarantined_events`; `get_pending_events` excludes quarantined |
| `unit_tests/test_sync_batching.py` | **New** — pure-logic tests |
| `unit_tests/test_local_db_quarantine.py` | **New** — migration + quarantine seam tests |
| `tests/unit/test_background_sync.py` | Extend — flush batching/guard/quarantine tests |

The POST envelope contract and env-var names are unchanged; the `local_db` schema change is
additive (migrates existing devices in place).

---

## 8. Out of scope

- **Optics capture / gzip / sha256 computation** — that is #288. This spec consumes its
  output shape and provides `split_log` for it to call.
- **Server-side reassembly / integrity verification** of chunks — platform (`acorn-analytics`).
- Any change to the event payload schema or the mTLS auth model (ADR-013).

---

## 9. Open questions

- [x] ~~Envelope reserve~~ — **resolved**: the reserve is now the *measured*
      `{device_id, events:[...]}` wrapper (`envelope_overhead_bytes`), not a fixed 4 KB
      guess, so a near-ceiling event is no longer needlessly quarantined.
- [ ] Does #288's producer split **before** enqueue (chunks as separate outbox events) or
      does Sync split at flush? This spec assumes producer-side split using `split_log`;
      `split_log` is built and unit-tested but intentionally **not wired into Sync** — #288
      (built concurrently) owns wiring it. Confirm the direction when #288 lands. — Owner: Jack
