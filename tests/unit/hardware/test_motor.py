"""
Unit tests for sentri_lib/motor_class.py (Axis and Drawer).

RPi.GPIO is patched at the module level before motor_class is imported so no
real hardware is required.  Config() is also replaced by a stub that returns
the same values as config_files/host_config.json (sn01) to avoid a hostname
lookup failure on non-Pi machines.

Axis positions from config_files/host_config.json (sn01/sn03):
    [320, 675, 1030, 1380, 1740, 2080]
"""
import sys
import types
import importlib
from unittest.mock import MagicMock, patch

import pytest

from tests.unit.conftest import MockGPIO


# ---------------------------------------------------------------------------
# Hard-coded config values (mirrors sn01 in config_files/host_config.json)
# ---------------------------------------------------------------------------

AXIS_CONFIG = {
    "home_steps": 2500,
    "step_multiplier": 8,
    "positions": [320, 675, 1030, 1380, 1740, 2080],
}

DRAWER_CONFIG = {
    "open_steps": 4500,
    "close_steps": 0,
    "read_steps": 152,
    "home_steps": 5000,
    "step_multiplier": 32,
}


class _StubConfig:
    """Minimal Config replacement — returns hard-coded axis/drawer dicts."""

    def __init__(self):
        self.axis = AXIS_CONFIG.copy()
        self.drawer = DRAWER_CONFIG.copy()
        self.state = {}
        self.dict = {}

    def load_config(self, config_file):
        return {}

    def find_by_serial_number(self, name):
        return None

    def find_by_vid_pid(self, name):
        return None


# ---------------------------------------------------------------------------
# Helpers: build fake RPi.GPIO module backed by a MockGPIO instance
# ---------------------------------------------------------------------------

def _make_fake_rpi_modules(gpio_instance):
    """Return (fake_RPi_pkg, fake_RPi_GPIO_module) wired to gpio_instance."""
    fake_rpi_pkg = types.ModuleType("RPi")

    fake = types.ModuleType("RPi.GPIO")
    fake.BCM = MockGPIO.BCM
    fake.BOARD = MockGPIO.BOARD
    fake.OUT = MockGPIO.OUT
    fake.IN = MockGPIO.IN
    fake.HIGH = MockGPIO.HIGH
    fake.LOW = MockGPIO.LOW
    fake.PUD_UP = MockGPIO.PUD_UP
    fake.PUD_DOWN = MockGPIO.PUD_DOWN
    fake.setmode = gpio_instance.setmode
    fake.setwarnings = gpio_instance.setwarnings
    fake.setup = gpio_instance.setup
    fake.output = gpio_instance.output
    fake.input = gpio_instance.input
    fake.cleanup = gpio_instance.cleanup

    return fake_rpi_pkg, fake


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def gpio():
    """A fresh MockGPIO instance per test."""
    return MockGPIO()


@pytest.fixture()
def motor_module(gpio):
    """
    Force-import sentri_lib.motor_class with:
      - RPi.GPIO replaced by MockGPIO
      - sentri_lib.config_module.Config replaced by _StubConfig
    Yields the module so tests can instantiate Axis/Drawer.
    """
    fake_rpi_pkg, fake_gpio = _make_fake_rpi_modules(gpio)

    # Build a stub sentri_lib.config_module that returns _StubConfig
    fake_config_mod = types.ModuleType("sentri_lib.config_module")
    fake_config_mod.Config = _StubConfig

    with patch.dict(
        sys.modules,
        {
            "RPi": fake_rpi_pkg,
            "RPi.GPIO": fake_gpio,
            "sentri_lib.config_module": fake_config_mod,
        },
    ):
        # Evict stale cached module so module-level code re-runs with our mocks
        for key in ["sentri_lib.motor_class"]:
            sys.modules.pop(key, None)

        mod = importlib.import_module("sentri_lib.motor_class")
        yield mod


@pytest.fixture()
def axis(motor_module, gpio):
    """An Axis instance with GPIO calls directed to MockGPIO."""
    return motor_module.Axis()


@pytest.fixture()
def drawer(motor_module, gpio):
    """A Drawer instance with GPIO calls directed to MockGPIO."""
    return motor_module.Drawer()


# ---------------------------------------------------------------------------
# Motor base-class: reset_position
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_reset_position_sets_position_to_zero(axis):
    """reset_position() must set position to 0 regardless of current value."""
    axis.position = 5
    axis.reset_position()
    assert axis.position == 0


@pytest.mark.unit
def test_reset_position_from_large_value(axis):
    """reset_position() works even when position is large (triggers warning only)."""
    axis.position = 500
    axis.reset_position()
    assert axis.position == 0


@pytest.mark.unit
def test_reset_position_already_zero(axis):
    """reset_position() on an already-zeroed motor stays zero."""
    axis.position = 0
    axis.reset_position()
    assert axis.position == 0


