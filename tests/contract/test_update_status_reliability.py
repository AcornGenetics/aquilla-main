"""OTA status must be honest in both directions (#350).

The failures this guards against are not "no message shown" — they are wrong
messages shown confidently:

  - a failed registry check reported `idle`, which the UI renders as a green
    "✓ Software is up to date"
  - a failed pull left the poll loop falling through to "✓ Update complete"
  - a slow-but-successful update raised ReadTimeout on a 60s budget and was
    reported as "Update failed"

So these tests assert on the *distinction* between "checked, nothing new" and
"could not check", which is the thing that was collapsed.
"""
import asyncio

import pytest

from aquila_web import main


@pytest.fixture(autouse=True)
def _reset_update_state():
    """Module-level globals hold the OTA state; isolate each test."""
    saved = {
        k: getattr(main, k)
        for k in (
            "_update_available", "_update_status", "_update_error",
            "_update_last_checked", "_startup_image_digest",
            "_startup_image_digest_ui", "_latest_ghcr_digest",
            "_latest_ghcr_digest_ui", "_OTA_GHCR_TOKEN", "_OTA_IMAGE_TAG",
        )
    }
    main._OTA_GHCR_TOKEN = "token"
    main._OTA_IMAGE_TAG = "pilot"
    # Reset, not just save/restore: an earlier test in another file may have left
    # these set, and several assertions here are about what a failed check does
    # to them.
    main._update_available = False
    main._update_status = "idle"
    main._update_error = None
    main._startup_image_digest = "sha256:api-old"
    main._startup_image_digest_ui = "sha256:ui-old"
    main._update_last_checked = None
    yield
    for k, v in saved.items():
        setattr(main, k, v)


def _digests(monkeypatch, api, ui):
    """Stub the registry so each call returns a (digest, error_kind) pair."""
    async def fake(repo, tag, user, token):
        return api if "api" in repo else ui
    monkeypatch.setattr(main, "_ghcr_manifest_digest", fake)


# ── A failed check must not look like a successful one ────────────────────────

def test_unreachable_registry_reports_offline_not_idle(monkeypatch):
    """`idle` means "checked, nothing new" — the UI paints it green."""
    _digests(monkeypatch, (None, main._ERR_NETWORK), (None, main._ERR_NETWORK))
    asyncio.run(main._do_check_update())
    assert main._update_status == "offline"
    assert main._update_status != "idle"


def test_network_and_auth_failures_are_distinguishable(monkeypatch):
    """They need different operator actions, so they cannot share a message."""
    _digests(monkeypatch, (None, main._ERR_NETWORK), (None, main._ERR_NETWORK))
    asyncio.run(main._do_check_update())
    network_msg = main._update_error

    _digests(monkeypatch, (None, main._ERR_AUTH), (None, main._ERR_AUTH))
    asyncio.run(main._do_check_update())
    assert main._update_error != network_msg
    assert "credential" in main._update_error.lower()


def test_failed_check_does_not_refresh_last_checked(monkeypatch):
    """It is shown as "last successful check"; a failed attempt must not bump it."""
    _digests(monkeypatch, ("sha256:api-old", None), ("sha256:ui-old", None))
    asyncio.run(main._do_check_update())
    good = main._update_last_checked
    assert good is not None

    _digests(monkeypatch, (None, main._ERR_NETWORK), (None, main._ERR_NETWORK))
    asyncio.run(main._do_check_update())
    assert main._update_last_checked == good


# ── Partial failure is a failed check, not a partial success ──────────────────

def test_partial_digest_failure_does_not_offer_an_update(monkeypatch):
    """One digest resolving while the other blips is how api/ui end up skewed."""
    _digests(monkeypatch, ("sha256:api-new", None), (None, main._ERR_NETWORK))
    asyncio.run(main._do_check_update())
    assert main._update_status == "offline"
    assert main._update_available is False


def test_failed_check_withdraws_a_previously_known_update(monkeypatch):
    """Otherwise the UI shows "Update Now" against a registry it cannot reach.

    renderUpdateStatus checks `available` before `status`, so leaving it set
    would also hide the offline warning entirely.
    """
    _digests(monkeypatch, ("sha256:api-new", None), ("sha256:ui-new", None))
    asyncio.run(main._do_check_update())
    assert main._update_available is True

    _digests(monkeypatch, (None, main._ERR_NETWORK), (None, main._ERR_NETWORK))
    asyncio.run(main._do_check_update())
    assert main._update_available is False
    assert main._update_status == "offline"


def test_both_digests_resolving_and_changing_offers_an_update(monkeypatch):
    _digests(monkeypatch, ("sha256:api-new", None), ("sha256:ui-new", None))
    asyncio.run(main._do_check_update())
    assert main._update_status == "available"
    assert main._update_available is True


