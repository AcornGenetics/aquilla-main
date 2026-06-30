"""
Unit tests for aquila_web.main._resolve_profile_display_name — History must
store the profile's display name (the JSON ``name`` field), not its file-path
id (issue #267).

Pure logic over the resolved profile dir. Marked ``unit``.
Spec: specs/backend/spec_history_profile_display_name.md.
"""
import json
import os
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Stub heavy hardware deps before importing main (same approach as the other
# unit test modules so importing aquila_web.main works on a dev machine / CI).
for _mod in ("RPi", "RPi.GPIO"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

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

from aquila_web import main as web_main


def _write_profile(profile_dir: Path, rel_path: str, data: dict) -> None:
    target = profile_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data))


def test_resolves_path_id_to_profile_name(tmp_path, monkeypatch):
    """A relative-path id resolves to the profile JSON's ``name`` field."""
    _write_profile(tmp_path, "local/A3_Invalid_Temp.json", {"name": "A3 Invalid Temp"})
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: tmp_path)

    assert web_main._resolve_profile_display_name("local/A3_Invalid_Temp.json") == "A3 Invalid Temp"


def test_resolved_name_has_no_path_or_extension_artifacts(tmp_path, monkeypatch):
    """The resolved value shows no path separator, no .json, no underscore-for-space."""
    _write_profile(tmp_path, "local/A3_Invalid_Temp.json", {"name": "A3 Invalid Temp"})
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: tmp_path)

    resolved = web_main._resolve_profile_display_name("local/A3_Invalid_Temp.json")
    assert "/" not in resolved and "\\" not in resolved
    assert ".json" not in resolved
    assert "_" not in resolved


def test_idempotent_for_already_resolved_name(tmp_path, monkeypatch):
    """Passing a value that is already the display name returns it unchanged."""
    _write_profile(tmp_path, "local/A3_Invalid_Temp.json", {"name": "A3 Invalid Temp"})
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: tmp_path)

    assert web_main._resolve_profile_display_name("A3 Invalid Temp") == "A3 Invalid Temp"


def test_empty_or_none_returns_placeholder(tmp_path, monkeypatch):
    """A falsy reference resolves to the '--' placeholder."""
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: tmp_path)

    assert web_main._resolve_profile_display_name(None) == "--"
    assert web_main._resolve_profile_display_name("") == "--"


def test_missing_file_falls_back_to_stem(tmp_path, monkeypatch):
    """An unresolvable id never shows a path/extension — falls back to the stem."""
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: tmp_path)

    assert web_main._resolve_profile_display_name("local/ghost.json") == "ghost"


def test_fallback_preserves_dots_in_name(tmp_path, monkeypatch):
    """A dotted name with no matching file keeps its dots (only .json is stripped)."""
    monkeypatch.setattr(web_main, "resolve_profile_dir", lambda: tmp_path)

    # Bare display name with a dot — nothing on disk matches it.
    assert web_main._resolve_profile_display_name("Sample 3.2 Panel") == "Sample 3.2 Panel"
    # Path-like id with a dotted stem — strip the dir and .json, keep the dot.
    assert web_main._resolve_profile_display_name("local/Cycle 2.5.json") == "Cycle 2.5"
