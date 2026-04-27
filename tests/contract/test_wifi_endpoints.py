"""
Contract tests for WiFi proxy endpoints in main.py.

The WiFi routes proxy to kiosk-control (a host service). In tests we patch
the internal helper functions so no real HTTP call is made.

Run with:
    pytest tests/contract/test_wifi_endpoints.py -m contract -v
"""
import pytest
from unittest.mock import patch, AsyncMock


# ---------------------------------------------------------------------------
# GET /wifi — page
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_wifi_page_returns_200(client):
    """GET /wifi serves the WiFi settings HTML page."""
    response = client.get("/wifi")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /wifi/status
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_wifi_status_connected(client):
    """GET /wifi/status returns connected=True when kiosk-control reports a connection."""
    payload = {"connected": True, "ssid": "HomeNetwork", "signal": 80}
    with patch("aquila_web.main._kiosk_get", new=AsyncMock(return_value=payload)):
        response = client.get("/wifi/status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert data["ssid"] == "HomeNetwork"
    assert data["signal"] == 80


@pytest.mark.contract
def test_wifi_status_not_connected(client):
    """GET /wifi/status returns connected=False when not on any network."""
    payload = {"connected": False, "ssid": None, "signal": None}
    with patch("aquila_web.main._kiosk_get", new=AsyncMock(return_value=payload)):
        response = client.get("/wifi/status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False


@pytest.mark.contract
def test_wifi_status_kiosk_unreachable_returns_safe_fallback(client):
    """GET /wifi/status returns a safe fallback dict when kiosk-control is down."""
    with patch("aquila_web.main._kiosk_get", side_effect=Exception("connection refused")):
        response = client.get("/wifi/status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert "error" in data


# ---------------------------------------------------------------------------
# GET /wifi/scan
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_wifi_scan_returns_network_list(client):
    """GET /wifi/scan proxies scan results from kiosk-control."""
    networks = [
        {"ssid": "NetworkA", "signal": 90, "secured": True, "in_use": True},
        {"ssid": "NetworkB", "signal": 60, "secured": False, "in_use": False},
    ]
    with patch("aquila_web.main._kiosk_get", new=AsyncMock(return_value={"networks": networks})):
        response = client.get("/wifi/scan")
    assert response.status_code == 200
    data = response.json()
    assert len(data["networks"]) == 2
    assert data["networks"][0]["ssid"] == "NetworkA"


@pytest.mark.contract
def test_wifi_scan_kiosk_unreachable_returns_empty_list(client):
    """GET /wifi/scan returns empty networks list when kiosk-control is down."""
    with patch("aquila_web.main._kiosk_get", side_effect=Exception("timeout")):
        response = client.get("/wifi/scan")
    assert response.status_code == 200
    data = response.json()
    assert data["networks"] == []
    assert "error" in data


# ---------------------------------------------------------------------------
# POST /wifi/connect
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_wifi_connect_success(client):
    """POST /wifi/connect with ssid+password returns ok=True on success."""
    with patch("aquila_web.main._kiosk_post", new=AsyncMock(return_value={"ok": True, "error": None})):
        response = client.post("/wifi/connect", json={"ssid": "HomeNetwork", "password": "secret"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.contract
def test_wifi_connect_wrong_password(client):
    """POST /wifi/connect returns ok=False when nmcli reports failure."""
    with patch("aquila_web.main._kiosk_post", new=AsyncMock(return_value={"ok": False, "error": "Secrets were required, but not provided"})):
        response = client.post("/wifi/connect", json={"ssid": "HomeNetwork", "password": "wrongpass"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error"] is not None


@pytest.mark.contract
def test_wifi_connect_open_network_no_password(client):
    """POST /wifi/connect with empty password works for open networks."""
    with patch("aquila_web.main._kiosk_post", new=AsyncMock(return_value={"ok": True, "error": None})):
        response = client.post("/wifi/connect", json={"ssid": "OpenNet", "password": ""})
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.contract
def test_wifi_connect_kiosk_unreachable(client):
    """POST /wifi/connect returns ok=False when kiosk-control is unreachable."""
    with patch("aquila_web.main._kiosk_post", side_effect=Exception("connection refused")):
        response = client.post("/wifi/connect", json={"ssid": "HomeNetwork", "password": "secret"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "error" in data


# ---------------------------------------------------------------------------
# POST /wifi/forget
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_wifi_forget_success(client):
    """POST /wifi/forget with a known ssid returns ok=True."""
    with patch("aquila_web.main._kiosk_post", new=AsyncMock(return_value={"ok": True, "error": None})):
        response = client.post("/wifi/forget", json={"ssid": "HomeNetwork"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.contract
def test_wifi_forget_unknown_ssid(client):
    """POST /wifi/forget with an unknown ssid returns ok=False."""
    with patch("aquila_web.main._kiosk_post", new=AsyncMock(return_value={"ok": False, "error": "No connection profile found"})):
        response = client.post("/wifi/forget", json={"ssid": "NonExistent"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False


@pytest.mark.contract
def test_wifi_forget_kiosk_unreachable(client):
    """POST /wifi/forget returns ok=False when kiosk-control is unreachable."""
    with patch("aquila_web.main._kiosk_post", side_effect=Exception("connection refused")):
        response = client.post("/wifi/forget", json={"ssid": "HomeNetwork"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "error" in data
