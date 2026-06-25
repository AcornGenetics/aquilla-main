"""
Unit tests for the countdown-timer backend helpers in aquila_web/main.py:

  - estimated_minutes_to_seconds()  (minutes -> seconds conversion)
  - _order_time_fields()            (JSON key placement / shape)

Pure logic, no hardware or network. Marked ``unit``.

The frontend countdown rendering (formatRemaining / finishing modal) lives in
script.js and is covered by the e2e DOM tests and the manual dev checklist
(spec §9.3 / §9.4), not here.
"""
import os
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Stub heavy hardware deps before importing main (same approach as the other
# unit test module so importing aquila_web.main works on a dev machine / CI).
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

from aquila_web.main import estimated_minutes_to_seconds, _order_time_fields


# ---------------------------------------------------------------------------
# estimated_minutes_to_seconds()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "minutes,expected",
    [
        (1, 60),
        (45, 2700),
        (90, 5400),
    ],
)
def test_positive_minutes_convert_to_seconds(minutes, expected):
    assert estimated_minutes_to_seconds(minutes) == expected


@pytest.mark.parametrize(
    "value",
    [None, 0, -5, "", "abc", float("nan"), float("inf"), float("-inf"), True, False],
)
def test_invalid_or_blank_returns_none(value):
    assert estimated_minutes_to_seconds(value) is None


def test_decimal_minutes_round_to_nearest():
    assert estimated_minutes_to_seconds(2.4) == 120  # rounds down to 2 min
    assert estimated_minutes_to_seconds(2.6) == 180  # rounds up to 3 min


# ---------------------------------------------------------------------------
# _order_time_fields()
# ---------------------------------------------------------------------------

def test_fields_inserted_after_rox_unavailable():
    profile = {
        "title": "P",
        "rox_unavailable": True,
        "time_unavailable": False,
        "estimated_completion_seconds": 2700,
        "steps": [],
    }
    keys = list(_order_time_fields(profile).keys())
    assert keys[keys.index("rox_unavailable") + 1] == "time_unavailable"
    assert keys[keys.index("time_unavailable") + 1] == "estimated_completion_seconds"
    assert keys.index("estimated_completion_seconds") < keys.index("steps")


def test_fields_inserted_after_title_when_no_rox():
    profile = {
        "title": "P",
        "time_unavailable": True,
        "estimated_completion_seconds": None,
        "steps": [],
    }
    keys = list(_order_time_fields(profile).keys())
    assert keys[keys.index("title") + 1] == "time_unavailable"
    assert keys[keys.index("time_unavailable") + 1] == "estimated_completion_seconds"


def test_values_and_other_keys_preserved():
    profile = {
        "title": "P",
        "time_unavailable": False,
        "estimated_completion_seconds": 3900,
        "steps": [1, 2],
        "labels": {"fam": "F"},
    }
    out = _order_time_fields(profile)
    assert out["time_unavailable"] is False
    assert out["estimated_completion_seconds"] == 3900
    assert out["steps"] == [1, 2]
    assert out["labels"] == {"fam": "F"}


def test_idempotent():
    profile = {
        "title": "P",
        "rox_unavailable": False,
        "time_unavailable": True,
        "estimated_completion_seconds": None,
        "steps": [],
    }
    once = _order_time_fields(profile)
    twice = _order_time_fields(once)
    assert once == twice
    assert list(once.keys()) == list(twice.keys())
