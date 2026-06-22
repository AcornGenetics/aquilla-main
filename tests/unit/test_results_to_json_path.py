import json
from pathlib import Path

import numpy as np
import pytest

from sentri_curve import curve as curve_module
from sentri_curve.curve import Curve


def _stub_evaluate_curve(*_args, **_kwargs):
    return {"status": "detected"}


def _stub_extract_data(*_args, **_kwargs):
    # Return 40 cycles of flat dummy data so baseline/cq math doesn't crash.
    xdata = list(range(1, 41))
    y = [0.01] * 40
    return (xdata, y, y)


def test_results_to_json_blocks_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(curve_module, "evaluate_curve", _stub_evaluate_curve)
    monkeypatch.setattr(Curve, "extract_data", _stub_extract_data)
    curve = Curve(src_basedir=str(tmp_path))

    with pytest.raises(ValueError):
        curve.results_to_json("raw.dat", "../escape.json")


def test_results_to_json_allows_basedir(tmp_path, monkeypatch):
    monkeypatch.setattr(curve_module, "evaluate_curve", _stub_evaluate_curve)
    monkeypatch.setattr(Curve, "extract_data", _stub_extract_data)
    curve = Curve(src_basedir=str(tmp_path))

    curve.results_to_json("raw.dat", "results.json")

    result_path = Path(tmp_path, "results.json")
    assert result_path.exists()
    assert json.loads(result_path.read_text())
