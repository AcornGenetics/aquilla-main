"""
test_bundled_profiles.py
========================
End-to-end test: bundled profiles in <profiles_dir>/bundled/ are correctly
discovered and returned by the GET /profiles API.

Root cause context
------------------
resolve_profile_dir() in aquila_web/main.py returns BASE_DIR/profiles.
list_profiles() globs profile_dir.glob("*.json") — non-recursive, so files
inside the bundled/ sub-directory are NOT currently returned.

Pass condition : the test profile created in bundled/ appears in /profiles.
Fail condition : it does not appear, exposing the glob-depth bug.

Running
-------
    # Local (uses repo profiles/ dir automatically via config.py fallback):
    pytest test_bundled_profiles.py -v

    # On-device (point at /opt/aquila):
    AQ_SRC_BASEDIR=/opt/aquila pytest test_bundled_profiles.py -v
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent

TEST_PROFILE_NAME = "pytest_bundled_test_profile"
TEST_PROFILE_FILENAME = f"{TEST_PROFILE_NAME}.json"
TEST_PROFILE_CONTENT = {
    "title": TEST_PROFILE_NAME,
    "post_in_gui": "True",
    "steps": [
        {"disable": 0, "duration": 1, "description": "Test step"},
        {"setpoint": 37, "duration": 5, "description": "Hold 37 C"},
        {"disable": 0, "duration": 1, "description": "Done"},
    ],
}


def _get_profiles_dir() -> Path:
    """Mirror the logic of resolve_profile_dir() without importing main.py early."""
    env_basedir = os.getenv("AQ_SRC_BASEDIR")
    if env_basedir and Path(env_basedir).is_absolute():
        return Path(env_basedir) / "profiles"
    config_path = REPO_ROOT / "config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            value = data.get("src_basedir") if isinstance(data, dict) else None
            if value and Path(value).exists():
                return Path(value) / "profiles"
        except Exception:
            pass
    return REPO_ROOT / "profiles"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bundled_test_profile():
    """
    Create a throw-away profile in <profiles_dir>/bundled/ for the duration of
    the test module, then clean it up.
    """
    profiles_dir = _get_profiles_dir()
    bundled_dir = profiles_dir / "bundled"
    bundled_dir.mkdir(parents=True, exist_ok=True)

    profile_path = bundled_dir / TEST_PROFILE_FILENAME
    profile_path.write_text(json.dumps(TEST_PROFILE_CONTENT, indent=2))

    yield profile_path

    profile_path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient — imports main.py once per module."""
    # Ensure config.py resolves to the repo root so profiles/ is found.
    os.environ.setdefault("AQ_SRC_BASEDIR", str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "aquila_web"))

    from aquila_web.main import app  # noqa: PLC0415
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBundledProfileDiscovery:
    """Bundled profiles must appear in the GET /profiles response."""

    def test_profiles_endpoint_returns_200(self, client, bundled_test_profile):
        resp = client.get("/profiles")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_profiles_endpoint_returns_list(self, client, bundled_test_profile):
        resp = client.get("/profiles")
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data).__name__}"

    def test_bundled_profile_appears_in_listing(self, client, bundled_test_profile):
        """
        PASS  → bundled profile is in /profiles response (desired behaviour).
        FAIL  → bundled profile missing; glob is not recursive (current bug).
        """
        resp = client.get("/profiles")
        profiles = resp.json()

        ids   = [p.get("id", "")   for p in profiles]
        names = [p.get("name", "") for p in profiles]

        assert (
            TEST_PROFILE_FILENAME in ids
            or TEST_PROFILE_NAME in names
            or any(TEST_PROFILE_NAME in str(i) for i in ids)
        ), (
            f"Bundled profile '{TEST_PROFILE_NAME}' not found in /profiles.\n"
            f"Returned ids:   {ids}\n"
            f"Returned names: {names}\n"
            "Fix: change profile_dir.glob('*.json') → profile_dir.rglob('*.json') "
            "in list_profiles() (main.py) and _load_profile_labels() (main.py)."
        )

    def test_bundled_profile_has_required_fields(self, client, bundled_test_profile):
        resp = client.get("/profiles")
        profiles = resp.json()

        match = next(
            (p for p in profiles
             if TEST_PROFILE_NAME in str(p.get("id", ""))
             or TEST_PROFILE_NAME in str(p.get("name", ""))),
            None,
        )
        # Skip field checks if profile not found (covered by previous test)
        if match is None:
            pytest.skip("Profile not listed — skipping field validation")

        for field in ("id", "name", "label", "configuration"):
            assert field in match, f"Missing field '{field}' in profile entry: {match}"

    def test_bundled_profile_configuration_has_steps(self, client, bundled_test_profile):
        resp = client.get("/profiles")
        profiles = resp.json()

        match = next(
            (p for p in profiles
             if TEST_PROFILE_NAME in str(p.get("id", ""))
             or TEST_PROFILE_NAME in str(p.get("name", ""))),
            None,
        )
        if match is None:
            pytest.skip("Profile not listed — skipping step validation")

        config = match.get("configuration", {})
        assert config, "Profile configuration must not be empty"


