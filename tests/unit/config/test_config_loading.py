"""
Unit tests for sentri_lib.config_module.Config — loading, hostname dispatch,
fallback paths, malformed JSON, and schema validation.

All tests use monkeypatch to set environment variables and tmp_path for
any synthetic config files.  No real hardware or serial ports are needed.
"""
import json
import os
from pathlib import Path

import pytest

# serial is a C-extension that may not be present in every CI environment.
# Mock it before importing config_module so collection never fails due to
# a missing pyserial wheel.
import sys
import types

if "serial" not in sys.modules:
    _serial_stub = types.ModuleType("serial")
    _serial_tools = types.ModuleType("serial.tools")
    _list_ports_mod = types.ModuleType("serial.tools.list_ports")
    _list_ports_mod.comports = lambda: []
    _serial_stub.tools = _serial_tools
    _serial_tools.list_ports = _list_ports_mod
    sys.modules["serial"] = _serial_stub
    sys.modules["serial.tools"] = _serial_tools
    sys.modules["serial.tools.list_ports"] = _list_ports_mod

from sentri_lib.config_module import Config

# Path to the real config files shipped with the project
REAL_CONFIG_DIR = str(
    Path(__file__).parents[3] / "config_files"
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _write_host_config(directory: Path, data: dict) -> None:
    (directory / "host_config.json").write_text(json.dumps(data))


def _write_state_config(directory: Path, data: dict | None = None) -> None:
    if data is None:
        # Copy the real state_config to the temp dir
        real = Path(REAL_CONFIG_DIR) / "state_config.json"
        (directory / "state_config.json").write_text(real.read_text())
    else:
        (directory / "state_config.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Happy-path loading
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_config_loads_correctly_for_known_hostname(monkeypatch):
    """Config() must load without error when DEVICE_HOSTNAME is 'sn01'."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    assert cfg.hostname == "sn01"


@pytest.mark.unit
def test_config_selects_per_device_config_by_hostname(monkeypatch):
    """Per-device config must be keyed by hostname, not returned as a flat blob."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    # If per-device dispatch worked, cfg.dict should be the sn01 sub-dict,
    # NOT a dict whose first key is 'sn01'.
    assert "sn01" not in cfg.dict, (
        "Config.dict appears to be the top-level per-device map, not the device slice"
    )


@pytest.mark.unit
def test_config_falls_back_to_config_files_when_env_not_set(monkeypatch):
    """When CONFIG_DIR is unset, Config() must fall back to 'config_files/'."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.delenv("CONFIG_DIR", raising=False)
    # Change cwd to project root so relative 'config_files' path resolves correctly
    original_cwd = os.getcwd()
    project_root = str(Path(__file__).parents[3])
    os.chdir(project_root)
    try:
        cfg = Config()
        assert cfg.hostname == "sn01"
    finally:
        os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_config_raises_key_error_for_unknown_hostname(tmp_path, monkeypatch):
    """Config() must raise KeyError when hostname is not in host_config.json."""
    _write_host_config(
        tmp_path,
        {"sn01": {"pcr": {}, "drawer": {}, "axis": {}, "optics": {}, "adc": {}}},
    )
    _write_state_config(tmp_path)
    monkeypatch.setenv("DEVICE_HOSTNAME", "does_not_exist")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    with pytest.raises(KeyError, match="does_not_exist"):
        Config()


@pytest.mark.unit
def test_config_raises_when_host_config_missing(tmp_path, monkeypatch):
    """Config() must raise when host_config.json does not exist."""
    _write_state_config(tmp_path)
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    # No host_config.json written into tmp_path
    with pytest.raises((FileNotFoundError, OSError)):
        Config()


@pytest.mark.unit
def test_config_raises_informative_error_on_malformed_json(tmp_path, monkeypatch):
    """Config() must raise (with a useful message) when host_config.json is invalid JSON."""
    (tmp_path / "host_config.json").write_text("{ this is: not valid JSON !!!")
    _write_state_config(tmp_path)
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    with pytest.raises((json.JSONDecodeError, ValueError)):
        Config()


# ---------------------------------------------------------------------------
# Schema — top-level device keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_loaded_config_has_required_top_level_keys(monkeypatch):
    """Device config must contain pcr, drawer, axis, optics, and adc keys."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    for key in ("pcr", "drawer", "axis", "optics", "adc"):
        assert key in cfg.dict, f"missing top-level config key '{key}'"


# ---------------------------------------------------------------------------
# Schema — drawer sub-config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_drawer_config_has_open_read_home_steps(monkeypatch):
    """drawer config must include open_steps, read_steps, and home_steps."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    drawer = cfg.dict["drawer"]
    for key in ("open_steps", "read_steps", "home_steps"):
        assert key in drawer, f"drawer missing key '{key}'"


@pytest.mark.unit
def test_drawer_open_steps_is_integer(monkeypatch):
    """open_steps must be a numeric value (int or float)."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    assert isinstance(cfg.dict["drawer"]["open_steps"], (int, float))


# ---------------------------------------------------------------------------
# Schema — axis sub-config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_axis_config_has_positions_list_of_length_6(monkeypatch):
    """axis.positions must be a list with exactly 6 entries."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    positions = cfg.dict["axis"]["positions"]
    assert isinstance(positions, list), "axis.positions is not a list"
    assert len(positions) == 6, (
        f"axis.positions has {len(positions)} entries, expected 6"
    )


# ---------------------------------------------------------------------------
# Schema — state config
# ---------------------------------------------------------------------------


REQUIRED_STATE_KEYS = {"-1", "-2", "-3", "-4", "-5", "0", "1", "2", "3"}


@pytest.mark.unit
def test_state_config_has_all_required_screen_keys(monkeypatch):
    """state_config must contain keys -5 through 3 (as strings)."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    missing = REQUIRED_STATE_KEYS - set(cfg.state.keys())
    assert not missing, f"state_config is missing keys: {sorted(missing)}"


@pytest.mark.unit
def test_state_config_entries_have_title_and_text(monkeypatch):
    """Each state entry must have 'title' and 'text' fields."""
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", REAL_CONFIG_DIR)
    cfg = Config()
    for key in REQUIRED_STATE_KEYS:
        entry = cfg.state[key]
        assert "title" in entry, f"state['{key}'] missing 'title'"
        assert "text" in entry, f"state['{key}'] missing 'text'"


# ---------------------------------------------------------------------------
# Flat config format (not per-device)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_flat_config_loaded_directly_without_hostname_lookup(tmp_path, monkeypatch):
    """A flat config (no per-device nesting) must be loaded as-is."""
    flat = {"pcr": {}, "drawer": {"open_steps": 100, "read_steps": 10, "home_steps": 200},
            "axis": {"positions": [1, 2, 3, 4, 5, 6]}, "optics": {}, "adc": {}}
    _write_host_config(tmp_path, flat)
    _write_state_config(tmp_path)
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cfg = Config()
    # Flat config: first value is {} (not a dict-of-dicts), so no hostname lookup
    assert "drawer" in cfg.dict


@pytest.mark.unit
def test_per_device_config_selects_correct_hostname(tmp_path, monkeypatch):
    """Per-device config must select the sub-dict matching DEVICE_HOSTNAME."""
    per_device = {
        "sn01": {
            "pcr": {}, "drawer": {"open_steps": 111, "read_steps": 11, "home_steps": 222},
            "axis": {"positions": [1, 2, 3, 4, 5, 6]}, "optics": {}, "adc": {},
        },
        "sn02": {
            "pcr": {}, "drawer": {"open_steps": 999, "read_steps": 99, "home_steps": 888},
            "axis": {"positions": [6, 5, 4, 3, 2, 1]}, "optics": {}, "adc": {},
        },
    }
    _write_host_config(tmp_path, per_device)
    _write_state_config(tmp_path)
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cfg = Config()
    assert cfg.dict["drawer"]["open_steps"] == 111, (
        "loaded config is for the wrong device"
    )


@pytest.mark.unit
def test_per_device_config_not_mixed_with_other_device(tmp_path, monkeypatch):
    """sn02 values must not bleed into the sn01 config slice."""
    per_device = {
        "sn01": {
            "pcr": {}, "drawer": {"open_steps": 111, "read_steps": 11, "home_steps": 222},
            "axis": {"positions": [1, 2, 3, 4, 5, 6]}, "optics": {}, "adc": {},
        },
        "sn02": {
            "pcr": {}, "drawer": {"open_steps": 999, "read_steps": 99, "home_steps": 888},
            "axis": {"positions": [6, 5, 4, 3, 2, 1]}, "optics": {}, "adc": {},
        },
    }
    _write_host_config(tmp_path, per_device)
    _write_state_config(tmp_path)
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cfg = Config()
    assert cfg.dict["drawer"]["open_steps"] != 999, (
        "sn02 open_steps leaked into sn01 config"
    )
