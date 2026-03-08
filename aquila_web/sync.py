import os
import logging
from typing import Any

import requests

from aquila_web.local_db import get_pending_events, mark_event_synced

logger = logging.getLogger(__name__)


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
    payload: dict[str, Any] = {
        "device_id": os.getenv("AQ_SYNC_DEVICE_ID") or os.getenv("DEVICE_ID"),
        "events": pending_events,
    }
    response = requests.post(resolved_endpoint, json=payload, timeout=resolved_timeout)
    response.raise_for_status()
    mark_event_synced([event["id"] for event in pending_events])
    logger.info("Synced %s events", len(pending_events))
    return len(pending_events)
