"""
Unit tests for instrument Plate Geometry + the geometry() read spine
(Phase A, Slices 1-2, #502 / #503).

The device's well count comes from an immutable identity record; geometry()
resolves it to a purely-logical PlateGeometry. 4-well is the baseline build;
15-well (3x5) is the Mk II build. A malformed record fails loud; an absent one
defaults to 4-well.
"""
import json
from pathlib import Path

import pytest

from aq_lib import geometry as geometry_mod
from aq_lib.geometry import (
    GEOMETRIES,
    PlateGeometry,
    assert_axis_positions_match,
    geometry,
    validate_registry,
)

def _shipped_axis_positions():
    """The real measured axis stops from the repo's 4-well host_config.json —
    read, not hardcoded, so this stays a genuine 4-well regression guard.
    axis.positions was renamed axis.stops in the 2-D coordinate schema (#510)."""
    cfg = json.loads(
        (Path(__file__).resolve().parents[2] / "config_files" / "host_config.json")
        .read_text()
    )
    device = next(iter(cfg.values()))
    return device["axis"]["stops"]


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


def test_four_well_sensor_gap_defaults_to_two():
    # The FAM/ROX carriage offset the 4-well profile has always used.
    assert PlateGeometry(rows=1, cols=4).sensor_gap == 2


def test_tube_at_maps_rox_to_its_stop_and_fam_to_the_gap_shifted_stop():
    # ROX reads the column at its own carriage stop; FAM trails by sensor_gap,
    # so the SAME tube's FAM capture happens `sensor_gap` stops later. The
    # inverse — (row, stop, dye) -> tube id — is what labels a capture.
    geo = PlateGeometry(rows=3, cols=5)  # sensor_gap 2
    assert geo.tube_at(row=0, stop=0, dye="rox") == "1A"
    assert geo.tube_at(row=0, stop=2, dye="fam") == "1A"  # same tube, 2 stops later
    assert geo.tube_at(row=1, stop=4, dye="rox") == "5B"
    assert geo.tube_at(row=2, stop=6, dye="fam") == "5C"


def test_read_plan_reads_every_fifteen_well_tube_in_both_dyes_exactly_once():
    # Coverage: the generated plan, labelled through tube_at, touches all 15
    # tubes and captures each in BOTH dyes — no tube missed, none doubled.
    from aq_lib.optics_read_plan import read_plan

    geo = PlateGeometry(rows=3, cols=5)
    seen: dict[str, list[str]] = {}
    for (stop, row), dyes in read_plan(geo):
        # 15-well is dual-ADC 'both': one capture reads ROX+FAM simultaneously.
        # Expand it to the real tubes each sensor sees at this stop (overhang
        # stops see only one; the other read is discarded) — ROX at stops
        # [0,cols), FAM at [sensor_gap, sensor_gap+cols).
        if dyes == ("both",):
            channels = []
            if 0 <= stop < geo.cols:
                channels.append("rox")
            if geo.sensor_gap <= stop < geo.sensor_gap + geo.cols:
                channels.append("fam")
        else:
            channels = dyes
        for dye in channels:
            seen.setdefault(geo.tube_at(row=row, stop=stop, dye=dye), []).append(dye)

    # Every tube captured in BOTH dyes exactly once — no tube missed, none doubled.
    assert set(seen) == set(geo.tube_ids)
    assert all(sorted(d) == ["fam", "rox"] for d in seen.values())


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


def test_shipped_four_well_host_config_matches_the_four_well_geometry():
    # The real 4-well host_config has cols(4) + sensor_gap(2) = 6 stops — a
    # match, so the check returns normally (no raise). Doubles as a guard that
    # the shipped 4-well config stays consistent with the 4-well geometry.
    assert_axis_positions_match(GEOMETRIES[4], _shipped_axis_positions())


def test_mismatched_axis_positions_fail_loud():
    # The issue's example: a 15-well unit whose host_config still only carries
    # the 4-well axis stops (6, not 5+2=7). Fail loud before the motor drives to
    # positions that don't exist.
    with pytest.raises(ValueError):
        assert_axis_positions_match(GEOMETRIES[15], _shipped_axis_positions())
