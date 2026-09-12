"""
test_managed_profiles.py
========================
Contract tests for Managed Profiles (acorn-fleet ADR-0002, issue #457).

A Managed Profile lives in <profiles_dir>/managed/ (populated by the on-device
sync agent from the `profiles` Device Shadow + S3). It must:
  - appear in GET /profiles, and
  - be read-only (editing it is rejected), like the legacy bundled/ profiles.

Mirrors test_bundled_profiles.py's client fixture (repo profiles/ dir).
"""
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent

MANAGED_NAME = "pytest_managed_test_profile"
MANAGED_FILENAME = f"{MANAGED_NAME}.json"
MANAGED_CONTENT = {
    "title": MANAGED_NAME,
    "post_in_gui": "True",
    "steps": [
        {"disable": 0, "duration": 1, "description": "Start"},
        {"setpoint": 37, "duration": 5, "description": "Hold 37 C"},
    ],
}


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("AQ_SRC_BASEDIR", str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "aquila_web"))
    from aquila_web.main import app  # noqa: PLC0415
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def managed_test_profile(client):
    from aquila_web import main as web_main
    managed_dir = web_main.profile_dir / "managed"
    managed_dir.mkdir(parents=True, exist_ok=True)
    profile_path = managed_dir / MANAGED_FILENAME
    profile_path.write_text(json.dumps(MANAGED_CONTENT, indent=2))
    yield profile_path
    profile_path.unlink(missing_ok=True)


def test_managed_profile_appears_in_listing(client, managed_test_profile):
    resp = client.get("/profiles")
    assert resp.status_code == 200
    profiles = resp.json()
    ids = [p.get("id", "") for p in profiles]
    names = [p.get("name", "") for p in profiles]
    assert MANAGED_NAME in names or any(MANAGED_NAME in str(i) for i in ids), (
        f"Managed profile not found in /profiles.\nids: {ids}\nnames: {names}"
    )


def _managed_entry(client):
    profiles = client.get("/profiles").json()
    return next(
        (p for p in profiles
         if MANAGED_NAME in str(p.get("id", "")) or MANAGED_NAME in str(p.get("name", ""))),
        None,
    )


def test_managed_profile_is_marked_read_only(client, managed_test_profile):
    """Managed Profiles are read-only; the listing flags them so the UI locks
    editing (same treatment as legacy bundled profiles)."""
    entry = _managed_entry(client)
    assert entry is not None
    assert entry.get("bundled") is True


def test_editing_a_managed_profile_is_rejected(client, managed_test_profile):
    """Saving over a Managed Profile is forbidden (403) — they are controlled,
    S3-backed artifacts, not on-device editable."""
    resp = client.post("/profiles", json={
        "profile_id": f"managed/{MANAGED_FILENAME}",
        "name": MANAGED_NAME,
        "steps": [{"setpoint": 99, "duration": 1}],
    })
    assert resp.status_code == 403


def test_managed_profile_is_selectable_for_a_run(client, managed_test_profile):
    """A Managed Profile can be selected to run — the delivery path feeds the
    run selection just like any other profile."""
    resp = client.post("/profile/select", json={"profile": f"managed/{MANAGED_FILENAME}"})
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    status = client.get("/button_status").json()
    assert MANAGED_NAME in str(status.get("profile", ""))
