"""
Unit tests for resolve_profile_editing_disabled() in aquila_web/main.py.

A per-device flag (`profile_editing_disabled` in config_files/device_profiles.json)
locks profile building (edit/new) on chosen devices. Resolution fails OPEN:
unknown hostname, missing flag, or unreadable config => editing stays enabled.
"""
import json
import os
import sys
import types
from pathlib import Path

import pytest

# Stub heavy hardware deps before importing main
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
os.environ.setdefault("AQ_SRC_BASEDIR", str(REPO_ROOT))


@pytest.fixture
def base_dir(monkeypatch, tmp_path):
    cfg = tmp_path / "config_files"
    cfg.mkdir()
    (cfg / "device_profiles.json").write_text(json.dumps({
        "locked-device": {"profile_group": "all", "profile_editing_disabled": True},
        "unlocked-device": {"profile_group": "all", "profile_editing_disabled": False},
        "default-device": {"profile_group": "all"},
    }))
    import aquila_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    return tmp_path


def test_flag_true_disables_editing(monkeypatch, base_dir):
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    import aquila_web.main as web_main
    assert web_main.resolve_profile_editing_disabled() is True


def test_flag_false_keeps_editing_enabled(monkeypatch, base_dir):
    monkeypatch.setenv("DEVICE_HOSTNAME", "unlocked-device")
    import aquila_web.main as web_main
    assert web_main.resolve_profile_editing_disabled() is False


def test_missing_flag_keeps_editing_enabled(monkeypatch, base_dir):
    monkeypatch.setenv("DEVICE_HOSTNAME", "default-device")
    import aquila_web.main as web_main
    assert web_main.resolve_profile_editing_disabled() is False


def test_unknown_hostname_keeps_editing_enabled(monkeypatch, base_dir):
    monkeypatch.setenv("DEVICE_HOSTNAME", "not-in-config")
    import aquila_web.main as web_main
    assert web_main.resolve_profile_editing_disabled() is False


def test_missing_config_keeps_editing_enabled(monkeypatch, base_dir):
    (base_dir / "config_files" / "device_profiles.json").unlink()
    monkeypatch.setenv("DEVICE_HOSTNAME", "locked-device")
    import aquila_web.main as web_main
    assert web_main.resolve_profile_editing_disabled() is False
