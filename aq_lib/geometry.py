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
    sensor_gap: int = 2  # FAM/ROX carriage-stop offset: the two optical sensors
    # sit this many stops apart, so a row sweeps cols + sensor_gap carriage stops
    # and each dye reads a window of columns offset by the gap. Logical only —
    # the measured step for each stop lives in host_config.json, read by the motor.
    # 2 for both current builds.

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

    def tube_at(self, row: int, stop: int, dye: str) -> str:
        """The tube id whose ``dye`` is captured at carriage ``stop`` in drawer
        ``row``. ROX reads the column at its own stop; FAM trails by
        ``sensor_gap``, so it reads the column ``sensor_gap`` stops back. This
        inverts ``read_plan`` — it labels a capture with the tube it belongs to."""
        col = stop if dye == "rox" else stop - self.sensor_gap
        return self._tube_id(row, col)

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


def assert_axis_positions_match(geo: PlateGeometry, positions) -> None:
    """Consistency check between the device's declared geometry and the measured
    axis stops it reads from host_config.json. The motor still owns those
    positions — this only asserts their shape: one stop per column plus the
    sensor gap. A mismatch (e.g. a 15-well unit still carrying the 4-well stops)
    fails loud before the motor drives to positions that don't exist."""
    expected = geo.cols + geo.sensor_gap
    actual = len(positions)
    if actual != expected:
        logger.error(
            "host_config axis positions (%d) do not match geometry: "
            "cols(%d) + sensor_gap(%d) = %d. Halting — re-calibrate or "
            "re-provision this device.",
            actual, geo.cols, geo.sensor_gap, expected,
        )
        raise ValueError(
            f"host_config has {actual} axis positions but the "
            f"{geo.well_count}-well geometry expects {expected} "
            f"(cols={geo.cols} + sensor_gap={geo.sensor_gap})"
        )


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
