"""Homing Sample emission (issue #325, ADR-021).

A Homing Sample is a structured record of how a motor returned to its physical
home reference. Every ``Motor.home()`` emits exactly one Sample as a JSON line
to the dedicated ``aquila.homing`` logger, kept separate from ``logger.log``.

The device is a *dumb sampler*: it records the point and never judges it. Drift
and miss-rate are derived downstream by acorn-analytics from the Sample series.
Emitting a Sample is a local logging call only -- no network, no database -- so
it never stalls the motor-control loop.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

HOMING_LOGGER_NAME = "aquila.homing"

DEFAULT_LOG_DIR = "logs/homing"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB, matching the compose logging cap
DEFAULT_BACKUP_COUNT = 3

def _homing_logger() -> logging.Logger:
    """The dedicated homing logger, resolved fresh each call.

    Resolving via getLogger (rather than caching a module-global reference)
    keeps this correct if the logging registry is reconfigured. Homing Samples
    never propagate to the parent 'aquila' logger, so they stay out of
    logger.log (and everything else stays out of the homing log).
    """
    logger = logging.getLogger(HOMING_LOGGER_NAME)
    logger.propagate = False
    return logger


def configure_homing_logger(log_dir: str = DEFAULT_LOG_DIR,
                            max_bytes: int = DEFAULT_MAX_BYTES,
                            backup_count: int = DEFAULT_BACKUP_COUNT) -> str:
    """Attach the rotating file handler for the homing log (idempotent).

    Called once at process start. Writes one JSON Sample per line (no text
    prefix -- the timestamp lives inside the JSON), rotated at a bounded size so
    the log never fills the SD card. Returns the log file path.
    """
    logger = _homing_logger()
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "homing.log")
    # Idempotent: drop any handler we previously attached before re-adding.
    for existing in list(logger.handlers):
        if getattr(existing, "_aquila_homing", False):
            logger.removeHandler(existing)
            existing.close()
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._aquila_homing = True  # tag so re-configuration is idempotent
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def emit_homing_sample(motor: str, steps_to_flag: int, residual: int,
                       reached_home: bool) -> dict:
    """Build a Homing Sample and write it as one JSON line to the homing log.

    Returns the Sample dict (the same object written to the log).
    """
    sample = {
        "id": uuid.uuid4().hex,
        "ts": _utc_now(),
        "motor": motor,
        "steps_to_flag": int(steps_to_flag),
        "residual": int(residual),
        "reached_home": bool(reached_home),
    }
    _homing_logger().info(json.dumps(sample))
    return sample
