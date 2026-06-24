"""
Unit tests for _merge_optics_history() in aquila_web/main.py.

Pure function: given the current recent-optics-path history and a candidate
path, return the new history (most-recent-first, deduped, capped). No file IO.
"""
import sys
import types

import pytest

# Stub heavy hardware dependencies before importing main.
for _mod in ("RPi", "RPi.GPIO"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

if "serial" not in sys.modules:
    _s = types.ModuleType("serial")
    _st = types.ModuleType("serial.tools")
    _lp = types.ModuleType("serial.tools.list_ports")
    _lp.comports = lambda: []
    _s.tools = _st
    _st.list_ports = _lp
    sys.modules.update({"serial": _s, "serial.tools": _st, "serial.tools.list_ports": _lp})

from aquila_web.main import _merge_optics_history, OPTICS_PATHS_LIMIT


def test_new_path_is_prepended_to_history():
    result = _merge_optics_history(["/old/path.log"], "/new/path.log")
    assert result == ["/new/path.log", "/old/path.log"]


def test_reentering_existing_path_moves_it_to_front_without_duplicate():
    result = _merge_optics_history(["/a.log", "/b.log", "/c.log"], "/c.log")
    assert result == ["/c.log", "/a.log", "/b.log"]


def test_history_is_capped_dropping_the_oldest_entry():
    full = [f"/path{i}.log" for i in range(OPTICS_PATHS_LIMIT)]
    result = _merge_optics_history(full, "/newest.log")
    assert len(result) == OPTICS_PATHS_LIMIT
    assert result[0] == "/newest.log"
    assert "/path19.log" not in result  # oldest dropped


@pytest.mark.parametrize("blank", [None, "", "   ", "\t\n"])
def test_blank_path_returns_history_unchanged(blank):
    history = ["/a.log", "/b.log"]
    result = _merge_optics_history(history, blank)
    assert result == ["/a.log", "/b.log"]


def test_surrounding_whitespace_is_trimmed_before_storing():
    result = _merge_optics_history([], "  /padded.log\n")
    assert result == ["/padded.log"]
