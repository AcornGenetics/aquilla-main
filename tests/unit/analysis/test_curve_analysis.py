"""
Unit tests for the Curve class — initialisation, get_curve, results schema,
summariseResults logic, and graceful error handling.

Tests that verify schema / status logic stub out evaluate_curve, get_curve_data,
get_threshold, and compute_cq so no real optics log file is required.

Tests that verify get_curve signal processing use the real optics fixture at
tests/fixtures/optics/sample_run.log.
"""
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from aq_curve import curve as curve_module
from aq_curve.curve import Curve

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parents[3] / "tests" / "fixtures"
OPTICS_LOG = FIXTURES_DIR / "optics" / "sample_run.log"
VALID_STATUSES = {"Detected", "Not Detected", "Inconclusive"}

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _stub_evaluate(status):
    def _stub(*_args, **_kwargs):
        return {"status": status}

    return _stub


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


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_curve_initialises_with_valid_src_basedir(tmp_path):
    """Curve() must not raise when given an existing directory as src_basedir."""
    curve = Curve(src_basedir=str(tmp_path))
    assert curve.src_basedir == str(tmp_path)


@pytest.mark.unit
def test_curve_stores_custom_cross_talk_matrix():
    """Custom cross-talk matrix must be stored, not replaced by the default."""
    custom = [
        [[1, -0.2], [0, 1]],
        [[1, -0.2], [0, 1]],
        [[1, -0.2], [0, 1]],
        [[1, -0.2], [0, 1]],
    ]
    curve = Curve(src_basedir=str(OPTICS_LOG.parent), cross_talk_matrix=custom)
    assert curve.cross_talk_matrix is custom


@pytest.mark.unit
def test_curve_stores_custom_thresholds():
    """Custom thresholds must be stored, not replaced by the default."""
    custom = [[0.3, 0.3]] * 4
    curve = Curve(src_basedir=str(OPTICS_LOG.parent), thresholds=custom)
    assert curve.thresholds is custom


@pytest.mark.unit
def test_curve_default_baseline_slice():
    """Default baseline_slice must be (5, 15)."""
    curve = Curve(src_basedir=str(OPTICS_LOG.parent))
    assert curve.baseline_slice == (5, 15)


# ---------------------------------------------------------------------------
# get_curve — output type and shape (real optics fixture)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_curve_returns_numpy_array():
    """get_curve must return a numpy array."""
    curve = Curve(src_basedir=str(OPTICS_LOG.parent))
    result = curve.get_curve(OPTICS_LOG.name, "fam", 1)
    assert isinstance(result, np.ndarray), f"expected ndarray, got {type(result)}"


@pytest.mark.unit
def test_get_curve_returns_nonempty_array():
    """get_curve result must contain at least one element."""
    curve = Curve(src_basedir=str(OPTICS_LOG.parent))
    result = curve.get_curve(OPTICS_LOG.name, "fam", 1)
    assert len(result) > 0, "get_curve returned an empty array"


@pytest.mark.unit
def test_get_curve_rox_returns_numpy_array():
    """get_curve must work for the rox dye as well."""
    curve = Curve(src_basedir=str(OPTICS_LOG.parent))
    result = curve.get_curve(OPTICS_LOG.name, "rox", 1)
    assert isinstance(result, np.ndarray)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# results_to_json schema — using the real optics fixture + evaluate stub
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_results_schema_has_row_keys_1_and_2(monkeypatch):
    """results_to_json output must have top-level keys '1' and '2'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shutil.copy(OPTICS_LOG, Path(tmpdir) / OPTICS_LOG.name)
        _patch_all(monkeypatch, "detected")
        curve = Curve(src_basedir=tmpdir)
        curve.results_to_json(OPTICS_LOG.name, "out.json")
        data = json.loads((Path(tmpdir) / "out.json").read_text())

    assert "1" in data
    assert "2" in data


@pytest.mark.unit
def test_results_schema_columns_1_to_4(monkeypatch):
    """Each dye row in results_to_json output must have column keys '1'–'4'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shutil.copy(OPTICS_LOG, Path(tmpdir) / OPTICS_LOG.name)
        _patch_all(monkeypatch, "undetected")
        curve = Curve(src_basedir=tmpdir)
        curve.results_to_json(OPTICS_LOG.name, "out.json")
        data = json.loads((Path(tmpdir) / "out.json").read_text())

    for row_key in ("1", "2"):
        for col_key in ("1", "2", "3", "4"):
            assert col_key in data[row_key], (
                f"row {row_key} missing column '{col_key}'"
            )


