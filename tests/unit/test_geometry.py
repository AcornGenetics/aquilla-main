"""
Unit tests for instrument Plate Geometry + the geometry() read spine
(Phase A, Slices 1-2, #502 / #503).

The device's well count comes from an immutable identity record; geometry()
resolves it to a purely-logical PlateGeometry. 4-well is the baseline build;
15-well (3x5) is the Mk II build. A malformed record fails loud; an absent one
defaults to 4-well.
"""
import json

import pytest

from aq_lib import geometry as geometry_mod
from aq_lib.geometry import GEOMETRIES, PlateGeometry, geometry, validate_registry


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point geometry() at an isolated config dir and clear the read cache so
    each test resolves the identity file fresh."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    geometry_mod._read_identity.cache_clear()
    yield tmp_path
    geometry_mod._read_identity.cache_clear()


def _write_identity(config_dir, wells):
    (config_dir / "device_identity.json").write_text(json.dumps({"wells": wells}))


def _write_raw_identity(config_dir, text):
    (config_dir / "device_identity.json").write_text(text)


def test_four_well_registry_entry_is_one_by_four():
    geo = GEOMETRIES[4]
    assert (geo.rows, geo.cols) == (1, 4)
    assert geo.well_count == 4


def test_four_well_tube_ids_are_column_then_row():
    assert GEOMETRIES[4].tube_ids == ["1A", "2A", "3A", "4A"]


def test_four_well_scan_order_is_single_row_left_to_right():
    assert GEOMETRIES[4].scan_order == ["1A", "2A", "3A", "4A"]


def test_fifteen_well_registry_entry_is_three_by_five():
    geo = GEOMETRIES[15]
    assert (geo.rows, geo.cols) == (3, 5)
    assert geo.well_count == 15


def test_scan_order_serpentines_across_rows():
    # Row A left-to-right, row B right-to-left, row C left-to-right — the
    # motor never doubles back to the start of a row.
    geo = PlateGeometry(rows=3, cols=5)
    assert geo.scan_order == [
        "1A", "2A", "3A", "4A", "5A",
        "5B", "4B", "3B", "2B", "1B",
        "1C", "2C", "3C", "4C", "5C",
    ]


def test_tube_ids_stay_row_major_regardless_of_scan_order():
    # Identity labels are column-then-row, row-major — the serpentine is a
    # traversal concern, not an identity one.
    geo = PlateGeometry(rows=3, cols=5)
    assert geo.tube_ids == [
        "1A", "2A", "3A", "4A", "5A",
        "1B", "2B", "3B", "4B", "5B",
        "1C", "2C", "3C", "4C", "5C",
    ]


def test_shipping_registry_satisfies_the_well_count_invariant():
    # No raise: every entry's derived well_count equals its key.
    validate_registry(GEOMETRIES)


def test_registry_entry_whose_well_count_mismatches_its_key_is_rejected():
    with pytest.raises(ValueError):
        validate_registry({4: PlateGeometry(rows=2, cols=3)})  # well_count 6 != 4


def test_geometry_defaults_to_four_well_when_identity_file_is_absent(config_dir):
    # 4-well is the baseline build: an un-provisioned device must still run.
    assert geometry() is GEOMETRIES[4]


def test_geometry_resolves_the_provisioned_well_count_from_the_identity_file(config_dir):
    # 15 (not the 4-well default) proves the file is actually read.
    _write_identity(config_dir, 15)
    assert geometry() is GEOMETRIES[15]


def test_geometry_reads_the_identity_file_once_and_caches_it(config_dir):
    # First resolve (no file) caches the 4-well default; a later file write
    # must not change the answer for a running process.
    assert geometry() is GEOMETRIES[4]
    _write_identity(config_dir, 15)
    assert geometry() is GEOMETRIES[4]


def test_geometry_halts_loud_on_an_unknown_well_count(config_dir, caplog):
    # A typo/mis-provision (5, 150, …) is not a known geometry: fail loud and
    # log — trusted flag, no hardware cross-check to fall back on.
    _write_identity(config_dir, 7)
    with pytest.raises(ValueError, match="7"):
        geometry()
    assert "7" in caplog.text


def test_geometry_halts_loud_on_a_malformed_identity_file(config_dir, caplog):
    # A present-but-corrupt record is NOT an un-provisioned device: fail loud
    # rather than silently defaulting to 4-well and driving the wrong plate.
    _write_raw_identity(config_dir, "{not valid json")
    with pytest.raises(ValueError):
        geometry()
    assert "device_identity.json" in caplog.text


def test_geometry_halts_loud_when_the_well_count_is_missing(config_dir, caplog):
    # Valid JSON but no "wells" key — the record exists but doesn't name a
    # geometry. Must fail loud, not default.
    _write_raw_identity(config_dir, '{"schema": 1}')
    with pytest.raises(ValueError):
        geometry()
    assert "device_identity.json" in caplog.text
