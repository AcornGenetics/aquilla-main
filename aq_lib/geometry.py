"""Instrument Plate Geometry — the single source of truth for a Sentri's well
layout (Phase A, Slice 1, #502).

The device's well count is provisioned once into an immutable identity record;
``geometry()`` resolves it to a purely-logical ``PlateGeometry``. Geometry holds
no measured motor steps — those stay in ``host_config.json``, read by the motor.
"""
import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlateGeometry:
    rows: int
    cols: int

    @property
    def well_count(self) -> int:
        return self.rows * self.cols

    @property
    def tube_ids(self) -> list[str]:
        # Column-then-row labels, row-major: "1A".."{cols}{last row letter}".
        return [
            self._tube_id(row, col)
            for row in range(self.rows)
            for col in range(self.cols)
        ]

    @property
    def scan_order(self) -> list[str]:
        # Serpentine traversal: alternate rows reverse direction so the motor
        # never doubles back to the start of a row. Row 0 left-to-right.
        order = []
        for row in range(self.rows):
            cols = range(self.cols) if row % 2 == 0 else reversed(range(self.cols))
            for col in cols:
                order.append(self._tube_id(row, col))
        return order

    def _tube_id(self, row: int, col: int) -> str:
        return f"{col + 1}{chr(ord('A') + row)}"


GEOMETRIES = {
    4: PlateGeometry(rows=1, cols=4),
    15: PlateGeometry(rows=3, cols=5),
}


def validate_registry(geometries: dict[int, PlateGeometry]) -> None:
    """Enforce the load-time invariant: every entry's derived well_count equals
    its key. A same-count/different-layout build is the only reason to revisit
    the one-geometry-per-well-count assumption; a mismatch here is a coding
    error in the registry, so we fail loud."""
    for key, geo in geometries.items():
        if geo.well_count != key:
            raise ValueError(
                f"registry key {key} != geometry well_count {geo.well_count} "
                f"(rows={geo.rows}, cols={geo.cols})"
            )


# Fail loud at import if the shipping registry ever violates the invariant.
validate_registry(GEOMETRIES)


DEFAULT_WELLS = 4  # An un-provisioned device is the 4-well baseline build.


@lru_cache(maxsize=None)
def _read_identity(config_dir: str) -> int:
    """Read the well count from the immutable device_identity.json under
    config_dir. Cached per config_dir so the identity file is read once.

    Absent file ⇒ the 4-well default (an un-provisioned device still runs). A
    present-but-malformed file (bad JSON, or no "wells" key) is NOT absent — it
    fails loud rather than silently defaulting and driving the wrong plate."""
    path = os.path.join(config_dir, "device_identity.json")
    try:
        with open(path, "r") as fp:
            record = json.load(fp)
    except FileNotFoundError:
        return DEFAULT_WELLS
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Malformed device_identity.json at %s: %s. Halting.", path, exc)
        raise ValueError(f"malformed device_identity.json at {path}: {exc}") from exc

    try:
        return record["wells"]
    except (KeyError, TypeError) as exc:
        logger.error(
            "device_identity.json at %s has no 'wells' well count. Halting.", path
        )
        raise ValueError(
            f"device_identity.json at {path} is missing the 'wells' well count"
        ) from exc


def geometry() -> PlateGeometry:
    """Resolve this device's PlateGeometry from its immutable identity record.

    Reads ONLY device_identity.json (via CONFIG_DIR); never touches
    host_config. An absent file defaults to 4-well; an unknown well count fails
    loud (no hardware cross-check — a trusted flag)."""
    config_dir = os.environ.get("CONFIG_DIR", "config_files")
    wells = _read_identity(config_dir)
    if wells not in GEOMETRIES:
        logger.error(
            "Unknown well count %r in device_identity.json; known counts: %s. "
            "Halting — re-provision the device.",
            wells,
            sorted(GEOMETRIES),
        )
        raise ValueError(
            f"unknown well count {wells!r}; known counts: {sorted(GEOMETRIES)}"
        )
    return GEOMETRIES[wells]
