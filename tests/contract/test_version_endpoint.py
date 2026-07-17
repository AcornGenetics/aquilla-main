"""
Contract tests for the /version endpoint.

The endpoint reports the app version baked into the image via the
AQ_APP_VERSION env var, so a deployed Sentri can self-report what it runs.

All tests carry the `@pytest.mark.contract` marker; run with:

    pytest tests/contract/ -m contract
"""
import pytest


@pytest.mark.contract
def test_version_returns_configured_version(client, monkeypatch):
    """GET /version returns the AQ_APP_VERSION value when it is set."""
    monkeypatch.setenv("AQ_APP_VERSION", "1.2.6.7")
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "1.2.6.7"}


@pytest.mark.contract
def test_version_unknown_when_unset(client, monkeypatch):
    """GET /version reports 'unknown' when AQ_APP_VERSION is not set."""
    monkeypatch.delenv("AQ_APP_VERSION", raising=False)
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "unknown"}


@pytest.mark.contract
def test_version_unknown_when_empty(client, monkeypatch):
    """An empty AQ_APP_VERSION (e.g. an empty build-arg) reports 'unknown',
    not an empty string that would render a blank 'V' in the footer."""
    monkeypatch.setenv("AQ_APP_VERSION", "")
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "unknown"}
