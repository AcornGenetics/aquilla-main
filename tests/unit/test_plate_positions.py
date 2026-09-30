"""
Unit tests for resolving measured motor steps against plate geometry (#510).

The logical shape lives in PlateGeometry; the MEASURED carriage steps live in
host_config.json. These resolvers bind the two and FAIL LOUD when a device's
host_config doesn't match its provisioned geometry — a 15-well unit with a
6-stop 4-well config must raise at load, not misdrive the axis mid-run.
"""
import pytest

from aq_lib.geometry import GEOMETRIES, PlateGeometry
from aq_lib.plate_positions import axis_stops, drawer_rows

# Today's shipping 4-well carriage steps (cols 4 + 2-stop sensor gap = 6).
FOUR_WELL_STOPS = [320, 675, 1030, 1380, 1740, 2080]


def test_axis_stops_returns_the_configured_stops_when_the_count_matches():
    axis = {"stops": FOUR_WELL_STOPS}
    assert axis_stops(axis, GEOMETRIES[4]) == FOUR_WELL_STOPS


def test_axis_stops_accepts_the_fifteen_well_seven_stop_config():
    axis = {"stops": [320, 675, 1030, 1380, 1740, 2080, 2420]}
    assert axis_stops(axis, GEOMETRIES[15]) == [320, 675, 1030, 1380, 1740, 2080, 2420]


def test_axis_stops_fails_loud_when_stop_count_mismatches_geometry():
    # 15-well geometry (needs cols+gap = 7) against a 6-stop 4-well config.
    axis = {"stops": FOUR_WELL_STOPS}
    with pytest.raises(ValueError, match="7"):
        axis_stops(axis, GEOMETRIES[15])


def test_drawer_rows_orders_the_read_positions_by_plate_row():
    drawer = {"rows": {"A": 115, "B": 435, "C": 755}}
    assert drawer_rows(drawer, GEOMETRIES[15]) == [115, 435, 755]


def test_drawer_rows_orders_by_label_not_dict_insertion():
    # Serpentine/out-of-order authoring must still resolve A, B, C in order.
    drawer = {"rows": {"C": 755, "A": 115, "B": 435}}
    assert drawer_rows(drawer, GEOMETRIES[15]) == [115, 435, 755]


def test_drawer_rows_fails_loud_when_row_count_mismatches_geometry():
    # 15-well needs 3 rows; a single-row 4-well drawer block must raise.
    with pytest.raises(ValueError, match="3"):
        drawer_rows({"rows": {"A": 152}}, GEOMETRIES[15])


def test_drawer_rows_fails_loud_when_a_row_label_is_missing():
    # Right count, wrong labels (no "C") — still a misconfiguration.
    with pytest.raises(ValueError, match="C"):
        drawer_rows({"rows": {"A": 115, "B": 435, "X": 755}}, GEOMETRIES[15])


def test_four_well_drawer_resolves_its_single_read_position():
    # 4-well is the degenerate 1-row plate: one read position, labelled A.
    assert drawer_rows({"rows": {"A": 152}}, GEOMETRIES[4]) == [152]
