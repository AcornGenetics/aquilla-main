"""Contract tests for the OTA auto-reboot completion flow (issue #183).

Drives the real endpoints via TestClient; the host reboot call is mocked.
"""


def test_show_complete_sentinel_surfaces_then_ack_clears(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)

    # Simulate the post-reboot boot: a "show_complete" sentinel is on disk.
    us.write_sentinel(path, "show_complete", web_main._utcnow_iso())
    web_main._resolve_startup_update_state()

    # The completion state is surfaced to the frontend.
    assert client.get("/update/status").json()["status"] == "complete"

    # Acknowledging clears the sentinel and returns to idle — fires exactly once.
    assert client.post("/update/ack-complete").json()["ok"] is True
    assert client.get("/update/status").json()["status"] == "idle"
    assert us.read_sentinel(path) is None


def test_reboot_pending_triggers_reboot_and_advances_sentinel(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "ready")  # not mid-run
    reboots = []
    monkeypatch.setattr(web_main, "_trigger_host_reboot", lambda: reboots.append(1) or True)

    # Post-update boot: the applying container left a "reboot_pending" sentinel.
    us.write_sentinel(path, "reboot_pending", web_main._utcnow_iso())
    web_main._resolve_startup_update_state()

    assert reboots == [1]  # rebooted exactly once
    # Sentinel advanced BEFORE the reboot, so the next boot shows the modal, not a loop.
    assert us.read_sentinel(path)["state"] == "show_complete"


def test_apply_writes_reboot_pending_sentinel(client, tmp_path, monkeypatch):
    """The sentinel is armed before Watchtower is triggered.

    It has to be: on success this container is killed mid-swap, so there is no
    "after" in which to write it. The successor reads it on startup to drive the
    reboot (#183).
    """
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "ready")  # not mid-run

    seen = []
    # web_main._sentinel IS the update_sentinel module, so keep a reference to the
    # original before patching or the wrapper calls itself.
    original = us.write_sentinel

    def _capture(p, state, ts):
        seen.append(state)
        return original(p, state, ts)

    monkeypatch.setattr(web_main._sentinel, "write_sentinel", _capture)
    client.post("/update/apply")
    assert seen == ["reboot_pending"]


def test_apply_disarms_the_sentinel_when_the_trigger_fails(client, tmp_path, monkeypatch):
    """Previously this left `reboot_pending` on disk for an update that never ran.

    Watchtower is unreachable under test, so the trigger fails. Any backend
    restart within the sentinel's 600s TTL would then reboot the device and show
    "Update Complete" for an update that never applied (#350 mode 4).
    """
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main, "_FLEET_ENV_PATH", str(tmp_path / "no-such.env"))
    monkeypatch.setattr(web_main.current_item, "screen", "ready")

    resp = client.post("/update/apply")

    assert resp.json()["ok"] is False
    assert us.read_sentinel(path) is None, "a failed trigger must leave no armed reboot"
    assert web_main._update_status == "update_failed"


def test_apply_during_active_run_is_rejected_and_writes_no_sentinel(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "running")

    resp = client.post("/update/apply")
    assert resp.status_code == 409
    assert us.read_sentinel(path) is None

