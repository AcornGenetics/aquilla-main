"""
Contract tests for the AQ_DEV_UPDATE_AVAILABLE dev-simulation flag.

This lets a developer force the "OTA update available" state from the launch
command, e.g.:

    AQ_DEV_SIMULATE=1 AQ_DEV_UPDATE_AVAILABLE=1 uvicorn aquila_web.main:app ...

so the Settings update badge (and its dismiss/reset lifecycle) can be exercised
locally without real GHCR credentials. Mirrors the style of
tests/contract/test_settings_nav.py.

Run with:
    pytest tests/contract/test_dev_update_simulation.py -m contract -v
"""
import pytest

from aquila_web import main as web_main


@pytest.fixture
def force_update_available(monkeypatch):
    """Simulate the app being launched with AQ_DEV_UPDATE_AVAILABLE=1."""
    monkeypatch.setattr(web_main, "DEV_UPDATE_AVAILABLE", True)
    # The flag must not depend on residual real state.
    monkeypatch.setattr(web_main, "_update_available", False)
    monkeypatch.setattr(web_main, "_update_dismissed", False)
    yield


# ---------------------------------------------------------------------------
# Slice 1 — off by default
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_not_available_by_default(client):
    """Without the dev flag, no update is reported (real polling governs)."""
    # Ensure a clean baseline regardless of test ordering.
    client.post("/update/reset")
    data = client.get("/update/status").json()
    assert data["available"] is False


# ---------------------------------------------------------------------------
# Slice 2 — flag forces an available update
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_dev_flag_forces_update_available(client, force_update_available):
    """AQ_DEV_UPDATE_AVAILABLE=1 makes /update/status report an update."""
    data = client.get("/update/status").json()
    assert data["available"] is True
    assert data["status"] == "available"


# ---------------------------------------------------------------------------
# Slice 3 — dismiss still hides the badge while the flag is on
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_dev_forced_update_can_be_dismissed(client, force_update_available):
    """Dismissing hides the badge (available reads false) even when forced."""
    assert client.get("/update/status").json()["available"] is True
    client.post("/update/dismiss")
    data = client.get("/update/status").json()
    assert data["dismissed"] is True
    assert data["available"] is False, (
        "a dismissed update must not keep showing the badge, even in dev mode"
    )


# ---------------------------------------------------------------------------
# Slice 4 — reset clears the dismissal so the badge can be re-tested
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_reset_restores_forced_update(client, force_update_available):
    """/update/reset clears dismissal, so the forced badge reappears."""
    client.post("/update/dismiss")
    assert client.get("/update/status").json()["available"] is False
    client.post("/update/reset")
    data = client.get("/update/status").json()
    assert data["available"] is True, (
        "after reset the dev-forced update should be available again"
    )
    assert data["dismissed"] is False
