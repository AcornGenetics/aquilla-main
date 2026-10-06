"""Unit tests for aq_curve.plot_utils.generate_optics_plot — well count derives
from plate geometry, not a hardcoded 4 (#521 / Phase B)."""
import numpy as np
import pytest

import aq_curve.plot_utils as plot_utils
from aq_lib.geometry import PlateGeometry


def _count_wells(tmp_path, monkeypatch, geo):
    calls = []

    def fake_get_curve_data(_curve, _path, dye, well):
        calls.append((dye, well))
        return np.array([]), np.array([]), np.array([])

    monkeypatch.setattr(plot_utils, "get_curve_data", fake_get_curve_data)
    monkeypatch.setattr(plot_utils, "_max_cycle_from_log", lambda _p: 40.0)
    plot_utils.generate_optics_plot("ignored.log", str(tmp_path / "plot.png"), geo=geo)
    return sorted({w for _dye, w in calls})


@pytest.mark.unit
def test_plot_draws_all_wells_for_fifteen_well_geometry(tmp_path, monkeypatch):
    wells = _count_wells(tmp_path, monkeypatch, PlateGeometry(rows=3, cols=5))
    assert wells == list(range(1, 16))


@pytest.mark.unit
def test_plot_draws_four_wells_for_four_well_geometry(tmp_path, monkeypatch):
    # Regression: 4-well plots exactly wells 1-4, unchanged.
    wells = _count_wells(tmp_path, monkeypatch, PlateGeometry(rows=1, cols=4))
    assert wells == [1, 2, 3, 4]
