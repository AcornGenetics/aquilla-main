"""Parse the on-device homing log into the SQLite outbox (issue #326, ADR-021).

motor_class writes Homing Samples as JSON lines to a dedicated homing log (#325).
This parser -- run in the backend, which owns the outbox -- reads that log and
enqueues each Sample as a ``homing_sample`` Event so it flushes upstream via the
existing Sync. It never talks to the motor process: both containers bind-mount
``logs/``, so the parser just reads the file the motor wrote.
"""
import json
import logging
import os

from aq_lib.homing_log import DEFAULT_LOG_DIR
from aquila_web.local_db import enqueue_event

logger = logging.getLogger("aquila")


def import_homing_samples(log_dir: str = DEFAULT_LOG_DIR) -> int:
    """Enqueue every Homing Sample in the homing log as a homing_sample Event.

    Returns the number of Samples newly enqueued.
    """
    inserted = 0
    # Oldest first: the rotated .1 holds Samples written before the active file.
    for name in ("homing.log.1", "homing.log"):
        path = os.path.join(log_dir, name)
        if not os.path.exists(path):
            continue
        with open(path) as fp:
            for line in fp:
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                    dedup_key = sample["id"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("Skipping malformed homing log line: %r", line[:200])
                    continue
                event_id = enqueue_event("homing_sample", sample, dedup_key=dedup_key)
                if event_id is not None:  # None -> already enqueued (dedup)
                    inserted += 1
    return inserted
