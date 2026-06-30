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
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "ready")  # not mid-run

    # Watchtower is unreachable in tests; the sentinel must be written first regardless.
    client.post("/update/apply")
    rec = us.read_sentinel(path)
    assert rec is not None and rec["state"] == "reboot_pending"


def test_apply_during_active_run_is_rejected_and_writes_no_sentinel(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "running")

    resp = client.post("/update/apply")
    assert resp.status_code == 409
    assert us.read_sentinel(path) is None