@pytest.mark.unit
def test_results_all_values_valid_statuses(monkeypatch):
    """All cell values in the result must be within the valid status set."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shutil.copy(OPTICS_LOG, Path(tmpdir) / OPTICS_LOG.name)
        _patch_all(monkeypatch, "inconclusive")
        curve = Curve(src_basedir=tmpdir)
        curve.results_to_json(OPTICS_LOG.name, "out.json")
        data = json.loads((Path(tmpdir) / "out.json").read_text())

    for row_key in ("1", "2"):
        for col_key in ("1", "2", "3", "4"):
            assert data[row_key][col_key] in VALID_STATUSES


# ---------------------------------------------------------------------------
# Graceful error handling — nonexistent optics log
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_curve_with_nonexistent_optics_log_raises(tmp_path):
    """Calling get_curve with a missing log file must raise, not return garbage."""
    curve = Curve(src_basedir=str(tmp_path))
    with pytest.raises(Exception):
        curve.get_curve("ghost.log", "fam", 1)


@pytest.mark.unit
def test_is_detected_with_nonexistent_log_raises(tmp_path):
    """is_detected must propagate the exception from a missing optics log."""
    curve = Curve(src_basedir=str(tmp_path))
    with pytest.raises(Exception):
        curve.is_detected("ghost.log", 1)


# ---------------------------------------------------------------------------
# summariseResults logic — status resolution rules (all via stubbed calls)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detected_plus_detected_gives_detected(tmp_path, monkeypatch):
    """When evaluate_curve returns 'detected' for every cell, all results are 'Detected'."""
    _patch_all(monkeypatch, "detected")
    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    for row_key in ("1", "2"):
        for col_key in ("1", "2", "3", "4"):
            assert data[row_key][col_key] == "Detected", (
                f"row {row_key} col {col_key} expected 'Detected'"
            )


@pytest.mark.unit
def test_inconclusive_evaluate_gives_inconclusive(tmp_path, monkeypatch):
    """When evaluate_curve returns 'inconclusive', all cells must be 'Inconclusive'."""
    _patch_all(monkeypatch, "inconclusive")
    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    for row_key in ("1", "2"):
        for col_key in ("1", "2", "3", "4"):
            assert data[row_key][col_key] == "Inconclusive"


@pytest.mark.unit
def test_undetected_evaluate_gives_not_detected(tmp_path, monkeypatch):
    """When evaluate_curve returns 'undetected', all cells must be 'Not Detected'."""
    _patch_all(monkeypatch, "undetected")
    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    for row_key in ("1", "2"):
        for col_key in ("1", "2", "3", "4"):
            assert data[row_key][col_key] == "Not Detected"


@pytest.mark.unit
def test_unknown_evaluate_status_gives_inconclusive(tmp_path, monkeypatch):
    """Any status string other than 'detected'/'undetected' must map to 'Inconclusive'."""
    _patch_all(monkeypatch, "some_weird_status")
    curve = Curve(src_basedir=str(tmp_path))
    curve.results_to_json("raw.dat", "results.json")
    data = json.loads((tmp_path / "results.json").read_text())
    for row_key in ("1", "2"):
        for col_key in ("1", "2", "3", "4"):
            assert data[row_key][col_key] == "Inconclusive"
