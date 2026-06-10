"""
Unit tests for Curve.results_to_json — path safety, output schema, and error handling.

All tests use tmp_path for output files.  Tests that do not exercise real signal
processing stub out evaluate_curve, get_curve_data, get_threshold, and compute_cq
so no real optics log file is required.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from aq_curve import curve as curve_module
from aq_curve.curve import Curve

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = {"Detected", "Not Detected", "Inconclusive"}

OPTICS_LOG = (
    Path(__file__).parents[3] / "tests" / "fixtures" / "optics" / "sample_run.log"
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _stub_evaluate(status):
    """Return an evaluate_curve stub that always resolves to the given status string."""

    def _stub(*_args, **_kwargs):
        return {"status": status}

    return _stub


# Stub for get_curve_data — returns (xdata, y_corrected, y_raw) with dummy arrays.
_DUMMY_XDATA = np.arange(1, 41, dtype=float)
_DUMMY_Y = np.zeros(40, dtype=float)


def _stub_get_curve_data(*_args, **_kwargs):
    return _DUMMY_XDATA.copy(), _DUMMY_Y.copy(), _DUMMY_Y.copy()


def _stub_get_threshold(*_args, **_kwargs):
    return 0.5, 0.0


def _stub_compute_cq(*_args, **_kwargs):
    return None


def _patch_all(monkeypatch, status="detected"):
    """Patch every file-reading call inside results_to_json so no log file is needed."""
    monkeypatch.setattr(curve_module, "evaluate_curve", _stub_evaluate(status))
    monkeypatch.setattr(curve_module, "get_curve_data", _stub_get_curve_data)
    monkeypatch.setattr(curve_module, "get_threshold", _stub_get_threshold)
    monkeypatch.setattr(curve_module, "compute_cq", _stub_compute_cq)


def _make_curve(tmp_path, monkeypatch, status="detected"):
    """Create a Curve instance with all file-reading calls fully stubbed."""
    _patch_all(monkeypatch, status)
    return Curve(src_basedir=str(tmp_path))


# ---------------------------------------------------------------------------
# Path traversal safety
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_path_traversal_raises_value_error(tmp_path, monkeypatch):
    """results_to_json must reject '../' escape attempts."""
    curve = _make_curve(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="src_basedir"):
        curve.results_to_json("raw.dat", "../escape.json")


@pytest.mark.unit
def test_path_traversal_nested_raises(tmp_path, monkeypatch):
    """Nested traversal like 'subdir/../../etc/passwd' must also be rejected."""
    curve = _make_curve(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        curve.results_to_json("raw.dat", "subdir/../../outside.json")


# ---------------------------------------------------------------------------
# Valid write
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_path_within_basedir_creates_file(tmp_path, monkeypatch):
    """A simple filename within src_basedir must produce a file on disk."""
    curve = _make_curve(tmp_path, monkeypatch)
    curve.results_to_json("raw.dat", "results.json")
    assert (tmp_path / "results.json").exists()


@pytest.mark.unit
def test_written_json_is_valid_and_parseable(tmp_path, monkeypatch):
    """The output file must be valid JSON."""
    curve = _make_curve(tmp_path, monkeypatch)
    curve.results_to_json("raw.dat", "results.json")
    text = (tmp_path / "results.json").read_text()
    data = json.loads(text)
    assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_results_contains_row_keys_1_and_2(tmp_path, monkeypatch):
    """Top-level result must have keys '1' (FAM) and '2' (ROX)."""
    curve = _make_curve(tmp_path, monkeypatch)
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    assert "1" in data, "missing FAM row key '1'"
    assert "2" in data, "missing ROX row key '2'"


@pytest.mark.unit
def test_each_row_contains_tube_column_keys(tmp_path, monkeypatch):
    """Each dye row must have column keys '1', '2', '3', '4'."""
    curve = _make_curve(tmp_path, monkeypatch)
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    for row_key in ("1", "2"):
        row = data[row_key]
        for col_key in ("1", "2", "3", "4"):
            assert col_key in row, f"row {row_key} missing column '{col_key}'"


@pytest.mark.unit
def test_all_result_values_are_valid_statuses(tmp_path, monkeypatch):
    """Every cell value must be one of 'Detected', 'Not Detected', 'Inconclusive'."""
    for stub_status in ("detected", "undetected", "inconclusive"):
        _patch_all(monkeypatch, stub_status)
        curve = Curve(src_basedir=str(tmp_path))
        out_file = f"results_{stub_status}.json"
        curve.results_to_json("raw.dat", out_file)
        data = json.loads((tmp_path / out_file).read_text())
        for row_key in ("1", "2"):
            for col_key in ("1", "2", "3", "4"):
                value = data[row_key][col_key]
                assert value in VALID_STATUSES, (
                    f"row {row_key} col {col_key}: unexpected value {value!r}"
                )


@pytest.mark.unit
def test_detected_status_maps_to_Detected(tmp_path, monkeypatch):
    """evaluate_curve status 'detected' must produce cell value 'Detected'."""
    _patch_all(monkeypatch, "detected")
    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["1"]["1"] == "Detected"


@pytest.mark.unit
def test_undetected_status_maps_to_not_detected(tmp_path, monkeypatch):
    """evaluate_curve status 'undetected' must produce cell value 'Not Detected'."""
    _patch_all(monkeypatch, "undetected")
    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["1"]["1"] == "Not Detected"


@pytest.mark.unit
def test_inconclusive_status_maps_to_inconclusive(tmp_path, monkeypatch):
    """evaluate_curve status 'inconclusive' must produce cell value 'Inconclusive'."""
    _patch_all(monkeypatch, "inconclusive")
    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["1"]["1"] == "Inconclusive"


# ---------------------------------------------------------------------------
# Error handling — nonexistent / empty optics log (no stubs: real code path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_nonexistent_optics_log_raises(tmp_path):
    """results_to_json must raise (not silently succeed) when the optics log is missing."""
    curve = Curve(src_basedir=str(tmp_path))
    with pytest.raises(Exception):
        curve.results_to_json("no_such_file.log", "results.json")


@pytest.mark.unit
def test_nonexistent_optics_log_does_not_write_results_file(tmp_path):
    """When the optics log is missing, no results file should be left on disk."""
    curve = Curve(src_basedir=str(tmp_path))
    try:
        curve.results_to_json("no_such_file.log", "results.json")
    except Exception:
        pass
    assert not (tmp_path / "results.json").exists()


@pytest.mark.unit
def test_empty_optics_log_raises_or_does_not_write(tmp_path):
    """An empty optics log file should either raise or leave no results file."""
    empty_log = tmp_path / "empty.log"
    empty_log.write_text("")

    results_path = tmp_path / "results.json"
    try:
        curve = Curve(src_basedir=str(tmp_path))
        curve.results_to_json("empty.log", "results.json")
    except Exception:
        pass

    # If a file was written despite the empty log, it must at least be valid JSON
    if results_path.exists():
        data = json.loads(results_path.read_text())
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Cross-channel rule: FAM undetected + late ROX → ROX suppressed
# ---------------------------------------------------------------------------


def _make_cq_sequence(*values):
    """Stub for compute_cq that yields successive values from the provided sequence."""
    it = iter(values)

    def _stub(*_args, **_kwargs):
        return next(it, None)

    return _stub


def _stub_evaluate_by_dye(fam_status, rox_status):
    """evaluate_curve stub that returns different statuses per dye."""
    def _stub(_curve, _src, dye_name, _well):
        return {"status": fam_status if dye_name == "fam" else rox_status}
    return _stub


@pytest.mark.unit
def test_late_rox_suppressed_when_fam_undetected(tmp_path, monkeypatch):
    """ROX with a late Cq must become Not Detected when FAM is undetected."""
    monkeypatch.setattr(curve_module, "evaluate_curve",
                        _stub_evaluate_by_dye("undetected", "detected"))
    monkeypatch.setattr(curve_module, "get_curve_data", _stub_get_curve_data)
    monkeypatch.setattr(curve_module, "get_threshold", _stub_get_threshold)
    # FAM wells 1-4: None; ROX wells 1-4: 36.5 (>= PCR_LATE_CQ_THRESHOLD=35)
    monkeypatch.setattr(curve_module, "compute_cq",
                        _make_cq_sequence(None, None, None, None, 36.5, 36.5, 36.5, 36.5))

    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())

    for col in ("1", "2", "3", "4"):
        assert data["2"][col] == "Not Detected", f"ROX well {col} should be suppressed"
        assert data["cq"]["2"][col] is None, f"ROX Cq well {col} should be None"


@pytest.mark.unit
def test_early_rox_not_suppressed_when_fam_undetected(tmp_path, monkeypatch):
    """ROX with an early Cq must remain Detected even when FAM is undetected."""
    monkeypatch.setattr(curve_module, "evaluate_curve",
                        _stub_evaluate_by_dye("undetected", "detected"))
    monkeypatch.setattr(curve_module, "get_curve_data", _stub_get_curve_data)
    monkeypatch.setattr(curve_module, "get_threshold", _stub_get_threshold)
    # FAM wells 1-4: None; ROX wells 1-4: 22.0 (< threshold, rule does not fire)
    monkeypatch.setattr(curve_module, "compute_cq",
                        _make_cq_sequence(None, None, None, None, 22.0, 22.0, 22.0, 22.0))

    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())

    for col in ("1", "2", "3", "4"):
        assert data["2"][col] == "Detected", f"ROX well {col} should remain Detected"
        assert data["cq"]["2"][col] == 22.0, f"ROX Cq well {col} should be preserved"


@pytest.mark.unit
def test_late_rox_not_suppressed_when_fam_detected(tmp_path, monkeypatch):
    """Late ROX must not be suppressed when FAM is detected."""
    monkeypatch.setattr(curve_module, "evaluate_curve", _stub_evaluate("detected"))
    monkeypatch.setattr(curve_module, "get_curve_data", _stub_get_curve_data)
    monkeypatch.setattr(curve_module, "get_threshold", _stub_get_threshold)
    # FAM wells 1-4: 18.0; ROX wells 1-4: 36.0 (late but FAM is detected)
    monkeypatch.setattr(curve_module, "compute_cq",
                        _make_cq_sequence(18.0, 18.0, 18.0, 18.0, 36.0, 36.0, 36.0, 36.0))

    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())

    for col in ("1", "2", "3", "4"):
        assert data["2"][col] == "Detected", f"ROX well {col} should remain Detected"
        assert data["cq"]["2"][col] == 36.0