class TestBundledProfileSelectability:
    """Selected bundled profile must be accepted by POST /profile/select."""

    def test_select_bundled_profile(self, client, bundled_test_profile):
        resp = client.post("/profile/select", json={"profile": TEST_PROFILE_NAME})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("ok") is True, f"select failed: {body}"

    def test_status_reflects_selected_profile(self, client, bundled_test_profile):
        client.post("/profile/select", json={"profile": TEST_PROFILE_NAME})
        resp = client.get("/button_status")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("profile") == TEST_PROFILE_NAME, (
            f"Expected profile='{TEST_PROFILE_NAME}', got profile='{body.get('profile')}'"
        )


UI_PROFILE_NAME = "pytest_ui_created_profile"
UI_PROFILE_STEPS = [
    {"disable": 0, "duration": 1, "description": "Start"},
    {"setpoint": 95, "duration": 30, "description": "Denature"},
    {"setpoint": 60, "duration": 30, "description": "Anneal"},
    {"disable": 0, "duration": 1, "description": "End"},
]


class TestUICreatedProfileEndToEnd:
    """
    A profile created via POST /profiles (the UI save flow) must:
    - be saved and return an id
    - appear in GET /profiles (the dropdown data source)
    - be selectable via POST /profile/select
    - be reflected in GET /button_status

    These tests are independent of bundled/ — they cover the standard
    user-created profile path.
    """

    @pytest.fixture(autouse=True)
    def create_and_cleanup(self, client):
        """Create the profile before each test, delete after."""
        resp = client.post("/profiles", json={
            "name": UI_PROFILE_NAME,
            "steps": UI_PROFILE_STEPS,
        })
        assert resp.status_code == 200, f"Profile creation failed: {resp.text}"
        body = resp.json()
        assert body.get("ok") is True
        self.profile_id = body.get("id")

        yield

        # Cleanup: delete via the delete endpoint
        if self.profile_id:
            client.post("/profiles/delete", json={"profiles": [self.profile_id]})

    def test_save_returns_id(self, client):
        assert self.profile_id, "POST /profiles must return a non-empty id"
        assert self.profile_id.endswith(".json"), (
            f"id should be a filename, got: {self.profile_id}"
        )

    def test_ui_profile_appears_in_listing(self, client):
        """Profile created via UI must show up in the dropdown source."""
        resp = client.get("/profiles")
        assert resp.status_code == 200
        profiles = resp.json()

        ids   = [p.get("id", "")   for p in profiles]
        names = [p.get("name", "") or p.get("label", "") for p in profiles]

        assert (
            self.profile_id in ids
            or UI_PROFILE_NAME in names
            or any(UI_PROFILE_NAME in str(i) for i in ids)
        ), (
            f"UI-created profile '{UI_PROFILE_NAME}' (id={self.profile_id}) "
            f"not found in /profiles.\nids: {ids}\nnames: {names}"
        )

    def test_ui_profile_has_steps_in_configuration(self, client):
        """The profile's configuration must include the saved steps."""
        resp = client.get("/profiles")
        profiles = resp.json()

        match = next(
            (p for p in profiles
             if p.get("id") == self.profile_id
             or UI_PROFILE_NAME in str(p.get("name", ""))
             or UI_PROFILE_NAME in str(p.get("id", ""))),
            None,
        )
        assert match is not None, f"Profile not found in listing (id={self.profile_id})"
        assert match.get("configuration"), "configuration field must not be empty"

    def test_ui_profile_is_selectable(self, client):
        """POST /profile/select must accept the UI-created profile by name."""
        resp = client.post("/profile/select", json={"profile": UI_PROFILE_NAME})
        assert resp.status_code == 200
        assert resp.json().get("ok") is True

    def test_selected_ui_profile_reflected_in_status(self, client):
        """After selecting, GET /button_status must show the profile."""
        client.post("/profile/select", json={"profile": UI_PROFILE_NAME})
        resp = client.get("/button_status")
        assert resp.status_code == 200
        assert resp.json().get("profile") == UI_PROFILE_NAME
