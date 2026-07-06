import base64
import binascii
import os
import logging
from typing import Any

import requests

from aquila_web.local_db import (
    get_pending_events,
    mark_event_quarantined,
    mark_event_synced,
)
from aquila_web.sync_batching import (
    batch_events,
    envelope_overhead_bytes,
    event_size_bytes,
    partition_oversized,
    split_log,
)

logger = logging.getLogger(__name__)

# SQS caps a single message at 256 KB; a batch that serializes past this is
# silently rejected. Overridable for tuning/tests via AQ_SYNC_MAX_MESSAGE_BYTES.
_SQS_MESSAGE_CEILING_BYTES = 256 * 1024

# Slack subtracted from a chunk's raw budget to absorb base64 padding and the
# extra digits chunk_index/chunk_count grow by as the chunk count climbs.
_CHUNK_SIZING_MARGIN_BYTES = 16

# A configured cap must leave at least this much room beyond the envelope for a
# real event; a cap barely above the envelope would mark every event oversized
# and quarantine the whole queue, so such a value is rejected as misconfiguration.
_MIN_EVENT_BUDGET_BYTES = 512


def _resolve_device_id() -> str | None:
    return os.getenv("AQ_SYNC_DEVICE_ID") or os.getenv("DEVICE_ID")


def _resolve_cert() -> tuple[str, str] | None:
    # The Sentri authenticates Sync with its Device Certificate (mTLS), not the
    # retired Fleet API Key (ADR-013). Cert/key paths are installed into
    # device.env at enrollment (#240); present them for the TLS handshake.
    client_cert = os.getenv("AQ_SYNC_CLIENT_CERT")
    client_key = os.getenv("AQ_SYNC_CLIENT_KEY")
    if client_cert and client_key:
        return (client_cert, client_key)
    # Fallback: if device.env is missing the cert vars (e.g. an enrollment that
    # predates #241, or a device.env rewrite that dropped them), present the cert
    # from its standard enrolled location. Without this, Sync silently POSTs
    # unauthenticated and the mTLS ingest edge resets the connection every flush.
    config_dir = os.getenv("CONFIG_DIR", "/opt/aquila/config")
    fallback_cert = os.path.join(config_dir, "device.crt")
    fallback_key = os.path.join(config_dir, "device.key")
    if os.path.exists(fallback_cert) and os.path.exists(fallback_key):
        return (fallback_cert, fallback_key)
    return None


def _resolve_max_message_bytes(device_id: str | None) -> int:
    """The per-message byte cap, defaulting to the SQS ceiling.

    A misconfigured ``AQ_SYNC_MAX_MESSAGE_BYTES`` (non-numeric, or too small to
    leave real room beyond the envelope) falls back to the real ceiling with a
    warning -- never crashes the flush, and never honours a cap so tight that
    every event is marked oversized and the whole queue is quarantined.
    """
    raw = os.getenv("AQ_SYNC_MAX_MESSAGE_BYTES")
    if raw is None:
        return _SQS_MESSAGE_CEILING_BYTES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "AQ_SYNC_MAX_MESSAGE_BYTES=%r is not an integer; using %d",
            raw, _SQS_MESSAGE_CEILING_BYTES,
        )
        return _SQS_MESSAGE_CEILING_BYTES
    minimum = envelope_overhead_bytes(device_id) + _MIN_EVENT_BUDGET_BYTES
    if value < minimum:
        logger.warning(
            "AQ_SYNC_MAX_MESSAGE_BYTES=%d leaves too little room (min %d); using %d",
            value, minimum, _SQS_MESSAGE_CEILING_BYTES,
        )
        return _SQS_MESSAGE_CEILING_BYTES
    return value


def _chunk_event(event: dict, descriptor: dict) -> dict:
    """One chunk Event: the source event with its payload's blob fields replaced
    by this chunk's ``data_b64`` / ``chunk_index`` / ``chunk_count`` / ``sha256``."""
    payload = {
        **(event.get("payload") or {}),
        "sha256": descriptor["sha256"],
        "chunk_index": descriptor["chunk_index"],
        "chunk_count": descriptor["chunk_count"],
        "data_b64": descriptor["data_b64"],
    }
    return {**event, "payload": payload}


