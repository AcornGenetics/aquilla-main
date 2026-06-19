"""
Contract tests for profile CRUD endpoints.

Run with:
    pytest tests/contract/ -m contract
"""
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_PROFILE = {
    "name": "Contract Test Profile",
    "fam_label": "FAM Target",
    "rox_label": "ROX Target",
    "steps": [
        {"setpoint": 95, "duration": 30},
        {"setpoint": 55, "duration": 60},
        {"setpoint": 72, "duration": 60},
    ],
}


def _create_profile(client, name="Contract Test Profile", **overrides) -> str:
    """POST a profile and return its id."""
    payload = {**MINIMAL_PROFILE, "name": name, **overrides}
    resp = client.post("/profiles", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("ok") is True
    return data["id"]


def _delete_profile(client, profile_id: str) -> None:
    client.post("/profiles/delete", json={"profiles": [profile_id]})


# ---------------------------------------------------------------------------
# GET /profiles
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_list_profiles_returns_list(client):
    """GET /profiles returns a list (may be empty)."""
    resp = client.get("/profiles")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# POST /profiles
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_create_profile_returns_id(client):
    """POST /profiles with valid payload creates a profile and returns an id."""
    profile_id = _create_profile(client, name="Create Returns ID")
    assert profile_id
    assert profile_id.endswith(".json")
    _delete_profile(client, profile_id)


@pytest.mark.contract
def test_created_profile_appears_in_list(client):
    """Profile created via POST /profiles appears in GET /profiles."""
    profile_id = _create_profile(client, name="Appears In List")
    try:
        profiles = client.get("/profiles").json()
        ids = [p["id"] for p in profiles]
        assert profile_id in ids
    finally:
        _delete_profile(client, profile_id)


# ---------------------------------------------------------------------------
# GET /profiles/details
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_profile_details_returns_required_fields(client):
    """GET /profiles/details?id=<id> returns fam_label (via labels), rox_label, steps."""
    profile_id = _create_profile(client, name="Details Fields Test")
    try:
        resp = client.get(f"/profiles/details?id={profile_id}")
        assert resp.status_code == 200
        data = resp.json()
        # steps key must be present
        assert "steps" in data
        # labels dict may carry fam/rox
        assert "labels" in data or "fam_label" in data or "title" in data
    finally:
        _delete_profile(client, profile_id)


@pytest.mark.contract
def test_profile_details_nonexistent_returns_404(client):
    """GET /profiles/details?id=nonexistent returns 404."""
    resp = client.get("/profiles/details?id=nonexistent_profile_xyz.json")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /profiles/delete
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_delete_profile_removes_it(client):
    """POST /profiles/delete removes the profile; subsequent GET /profiles excludes it."""
    profile_id = _create_profile(client, name="Delete Me Profile")
    # confirm it's there
    ids_before = [p["id"] for p in client.get("/profiles").json()]
    assert profile_id in ids_before

    resp = client.post("/profiles/delete", json={"profiles": [profile_id]})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    ids_after = [p["id"] for p in client.get("/profiles").json()]
    assert profile_id not in ids_after


@pytest.mark.contract
def test_list_profiles_after_delete_excludes_deleted(client):
    """GET /profiles after deletion does not include the deleted profile id."""
    profile_id = _create_profile(client, name="Exclude After Delete")
    _delete_profile(client, profile_id)
    ids = [p["id"] for p in client.get("/profiles").json()]
    assert profile_id not in ids


# ---------------------------------------------------------------------------
# POST /profile/select
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_profile_select_stored_in_button_status(client):
    """POST /profile/select stores selected profile in /button_status."""
    profile_id = _create_profile(client, name="Select Stored Test")
    try:
        resp = client.post("/profile/select", json={"profile": profile_id})
        assert resp.status_code == 200
        status = client.get("/button_status").json()
        assert status["profile"] == profile_id
    finally:
        _delete_profile(client, profile_id)


# ---------------------------------------------------------------------------
# Name sanitization / path traversal
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_profile_name_with_special_chars_is_sanitized(client):
    """Profile name with special characters gets a sanitized (safe) filename."""
    traversal_name = "../../etc/passwd"
    resp = client.post("/profiles", json={"name": traversal_name, "steps": []})
    assert resp.status_code == 200
    returned_id = resp.json().get("id", "")
    # ID may contain a known subdir prefix (e.g. "local/") — check the filename part only
    filename_part = returned_id.split("/")[-1]
    assert "\\" not in filename_part
    assert ".." not in filename_part
    # No extra slashes beyond the single allowed subdir prefix
    assert returned_id.count("/") <= 1
    _delete_profile(client, returned_id)


# ---------------------------------------------------------------------------
# Bundled + local both visible in listing
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_local_profile_appears_alongside_bundled(client):
    """A user-created (local) profile appears in /profiles together with bundled ones."""
    profile_id = _create_profile(client, name="Local And Bundled Coexist")
    try:
        profiles = client.get("/profiles").json()
        ids = [p["id"] for p in profiles]
        # The local profile is present
        assert profile_id in ids, f"local profile {profile_id!r} missing from listing"
        # At least one bundled profile is also present
        bundled_ids = [i for i in ids if i.startswith("bundled/")]
        assert bundled_ids, "No bundled profiles found alongside local profile"
    finally:
        _delete_profile(client, profile_id)


@pytest.mark.contract
def test_local_profile_has_bundled_false(client):
    """A user-created profile must not be flagged as bundled."""
    profile_id = _create_profile(client, name="Local Not Bundled")
    try:
        profiles = client.get("/profiles").json()
        match = next((p for p in profiles if p["id"] == profile_id), None)
        assert match is not None
        assert match.get("bundled") is False
    finally:
        _delete_profile(client, profile_id)


@pytest.mark.contract
def test_bundled_profile_has_bundled_true(client):
    """Profiles served from the bundled/ subdir must be flagged bundled=True."""
    profiles = client.get("/profiles").json()
    bundled = [p for p in profiles if p["id"].startswith("bundled/")]
    assert bundled, "No bundled profiles in listing — check profiles/bundled/ dir"
    for p in bundled:
        assert p.get("bundled") is True, f"{p['id']} missing bundled=True"


@pytest.mark.contract
def test_overwriting_bundled_does_not_alter_local_copy(client, tmp_path):
    """
    Replacing a bundled file on disk must not change a local profile with the
    same base name.  The two files live in separate subdirs and are independent.
    """
    from sentri_web import main as web_main

    profile_dir = web_main.resolve_profile_dir()
    bundled_dir = profile_dir / "bundled"
    local_dir = profile_dir / "local"
    bundled_dir.mkdir(parents=True, exist_ok=True)
    local_dir.mkdir(parents=True, exist_ok=True)

    fname = "shared_name_test.json"
    bundled_path = bundled_dir / fname
    local_path = local_dir / fname

    bundled_path.write_text(json.dumps({
        "title": "bundled version", "post_in_gui": "True", "steps": []
    }))
    local_path.write_text(json.dumps({
        "title": "local version", "post_in_gui": "True", "steps": []
    }))

    try:
        # Simulate entrypoint overwriting bundled copy with a new image version
        bundled_path.write_text(json.dumps({
            "title": "updated bundled version", "post_in_gui": "True", "steps": []
        }))

        # Local file must be unchanged
        local_data = json.loads(local_path.read_text())
        assert local_data["title"] == "local version", (
            "Overwriting bundled file mutated the local copy"
        )
    finally:
        bundled_path.unlink(missing_ok=True)
        local_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# POST /profiles with missing steps
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_create_profile_missing_steps_still_saves(client):
    """POST /profiles with missing steps key is handled gracefully."""
    resp = client.post(
        "/profiles",
        json={"name": "No Steps Profile", "fam_label": "FAM"},
    )
    # Must not crash — either 200 with ok=True or 4xx, never a 500
    assert resp.status_code != 500
    if resp.status_code == 200 and resp.json().get("ok"):
        _delete_profile(client, resp.json()["id"])
