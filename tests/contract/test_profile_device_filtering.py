"""
Contract tests for per-device profile filtering via GET /profiles.

Tests that the allowlist from resolve_device_profiles() is correctly applied
by list_profiles(), and that devices not in device_profiles.json see all profiles.
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


ABBA_FILE = "ABBA_ramp1.75_EA30.json"
HYGIENA_FILE = "Hygiena_ramp1.75_EA30.json"
O157_FILE = "O157__ESBL_full.json"
STEC_FILE = "STEC_and_EPEC_Hygiena1.75_no37Cstep.json"
VERIFICATION_FILE = "verification_profile.json"
RYAN_FILE = "ryan_thermal_tests.json"


@pytest.fixture
def client_with_filtering(monkeypatch, tmp_path):
    """
    TestClient with BASE_DIR pointed at a tmp dir containing controlled
    config_files/ and a profiles/bundled/ directory with two test profiles.
    """
    cfg = tmp_path / "config_files"
    cfg.mkdir()
    (cfg / "profile_groups.json").write_text(json.dumps({
        "all": None,
        "classic": [ABBA_FILE, HYGIENA_FILE, VERIFICATION_FILE],
        "duke": [ABBA_FILE, O157_FILE, STEC_FILE, VERIFICATION_FILE],
    }))
    (cfg / "device_profiles.json").write_text(json.dumps({
        "classic-device": {"profile_group": "classic"},
        "duke-device": {"profile_group": "duke"},
        "all-device": {"profile_group": "all"},
    }))

    bundled = tmp_path / "profiles" / "bundled"
    bundled.mkdir(parents=True)
    for fname in [ABBA_FILE, HYGIENA_FILE, O157_FILE, STEC_FILE, VERIFICATION_FILE]:
        profile = {
            "title": fname.replace(".json", ""),
            "post_in_gui": "True",
            "steps": [{"setpoint": 95, "duration": 1, "description": "step"}],
        }
        (bundled / fname).write_text(json.dumps(profile))

    from sentri_web import main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)

    with TestClient(web_main.app) as c:
        yield c, web_main


def _profile_names(resp) -> set:
    return {p["id"].split("/")[-1] for p in resp.json()}


def test_classic_device_sees_only_classic_profiles(monkeypatch, client_with_filtering):
    client, web_main = client_with_filtering
    monkeypatch.setenv("DEVICE_HOSTNAME", "classic-device")
    resp = client.get("/profiles")
    assert resp.status_code == 200
    names = _profile_names(resp)
    assert ABBA_FILE in names
    assert HYGIENA_FILE in names
    assert VERIFICATION_FILE in names
    assert O157_FILE not in names
    assert STEC_FILE not in names


def test_duke_device_sees_only_duke_profiles(monkeypatch, client_with_filtering):
    client, web_main = client_with_filtering
    monkeypatch.setenv("DEVICE_HOSTNAME", "duke-device")
    resp = client.get("/profiles")
    assert resp.status_code == 200
    names = _profile_names(resp)
    assert ABBA_FILE in names
    assert O157_FILE in names
    assert STEC_FILE in names
    assert VERIFICATION_FILE in names
    assert HYGIENA_FILE not in names


def test_unknown_device_sees_all_profiles(monkeypatch, client_with_filtering):
    client, web_main = client_with_filtering
    monkeypatch.setenv("DEVICE_HOSTNAME", "unknown-device")
    resp = client.get("/profiles")
    assert resp.status_code == 200
    names = _profile_names(resp)
    assert ABBA_FILE in names
    assert HYGIENA_FILE in names
    assert O157_FILE in names
    assert STEC_FILE in names
    assert VERIFICATION_FILE in names


def test_all_group_device_sees_all_profiles(monkeypatch, client_with_filtering):
    client, web_main = client_with_filtering
    monkeypatch.setenv("DEVICE_HOSTNAME", "all-device")
    resp = client.get("/profiles")
    assert resp.status_code == 200
    names = _profile_names(resp)
    assert ABBA_FILE in names
    assert HYGIENA_FILE in names
    assert O157_FILE in names
    assert STEC_FILE in names
    assert VERIFICATION_FILE in names
