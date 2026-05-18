"""
Test that the result summary shown in all three displays is consistent:
  1. Results page  — reads from /results (live, current run)
  2. History table — reads from /results/by-path (per-entry results file)
  3. Run detail    — reads from /results/path + /results (per-entry results file)

All three should compute the same summary for the same run.
"""

import json
import pytest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers that mirror the JS summarize logic so we can validate end-to-end
# ---------------------------------------------------------------------------

def js_summarize_results(results_data: dict, tube_count: int = 4) -> list[str]:
    """Mirror of summarizeResults() in history.js / history_detail.js."""
    per_tube = ["not-detected"] * tube_count
    if not isinstance(results_data, dict):
        return per_tube
    for tube in range(1, tube_count + 1):
        fam = results_data.get("1", {}).get(str(tube))
        rox = results_data.get("2", {}).get(str(tube))
        if fam == "Inconclusive" or rox == "Inconclusive":
            per_tube[tube - 1] = "inconclusive"
        elif fam == "Detected" or rox == "Detected":
            per_tube[tube - 1] = "detected"
    return per_tube


def js_format_result_summary(per_tube: list[str], tube_names: list[str]) -> str:
    """Mirror of formatResultSummary() in history.js / history_detail.js."""
    detected = [tube_names[i] for i, s in enumerate(per_tube) if s == "detected"]
    inconclusive = [f"{tube_names[i]} inconclusive" for i, s in enumerate(per_tube) if s == "inconclusive"]
    if not detected and not inconclusive:
        return "No targets detected"
    parts = []
    if detected:
        parts.append(f"Detected: {', '.join(detected)}")
    if inconclusive:
        parts.append(", ".join(inconclusive))
    return " · ".join(parts)


DEFAULT_TUBE_NAMES = ["Tube 1", "Tube 2", "Tube 3", "Tube 4"]

RESULTS_ALL_NOT_DETECTED = {
    "1": {"1": "Not Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "2": {"1": "Not Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "cq": {"1": {"1": None, "2": None, "3": None, "4": None},
           "2": {"1": None, "2": None, "3": None, "4": None}},
}

RESULTS_TUBE1_DETECTED = {
    "1": {"1": "Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "2": {"1": "Not Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "cq": {"1": {"1": 22.5, "2": None, "3": None, "4": None},
           "2": {"1": None, "2": None, "3": None, "4": None}},
}

RESULTS_TUBES_1_2_DETECTED = {
    "1": {"1": "Detected", "2": "Detected", "3": "Not Detected", "4": "Not Detected"},
    "2": {"1": "Not Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
}

RESULTS_INCONCLUSIVE = {
    "1": {"1": "Inconclusive", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
    "2": {"1": "Not Detected", "2": "Not Detected", "3": "Not Detected", "4": "Not Detected"},
}


# ---------------------------------------------------------------------------
# Backend import — skip gracefully if dependencies are missing
# ---------------------------------------------------------------------------

try:
    from aquila_web.main import app, _summarize_results_from_file, _summarize_results
    BACKEND_AVAILABLE = True
except Exception:
    BACKEND_AVAILABLE = False

pytestmark = pytest.mark.skipif(not BACKEND_AVAILABLE, reason="FastAPI app could not be imported")


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Unit tests for the backend summarize helpers
# ---------------------------------------------------------------------------

class TestBackendSummarize:
    def test_all_not_detected(self, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_ALL_NOT_DETECTED))
        assert _summarize_results_from_file(f) == "No targets detected"

    def test_tube1_detected(self, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_TUBE1_DETECTED))
        assert _summarize_results_from_file(f) == "Detected: Tube 1"

    def test_tubes_1_2_detected(self, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_TUBES_1_2_DETECTED))
        assert _summarize_results_from_file(f) == "Detected: Tube 1, Tube 2"

    def test_inconclusive(self, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_INCONCLUSIVE))
        result = _summarize_results_from_file(f)
        assert "inconclusive" in result.lower()

    def test_missing_file(self, tmp_path):
        assert _summarize_results_from_file(tmp_path / "missing.json") == "Results unavailable"


# ---------------------------------------------------------------------------
# 2. Unit tests for the JS-mirror summarize helpers
# ---------------------------------------------------------------------------

class TestJsSummarize:
    def test_all_not_detected(self):
        per_tube = js_summarize_results(RESULTS_ALL_NOT_DETECTED)
        assert js_format_result_summary(per_tube, DEFAULT_TUBE_NAMES) == "No targets detected"

    def test_tube1_detected(self):
        per_tube = js_summarize_results(RESULTS_TUBE1_DETECTED)
        assert js_format_result_summary(per_tube, DEFAULT_TUBE_NAMES) == "Detected: Tube 1"

    def test_tubes_1_2_detected(self):
        per_tube = js_summarize_results(RESULTS_TUBES_1_2_DETECTED)
        assert js_format_result_summary(per_tube, DEFAULT_TUBE_NAMES) == "Detected: Tube 1, Tube 2"

    def test_inconclusive(self):
        per_tube = js_summarize_results(RESULTS_INCONCLUSIVE)
        result = js_format_result_summary(per_tube, DEFAULT_TUBE_NAMES)
        assert "inconclusive" in result.lower()


