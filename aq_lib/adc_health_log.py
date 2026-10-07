"""ADC health Sample emission (#528, Phase C — homing-error → QC hook).

The ADC read path already counts read-quality signals (RDY retries, stale frames,
never-ready reads, unrepairable sentinels — #517 Slice 3). Those used to land only
as aggregate text in ``logger.log``. This emits them as structured JSON Samples on
a dedicated ``aquila.adc_health`` logger, kept out of ``logger.log``, so downstream
can **correlate read quality against homing-position errors** (both carry a run +
position/time key) and disqualify optics samples taken after a motor stall.

The device samples but never judges (same contract as the Homing and Lid Samples,
ADR-021 / ADR-022): what counts as "too noisy to trust" lives in acorn-analytics.
Emitting a Sample is a local file append only — no network, no database — so it
never stalls the optics path. There is no ``motor.log``: homing stall telemetry
already lives in the homing log (ADR-021); this is the optics-side half.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

ADC_HEALTH_LOGGER_NAME = "aquila.adc_health"

DEFAULT_LOG_DIR = "logs/adc_health"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB, matching the compose logging cap
DEFAULT_BACKUP_COUNT = 3


def _adc_health_logger() -> logging.Logger:
    """The dedicated ADC-health logger, resolved fresh each call.

    ``propagate`` False keeps Samples out of logger.log; ``disabled`` is cleared
    on every resolve because ``logging.config.dictConfig`` (called at import by
    several modules) disables loggers it does not name, and telemetry that fails
    silently is worse than telemetry that fails loudly.
    """
    logger = logging.getLogger(ADC_HEALTH_LOGGER_NAME)
    logger.propagate = False
    logger.disabled = False
    return logger


def configure_adc_health_logger(log_dir: str = None,
                                max_bytes: int = DEFAULT_MAX_BYTES,
                                backup_count: int = DEFAULT_BACKUP_COUNT) -> str:
    """Attach the rotating file handler for the ADC-health log (idempotent).

    One JSON Sample per line, no text prefix — the timestamp lives inside the
    JSON. ``log_dir`` falls back to AQ_ADC_HEALTH_LOG_DIR then DEFAULT_LOG_DIR so
    the assay container that writes and the backend that drains agree. Returns
    the log file path."""
    logger = _adc_health_logger()
    log_dir = log_dir or os.getenv("AQ_ADC_HEALTH_LOG_DIR", DEFAULT_LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "adc_health.log")
    for existing in list(logger.handlers):
        if getattr(existing, "_aquila_adc_health", False):
            logger.removeHandler(existing)
            existing.close()
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._aquila_adc_health = True
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def emit_adc_health_sample(run_timestamp, position, *, n_stale_frames,
                           n_retries, n_failed_reads, n_unrepairable) -> dict:
    """Build an ADC health Sample and write it as one JSON line.

    Carries the run + position + time correlation key so the Sample can be joined
    downstream against the Homing Samples (by run and time/position) to flag reads
    taken after a stall. Returns the Sample dict written."""
    sample = {
        "id": uuid.uuid4().hex,
        "ts": _utc_now(),
        "run_timestamp": run_timestamp,
        "position": position,
        "n_stale_frames": int(n_stale_frames),
        "n_retries": int(n_retries),
        "n_failed_reads": int(n_failed_reads),
        "n_unrepairable": int(n_unrepairable),
    }
    _adc_health_logger().info(json.dumps(sample))
    return sample
