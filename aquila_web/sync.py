import os
import logging
from typing import Any

import requests

from aquila_web.local_db import get_pending_events, mark_event_synced
from aquila_web.sync_batching import (
    MAX_BATCH_BYTES,
    batch_events,
    event_size_bytes,
    partition_oversized,
)

logger = logging.getLogger(__name__)


def _resolve_max_batch_bytes() -> int:
    """Byte cap for the events in one POST body, overridable for tests/tuning."""
    override = os.getenv("AQ_SYNC_MAX_MESSAGE_BYTES")
    return int(override) if override else MAX_BATCH_BYTES


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
    pending_events = get_pending_events(resolved_batch_size)
    if not pending_events:
        return 0

    device_id = os.getenv("AQ_SYNC_DEVICE_ID") or os.getenv("DEVICE_ID")
    # The Sentri authenticates Sync with its Device Certificate (mTLS), not the
    # retired Fleet API Key (ADR-013). Cert/key paths are installed into
    # device.env at enrollment (#240); present them for the TLS handshake.
    cert = None
    client_cert = os.getenv("AQ_SYNC_CLIENT_CERT")
    client_key = os.getenv("AQ_SYNC_CLIENT_KEY")
    if client_cert and client_key:
        cert = (client_cert, client_key)

    # Size guard (#289): an event too large to fit even alone is quarantined —
    # left pending, never truncated — so one poison payload cannot silently
    # corrupt the queue or block healthy events behind it.
    max_batch_bytes = _resolve_max_batch_bytes()
    fittable, oversized = partition_oversized(pending_events, max_batch_bytes)
    for event in oversized:
        logger.error(
            "Oversized event id=%s (%d bytes) exceeds cap %d — quarantined "
            "(left pending, not truncated)",
            event["id"],
            event_size_bytes(event),
            max_batch_bytes,
        )

    # Byte-capped batching (#289): a large optics payload lands alone in its own
    # POST rather than pushing a shared batch past the SQS 256 KB message limit.
    synced_count = 0
    for batch in batch_events(fittable, max_batch_bytes):
        payload: dict[str, Any] = {"device_id": device_id, "events": batch}
        try:
            response = requests.post(
                resolved_endpoint, json=payload, cert=cert, timeout=resolved_timeout
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.warning("Sync failed (will retry next interval): %s", exc)
            break  # leave this and later batches pending; keep what already synced
        mark_event_synced([event["id"] for event in batch])
        synced_count += len(batch)

    if synced_count:
        logger.info("Synced %s events", synced_count)
    return synced_count
