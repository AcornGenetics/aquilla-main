"""
Unit tests for resolve_device_profiles() in sentri_web/main.py.
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
sys.path.insert(0, str(REPO_ROOT / "sentri_web"))

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
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    return tmp_path


def _call(monkeypatch, hostname):
    monkeypatch.setenv("DEVICE_HOSTNAME", hostname)
    from sentri_web import main as web_main
    import importlib
    importlib.reload(web_main)
    monkeypatch.setattr(web_main, "BASE_DIR", monkeypatch._patches[-2].temp if hasattr(monkeypatch, "_patches") else web_main.BASE_DIR)
    return web_main.resolve_device_profiles()


def test_unknown_hostname_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn99")
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_group_null_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn01")
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_known_hostname_returns_correct_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result == {"ABBA_ramp1.75_EA30.json", "Hygiena_ramp1.75_EA30.json", "verification_profile.json"}


def test_extra_profiles_included(monkeypatch, tmp_path):
    (tmp_path / "config_files" / "device_profiles.json").write_text(json.dumps({
        "sn03": {"profile_group": "classic", "extra_profiles": ["ryan_thermal_tests.json"]}
    }))
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert "ryan_thermal_tests.json" in result
    assert "ABBA_ramp1.75_EA30.json" in result


def test_missing_device_profiles_file_returns_none(monkeypatch, tmp_path):
    (tmp_path / "config_files" / "device_profiles.json").unlink()
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_missing_profile_groups_file_returns_none(monkeypatch, tmp_path):
    (tmp_path / "config_files" / "profile_groups.json").unlink()
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn03")
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result is None


def test_duke_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_HOSTNAME", "sn02")
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main.resolve_device_profiles()
    assert result == {
        "ABBA_ramp1.75_EA30.json",
        "O157__ESBL_full.json",
        "STEC_and_EPEC_Hygiena1.75_no37Cstep.json",
        "verification_profile.json",
    }


# ── Migration tests ──────────────────────────────────────────────────────────

def _write_profile(path: Path, title: str = "Test") -> None:
    path.write_text(json.dumps({"title": title, "post_in_gui": "True", "steps": []}))


def test_migration_moves_bundled_files_to_bundled_subdir(monkeypatch, tmp_path):
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    _write_profile(pdir / "ABBA_ramp1.75_EA30.json")
    _write_profile(pdir / "verification_profile.json")

    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: pdir)
    web_main._migrate_profiles()

    assert (pdir / "bundled" / "ABBA_ramp1.75_EA30.json").exists()
    assert (pdir / "bundled" / "verification_profile.json").exists()
    assert not (pdir / "ABBA_ramp1.75_EA30.json").exists()


def test_migration_moves_unknown_files_to_local_subdir(monkeypatch, tmp_path):
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    _write_profile(pdir / "my_custom_profile.json")

    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: pdir)
    web_main._migrate_profiles()

    assert (pdir / "local" / "my_custom_profile.json").exists()
    assert not (pdir / "my_custom_profile.json").exists()


def test_migration_is_noop_when_subdirs_exist(monkeypatch, tmp_path):
    pdir = tmp_path / "profiles"
    (pdir / "bundled").mkdir(parents=True)
    (pdir / "local").mkdir(parents=True)
    _write_profile(pdir / "leftover.json")

    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: pdir)
    web_main._migrate_profiles()

    # flat file should NOT have been moved — migration was a no-op
    assert (pdir / "leftover.json").exists()


def test_migration_skips_flat_if_bundled_already_has_file(monkeypatch, tmp_path):
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    flat = pdir / "ABBA_ramp1.75_EA30.json"
    _write_profile(flat, title="old local edit")

    # Simulate entrypoint having already written the image version
    bundled_sub = pdir / "bundled"
    bundled_sub.mkdir()
    _write_profile(bundled_sub / "ABBA_ramp1.75_EA30.json", title="image version")
    # local/ does not exist yet — triggers migration
    (pdir / "local").mkdir()

    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: pdir)
    # Both subdirs exist → no-op; flat file untouched
    web_main._migrate_profiles()

    # Image version preserved
    data = json.loads((bundled_sub / "ABBA_ramp1.75_EA30.json").read_text())
    assert data["title"] == "image version"


def test_migration_aborts_gracefully_if_profile_groups_missing(monkeypatch, tmp_path):
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    _write_profile(pdir / "some_profile.json")
    # Remove profile_groups.json so migration can't determine bundled filenames
    (tmp_path / "config_files" / "profile_groups.json").unlink()

    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: pdir)
    web_main._migrate_profiles()  # should not raise

    # File should be untouched
    assert (pdir / "some_profile.json").exists()


# ── Filter works with real bundled/ subdir (production layout) ───────────────

def test_all_bundled_filenames_returns_union_of_all_groups(monkeypatch, tmp_path):
    import sentri_web.main as web_main
    monkeypatch.setattr(web_main, "BASE_DIR", tmp_path)
    result = web_main._all_bundled_filenames()
    assert "ABBA_ramp1.75_EA30.json" in result
    assert "O157__ESBL_full.json" in result
    assert "verification_profile.json" in result