def test_no_change_reports_idle(monkeypatch):
    _digests(monkeypatch, ("sha256:api-old", None), ("sha256:ui-old", None))
    asyncio.run(main._do_check_update())
    assert main._update_status == "idle"
    assert main._update_available is False


# ── The status endpoint ───────────────────────────────────────────────────────

def test_status_exposes_staleness(client, monkeypatch):
    """A device that has never checked is stale — it cannot claim to be current."""
    main._update_last_checked = None
    body = client.get("/update/status").json()
    assert body["stale"] is True
    assert body["last_checked_age_seconds"] is None


def test_recent_successful_check_is_not_stale(client, monkeypatch):
    _digests(monkeypatch, ("sha256:api-old", None), ("sha256:ui-old", None))
    asyncio.run(main._do_check_update())
    body = client.get("/update/status").json()
    assert body["stale"] is False
    assert body["last_checked_age_seconds"] is not None
    assert body["last_checked_age_seconds"] < 60


def test_offline_status_is_reported_to_the_ui(client, monkeypatch):
    _digests(monkeypatch, (None, main._ERR_NETWORK), (None, main._ERR_NETWORK))
    asyncio.run(main._do_check_update())
    body = client.get("/update/status").json()
    assert body["status"] == "offline"
    assert body["error"]


# ── Watchtower metrics parsing ────────────────────────────────────────────────

def test_parses_prometheus_metrics():
    body = (
        "# HELP watchtower_containers_updated Number of containers updated\n"
        "# TYPE watchtower_containers_updated gauge\n"
        "watchtower_containers_updated 2\n"
        "watchtower_containers_failed 0\n"
        "watchtower_scans_total 17\n"
    )
    assert main._parse_prom_metric(body, "watchtower_containers_updated") == 2
    assert main._parse_prom_metric(body, "watchtower_containers_failed") == 0
    assert main._parse_prom_metric(body, "watchtower_scans_total") == 17


def test_missing_metric_returns_none():
    assert main._parse_prom_metric("watchtower_scans_total 3\n", "nope") is None


def test_comment_lines_are_not_mistaken_for_values():
    """A HELP line contains the metric name and must not be parsed as a value."""
    body = "# HELP watchtower_containers_failed some text 99\nwatchtower_containers_failed 0\n"
    assert main._parse_prom_metric(body, "watchtower_containers_failed") == 0


# ── A confirmed failure must disarm the reboot ────────────────────────────────

def test_confirmed_failure_clears_the_sentinel(tmp_path, monkeypatch):
    """A stale `reboot_pending` reboots the device for an update that never applied."""
    sentinel = tmp_path / "last_update.json"
    monkeypatch.setattr(main, "_UPDATE_SENTINEL_PATH", str(sentinel))
    monkeypatch.setattr(main, "_FLEET_ENV_PATH", str(tmp_path / "no-such.env"))
    main._sentinel.write_sentinel(str(sentinel), "reboot_pending", main._utcnow_iso())
    assert sentinel.exists()

    main._fail_update("pull failed", (None, None))

    assert main._update_status == "update_failed"
    assert main._sentinel.read_sentinel(str(sentinel)) in (None, {})


def test_confirmed_failure_leaves_the_update_outstanding(tmp_path, monkeypatch):
    """The update still needs applying, so it must not be marked done."""
    monkeypatch.setattr(main, "_UPDATE_SENTINEL_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(main, "_FLEET_ENV_PATH", str(tmp_path / "no-such.env"))
    main._fail_update("pull failed", (None, None))
    assert main._update_available is True


def test_confirmed_failure_restores_the_recorded_digests(tmp_path, monkeypatch):
    """/opt/fleet/.env must not claim a version the device is not running."""
    env = tmp_path / "fleet.env"
    env.write_text("RUNNING_IMAGE_DIGEST=sha256:old\nRUNNING_IMAGE_DIGEST_UI=sha256:oldui\nOTHER=keep\n")
    monkeypatch.setattr(main, "_FLEET_ENV_PATH", str(env))
    monkeypatch.setattr(main, "_UPDATE_SENTINEL_PATH", str(tmp_path / "s.json"))

    main._write_fleet_digests("sha256:new", "sha256:newui")
    assert "sha256:new" in env.read_text()

    main._fail_update("pull failed", ("sha256:old", "sha256:oldui"))
    text = env.read_text()
    assert "RUNNING_IMAGE_DIGEST=sha256:old" in text
    assert "RUNNING_IMAGE_DIGEST_UI=sha256:oldui" in text
    assert "OTHER=keep" in text, "unrelated lines must survive"