def _chunk_events(event: dict, cap: int, device_id: str | None) -> list[dict] | None:
    """Split one oversized Event into chunk Events, or ``None`` if unsplittable.

    Only a gzipped optics log carries a blob (``data_b64`` + ``sha256``) that can
    be sliced; anything else has nothing to chunk and must be quarantined instead.
    Each raw slice is sized so its chunk Event fits in a POST alone; if even the
    non-blob fields already fill a message, or any built chunk still overflows,
    returns ``None`` so the caller quarantines rather than emit a bad POST.
    """
    payload = event.get("payload") or {}
    data_b64 = payload.get("data_b64")
    sha256 = payload.get("sha256")
    if not data_b64 or not sha256:
        return None
    try:
        blob = base64.b64decode(data_b64)
    except (ValueError, binascii.Error):
        return None

    fits_alone = cap - envelope_overhead_bytes(device_id)
    empty = _chunk_event(event, {"sha256": sha256, "chunk_index": 0, "chunk_count": 0, "data_b64": ""})
    budget_for_b64 = fits_alone - event_size_bytes(empty) - _CHUNK_SIZING_MARGIN_BYTES
    if budget_for_b64 < 4:
        return None  # non-blob fields alone already fill a message
    max_chunk_raw = (budget_for_b64 * 3) // 4
    if max_chunk_raw < 1:
        return None

    chunks = [_chunk_event(event, d) for d in split_log(blob, sha256, max_chunk_raw)]
    # Defence in depth: never emit a chunk that itself exceeds the ceiling.
    if any(event_size_bytes(c) > fits_alone for c in chunks):
        return None
    return chunks


def _post_batch(endpoint: str, body: dict[str, Any], cert, timeout: int) -> bool:
    """POST one batch; True on success, False on network error (caller retries)."""
    try:
        response = requests.post(endpoint, json=body, cert=cert, timeout=timeout)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as exc:
        logger.warning("Sync failed (will retry next interval): %s", exc)
        return False


def sync_pending_events(
    endpoint: str | None = None,
    batch_size: int | None = None,
    timeout_seconds: int | None = None,
) -> int:
    resolved_endpoint = endpoint or os.getenv("AQ_SYNC_ENDPOINT")
    if not resolved_endpoint:
        return 0
    resolved_batch_size = batch_size or int(os.getenv("AQ_SYNC_BATCH_SIZE", "100"))
    resolved_timeout = timeout_seconds or int(os.getenv("AQ_SYNC_TIMEOUT_SECONDS", "10"))
    device_id = _resolve_device_id()
    cap = _resolve_max_message_bytes(device_id)
    cert = _resolve_cert()

    pending_events = get_pending_events(resolved_batch_size)
    if not pending_events:
        return 0

    syncable, oversized = partition_oversized(pending_events, cap, device_id)

    # Size guard: an event too large to POST even alone is either split into
    # chunk events (a gzipped optics log) or, if it has no blob to chunk,
    # quarantined -- retained and logged loudly, never dropped or truncated, and
    # never allowed to block the healthy events behind it.
    split_groups: list[tuple[dict, list[dict]]] = []
    for event in oversized:
        chunks = _chunk_events(event, cap, device_id)
        if chunks is None:
            reason = f"event {event['id']} exceeds {cap} B and cannot be split"
            logger.error("Sync size guard: quarantining %s", reason)
            mark_event_quarantined(event["id"], reason)
        else:
            split_groups.append((event, chunks))

    synced = 0

    # Normal events: each byte-capped batch is one POST, marked synced on success.
    for batch in batch_events(syncable, cap, device_id):
        body: dict[str, Any] = {"device_id": device_id, "events": batch}
        if not _post_batch(resolved_endpoint, body, cert, resolved_timeout):
            # Batches already POSTed stay synced; the rest stay pending. Never
            # lose or double-mark events.
            return synced
        mark_event_synced([event["id"] for event in batch])
        synced += len(batch)

    # Split events: POST every chunk before marking the source synced, so a
    # mid-split network drop leaves the source pending to be re-split next flush
    # rather than half-delivered-and-marked-done.
    for source, chunks in split_groups:
        delivered = True
        for batch in batch_events(chunks, cap, device_id):
            body = {"device_id": device_id, "events": batch}
            if not _post_batch(resolved_endpoint, body, cert, resolved_timeout):
                delivered = False
                break
        if not delivered:
            return synced
        mark_event_synced([source["id"]])
        synced += 1

    if synced:
        logger.info("Synced %s events", synced)
    return synced
