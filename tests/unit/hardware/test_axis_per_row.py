"""Row-aware axis positioning (#526 / Phase C Slice 1).

motor_class imports pigpio at load, stubbed here. goto_position selects the
current row's stops when the axis is calibrated per-row; the shared (flat) form
ignores the row — byte-identical to today.
"""
import sys
import types

import pytest
from unittest.mock import patch


@pytest.fixture
def motor_module():
    fake_pigpio = types.ModuleType("pigpio")
    fake_pigpio.pulse = lambda *a, **k: None
    fake_pigpio.pi = lambda *a, **k: None
    fake_pigpio.OUTPUT = 1
    fake_pigpio.INPUT = 0
    with patch.dict(sys.modules, {"pigpio": fake_pigpio}):
        sys.modules.pop("aq_lib.motor_class", None)
        import aq_lib.motor_class as m
        yield m
    sys.modules.pop("aq_lib.motor_class", None)


def _axis(module, positions):
    axis = object.__new__(module.Axis)
    axis.positions = positions
    axis._captured = []
    axis.move_abs_wo_home_flag = lambda pos, *a, **k: axis._captured.append(pos)
    return axis


@pytest.mark.unit
def test_goto_position_shared_stops_ignores_row(motor_module):
    axis = _axis(motor_module, [320, 675, 1030, 1380, 1740, 2080])  # flat/shared
    axis.goto_position(2)          # default row 0
    axis.goto_position(2, row=1)   # row ignored for shared
    assert axis._captured == [1030, 1030]


@pytest.mark.unit
def test_goto_position_per_row_uses_the_current_row(motor_module):
    axis = _axis(motor_module, [
        [10, 11, 12, 13, 14, 15, 16],
        [20, 21, 22, 23, 24, 25, 26],
        [30, 31, 32, 33, 34, 35, 36],
    ])
    axis.goto_position(2, row=0)   # -> 12
    axis.goto_position(2, row=2)   # -> 32
    assert axis._captured == [12, 32]
