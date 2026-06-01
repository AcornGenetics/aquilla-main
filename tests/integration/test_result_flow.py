"""
Integration tests: results flow from file to API to display.

All tests run without real hardware.  Results fixtures live under:
    tests/fixtures/results/{detected,not_detected,inconclusive}.json
"""
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_RESULTS = Path(__file__).parent.parent / "fixtures" / "results"

DETECTED_JSON = FIXTURES_RESULTS / "detected.json"
NOT_DETECTED_JSON = FIXTURES_RESULTS / "not_detected.json"
INCONCLUSIVE_JSON = FIXTURES_RESULTS / "inconclusive.json"

VALID_VALUES = {"Detected", "Not Detected", "Inconclusive"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_results_around_test(client):
    """Ensure results state is clean before and after every test."""
    client.post("/results/clear")
    yield
    client.post("/results/clear")


def _result_values(data: dict) -> set[str]:
    """Extract all leaf result strings from a results dict (skips 'cq' key)."""
    values = set()
    for row_key, row in data.items():
        if row_key == "cq":
            continue
        if isinstance(row, dict):
            for val in row.values():
                if isinstance(val, str):
                    values.add(val)
    return values


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestResultsFileToAPI:
    """Fixture file → POST /results/path → GET /results round-trip."""

    def test_detected_fixture_returned_by_results(self, client):
        """POST /results/path with detected.json → GET /results returns same data."""
        expected = json.loads(DETECTED_JSON.read_text())
        client.post("/results/path", json={"path": str(DETECTED_JSON)})
        response = client.get("/results")
        assert response.status_code == 200
        data = response.json()
        # Top-level result keys should match
        assert data.get("1") == expected["1"]
        assert data.get("2") == expected["2"]

    def test_not_detected_fixture_returned_by_results(self, client):
        """POST /results/path with not_detected.json → GET /results returns same data."""
        expected = json.loads(NOT_DETECTED_JSON.read_text())
        client.post("/results/path", json={"path": str(NOT_DETECTED_JSON)})
        data = client.get("/results").json()
        assert data.get("1") == expected["1"]
        assert data.get("2") == expected["2"]

    def test_inconclusive_fixture_returned_by_results(self, client):
        """POST /results/path with inconclusive.json → GET /results returns same data."""
        expected = json.loads(INCONCLUSIVE_JSON.read_text())
        client.post("/results/path", json={"path": str(INCONCLUSIVE_JSON)})
        data = client.get("/results").json()
        assert data.get("1") == expected["1"]
        assert data.get("2") == expected["2"]


@pytest.mark.integration
class TestResultsSchema:
    """Results data structure validation."""

    def test_schema_has_row_keys_1_and_2(self, client):
        """Results object has top-level keys '1' and '2'."""
        client.post("/results/path", json={"path": str(DETECTED_JSON)})
        data = client.get("/results").json()
        assert "1" in data
        assert "2" in data

    def test_schema_each_row_has_four_column_keys(self, client):
        """Each row ('1', '2') has sub-keys '1'–'4'."""
        client.post("/results/path", json={"path": str(DETECTED_JSON)})
        data = client.get("/results").json()
        for row_key in ("1", "2"):
            row = data[row_key]
            assert isinstance(row, dict)
            for col_key in ("1", "2", "3", "4"):
                assert col_key in row, f"Missing key {col_key} in row {row_key}"

    @pytest.mark.parametrize("fixture_path", [
        DETECTED_JSON,
        NOT_DETECTED_JSON,
        INCONCLUSIVE_JSON,
    ])
    def test_result_values_are_valid_enum_members(self, client, fixture_path):
        """All result cell values are valid enum members."""
        client.post("/results/path", json={"path": str(fixture_path)})
        data = client.get("/results").json()
        values = _result_values(data)
        assert values, "Expected at least one result value"
        invalid = values - VALID_VALUES
        assert not invalid, f"Invalid result values found: {invalid}"


@pytest.mark.integration
class TestResultsByPath:
    """GET /results/by-path endpoint."""

    def test_by_path_returns_same_data_as_fixture(self, client):
        """GET /results/by-path?path=<abs> returns same data as reading the file directly."""
        expected = json.loads(DETECTED_JSON.read_text())
        response = client.get("/results/by-path", params={"path": str(DETECTED_JSON)})
        assert response.status_code == 200
        data = response.json()
        assert data.get("1") == expected["1"]
        assert data.get("2") == expected["2"]

    def test_by_path_blocks_path_traversal(self, client):
        """GET /results/by-path with ../../etc/passwd returns 4xx or a failed payload."""
        response = client.get("/results/by-path", params={"path": "../../etc/passwd"})
        # The endpoint must NOT serve arbitrary filesystem paths.
        # It returns a 200 with {"data": {"failed": True}} when the file isn't a
        # valid results file, or a 4xx status.
        if response.status_code == 200:
            data = response.json()
            # Should not contain a "1" key with PCR result structure
            assert "1" not in data or not isinstance(data.get("1"), dict), (
                "Path traversal returned valid-looking results data"
            )
        else:
            assert response.status_code in (400, 403, 404, 422)

    def test_by_path_nonexistent_file_no_500(self, client, tmp_path):
        """GET /results/by-path with nonexistent path does not return 500."""
        fake = tmp_path / "ghost.json"
        response = client.get("/results/by-path", params={"path": str(fake)})
        assert response.status_code != 500


@pytest.mark.integration
class TestResultsClearFlow:
    """Results clear state machine."""

    def test_clear_sets_cleared_true(self, client):
        """POST /results/clear → GET /results/status returns cleared=True."""
        client.post("/results/path", json={"path": str(DETECTED_JSON)})
        client.post("/results/clear")
        status = client.get("/results/status").json()
        assert status["cleared"] is True

    def test_results_after_clear_returns_gracefully(self, client):
        """GET /results after clear returns gracefully (no 500, no file data)."""
        client.post("/results/path", json={"path": str(DETECTED_JSON)})
        client.post("/results/clear")
        response = client.get("/results")
        assert response.status_code == 200
        # Should not return normal results structure (cleared means no path)
        data = response.json()
        # Either a failed indicator or no "1"/"2" keys with dict values
        if "1" in data:
            # If "1" is present it should indicate failure, not a row dict
            row = data["1"]
            assert not isinstance(row, dict) or row.get("failed") is True

    def test_results_status_cleared_false_before_clear(self, client):
        """GET /results/status returns cleared=False immediately after path set."""
        client.post("/results/path", json={"path": str(DETECTED_JSON)})
        status = client.get("/results/status").json()
        assert status["cleared"] is False

    def test_set_path_after_clear_resets_cleared(self, client):
        """POST /results/path after clear sets cleared=False again."""
        client.post("/results/clear")
        client.post("/results/path", json={"path": str(DETECTED_JSON)})
        status = client.get("/results/status").json()
        assert status["cleared"] is False
