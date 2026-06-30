"""
Contract tests for per-device profile-editing lock.

A device flagged `profile_editing_disabled: true` in device_profiles.json must
have the profile build/edit surfaces blocked (403), while viewing and selecting
profiles for a run stay enabled. Devices without the flag behave as before.
"""
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("AQ_SRC_BASEDIR", str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = tmp_path / "config_files"
    cfg.mkdir()
    (cfg / "device_profiles.json").write_text(json.dumps({
        "locked-device": {"profile_group": "all", "profile_editing_disabled": True},
        "open-device": {"profile_group": "all"},
    }))
    (cfg / "profile_groups.json").write_text(json.dumps({"all": None}))

    bundled = tmp_path / "profiles" / "bundled"
    bundled.mkdir(parents=True)
    (bundled / "verification_profile.json").write_text(json.dumps({
        "title": "verification_profile",
        "post_in_gui": "True",
        "steps": [{"setpoint": 95, "duration": 1, "description": "step"}],
    }))

    from aquila_web import main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    with TestClient(web_main.app) as c:
        yield c


def test_locked_device_blocks_builder_page(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.get("/profiles/builder")
    assert resp.status_code == 403


def test_locked_device_blocks_edit_page(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.get("/profiles/edit")
    assert resp.status_code == 403


def test_locked_device_blocks_edit_form_editing(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.get("/profiles/edit-form")
    assert resp.status_code == 403


def test_locked_device_allows_read_only_view(monkeypatch, client):
    # Legacy profiles open read-only via ?view=1 — viewing stays enabled.
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.get("/profiles/edit-form?id=verification_profile.json&view=1")
    assert resp.status_code == 200


def test_locked_device_blocks_save_profile(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.post("/profiles", json={"name": "New", "steps": []})
    assert resp.status_code == 403


def test_locked_device_blocks_delete_profile(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.post("/profiles/delete", json={"profiles": ["local/foo.json"]})
    assert resp.status_code == 403


def test_locked_device_can_still_list_profiles(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.get("/profiles")
    assert resp.status_code == 200


def test_locked_device_can_still_select_profile(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.post("/profile/select", json={"profile": "verification_profile"})
    assert resp.status_code == 200


def test_open_device_can_access_edit(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "open-device")
    resp = client.get("/profiles/edit")
    assert resp.status_code == 200


def test_permissions_endpoint_reflects_locked_device(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    resp = client.get("/profiles/permissions")
    assert resp.status_code == 200
    assert resp.json()["editing_disabled"] is True


def test_permissions_endpoint_reflects_open_device(monkeypatch, client):
    monkeypatch.setenv("DEVICE_HOSTNAME", "open-device")
    resp = client.get("/profiles/permissions")
    assert resp.status_code == 200
    assert resp.json()["editing_disabled"] is False
