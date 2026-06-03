"""
Unit tests for resolve_device_profiles() in aquila_web/main.py.
"""
import json
import os
import sys
from pathlib import Path

import pytest

# Stub heavy dependencies before importing main
import types

for mod in ("RPi", "RPi.GPIO"):
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

if "serial" not in sys.modules:
    _s = types.ModuleType("serial")
    _st = types.ModuleType("serial.tools")
    _lp = types.ModuleType("serial.tools.list_ports")
    _lp.comports = lambda: []
    _s.tools = _st
    _st.list_ports = _lp
    sys.modules.update({"serial": _s, "serial.tools": _st, "serial.tools.list_ports": _lp})

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "aquila_web"))

os.environ.setdefault("AQ_DEV_SIMULATE", "1")
os.environ.setdefault("AQ_SRC_BASEDIR", str(REPO_ROOT))


def _make_configs(tmp_path, device_profiles: dict, profile_groups: dict) -> Path:
    cfg = tmp_path / "config_files"
    cfg.mkdir()
    (cfg / "device_profiles.json").write_text(json.dumps(device_profiles))
    (cfg / "profile_groups.json").write_text(json.dumps(profile_groups))
    return tmp_path


@pytest.fixture(autouse=True)
def patch_base_dir(monkeypatch, tmp_path):
    _make_configs(
        tmp_path,
        {
            "sn01": {"profile_group": "all"},
            "sn02": {"profile_group": "duke"},
            "sn03": {"profile_group": "classic"},
        },
        {
            "all": None,
            "classic": ["ABBA_ramp1.75_EA30.json", "Hygiena_ramp1.75_EA30.json", "verification_profile.json"],
            "duke": ["ABBA_ramp1.75_EA30.json", "O157__ESBL_full.json", "STEC_and_EPEC_Hygiena1.75_no37Cstep.json", "verification_profile.json"],
        },
    )
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    return tmp_path


def _call(monkeypatch, hostname):
    monkeypatch.setenv("DEVICE_HOSTNAME", hostname)
    from aquila_web import main as web_main
    import importlib
    importlib.reload(web_main)
    monkeypatch.setattr(web_main, "BASE_DIR", monkeypatch._patches[-2].temp if hasattr(monkeypatch, "_patches") else web_main.BASE_DIR)
    return web_main.resolve_device_profiles()


def test_unknown_hostname_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn99")
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_group_null_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_known_hostname_returns_correct_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result == {"ABBA_ramp1.75_EA30.json", "Hygiena_ramp1.75_EA30.json", "verification_profile.json"}


def test_extra_profiles_included(monkeypatch, tmp_path):
    (tmp_path / "config_files" / "device_profiles.json").write_text(json.dumps({
        "sn03": {"profile_group": "classic", "extra_profiles": ["ryan_thermal_tests.json"]}
    }))
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert "ryan_thermal_tests.json" in result
    assert "ABBA_ramp1.75_EA30.json" in result


def test_missing_device_profiles_file_returns_none(monkeypatch, tmp_path):
    (tmp_path / "config_files" / "device_profiles.json").unlink()
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_missing_profile_groups_file_returns_none(monkeypatch, tmp_path):
    (tmp_path / "config_files" / "profile_groups.json").unlink()
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_duke_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn02")
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result == {
        "ABBA_ramp1.75_EA30.json",
        "O157__ESBL_full.json",
        "STEC_and_EPEC_Hygiena1.75_no37Cstep.json",
        "verification_profile.json",
    }
