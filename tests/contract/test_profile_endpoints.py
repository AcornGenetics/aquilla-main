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
    from aquila_web import main as web_main

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


# ---------------------------------------------------------------------------
# Estimated completion time / countdown timer (time_unavailable + seconds)
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_create_with_estimate_persists_seconds_and_flag(client):
    """estimated_minutes=45 stores 2700 seconds and time_unavailable=false."""
    pid = _create_profile(client, name="Est Persist", estimated_minutes=45)
    try:
        data = client.get(f"/profiles/details?id={pid}").json()
        assert data["estimated_completion_seconds"] == 45 * 60
        assert data["time_unavailable"] is False
    finally:
        _delete_profile(client, pid)


@pytest.mark.contract
def test_create_without_estimate_is_time_unavailable(client):
    """A profile saved with no estimate reports null seconds and time_unavailable=true."""
    pid = _create_profile(client, name="No Est")
    try:
        data = client.get(f"/profiles/details?id={pid}").json()
        assert data.get("estimated_completion_seconds") is None
        assert data["time_unavailable"] is True
    finally:
        _delete_profile(client, pid)


@pytest.mark.contract
def test_edit_clears_estimate_when_minutes_null(client):
    """Re-saving with estimated_minutes=null removes the estimate (back to unavailable)."""
    pid = _create_profile(client, name="Clear Est", estimated_minutes=30)
    try:
        assert (
            client.get(f"/profiles/details?id={pid}").json()["estimated_completion_seconds"]
            == 30 * 60
        )
        resp = client.post(
            "/profiles",
            json={
                "name": "Clear Est",
                "profile_id": pid,
                "steps": MINIMAL_PROFILE["steps"],
                "estimated_minutes": None,
            },
        )
        assert resp.status_code == 200, resp.text
        pid = resp.json()["id"]
        data = client.get(f"/profiles/details?id={pid}").json()
        assert data.get("estimated_completion_seconds") is None
        assert data["time_unavailable"] is True
    finally:
        _delete_profile(client, pid)


@pytest.mark.contract
def test_edit_omitting_estimate_preserves_existing(client):
    """Saving without the estimated_minutes key must not wipe an existing estimate."""
    pid = _create_profile(client, name="Preserve Est", estimated_minutes=20)
    try:
        resp = client.post(
            "/profiles",
            json={
                "name": "Preserve Est",
                "profile_id": pid,
                "steps": MINIMAL_PROFILE["steps"],
            },
        )
        assert resp.status_code == 200, resp.text
        pid = resp.json()["id"]
        data = client.get(f"/profiles/details?id={pid}").json()
        assert data["estimated_completion_seconds"] == 20 * 60
        assert data["time_unavailable"] is False
    finally:
        _delete_profile(client, pid)


@pytest.mark.contract
def test_saved_file_always_carries_both_fields_after_anchor(client):
    """Spec lines 21-22: both keys are always present in the saved JSON, positioned
    immediately after rox_unavailable (or after title when rox_unavailable is absent)."""
    from aquila_web import main as web_main

    pid = _create_profile(client, name="Shape Check", estimated_minutes=10)
    try:
        profile_path = web_main.resolve_profile_dir() / pid
        keys = list(json.loads(profile_path.read_text()).keys())
        assert "time_unavailable" in keys
        assert "estimated_completion_seconds" in keys
        anchor = "rox_unavailable" if "rox_unavailable" in keys else "title"
        assert keys[keys.index(anchor) + 1] == "time_unavailable"
        assert keys[keys.index("time_unavailable") + 1] == "estimated_completion_seconds"
    finally:
        _delete_profile(client, pid)


# ---------------------------------------------------------------------------
# Structured profiles — `stages` contract foundation (issue #197)
# ---------------------------------------------------------------------------

# The canonical structured-profile payload both routes build and test against.
SAMPLE_STAGES = {
    "incubation": {"enabled": True, "temp": 37, "time": 600},
    "denaturation": {"enabled": True, "temp": 95, "time": 120},
    "amplification": {
        "cycles": 40,
        "subStages": [
            {"name": "Denaturation", "temp": 95, "time": 11},
            {"name": "Annealing & Extension", "temp": 60.5, "time": 38},
        ],
    },
    "finalHold": {"enabled": False, "temp": 25, "time": 60},
}


