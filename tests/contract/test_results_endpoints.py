"""
Contract tests for results endpoints.

Uses fixture files at:
  tests/fixtures/results/detected.json
  tests/fixtures/results/not_detected.json

Run with:
    pytest tests/contract/ -m contract
"""
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "results"
DETECTED_PATH = FIXTURES_DIR / "detected.json"
NOT_DETECTED_PATH = FIXTURES_DIR / "not_detected.json"

VALID_RESULT_VALUES = {"Detected", "Not Detected", "Inconclusive"}


# ---------------------------------------------------------------------------
# GET /results — no path set
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_results_no_path_does_not_500(client):
    """GET /results when no results_path set returns something graceful (not 500)."""
    # ensure cleared so no path is active
    client.post("/results/clear")
    resp = client.get("/results")
    assert resp.status_code != 500


# ---------------------------------------------------------------------------
# GET /results/status
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_results_status_returns_cleared_key(client):
    """GET /results/status returns a dict with a 'cleared' key."""
    resp = client.get("/results/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "cleared" in data
    assert isinstance(data["cleared"], bool)


# ---------------------------------------------------------------------------
# POST /results/path → GET /results
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_set_results_path_then_get_loads_file(client):
    """POST /results/path sets the path; GET /results loads from that file."""
    resp = client.post("/results/path", json={"path": str(DETECTED_PATH)})
    assert resp.status_code == 200
    assert resp.json().get("ok") is True

    results = client.get("/results").json()
    # Should contain row keys "1" and "2"
    assert "1" in results
    assert "2" in results


@pytest.mark.contract
def test_results_schema_is_nested_dict_of_strings(client):
    """GET /results with a valid file returns JSON with keys "1","2" each mapping to dicts of strings."""
    client.post("/results/path", json={"path": str(DETECTED_PATH)})
    results = client.get("/results").json()

    for row_key in ("1", "2"):
        assert row_key in results, f"Missing row key '{row_key}'"
        row = results[row_key]
        assert isinstance(row, dict)
        for col_key, value in row.items():
            assert isinstance(value, str), f"Result value for row {row_key} col {col_key} is not a string"


@pytest.mark.contract
def test_results_values_in_allowed_set(client):
    """GET /results — all values are in {Detected, Not Detected, Inconclusive}."""
    client.post("/results/path", json={"path": str(NOT_DETECTED_PATH)})
    results = client.get("/results").json()

    for row_key in ("1", "2"):
        if row_key not in results:
            continue
        for col_key, value in results[row_key].items():
            assert value in VALID_RESULT_VALUES, (
                f"Unexpected value '{value}' at row={row_key} col={col_key}"
            )


# ---------------------------------------------------------------------------
# GET /results/by-path — path traversal blocked
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_results_by_path_traversal_does_not_leak(client):
    """GET /results/by-path?path=../../etc/passwd does not return file contents."""
    resp = client.get("/results/by-path", params={"path": "../../etc/passwd"})
    # Must not be a 500; body must not look like /etc/passwd contents
    assert resp.status_code < 500
    body = resp.text
    assert "root:" not in body, "Path traversal may have leaked /etc/passwd"


# ---------------------------------------------------------------------------
# POST /results/clear
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_results_clear_sets_cleared_true(client):
    """POST /results/clear sets results_cleared=True."""
    client.post("/results/path", json={"path": str(DETECTED_PATH)})
    resp = client.post("/results/clear")
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


@pytest.mark.contract
def test_results_status_after_clear_is_true(client):
    """GET /results/status after POST /results/clear returns {"cleared": true}."""
    client.post("/results/clear")
    status = client.get("/results/status").json()
    assert status["cleared"] is True