# ---------------------------------------------------------------------------
# Motor base-class: move_abs_wo_home_flag
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_move_abs_wo_home_flag_moves_to_absolute_position(axis):
    """move_abs_wo_home_flag(target) accumulates position to target."""
    axis.position = 0
    axis.move_abs_wo_home_flag(200, step_delay=0)
    assert axis.position == 200


@pytest.mark.unit
def test_move_abs_wo_home_flag_from_nonzero_start(axis):
    """move_abs_wo_home_flag works correctly when starting from non-zero."""
    axis.position = 100
    axis.move_abs_wo_home_flag(300, step_delay=0)
    assert axis.position == 300


@pytest.mark.unit
def test_move_abs_wo_home_flag_negative_delta(axis):
    """move_abs_wo_home_flag(target < current) moves in negative direction."""
    axis.position = 500
    axis.move_abs_wo_home_flag(200, step_delay=0)
    assert axis.position == 200


# ---------------------------------------------------------------------------
# Motor base-class: move direction and position tracking
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_move_negative_steps_moves_in_negative_direction(axis):
    """move_wo_home_flag with negative steps decreases position."""
    axis.position = 300
    axis.move_wo_home_flag(-100, step_delay=0)
    assert axis.position == 200


@pytest.mark.unit
def test_move_positive_steps_increases_position(axis):
    """move_wo_home_flag with positive steps increases position."""
    axis.position = 0
    axis.move_wo_home_flag(150, step_delay=0)
    assert axis.position == 150


@pytest.mark.unit
def test_position_accumulates_across_multiple_moves(axis):
    """Sequential moves accumulate position correctly."""
    axis.position = 0
    axis.move_wo_home_flag(100, step_delay=0)
    axis.move_wo_home_flag(50, step_delay=0)
    axis.move_wo_home_flag(-30, step_delay=0)
    assert axis.position == 120  # 0 + 100 + 50 - 30


@pytest.mark.unit
def test_position_accumulates_after_reset(axis):
    """Moves after reset_position() start from 0."""
    axis.position = 200
    axis.reset_position()
    axis.move_wo_home_flag(75, step_delay=0)
    assert axis.position == 75


# ---------------------------------------------------------------------------
# Axis.goto_position — maps slot index to step count from config
# ---------------------------------------------------------------------------

EXPECTED_POSITIONS = [320, 675, 1030, 1380, 1740, 2080]


@pytest.mark.unit
@pytest.mark.parametrize("slot, expected", enumerate(EXPECTED_POSITIONS))
def test_goto_position_maps_slot_to_correct_steps(axis, slot, expected):
    """goto_position(N) moves the axis to positions[N] step count."""
    axis.position = 0
    axis.goto_position(slot)
    assert axis.position == expected


@pytest.mark.unit
def test_goto_position_then_reset_then_goto_again(axis):
    """goto_position works correctly after a reset_position in between."""
    axis.position = 0
    axis.goto_position(2)        # → 1030
    assert axis.position == 1030

    axis.reset_position()        # → 0
    axis.goto_position(0)        # → 320
    assert axis.position == 320


@pytest.mark.unit
def test_goto_position_from_nonzero_start(axis):
    """goto_position uses absolute addressing regardless of current position."""
    axis.position = 500
    axis.goto_position(1)        # → 675
    assert axis.position == 675


# ---------------------------------------------------------------------------
# Drawer convenience
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_drawer_initial_position_is_zero(drawer):
    """Drawer starts at position 0 after __init__."""
    assert drawer.position == 0


@pytest.mark.unit
def test_drawer_move_and_reset(drawer):
    """Drawer move + reset follows same logic as base Motor."""
    drawer.move_wo_home_flag(100, step_delay=0)
    assert drawer.position == 100
    drawer.reset_position()
    assert drawer.position == 0


# ---------------------------------------------------------------------------
# GPIO direction pin behaviour
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_positive_move_sets_dir_forward(axis, gpio):
    """Positive steps must set DIR_PIN to DIR_FORWARD_STATE (LOW for Axis)."""
    axis.position = 0
    axis.move_wo_home_flag(10, step_delay=0)
    # Axis.DIR_FORWARD_STATE == LOW == 0
    assert gpio.pins.get(axis.DIR_PIN, {}).get("val") == axis.DIR_FORWARD_STATE


@pytest.mark.unit
def test_negative_move_sets_dir_back(axis, gpio):
    """Negative steps must set DIR_PIN to DIR_BACK_STATE (HIGH for Axis)."""
    axis.position = 500
    axis.move_wo_home_flag(-10, step_delay=0)
    # Axis.DIR_BACK_STATE == HIGH == 1
    assert gpio.pins.get(axis.DIR_PIN, {}).get("val") == axis.DIR_BACK_STATE
