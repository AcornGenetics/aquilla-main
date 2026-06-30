"""
Unit tests for aquila_web.main._order_profile_keys — canonical top-level key
ordering for structured profiles (issue #213 / A4).

Pure dict->dict logic. Marked ``unit``. Spec: specs/backend/spec_profile_key_order.md.
"""
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

from aquila_web.main import _order_profile_keys


def test_orders_keys_canonically_regardless_of_input_order():
    """Keys are emitted in canonical order even when the input is scrambled."""
    scrambled = {
        "steps": [],
        "labels": {"fam": "FAM"},
        "title": "X",
        "stages": {},
        "output_dir": "pcr_data",
        "estimated_completion_seconds": 60,
        "post_in_gui": "True",
        "time_unavailable": False,
    }
    assert list(_order_profile_keys(scrambled).keys()) == [
        "output_dir", "post_in_gui", "title",
        "time_unavailable", "estimated_completion_seconds",
        "labels", "stages", "steps",
    ]


def test_only_present_keys_are_emitted():
    """Absent canonical keys (e.g. rox_unavailable, labels) are not invented."""
    profile = {"steps": [], "title": "X", "output_dir": "pcr_data"}
    assert list(_order_profile_keys(profile).keys()) == ["output_dir", "title", "steps"]


def test_rox_unavailable_placed_before_countdown_when_present():
    """rox_unavailable sits after title, before the countdown fields."""
    profile = {
        "steps": [], "title": "X", "output_dir": "pcr_data",
        "rox_unavailable": True, "time_unavailable": False,
    }
    assert list(_order_profile_keys(profile).keys()) == [
        "output_dir", "title", "rox_unavailable", "time_unavailable", "steps",
    ]


def test_unknown_keys_are_preserved_and_appended():
    """Keys not in the canonical list are kept (never dropped) and trail in order."""
    profile = {
        "steps": [], "output_dir": "pcr_data", "title": "X",
        "custom_one": 1, "custom_two": 2,
    }
    result = _order_profile_keys(profile)
    assert result["custom_one"] == 1 and result["custom_two"] == 2
    assert list(result.keys()) == ["output_dir", "title", "steps", "custom_one", "custom_two"]
