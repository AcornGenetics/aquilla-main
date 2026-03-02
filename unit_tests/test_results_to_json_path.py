import json
from pathlib import Path

import pytest

from aq_curve import curve as curve_module
from aq_curve.curve import Curve


def _stub_evaluate_curve(*_args, **_kwargs):
    return {"status": "detected"}


def test_results_to_json_blocks_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(curve_module, "evaluate_curve", _stub_evaluate_curve)
    curve = Curve(src_basedir=str(tmp_path))

    with pytest.raises(ValueError):
        curve.results_to_json("raw.dat", "../escape.json")


def test_results_to_json_allows_basedir(tmp_path, monkeypatch):
    monkeypatch.setattr(curve_module, "evaluate_curve", _stub_evaluate_curve)
    curve = Curve(src_basedir=str(tmp_path))

    curve.results_to_json("raw.dat", "results.json")

    result_path = Path(tmp_path, "results.json")
    assert result_path.exists()
    assert json.loads(result_path.read_text())
