"""Contract tests for Updates-tab failure reporting (issue #423).

A check that could not reach the image registry used to leave the status at
"idle" while quietly setting an error string. The Updates panel renders an idle
status as a green "Software is up to date." — so a check that had actually
failed reported success to the operator.
"""
import asyncio

import pytest


@pytest.fixture
def configured(monkeypatch):
    """A device provisioned with registry credentials and a ring tag."""
    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "_OTA_GHCR_TOKEN", "token")
    monkeypatch.setattr(web_main, "_OTA_IMAGE_TAG", "prod")
    monkeypatch.setattr(web_main, "_update_dismissed", False)
    return web_main


def _run_check(web_main):
    asyncio.run(web_main._do_check_update())


@pytest.mark.contract
def test_unreachable_registry_is_not_reported_as_up_to_date(client, configured, monkeypatch):
    """The failure must not fall through to the panel's success branch."""
    async def _unreachable(*a, **kw):
        return None

    monkeypatch.setattr(configured, "_ghcr_manifest_digest", _unreachable)
    _run_check(configured)

    body = client.get("/update/status").json()
    assert body["status"] == "error", "an unreachable registry reported a non-error status"
    assert body["available"] is False


@pytest.mark.contract
def test_failed_check_message_carries_no_technical_detail(client, configured, monkeypatch):
    async def _boom(*a, **kw):
        raise RuntimeError("[Errno -3] Temporary failure in name resolution")

    monkeypatch.setattr(configured, "_ghcr_manifest_digest", _boom)
    _run_check(configured)

    error = client.get("/update/status").json()["error"]
    assert error == "Could not check for updates"
    assert "Errno" not in error


@pytest.mark.contract
def test_misconfigured_device_is_told_to_contact_support(client, monkeypatch):
    """No registry token or ring tag: retrying and restarting cannot help."""
    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "_OTA_GHCR_TOKEN", "")
    monkeypatch.setattr(web_main, "_OTA_IMAGE_TAG", "")
    _run_check(web_main)

    body = client.get("/update/status").json()
    assert body["status"] == "error"
    assert "contact Acorn Genetics for support" in body["error"]
    assert "IMAGE_TAG" not in body["error"]
    assert "credentials" not in body["error"]


@pytest.mark.contract
def test_a_later_successful_check_clears_the_failure(client, configured, monkeypatch):
    """A failure must not stick once the registry is reachable again."""
    async def _unreachable(*a, **kw):
        return None

    monkeypatch.setattr(configured, "_ghcr_manifest_digest", _unreachable)
    _run_check(configured)
    assert client.get("/update/status").json()["status"] == "error"

    async def _same_digest(*a, **kw):
        return "sha256:same"

    monkeypatch.setattr(configured, "_ghcr_manifest_digest", _same_digest)
    monkeypatch.setattr(configured, "_startup_image_digest", "sha256:same")
    monkeypatch.setattr(configured, "_startup_image_digest_ui", "sha256:same")
    _run_check(configured)

    body = client.get("/update/status").json()
    assert body["status"] == "idle"
    assert body["error"] is None


@pytest.mark.contract
def test_misconfigured_check_request_signals_failure_over_http(client, monkeypatch):
    """The panel branches on the HTTP status.

    POST /update/check answered 200 with {"ok": false}, so the page's error
    branch never fired and the message was unreachable (#423).
    """
    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "_OTA_GHCR_TOKEN", "")
    monkeypatch.setattr(web_main, "_OTA_IMAGE_TAG", "")

    response = client.post("/update/check")
    assert response.status_code >= 400, "a 2xx leaves the failure undetectable"
    body = response.json()
    assert body["ok"] is False
    assert "contact Acorn Genetics for support" in body["error"]


@pytest.mark.contract
def test_a_healthy_check_request_is_accepted(client, configured):
    assert client.post("/update/check").status_code == 200


