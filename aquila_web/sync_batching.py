"""
Size-aware Sync batching (#289).

Pure functions (no IO) that keep every Sync POST under the SQS 256 KB message
ceiling, so a large optics_readings payload (#288) never gets a batch silently
rejected. Three complementary defenses, none of which drops or truncates data:

  * byte-capped batching  -- pack pending Events into batches each <= the cap;
    a large event lands alone in its own POST.
  * size guard            -- an event too large to fit even alone is partitioned
    out (the caller quarantines it: left pending, logged loudly, never truncated).
  * chunk split           -- split_log() slices an over-ceiling gzipped blob into
    ordered chunks sharing one sha256 (reconstructs to the exact original bytes).

Kept IO-free so the batching math is unit-testable without a DB or network.
"""
import base64
import json

# json.dumps puts ", " between array items by default: 2 bytes per gap. Counted
# per gap while packing so a maximally-full batch can't serialize past the cap.
_ITEM_SEPARATOR_BYTES = 2


def event_size_bytes(event: dict) -> int:
    """Bytes one Event contributes to the POST body: its JSON serialization."""
    return len(json.dumps(event).encode("utf-8"))


def envelope_overhead_bytes(device_id: str | None) -> int:
    """Fixed cost of the ``{"device_id": ..., "events": []}`` POST wrapper.

    Measured (not a guessed constant) and device-aware, so the batch cap
    reserves exactly the real wrapper size — an event just under the ceiling
    still fits instead of being needlessly quarantined.
    """
    return len(json.dumps({"device_id": device_id, "events": []}).encode("utf-8"))


def batch_events(events: list[dict], cap: int, device_id: str | None) -> list[list[dict]]:
    """Greedily pack Events into ordered batches each <= ``cap`` bytes serialized.

    Reserves the measured envelope and the 2-byte item separator between events,
    so every returned batch (wrapper + events) stays under the SQS ceiling. A
    large event ends up alone in its own batch (its own POST). Assumes every
    event individually fits under the cap -- oversized events must be removed
    first via :func:`partition_oversized`, which the caller quarantines.
    """
    available = cap - envelope_overhead_bytes(device_id)
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_bytes = 0
    for event in events:
        size = event_size_bytes(event)
        separator = _ITEM_SEPARATOR_BYTES if current else 0
        if current and current_bytes + separator + size > available:
            batches.append(current)
            current = []
            current_bytes = 0
            separator = 0
        current.append(event)
        current_bytes += separator + size
    if current:
        batches.append(current)
    return batches


def partition_oversized(
    events: list[dict], cap: int, device_id: str | None
) -> tuple[list[dict], list[dict]]:
    """Split events into ``(syncable, oversized)`` by the size guard.

    An event is *oversized* when it cannot fit in a POST even alone (its own
    serialization plus the envelope exceeds ``cap``). The caller quarantines
    those -- never dropped or truncated -- so one poison event can't take the
    whole flush hostage while healthy events keep syncing. Order is preserved
    within each list.
    """
    fits_alone = cap - envelope_overhead_bytes(device_id)
    syncable: list[dict] = []
    oversized: list[dict] = []
    for event in events:
        (oversized if event_size_bytes(event) > fits_alone else syncable).append(event)
    return syncable, oversized


def split_log(blob: bytes, sha256: str, max_chunk_bytes: int) -> list[dict]:
    """Slice a gzipped optics blob into ordered chunks that share one ``sha256``.

    Each chunk carries at most ``max_chunk_bytes`` of the raw blob, base64-encoded
    in ``data_b64``, tagged with ``chunk_index``/``chunk_count`` for ordering. All
    chunks share the single ``sha256`` (of the logical file) so the cloud can
    group and reassemble them; concatenating the decoded chunks in index order
    reproduces the blob exactly -- never dropped or truncated. A blob within the
    limit yields exactly one chunk. ``max_chunk_bytes`` bounds the *raw* slice;
    the caller sizes it to leave room for base64 expansion and the event envelope.
    """
    if max_chunk_bytes < 1:
        raise ValueError("max_chunk_bytes must be positive")
    slices = [blob[i : i + max_chunk_bytes] for i in range(0, len(blob), max_chunk_bytes)] or [b""]
    chunk_count = len(slices)
    return [
        {
            "sha256": sha256,
            "chunk_index": index,
            "chunk_count": chunk_count,
            "data_b64": base64.b64encode(piece).decode("ascii"),
        }
        for index, piece in enumerate(slices)
    ]
