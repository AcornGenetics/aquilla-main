"""
Contract tests for OTA update endpoints.

Run with:
    pytest tests/contract/test_update_endpoints.py -m contract -v
"""
import pytest
from unittest.mock import patch, AsyncMock


def reset_update(client):
    client.post("/update/reset")


# ---------------------------------------------------------------------------
# GET /update/status
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_status_default_structure(client):
    """GET /update/status returns expected fields with safe defaults."""
    reset_update(client)
    response = client.get("/update/status")
    assert response.status_code == 200
    data = response.json()
    assert "available" in data
    assert "dismissed" in data
    assert "status" in data
    assert data["available"] is False
    assert data["dismissed"] is False


@pytest.mark.contract
def test_update_status_reflects_dismiss(client):
    """POST /update/dismiss marks update as dismissed."""
    reset_update(client)
    client.post("/update/dismiss")
    response = client.get("/update/status")
    assert response.status_code == 200
    assert response.json()["dismissed"] is True


# ---------------------------------------------------------------------------
# POST /update/check
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_check_returns_error_when_no_credentials(client):
    """POST /update/check returns ok=False when GHCR credentials are not configured."""
    reset_update(client)
    import aquila_web.main as web_main
    with patch.object(web_main, "_OTA_GHCR_TOKEN", ""), \
         patch.object(web_main, "_OTA_IMAGE_TAG", "prod"):
        response = client.post("/update/check")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "error" in data


@pytest.mark.contract
def test_update_check_returns_error_when_no_image_tag(client):
    """POST /update/check returns ok=False when IMAGE_TAG is not set."""
    reset_update(client)
    import aquila_web.main as web_main
    with patch.object(web_main, "_OTA_GHCR_TOKEN", "sometoken"), \
         patch.object(web_main, "_OTA_IMAGE_TAG", ""):
        response = client.post("/update/check")
    assert response.status_code == 200
    assert response.json()["ok"] is False


@pytest.mark.contract
def test_update_check_spawns_background_task_when_credentialed(client):
    """POST /update/check returns ok=True and starts background check when credentials exist."""
    reset_update(client)
    import aquila_web.main as web_main
    with patch.object(web_main, "_OTA_GHCR_TOKEN", "tok"), \
         patch.object(web_main, "_OTA_IMAGE_TAG", "prod"), \
         patch("asyncio.create_task") as mock_create:
        response = client.post("/update/check")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# POST /update/apply
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_apply_calls_watchtower_api(client):
    """POST /update/apply calls Watchtower HTTP API and returns ok=True on success."""
    reset_update(client)
    mock_response = AsyncMock()
    mock_response.status_code = 200
    with patch("aquila_web.main.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        response = client.post("/update/apply")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.contract
def test_update_apply_returns_error_on_watchtower_failure(client):
    """POST /update/apply returns ok=False when Watchtower returns non-200."""
    reset_update(client)
    mock_response = AsyncMock()
    mock_response.status_code = 500
    with patch("aquila_web.main.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        response = client.post("/update/apply")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "error" in data


@pytest.mark.contract
def test_update_apply_returns_error_on_network_failure(client):
    """POST /update/apply returns ok=False when Watchtower is unreachable."""
    reset_update(client)
    with patch("aquila_web.main.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("connection refused")
        )
        response = client.post("/update/apply")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "error" in data


@pytest.mark.contract
def test_update_apply_does_not_restart_without_user_action(client):
    """Containers must not restart unless /update/apply is explicitly called."""
    reset_update(client)
    status = client.get("/update/status").json()
    # Status must remain idle / not-updating without an explicit apply call
    assert status["status"] in ("idle", "checking", "available", "error")
    assert status["status"] != "updating"


# ---------------------------------------------------------------------------
# POST /update/dismiss
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_dismiss_sets_dismissed_flag(client):
    """POST /update/dismiss sets dismissed=True."""
    reset_update(client)
    resp = client.post("/update/dismiss")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert client.get("/update/status").json()["dismissed"] is True


@pytest.mark.contract
def test_update_dismiss_idempotent(client):
    """POST /update/dismiss called twice still returns ok=True."""
    reset_update(client)
    client.post("/update/dismiss")
    resp = client.post("/update/dismiss")
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# POST /update/reset (test helper)
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_update_reset_clears_state(client):
    """POST /update/reset clears all update state back to defaults."""
    client.post("/update/dismiss")
    client.post("/update/reset")
    data = client.get("/update/status").json()
    assert data["available"] is False
    assert data["dismissed"] is False
    assert data["status"] == "idle"
