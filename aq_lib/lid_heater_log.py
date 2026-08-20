"""Lid Heater Sample emission (issue #452, ADR-022).

A Lid Heater Sample summarises one Sample Window of the lid heater's behaviour.
Each closed window is written as a JSON line to a dedicated ``aquila.lid_samples``
logger, kept separate from both ``logger.log`` and the lid heater's own debug log.

The device summarises but never judges: what counts as too cold, too wobbly or
too slow to climb lives in acorn-analytics read views. Emitting a Sample is a
local file append only -- no network, no database -- so it never stalls the
lid-heater control loop.
"""
import json
import logging
import os
from logging.handlers import RotatingFileHandler

LID_SAMPLE_LOGGER_NAME = "aquila.lid_samples"

DEFAULT_LOG_DIR = "logs/lid_heater"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB, matching the compose logging cap
DEFAULT_BACKUP_COUNT = 3


def _lid_sample_logger() -> logging.Logger:
    """The dedicated Sample logger, resolved fresh each call.

    Samples never propagate to the parent 'aquila' logger, so they stay out of
    logger.log -- and the lid heater's existing per-read debug lines stay out of
    the Sample log.
    """
    logger = logging.getLogger(LID_SAMPLE_LOGGER_NAME)
    logger.propagate = False
    return logger


def configure_lid_sample_logger(log_dir: str = DEFAULT_LOG_DIR,
                                max_bytes: int = DEFAULT_MAX_BYTES,
                                backup_count: int = DEFAULT_BACKUP_COUNT) -> str:
    """Attach the rotating file handler for the Sample log (idempotent).

    One JSON Sample per line, no text prefix -- the timestamp lives inside the
    JSON. Returns the log file path.
    """
    logger = _lid_sample_logger()
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "lid_samples.log")
    # Idempotent: drop any handler we previously attached before re-adding.
    for existing in list(logger.handlers):
        if getattr(existing, "_aquila_lid_sample", False):
            logger.removeHandler(existing)
            existing.close()
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._aquila_lid_sample = True  # tag so re-configuration is idempotent
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def emit_lid_sample(sample: dict) -> dict:
    """Write one Lid Heater Sample as a JSON line. Returns the Sample."""
    _lid_sample_logger().info(json.dumps(sample))
    return sample
