"""Size-aware Sync helpers (issue #289).

Pure logic, no IO: pack outbox events into byte-capped batches so a large
optics payload never pushes a POST past the SQS 256 KB message limit, guard
against a single oversized event, and split an over-limit gzipped log into
ordered chunks that share one sha256.
"""
import base64
import json
from typing import Any

MAX_MESSAGE_BYTES = 262_144  # SQS hard limit: 256 KiB
ENVELOPE_OVERHEAD_BYTES = 4_096  # headroom for the {device_id, events:[...]} wrapper
MAX_BATCH_BYTES = MAX_MESSAGE_BYTES - ENVELOPE_OVERHEAD_BYTES


def event_size_bytes(event: dict[str, Any]) -> int:
    """Serialised UTF-8 byte length of one event as it appears in the POST body."""
    return len(json.dumps(event).encode("utf-8"))


def partition_oversized(
    events: list[dict[str, Any]], max_bytes: int = MAX_BATCH_BYTES
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split events into (fittable, oversized), preserving order in each.

    An oversized event cannot fit in a message even alone; the caller
    quarantines it (leave pending, log loudly) rather than drop or truncate.
    """
    ok: list[dict[str, Any]] = []
    oversized: list[dict[str, Any]] = []
    for event in events:
        if event_size_bytes(event) > max_bytes:
            oversized.append(event)
        else:
            ok.append(event)
    return ok, oversized


def batch_events(
    events: list[dict[str, Any]], max_bytes: int
) -> list[list[dict[str, Any]]]:
    """Greedily pack events (each assumed to fit alone) into batches ≤ max_bytes.

    Id order is preserved. An event that fits alone but not alongside the
    current batch starts a new one — so a large optics event lands alone.
    """
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size = 0
    for event in events:
        size = event_size_bytes(event)
        if current and current_size + size > max_bytes:
            batches.append(current)
            current = []
            current_size = 0
        current.append(event)
        current_size += size
    if current:
        batches.append(current)
    return batches


def split_log(
    compressed: bytes, sha256: str, max_chunk_bytes: int = MAX_BATCH_BYTES
) -> list[dict[str, Any]]:
    """Split a gzipped log into ordered chunk payloads sharing one sha256.

    Each chunk carries a base64 slice of ``compressed``; concatenating the
    decoded slices in ``chunk_index`` order reconstructs the original bytes.
    A blob that fits in one chunk yields a single chunk with ``chunk_count`` 1.
    """
    # base64 expands 3 raw bytes into 4 chars, so slice on a multiple of 3 to
    # keep each encoded chunk within max_chunk_bytes (last chunk may be shorter).
    raw_per_chunk = (max_chunk_bytes // 4) * 3
    if raw_per_chunk <= 0:
        raise ValueError("max_chunk_bytes too small to hold any base64 payload")

    slices = [
        compressed[start : start + raw_per_chunk]
        for start in range(0, len(compressed) or 1, raw_per_chunk)
    ]
    count = len(slices)
    return [
        {
            "sha256": sha256,
            "chunk_index": index,
            "chunk_count": count,
            "data": base64.b64encode(piece).decode("ascii"),
        }
        for index, piece in enumerate(slices)
    ]
