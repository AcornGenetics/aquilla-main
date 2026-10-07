"""Bind measured motor steps (host_config.json) to plate geometry (#510).

The logical *shape* is a PlateGeometry; the *measured* carriage steps and drawer
read positions are per-device calibration in host_config.json. These resolvers
validate one against the other and FAIL LOUD on mismatch, so a device whose
host_config doesn't match its provisioned geometry raises at motor load rather
than driving to carriage stops that don't exist. Hardware-free: takes plain
config dicts, so it unit-tests without GPIO.
"""
from aq_lib.geometry import PlateGeometry, assert_axis_positions_match


def axis_stops(axis_config: dict, geo: PlateGeometry):
    """Measured axis carriage steps for ``geo``, accepting either calibration form
    (#526). A row sweeps ``cols + sensor_gap`` stops (columns + the FAM/ROX
    offset), so each list must be that many steps.

    - **Shared** (flat list): the same X-stops at every row — returned as the flat
      list (4-well and 15-well-separable; byte-identical to before).
    - **Per-row** (dict ``{"A":[…],"B":[…],…}``): the X-stops measured per row when
      the carriage drifts between rows — returned as a list-of-lists ordered by
      plate row.

    Delegates the per-list count check to ``assert_axis_positions_match`` (#505).
    Raises ``ValueError`` on a count mismatch, a wrong row count, or a missing
    row label."""
    stops = axis_config["stops"]
    if isinstance(stops, dict):
        labels = [chr(ord("A") + i) for i in range(geo.rows)]
        if len(stops) != geo.rows:
            raise ValueError(
                f"host_config axis.stops has {len(stops)} rows but geometry "
                f"needs {geo.rows}"
            )
        try:
            per_row = [list(stops[label]) for label in labels]
        except KeyError as exc:
            raise ValueError(
                f"host_config axis.stops missing row {exc.args[0]!r}; "
                f"expected labels {labels}"
            ) from exc
        for row_stops in per_row:
            assert_axis_positions_match(geo, row_stops)
        return per_row
    stops = list(stops)
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