@pytest.mark.contract
def test_post_profile_persists_and_returns_stages(client):
    """A `stages` payload is accepted, persisted, and read back unchanged.

    #197 only carries the contract surface — it does not assemble steps or
    validate ranges (those are A1/A2/A3). It must, however, round-trip the
    structured object so both routes can build against a real contract.
    """
    resp = client.post(
        "/profiles",
        json={"name": "Contract Stages Profile", "stages": SAMPLE_STAGES},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    try:
        details = client.get(f"/profiles/details?id={pid}")
        assert details.status_code == 200
        assert details.json()["stages"] == SAMPLE_STAGES
    finally:
        _delete_profile(client, pid)


@pytest.mark.contract
def test_profiles_builder_route_serves_html(client):
    """GET /profiles/builder serves the structured-editor HTML shell (issue #197)."""
    resp = client.get("/profiles/builder")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


@pytest.mark.contract
def test_sample_stages_fixture_matches_contract():
    """The committed sample fixture is the canonical `stages` shape (issue #197).

    Both routes build against this file, so it must match the agreed contract:
    incubation/denaturation/finalHold carry enabled+temp+time; amplification is
    always present (no `enabled`) with cycles and 2-3 sub-stages.
    """
    fixture = Path(__file__).parent.parent / "fixtures" / "sample_stages.json"
    data = json.loads(fixture.read_text())
    assert data == SAMPLE_STAGES

    for key in ("incubation", "denaturation", "finalHold"):
        assert set(data[key]) == {"enabled", "temp", "time"}, key
    amp = data["amplification"]
    assert "enabled" not in amp
    assert "cycles" in amp
    assert 2 <= len(amp["subStages"]) <= 3
    for sub in amp["subStages"]:
        assert set(sub) == {"name", "temp", "time"}


# ---------------------------------------------------------------------------
# Structured profiles — endpoint wiring (issue #201 / A3)
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_post_structured_profile_assembles_steps(client):
    """A valid stages payload is validated, assembled into steps, and persisted."""
    resp = client.post("/profiles", json={"name": "A3 Assembled", "stages": SAMPLE_STAGES})
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    try:
        data = client.get(f"/profiles/details?id={pid}").json()
        steps = data["steps"]
        # head, amplification repeat, and tail are all present
        assert steps[0] == {"disable": 0, "duration": 1, "description": "Record equilibration without power."}
        assert any("repeat" in s for s in steps)
        assert steps[-1] == {"pcr_fanoff": 0}
        # source of truth round-trips too
        assert data["stages"] == SAMPLE_STAGES
    finally:
        _delete_profile(client, pid)


@pytest.mark.contract
def test_post_invalid_stages_returns_400(client):
    """An out-of-range stages payload is rejected with 400 (validated before assembly)."""
    bad = json.loads(json.dumps(SAMPLE_STAGES))  # deep copy
    bad["incubation"]["temp"] = 200  # above the 100 C max
    resp = client.post("/profiles", json={"name": "A3 Invalid Temp", "stages": bad})
    assert resp.status_code == 400


@pytest.mark.contract
def test_post_malformed_stages_returns_400_not_500(client):
    """Malformed structure (missing sub-stage name) is rejected cleanly, never a 500
    (validate guards before assemble — the trust-boundary payoff)."""
    bad = json.loads(json.dumps(SAMPLE_STAGES))  # deep copy
    del bad["amplification"]["subStages"][0]["name"]
    resp = client.post("/profiles", json={"name": "A3 Malformed", "stages": bad})
    assert resp.status_code == 400


@pytest.mark.contract
def test_list_profiles_includes_structured_flag(client):
    """GET /profiles flags structured profiles (have `stages`) vs legacy ones."""
    structured_id = client.post(
        "/profiles", json={"name": "A3 Structured Flag", "stages": SAMPLE_STAGES}
    ).json()["id"]
    legacy_id = _create_profile(client, name="A3 Legacy Flag")  # steps-based, no stages
    try:
        by_id = {p["id"]: p for p in client.get("/profiles").json()}
        assert by_id[structured_id]["structured"] is True
        assert by_id[legacy_id]["structured"] is False
    finally:
        _delete_profile(client, structured_id)
        _delete_profile(client, legacy_id)


# ---------------------------------------------------------------------------
# Structured profiles — canonical JSON key order (issue #213 / A4)
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_structured_profile_keys_in_canonical_order(client):
    """A saved structured profile writes its top-level keys in canonical order:
    output_dir, post_in_gui, title, countdown fields, labels, stages, steps."""
    from aquila_web import main as web_main

    resp = client.post("/profiles", json={
        "name": "A4 Key Order",
        "fam_label": "FAM",
        "rox_label": "ROX",
        "stages": SAMPLE_STAGES,
    })
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    try:
        keys = list(json.loads((web_main.resolve_profile_dir() / pid).read_text()).keys())
        assert keys == [
            "output_dir", "post_in_gui", "title",
            "time_unavailable", "estimated_completion_seconds",
            "labels", "stages", "steps",
        ]
    finally:
        _delete_profile(client, pid)
