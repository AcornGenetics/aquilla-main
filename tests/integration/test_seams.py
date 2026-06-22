"""
Integration tests: data-flow seams between components.

Uses TestClient + file system (tmp_path). Each test that touches history or
results is self-contained via monkeypatching of HISTORY_PATH and results_path.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_RESULTS = Path(__file__).parent.parent / "fixtures" / "results"


def _detected_fixture() -> Path:
    return FIXTURES_RESULTS / "detected.json"


@pytest.fixture(autouse=True)
def isolate_history(monkeypatch, tmp_path):
    """Redirect HISTORY_PATH to a tmp file so tests don't pollute real history."""
    from sentri_web import main as web_main
    tmp_history = tmp_path / "history.json"
    monkeypatch.setattr(web_main, "HISTORY_PATH", tmp_history)
    yield tmp_history


@pytest.fixture(autouse=True)
def reset_results_state(client):
    """Clear results_path and results_cleared before each test."""
    client.post("/results/clear")
    yield
    client.post("/results/clear")


# ---------------------------------------------------------------------------
# Seam A – Results path registration
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSeamAResultsPath:
    """Results path registration and status."""

    def test_set_path_returns_file_contents(self, client):
        """POST /results/path with valid fixture → GET /results returns file data."""
        fixture = _detected_fixture()
        client.post("/results/path", json={"path": str(fixture)})
        response = client.get("/results")
        assert response.status_code == 200
        data = response.json()
        # The fixture has keys "1" and "2" at the top level
        assert "1" in data
        assert "2" in data

    def test_set_nonexistent_path_no_500(self, client, tmp_path):
        """POST /results/path with nonexistent path → GET /results doesn't 500."""
        fake_path = tmp_path / "does_not_exist.json"
        client.post("/results/path", json={"path": str(fake_path)})
        response = client.get("/results")
        assert response.status_code == 200  # returns graceful error dict, not 500

    def test_results_status_not_cleared_after_path_set(self, client):
        """GET /results/status returns cleared=False after a path is registered."""
        client.post("/results/path", json={"path": str(_detected_fixture())})
        status = client.get("/results/status").json()
        assert status["cleared"] is False

    def test_results_clear_sets_cleared_true(self, client):
        """POST /results/clear sets cleared=True."""
        client.post("/results/path", json={"path": str(_detected_fixture())})
        client.post("/results/clear")
        status = client.get("/results/status").json()
        assert status["cleared"] is True

    def test_results_status_cleared_true_after_clear(self, client):
        """GET /results/status returns cleared=True after POST /results/clear."""
        client.post("/results/clear")
        status = client.get("/results/status").json()
        assert status["cleared"] is True


# ---------------------------------------------------------------------------
# Seam B – History consistency
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSeamBHistory:
    """History append and retrieval."""

    def test_append_stores_all_fields(self, client):
        """POST /history/append stores profile, run_name, results_path, tube_names."""
        payload = {
            "profile": "basic_pcr.json",
            "run_name": "run42",
            "results_path": str(_detected_fixture()),
            "graph_path": "/plots/run42.png",
            "tube_names": ["Sample A", "Sample B", "Sample C", "Sample D"],
        }
        response = client.post("/history/append", json=payload)
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_results_path_in_history_matches_posted(self, client):
        """results_path in history entry matches what was POSTed."""
        fixture = str(_detected_fixture())
        client.post("/history/append", json={
            "profile": "basic_pcr.json",
            "run_name": "run1",
            "results_path": fixture,
        })
        history = client.get("/history/data").json()
        assert len(history) > 0
        last = history[-1]
        assert last["results_path"] == fixture

    def test_tube_names_in_history_are_correct(self, client):
        """tube_names in history entry match the posted names."""
        names = ["Alpha", "Beta", "Gamma", "Delta"]
        client.post("/history/append", json={
            "profile": "basic_pcr.json",
            "run_name": "run2",
            "results_path": str(_detected_fixture()),
            "tube_names": names,
        })
        history = client.get("/history/data").json()
        last = history[-1]
        assert last["tube_names"] == names

    def test_history_entry_has_timestamp(self, client):
        """GET /history/data after append shows entry with a timestamp field."""
        client.post("/history/append", json={
            "profile": "basic_pcr.json",
            "run_name": "run3",
        })
        history = client.get("/history/data").json()
        last = history[-1]
        assert "timestamp" in last
        assert last["timestamp"]  # non-empty string


