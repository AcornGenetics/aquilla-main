"""Bind measured motor steps (host_config.json) to plate geometry (#510).

The logical *shape* is a PlateGeometry; the *measured* carriage steps and drawer
read positions are per-device calibration in host_config.json. These resolvers
validate one against the other and FAIL LOUD on mismatch, so a device whose
host_config doesn't match its provisioned geometry raises at motor load rather
than driving to carriage stops that don't exist. Hardware-free: takes plain
config dicts, so it unit-tests without GPIO.
"""
from aq_lib.geometry import PlateGeometry, assert_axis_positions_match


def axis_stops(axis_config: dict, geo: PlateGeometry) -> list[int]:
    """Ordered axis carriage steps for ``geo``. A row sweeps ``cols + sensor_gap``
    stops (columns + the FAM/ROX offset), so that many measured steps must be
    present. Delegates the shape check to ``assert_axis_positions_match`` (#505),
    the single source of truth for the axis-count consistency assert, then returns
    the validated list. Raises ``ValueError`` on a count mismatch."""
    stops = list(axis_config["stops"])
    assert_axis_positions_match(geo, stops)
    return stops


def drawer_rows(drawer_config: dict, geo: PlateGeometry) -> list[int]:
    """Drawer read positions ordered by plate row (A, B, C, …). One measured
    step per row; ``geo.rows`` of them. Raises ``ValueError`` on a count
    mismatch or a missing row label."""
    rows = drawer_config["rows"]
    if len(rows) != geo.rows:
        raise ValueError(
            f"host_config drawer.rows has {len(rows)} positions but geometry "
            f"needs {geo.rows}"
        )
    labels = [chr(ord("A") + i) for i in range(geo.rows)]
    try:
        return [rows[label] for label in labels]
    except KeyError as exc:
        raise ValueError(
            f"host_config drawer.rows missing row {exc.args[0]!r}; "
            f"expected labels {labels}"
        ) from exc
