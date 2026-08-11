"""
Unit tests for the profile_json snapshot on run_complete (#417).

`fact_run.profile` carries only a path; the profile body exists nowhere but the
device's filesystem at run time, so it has to travel with the Run for the
internal app to show an analyst what the run actually did.

Behaviors tested:
  1. run_complete carries the profile body as a parsed object, matching the
     file at profiles/<profile>.
  2. A profile that cannot be resolved -> profile_json: null, run still enqueues.
  3. Invalid JSON in the profile file -> profile_json: null, run still enqueues.
  4. A profile over MAX_PROFILE_JSON_BYTES -> profile_json: null, not a
     truncated or oversized payload.
  5. A profile whose body is not a JSON object -> profile_json: null.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# serial is hardware-only; stub so aq_lib.state_requests imports without a device.
for _hw_mod in ("serial", "serial.tools", "serial.tools.list_ports"):
    sys.modules.setdefault(_hw_mod, MagicMock())
sys.modules.setdefault("aq_lib.config_module", MagicMock())

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


# A profile exactly as the device stores it: the thermal program that drove the run.
_PROFILE_BODY = {
    "name": "ABBA ramp1.75 EA30 sn005",
    "ramp_rate": 1.75,
    "labels": {"1": "FAM", "2": "ROX"},
    "steps": [
        {"label": "Initial Denature", "target_c": 95.0, "hold_s": 120},
        {"label": "Denature", "target_c": 95.0, "hold_s": 5, "cycles": 40},
        {"label": "Anneal/Extend", "target_c": 60.0, "hold_s": 30, "cycles": 40},
    ],
}


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    """TestClient backed by an isolated temp DB and an isolated profiles dir."""
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "test_events.db"))
    from aquila_web import local_db, main as web_main

    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: profile_dir)

    local_db.init_local_db()
    with TestClient(web_main.app) as c:
        yield c, local_db, profile_dir


def _write_profile(profile_dir: Path, name: str, text: str) -> Path:
    path = profile_dir / name
    path.write_text(text)
    return path


def _run_complete_payload(local_db):
    events = [e for e in local_db.get_pending_events() if e["event_type"] == "run_complete"]
    assert len(events) == 1, f"expected exactly one run_complete, got {len(events)}"
    return events[0]["payload"]


def _post_run(client, profile: str):
    response = client.post(
        "/events/run_complete",
        json={"run_name": "Run 1", "profile": profile},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


class TestProfileJsonSnapshot:
    def test_run_complete_carries_the_profile_body_as_an_object(self, db_client):
        client, local_db, profile_dir = db_client
        _write_profile(profile_dir, "abba.json", json.dumps(_PROFILE_BODY))

        _post_run(client, "abba.json")

        payload = _run_complete_payload(local_db)
        # A parsed object, not a string — the loader stores it as JSONB directly.
        assert isinstance(payload["profile_json"], dict)
        assert payload["profile_json"] == _PROFILE_BODY
        # The path is unchanged; profile_json is additive alongside it.
        assert payload["profile"] == "abba.json"

    def test_body_matches_the_file_that_actually_drove_the_run(self, db_client):
        """Two profiles on disk: the snapshot is the one the run named."""
        client, local_db, profile_dir = db_client
        other = {"name": "Other", "steps": [{"label": "Nope", "target_c": 4.0}]}
        _write_profile(profile_dir, "abba.json", json.dumps(_PROFILE_BODY))
        _write_profile(profile_dir, "other.json", json.dumps(other))

        _post_run(client, "other.json")

        assert _run_complete_payload(local_db)["profile_json"] == other

    def test_missing_profile_yields_null_and_the_run_still_completes(self, db_client):
        client, local_db, profile_dir = db_client

        _post_run(client, "nonexistent.json")

        payload = _run_complete_payload(local_db)
        assert payload["profile_json"] is None
        # The run reached the outbox regardless — never fail a run over this.
        assert payload["run_name"] == "Run 1"

    def test_invalid_json_yields_null_and_the_run_still_completes(self, db_client):
        client, local_db, profile_dir = db_client
        _write_profile(profile_dir, "broken.json", "{not valid json,,,")

        _post_run(client, "broken.json")

        payload = _run_complete_payload(local_db)
        assert payload["profile_json"] is None
        assert payload["run_name"] == "Run 1"

    def test_oversize_profile_yields_null_rather_than_a_bloated_payload(
        self, db_client, monkeypatch
    ):
        client, local_db, profile_dir = db_client
        from aquila_web import main as web_main

        # Valid JSON, but past the cap: the guard is on bytes on disk, so the
        # outbox never carries it.
        monkeypatch.setattr(web_main, "MAX_PROFILE_JSON_BYTES", 512)
        bloated = dict(_PROFILE_BODY, padding="x" * 2000)
        _write_profile(profile_dir, "huge.json", json.dumps(bloated))

        _post_run(client, "huge.json")

        payload = _run_complete_payload(local_db)
        assert payload["profile_json"] is None
        assert "padding" not in json.dumps(payload)

    def test_non_object_body_yields_null(self, db_client):
        """A JSON array parses fine but is not a profile; JSONB wants an object."""
        client, local_db, profile_dir = db_client
        _write_profile(profile_dir, "list.json", json.dumps([1, 2, 3]))

        _post_run(client, "list.json")

        assert _run_complete_payload(local_db)["profile_json"] is None


class TestProfileReferenceIsAPath:
    """The device's profile ref is the relative path GET /profiles emits.

    `/profile/select` stores ids like ``local/A3_Invalid_Temp.json`` and the run
    itself loads ``profiles/<ref>`` directly (state_run_assay.py). Matching only on
    name/stem/filename would miss every prefixed ref — i.e. capture nothing at all
    on a real device — so resolution must try the ref AS A PATH first, exactly as
    the run does.
    """

    def test_resolves_a_local_prefixed_reference(self, db_client):
        client, local_db, profile_dir = db_client
        (profile_dir / "local").mkdir()
        body = dict(_PROFILE_BODY, name="Local Copy")
        _write_profile(profile_dir / "local", "abba.json", json.dumps(body))

        _post_run(client, "local/abba.json")

        assert _run_complete_payload(local_db)["profile_json"] == body

    def test_resolves_a_bundled_prefixed_reference(self, db_client):
        client, local_db, profile_dir = db_client
        (profile_dir / "bundled").mkdir()
        body = dict(_PROFILE_BODY, name="Bundled Copy")
        _write_profile(profile_dir / "bundled", "abba.json", json.dumps(body))

        _post_run(client, "bundled/abba.json")

        assert _run_complete_payload(local_db)["profile_json"] == body

    def test_the_path_disambiguates_same_named_profiles(self, db_client):
        """profiles/ ships duplicate stems (test_profile, testing1) in root AND local.

        A fuzzy stem match returns whichever rglob happens to reach first, so the
        prefixed path is the only thing that can pick the right one.
        """
        client, local_db, profile_dir = db_client
        (profile_dir / "local").mkdir()
        root_body = dict(_PROFILE_BODY, name="Root", ramp_rate=1.0)
        local_body = dict(_PROFILE_BODY, name="Local", ramp_rate=2.0)
        _write_profile(profile_dir, "dupe.json", json.dumps(root_body))
        _write_profile(profile_dir / "local", "dupe.json", json.dumps(local_body))

        _post_run(client, "local/dupe.json")

        assert _run_complete_payload(local_db)["profile_json"] == local_body

    def test_refuses_to_escape_the_profile_dir(self, db_client, tmp_path):
        """A ref is device state, not a trusted path — no ../ reads outside profiles/."""
        client, local_db, profile_dir = db_client
        secret = tmp_path / "secret.json"
        secret.write_text(json.dumps({"token": "super-secret"}))

        _post_run(client, "../secret.json")

        assert _run_complete_payload(local_db)["profile_json"] is None


class TestProfileResolutionStaysShared:
    """_find_profile is the one resolution rule; labels and rox must not drift."""

    def test_labels_and_profile_json_resolve_the_same_file(self, db_client):
        client, local_db, profile_dir = db_client
        from aquila_web import main as web_main

        _write_profile(profile_dir, "abba.json", json.dumps(_PROFILE_BODY))

        assert web_main._load_profile_labels("abba.json") == _PROFILE_BODY["labels"]
        assert web_main._load_profile_json("abba.json")["labels"] == _PROFILE_BODY["labels"]

    def test_matching_by_body_name_not_just_filename(self, db_client):
        """The run's profile ref may be the display name, as list_profiles emits."""
        client, local_db, profile_dir = db_client
        from aquila_web import main as web_main

        _write_profile(profile_dir, "abba.json", json.dumps(_PROFILE_BODY))

        assert web_main._load_profile_json("ABBA ramp1.75 EA30 sn005") == _PROFILE_BODY

    def test_rox_unavailable_still_reads_through_the_shared_finder(self, db_client):
        client, local_db, profile_dir = db_client
        from aquila_web import main as web_main

        _write_profile(
            profile_dir, "rox.json", json.dumps({"name": "Rox", "rox_unavailable": True})
        )

        assert web_main._profile_rox_unavailable("rox.json") is True
        assert web_main._profile_rox_unavailable("abba.json") is False
