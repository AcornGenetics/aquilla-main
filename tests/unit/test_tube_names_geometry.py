"""Tube-name width derives from plate geometry, not a hardcoded 4
(#522 / Phase B, ADR-023)."""
import pytest

from aquila_web.main import _normalize_tube_names, _build_results
from aq_lib.geometry import PlateGeometry

FIFTEEN = PlateGeometry(rows=3, cols=5)
FOUR = PlateGeometry(rows=1, cols=4)


@pytest.mark.unit
def test_normalize_defaults_span_all_wells_for_fifteen(tmp_path):
    names = _normalize_tube_names(None, geo=FIFTEEN)
    assert names == [f"Tube {i}" for i in range(1, 16)]


@pytest.mark.unit
def test_normalize_pads_short_list_to_geometry_width():
    names = _normalize_tube_names(["A", "B"], geo=FIFTEEN)
    assert len(names) == 15
    assert names[:2] == ["A", "B"]
    assert names[2] == "Tube 3"  # fallback for the rest


@pytest.mark.unit
def test_normalize_caps_long_list_to_geometry_width():
    names = _normalize_tube_names([f"n{i}" for i in range(20)], geo=FOUR)
    assert names == ["n0", "n1", "n2", "n3"]


@pytest.mark.unit
def test_normalize_four_well_default_is_unchanged():
    # 4-well regression: byte-identical to the legacy DEFAULT_TUBE_NAMES.
    assert _normalize_tube_names(None, geo=FOUR) == ["Tube 1", "Tube 2", "Tube 3", "Tube 4"]


@pytest.mark.unit
def test_build_results_spans_all_wells_for_fifteen():
    results = _build_results([1, 15], geo=FIFTEEN)
    for row in ("1", "2"):
        assert sorted(results[row], key=int) == [str(c) for c in range(1, 16)]
    assert results["1"]["1"] == "Detected"
    assert results["1"]["15"] == "Detected"
    assert results["1"]["2"] == "Not Detected"


@pytest.mark.unit
def test_build_results_four_well_unchanged():
    # 4-well regression: exactly columns 1-4 in both rows.
    results = _build_results([2], geo=FOUR)
    for row in ("1", "2"):
        assert sorted(results[row], key=int) == ["1", "2", "3", "4"]
