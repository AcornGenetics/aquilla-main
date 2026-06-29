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
    monkeypatch.setattr(web_main, "_fetch_running_digest", lambda: None, raising=False)

    # Post-update boot: the applying container left a "reboot_pending" sentinel.
    us.write_sentinel(path, "reboot_pending", web_main._utcnow_iso())
    web_main._resolve_startup_update_state()

    assert reboots == [1]  # rebooted exactly once
    # Sentinel advanced BEFORE the reboot, so the next boot shows the modal, not a loop.
    assert us.read_sentinel(path)["state"] == "show_complete"


def test_reboot_pending_with_mismatched_digest_advances_to_show_failed(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "ready")  # not mid-run
    reboots = []
    monkeypatch.setattr(web_main, "_trigger_host_reboot", lambda: reboots.append(1) or True)
    # The device crashed mid-update: it is still running the OLD image, not the target.
    monkeypatch.setattr(web_main, "_fetch_running_digest", lambda: "sha256:old", raising=False)

    us.write_sentinel(path, "reboot_pending", web_main._utcnow_iso(), target_digest="sha256:new")
    web_main._resolve_startup_update_state()

    assert reboots == [1]  # still reboots once (clean screen for the modal)
    # Confirmed mismatch -> the next boot must show "Update Failed", not a false "Complete".
    assert us.read_sentinel(path)["state"] == "show_failed"


def test_show_failed_sentinel_surfaces_then_ack_clears(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)

    # The post-failure boot: a "show_failed" sentinel is on disk.
    us.write_sentinel(path, "show_failed", web_main._utcnow_iso())
    web_main._resolve_startup_update_state()

    # The failure is surfaced to the frontend, not a false "complete".
    assert client.get("/update/status").json()["status"] == "failed"

    # Acknowledging clears the sentinel and returns to idle — fires exactly once.
    assert client.post("/update/ack-failed").json()["ok"] is True
    assert client.get("/update/status").json()["status"] == "idle"
    assert us.read_sentinel(path) is None


def test_reboot_pending_with_matching_digest_advances_to_show_complete(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "ready")
    monkeypatch.setattr(web_main, "_trigger_host_reboot", lambda: True)
    # Update applied cleanly: the running image is the one we installed.
    monkeypatch.setattr(web_main, "_fetch_running_digest", lambda: "sha256:new", raising=False)

    us.write_sentinel(path, "reboot_pending", web_main._utcnow_iso(), target_digest="sha256:new")
    web_main._resolve_startup_update_state()

    assert us.read_sentinel(path)["state"] == "show_complete"


def test_reboot_pending_with_unreachable_digest_stays_optimistic(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "ready")
    monkeypatch.setattr(web_main, "_trigger_host_reboot", lambda: True)
    # Host can't be reached / has no /image-digest -> indeterminate. Must NOT show a
    # false "Update Failed"; fall back to today's optimistic completion.
    monkeypatch.setattr(web_main, "_fetch_running_digest", lambda: None, raising=False)

    us.write_sentinel(path, "reboot_pending", web_main._utcnow_iso(), target_digest="sha256:new")
    web_main._resolve_startup_update_state()

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


def test_apply_records_target_digest_for_later_verification(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "ready")
    # The digest we are updating to, discovered by the GHCR poll.
    monkeypatch.setattr(web_main, "_latest_ghcr_digest", "sha256:new")

    client.post("/update/apply")
    rec = us.read_sentinel(path)
    # Recorded so the post-update boot can tell a real update from a crash.
    assert rec["target_digest"] == "sha256:new"


def test_apply_during_active_run_is_rejected_and_writes_no_sentinel(client, tmp_path, monkeypatch):
    from aquila_web import main as web_main
    from aquila_web import update_sentinel as us

    path = str(tmp_path / "last_update.json")
    monkeypatch.setattr(web_main, "_UPDATE_SENTINEL_PATH", path)
    monkeypatch.setattr(web_main.current_item, "screen", "running")

    resp = client.post("/update/apply")
    assert resp.status_code == 409
    assert us.read_sentinel(path) is None