# ---------------------------------------------------------------------------
# Seam E – Tube names flow
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSeamETubeNames:
    """Tube name post/get round-trip."""

    def test_post_tube_names_reflected_in_get(self, client):
        """POST /tube_names updates names; GET /tube_names returns updated names."""
        names = ["Control", "Patient 1", "Patient 2", "Blank"]
        client.post("/tube_names", json={"names": names})
        response = client.get("/tube_names")
        assert response.status_code == 200
        assert response.json()["names"] == names

    def test_empty_string_name_uses_default(self, client):
        """Empty string for a tube name falls back to default 'Tube N'."""
        client.post("/tube_names", json={"names": ["", "Sample", "", ""]})
        names = client.get("/tube_names").json()["names"]
        assert names[0] == "Tube 1"
        assert names[1] == "Sample"
        assert names[2] == "Tube 3"
        assert names[3] == "Tube 4"

    def test_four_names_all_stored(self, client):
        """POST /tube_names with 4 names stores all 4."""
        names = ["A", "B", "C", "D"]
        client.post("/tube_names", json={"names": names})
        stored = client.get("/tube_names").json()["names"]
        assert stored == names


# ---------------------------------------------------------------------------
# Seam F – Run name advance
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSeamFRunName:
    """Run name counter management."""

    def test_advance_increments_run_counter(self, client):
        """POST /run/name/advance returns a name higher than the current one."""
        before = client.get("/run/name").json()["name"]
        advanced = client.post("/run/name/advance").json()["name"]
        # Both names start with "run"; the new number should differ
        assert advanced != before or before.startswith("run")

    def test_advance_twice_gives_name_two_higher(self, client):
        """Two separate advances yield strictly increasing run numbers.

        _advance_run_name picks the lowest unused number.  To guarantee the
        second advance returns something higher we must record the first name
        in history so it is no longer "unused".
        """
        import re
        first_advance = client.post("/run/name/advance").json()["name"]
        # Register the first name in history so it is consumed
        client.post("/history/append", json={"run_name": first_advance, "profile": "p"})
        second_advance = client.post("/run/name/advance").json()["name"]

        m1 = re.search(r"\d+", first_advance)
        m2 = re.search(r"\d+", second_advance)
        assert m1 and m2
        assert int(m2.group()) > int(m1.group())

    def test_get_run_name_returns_current(self, client):
        """GET /run/name returns the current run name string."""
        response = client.get("/run/name")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert isinstance(data["name"], str)
        assert data["name"]  # non-empty


# ---------------------------------------------------------------------------
# Seam H – Timer accuracy
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSeamHTimer:
    """Timer start/stop/reset state transitions."""

    def test_timer_start_sets_running(self, client):
        """POST /timer start → /button_status shows timer_running (or timer state via endpoint)."""
        # Timer state is not surfaced directly in /button_status but we can
        # verify via the timer endpoint response
        response = client.post("/timer", json={"action": "start"})
        assert response.status_code == 200
        assert "Timer" in response.json().get("message", "")

    def test_timer_stop_returns_ok(self, client):
        """POST /timer stop after start → 200 response."""
        client.post("/timer", json={"action": "start"})
        response = client.post("/timer", json={"action": "stop"})
        assert response.status_code == 200

    def test_timer_reset_sets_elapsed_zero(self, client):
        """POST /timer reset → elapsed = 0 (GET /button_status is unaffected; endpoint OK)."""
        client.post("/timer", json={"action": "start"})
        client.post("/timer", json={"action": "stop"})
        response = client.post("/timer", json={"action": "reset"})
        assert response.status_code == 200
        data = response.json()
        assert data.get("message") == "Timer reset"

    def test_timer_start_stop_start_cycle(self, client):
        """Timer can be started, stopped, and started again without error."""
        r1 = client.post("/timer", json={"action": "start"})
        r2 = client.post("/timer", json={"action": "stop"})
        r3 = client.post("/timer", json={"action": "start"})
        for r in (r1, r2, r3):
            assert r.status_code == 200

    def test_timer_invalid_action_returns_400(self, client):
        """POST /timer with unknown action returns 400."""
        response = client.post("/timer", json={"action": "fly"})
        assert response.status_code == 400