# ---------------------------------------------------------------------------
# 3. Backend vs JS-mirror consistency
#    The backend (_summarize_results_from_file) and JS logic must agree.
# ---------------------------------------------------------------------------

class TestBackendVsJsConsistency:
    @pytest.mark.parametrize("results_data,expected", [
        (RESULTS_ALL_NOT_DETECTED, "No targets detected"),
        (RESULTS_TUBE1_DETECTED,   "Detected: Tube 1"),
        (RESULTS_TUBES_1_2_DETECTED, "Detected: Tube 1, Tube 2"),
    ])
    def test_backend_matches_js(self, tmp_path, results_data, expected):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(results_data))

        backend_result = _summarize_results_from_file(f)
        js_result = js_format_result_summary(
            js_summarize_results(results_data), DEFAULT_TUBE_NAMES
        )

        assert backend_result == expected, f"Backend gave: {backend_result!r}"
        assert js_result == expected,      f"JS mirror gave: {js_result!r}"
        assert backend_result == js_result, "Backend and JS disagree"


# ---------------------------------------------------------------------------
# 4. /results/by-path endpoint (used by history table)
# ---------------------------------------------------------------------------

class TestResultsByPathEndpoint:
    def test_returns_results_data(self, client, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_TUBE1_DETECTED))
        resp = client.get(f"/results/by-path?path={f}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["1"]["1"] == "Detected"

    def test_missing_file_returns_failed(self, client, tmp_path):
        resp = client.get(f"/results/by-path?path={tmp_path / 'nope.json'}")
        assert resp.status_code == 200
        assert resp.json().get("data", {}).get("failed") is True

    def test_result_consistent_with_backend_summary(self, client, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_TUBES_1_2_DETECTED))

        # What the backend would store as entry.result at run time
        backend_summary = _summarize_results_from_file(f)

        # What the history table now fetches via /results/by-path
        data = client.get(f"/results/by-path?path={f}").json()
        per_tube = js_summarize_results(data)
        js_summary = js_format_result_summary(per_tube, DEFAULT_TUBE_NAMES)

        assert backend_summary == js_summary, (
            f"History table would show {js_summary!r} "
            f"but backend stored {backend_summary!r}"
        )


# ---------------------------------------------------------------------------
# 5. /results endpoint (used by results page and run detail)
# ---------------------------------------------------------------------------

class TestResultsEndpoint:
    def test_set_path_and_get(self, client, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_TUBE1_DETECTED))

        # Run detail sets path then fetches
        client.post("/results/path", json={"path": str(f)})
        data = client.get("/results").json()
        assert data["1"]["1"] == "Detected"

    def test_results_and_by_path_return_same_data(self, client, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_TUBES_1_2_DETECTED))

        client.post("/results/path", json={"path": str(f)})
        via_results     = client.get("/results").json()
        via_by_path     = client.get(f"/results/by-path?path={f}").json()

        # Both endpoints must return the same raw data
        for row in ("1", "2"):
            for tube in ("1", "2", "3", "4"):
                assert via_results.get(row, {}).get(tube) == via_by_path.get(row, {}).get(tube), (
                    f"row={row} tube={tube}: /results={via_results.get(row,{}).get(tube)!r} "
                    f"vs /results/by-path={via_by_path.get(row,{}).get(tube)!r}"
                )


# ---------------------------------------------------------------------------
# 6. Catch the real bug: stored entry.result disagrees with results file
# ---------------------------------------------------------------------------

class TestStoredResultVsFile:
    """
    Simulates the observed bug: history entry stores 'Detected: Tube 1, Tube 2'
    but the actual results file has all 'Not Detected'.
    Verifies that reading from the file gives the correct answer.
    """

    def test_stale_stored_result_detected_by_file_read(self, client, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_ALL_NOT_DETECTED))

        stale_entry_result = "Detected: Tube 1, Tube 2"

        # What the history table now computes from the file
        data = client.get(f"/results/by-path?path={f}").json()
        per_tube = js_summarize_results(data)
        actual = js_format_result_summary(per_tube, DEFAULT_TUBE_NAMES)

        assert actual == "No targets detected", (
            f"File says 'No targets detected' but computed: {actual!r}"
        )
        assert actual != stale_entry_result, (
            "Stale stored result was used instead of reading from file"
        )

    def test_correct_stored_result_matches_file(self, client, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps(RESULTS_TUBES_1_2_DETECTED))

        stored = _summarize_results_from_file(f)  # what backend saves at run time

        data = client.get(f"/results/by-path?path={f}").json()
        per_tube = js_summarize_results(data)
        from_file = js_format_result_summary(per_tube, DEFAULT_TUBE_NAMES)

        assert stored == from_file == "Detected: Tube 1, Tube 2"