# ---------------------------------------------------------------------------
# Applying an update
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_update_service_error_gives_the_operator_message(client, monkeypatch, tmp_path):
    """Watchtower answered but refused; the HTTP status is not the operator's problem."""
    from unittest.mock import AsyncMock, patch

    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(web_main.current_item, "screen", "ready")

    class _Resp:
        status_code = 500

    with patch.object(web_main.httpx, "AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=_Resp())
        body = client.post("/update/apply").json()

    assert body["ok"] is False
    assert body["error"] == "Update failed. Please try again."
    assert "500" not in body["error"]
    assert "Watchtower" not in body["error"]


@pytest.mark.contract
def test_unreachable_update_service_gives_the_same_message(client, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, patch

    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(web_main.current_item, "screen", "ready")

    with patch.object(web_main.httpx, "AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("All connection attempts failed")
        )
        body = client.post("/update/apply").json()

    assert body["ok"] is False
    assert body["error"] == "Update failed. Please try again."
    assert "connection attempts" not in body["error"]


@pytest.mark.contract
def test_a_failed_apply_is_reported_as_an_apply_failure(client, monkeypatch, tmp_path):
    """Check and apply shared one error slot, so an apply failure could be
    rendered under the panel's 'could not check for updates' heading."""
    from unittest.mock import AsyncMock, patch

    from aquila_web import main as web_main

    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(web_main.current_item, "screen", "ready")

    with patch.object(web_main.httpx, "AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("boom")
        )
        client.post("/update/apply")

    body = client.get("/update/status").json()
    assert body["error_kind"] == "apply"
    assert body["error"] == "Update failed. Please try again."


@pytest.mark.contract
def test_a_failed_check_after_a_failed_apply_reports_the_check(client, configured, monkeypatch, tmp_path):
    """The newer failure wins; the stale apply message must not leak through."""
    from unittest.mock import AsyncMock, patch

    monkeypatch.setattr(configured, "_UPDATE_SENTINEL_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(configured.current_item, "screen", "ready")

    with patch.object(configured.httpx, "AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("boom")
        )
        client.post("/update/apply")

    async def _unreachable(*a, **kw):
        return None

    monkeypatch.setattr(configured, "_ghcr_manifest_digest", _unreachable)
    _run_check(configured)

    body = client.get("/update/status").json()
    assert body["error_kind"] == "check"
    assert body["error"] == "Could not check for updates"
    assert "Update failed" not in body["error"]


@pytest.mark.contract
def test_the_technical_cause_is_kept_in_the_log(client, configured, monkeypatch):
    """Hiding the detail from the operator must not lose it for diagnosis.

    Asserts against the logger rather than caplog: other modules in the suite
    call logging.config.dictConfig, which disables existing loggers by default.
    """
    from unittest.mock import MagicMock

    async def _boom(*a, **kw):
        raise RuntimeError("[Errno -3] Temporary failure in name resolution")

    monkeypatch.setattr(configured, "_ghcr_manifest_digest", _boom)
    mock_logger = MagicMock()
    monkeypatch.setattr(configured, "logger", mock_logger)
    _run_check(configured)

    logged = " ".join(
        str(a)
        for call in mock_logger.exception.call_args_list + mock_logger.warning.call_args_list
        for a in call[0]
    )
    assert "name resolution" in logged or "Errno" in logged


@pytest.mark.contract
def test_panel_renders_the_message_verbatim():
    """The panel prefixed every error with 'Could not check for updates:'.

    That prefix is what let an apply failure read as a check failure, and it
    also double-headed the message now that the backend sends a complete
    sentence.
    """
    from pathlib import Path

    settings = (
        Path(__file__).parents[2] / "aquila_web" / "static" / "settings.html"
    ).read_text(encoding="utf-8")

    assert "Could not check for updates: $" not in settings
    assert "Update failed: $" not in settings


@pytest.mark.contract
def test_active_run_refusal_keeps_its_specific_wording(client, monkeypatch):
    """This one names a real next step, so it must not be genericised."""
    from aquila_web import main as web_main

    monkeypatch.setattr(web_main.current_item, "screen", "running")
    response = client.post("/update/apply")
    assert response.status_code == 409
    assert response.json()["error"] == "Cannot update during an active run. Stop the run first."
