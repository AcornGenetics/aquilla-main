"""Parse the on-device Lid Heater Sample log into the SQLite outbox (#452, ADR-022).

The lid-heater worker writes a Sample per closed Sample Window as a JSON line
(``aq_lib/lid_heater_log``), but it runs in the assay container and cannot reach
the outbox -- ``app.db`` is mounted only on the backend. The shared ``logs/``
directory is the seam, exactly as it is for Homing Samples (ADR-021), and this
parser runs on the backend's sync cadence.

Exactly-once is a property of the data: each Sample's ``sample_id`` backs the
UNIQUE dedup_key, so re-scanning a log or crossing a rotation is a no-op.
"""
import json
import logging
import os

from aq_lib.lid_heater_log import DEFAULT_LOG_DIR
from aquila_web.local_db import enqueue_event

logger = logging.getLogger("aquila")


def import_lid_samples(log_dir: str = DEFAULT_LOG_DIR) -> int:
    """Enqueue every Lid Heater Sample in the log as a lid_heater_sample Event.

    Returns the number of Samples newly enqueued.
    """
    inserted = 0
    # Oldest first: the rotated .1 holds Samples written before the active file.
    for name in ("lid_samples.log.1", "lid_samples.log"):
        path = os.path.join(log_dir, name)
        if not os.path.exists(path):
            continue
        with open(path) as fp:
            for line in fp:
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                    dedup_key = sample["sample_id"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("Skipping malformed lid sample line: %r", line[:200])
                    continue
                event_id = enqueue_event("lid_heater_sample", sample, dedup_key=dedup_key)
                if event_id is not None:  # None -> already enqueued (dedup)
                    inserted += 1
    return inserted
