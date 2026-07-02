"""
optics_readings capture (#288).

Builds the frozen device->cloud ``optics_readings`` payload
(AcornGenetics/acorn-analytics#45) from a completed run's optics log: the raw
file is hashed and gzipped whole (ADR-0007 stores it, never re-analyses it), and
a completeness signal is derived from the data-row count.
"""
import base64
import gzip
import hashlib
from pathlib import Path

# Samples written per blink -- fixed in the device's capture_blink (for j in range(60)).
SAMPLES_PER_BLINK = 60


def expected_lines(read_passes: int, reads_per_cycle: int) -> int:
    """Data rows a full run should emit (frozen constant, acorn-analytics#45).

    A run captures ``read_passes`` optical passes (a baseline pass + one per
    cycle), each firing ``reads_per_cycle`` blinks (8 for the standard rox/fam
    profile), each blink writing ``SAMPLES_PER_BLINK`` rows. The device computes
    this from its profile rather than hardcoding 480, which is only the
    per-pass count for the standard 2-channel profile.
    """
    return read_passes * reads_per_cycle * SAMPLES_PER_BLINK


def _count_rows(text: str) -> int:
    """Data rows only: non-empty lines that are not # comments/headers."""
    return sum(1 for line in text.splitlines() if line and not line.startswith("#"))


def count_data_lines(optics_path: str | Path) -> int:
    """Count data rows in an optics log (non-empty rows, excluding # headers).

    Returns 0 when the file is missing. This is the ``line_count`` the frozen
    contract compares against ``expected_lines`` for the completeness signal.
    """
    path = Path(optics_path)
    if not path.exists():
        return 0
    return _count_rows(path.read_bytes().decode("utf-8", errors="replace"))


def build_optics_readings(
    optics_path: str | Path,
    run_timestamp: str,
    expected_lines: int,
    aborted: bool,
) -> dict | None:
    """Build the frozen ``optics_readings`` payload from a run's optics log.

    Returns ``None`` when an aborted run produced no capture at all (the optics
    file is missing or holds no data rows) so the cloud coverage view shows the
    run as genuinely missing rather than as an empty-but-present capture.
    """
    path = Path(optics_path)
    raw = path.read_bytes() if path.exists() else b""
    line_count = _count_rows(raw.decode("utf-8", errors="replace"))
    if aborted and line_count == 0:
        return None
    return {
        "run_timestamp": run_timestamp,
        "filename": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "line_count": line_count,
        "expected_lines": expected_lines,
        "complete": line_count == expected_lines,
        "aborted": aborted,
        "chunk_index": 0,
        "chunk_count": 1,
        "data_b64": base64.b64encode(gzip.compress(raw)).decode("ascii"),
    }
