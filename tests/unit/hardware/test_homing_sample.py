"""
Seam-1 unit tests for Homing Sample emission (issue #325, ADR-021).

Every Motor.home() must emit exactly one structured Homing Sample as a JSON
line to the dedicated ``aquila.homing`` logger. These tests observe that
logger's output (never files or internals), so they describe behavior and
survive refactors.

RPi.GPIO and Config are mocked the same way as tests/unit/hardware/test_motor.py
so no real hardware is required.
"""
import importlib
import json
import logging
import sys
import types

import pytest

from tests.unit.conftest import MockGPIO


# ---------------------------------------------------------------------------
# Config stub (mirrors sn01 in config_files/host_config.json), as in test_motor
# ---------------------------------------------------------------------------

AXIS_CONFIG = {"home_steps": 2500, "step_multiplier": 8,
               "positions": [320, 675, 1030, 1380, 1740, 2080]}
DRAWER_CONFIG = {"open_steps": 4500, "close_steps": 0, "read_steps": 152,
                 "home_steps": 5000, "step_multiplier": 32}


class _StubConfig:
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


def _make_fake_rpi_modules(gpio_instance):
    fake_rpi_pkg = types.ModuleType("RPi")
    fake = types.ModuleType("RPi.GPIO")
    for attr in ("BCM", "BOARD", "OUT", "IN", "HIGH", "LOW", "PUD_UP", "PUD_DOWN"):
        setattr(fake, attr, getattr(MockGPIO, attr))
    for m in ("setmode", "setwarnings", "setup", "output", "input", "cleanup"):
        setattr(fake, m, getattr(gpio_instance, m))
    return fake_rpi_pkg, fake


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def gpio():
    return MockGPIO()


@pytest.fixture()
def motor_module(gpio):
    fake_rpi_pkg, fake_gpio = _make_fake_rpi_modules(gpio)
    fake_config_mod = types.ModuleType("aq_lib.config_module")
    fake_config_mod.Config = _StubConfig
    with patch_modules(fake_rpi_pkg, fake_gpio, fake_config_mod):
        sys.modules.pop("aq_lib.motor_class", None)
        yield importlib.import_module("aq_lib.motor_class")


def patch_modules(fake_rpi_pkg, fake_gpio, fake_config_mod):
    from unittest.mock import patch
    return patch.dict(sys.modules, {
        "RPi": fake_rpi_pkg,
        "RPi.GPIO": fake_gpio,
        "aq_lib.config_module": fake_config_mod,
    })


class _CaptureHandler(logging.Handler):
    """Collects the raw message string of each record emitted to a logger."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture()
def homing_records():
    """Capture everything emitted to the aquila.homing logger as parsed dicts."""
    handler = _CaptureHandler()
    logger = logging.getLogger("aquila.homing")
    prev_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield lambda: [json.loads(m) for m in handler.messages]
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)


# ---------------------------------------------------------------------------
# Cycle 1: home() emits exactly one Homing Sample
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_drawer_home_emits_one_sample_reached(motor_module, gpio, homing_records):
    """A Drawer.home() with the home flag present emits exactly one Homing
    Sample tagged motor='drawer' with reached_home=True."""
    drawer = motor_module.Drawer()
    gpio.simulate_home_flag(drawer.HME_PIN, 1)  # flag detected -> reaches home

    drawer.home()

    samples = homing_records()
    assert len(samples) == 1
    assert samples[0]["motor"] == "drawer"
    assert samples[0]["reached_home"] is True


# ---------------------------------------------------------------------------
# Cycle 2: a homing where the flag never fires records reached_home=False
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_axis_home_missed_records_not_reached(motor_module, gpio, homing_records):
    """An Axis.home() where the home flag never fires emits a Sample tagged
    motor='axis' with reached_home=False (a missed homing)."""
    axis = motor_module.Axis()
    axis.home_steps = 5  # keep the no-catch path fast; flag is never set

    axis.home()

    samples = homing_records()
    assert len(samples) == 1
    assert samples[0]["motor"] == "axis"
    assert samples[0]["reached_home"] is False


# ---------------------------------------------------------------------------
# Cycle 3: steps_to_flag reflects the step at which the home flag tripped
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_steps_to_flag_reflects_trip_step(motor_module, gpio, homing_records):
    """When the home flag trips mid-travel, steps_to_flag records the step it
    fired at, and reached_home is True."""
    drawer = motor_module.Drawer()
    # Flag reads LOW for 6 input() calls, then HIGH. The first LOW read is
    # home()'s isHome() pre-check; the home-flag loop then misses 5 times before
    # catching, so the flag fires at loop step 5.
    gpio.trip_home_flag_after(drawer.HME_PIN, 6)

    drawer.home()

    samples = homing_records()
    assert samples[0]["steps_to_flag"] == 5
    assert samples[0]["reached_home"] is True


# ---------------------------------------------------------------------------
# Cycle 4: residual is the position captured BEFORE reset_position zeroes it
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_residual_is_position_before_reset(motor_module, gpio, homing_records):
    """residual records the accumulated position error at the moment of homing,
    captured before reset_position() zeroes it."""
    drawer = motor_module.Drawer()
    gpio.trip_home_flag_after(drawer.HME_PIN, 6)  # catches at loop step 5

    drawer.home()

    samples = homing_records()
    # Travel was 5 steps in the negative direction before catching, so position
    # at homing was -5 -- recorded even though reset then zeroes the motor.
    assert samples[0]["residual"] == -5
    assert drawer.position == 0  # reset ran AFTER the Sample captured residual


# ---------------------------------------------------------------------------
# Cycle 5: homing Samples do not propagate to the aquila logger (logger.log)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_homing_sample_does_not_reach_aquila_logger(motor_module, gpio):
    """A Homing Sample stays out of logger.log: it must not propagate up to the
    'aquila' logger that feeds logger.log."""
    aquila_handler = _CaptureHandler()
    aquila_logger = logging.getLogger("aquila")
    aquila_logger.addHandler(aquila_handler)
    aquila_logger.setLevel(logging.DEBUG)
    try:
        drawer = motor_module.Drawer()
        gpio.simulate_home_flag(drawer.HME_PIN, 1)
        drawer.home()
    finally:
        aquila_logger.removeHandler(aquila_handler)

    leaked = [m for m in aquila_handler.messages if '"reached_home"' in m]
    assert leaked == []


# ---------------------------------------------------------------------------
# Cycle 6: every homing gets a unique id and a timestamp
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_each_homing_has_unique_id_and_timestamp(motor_module, gpio, homing_records):
    """Two homings produce two Samples with distinct ids and populated ts, so
    the parser can dedup and acorn-analytics can order the series."""
    drawer = motor_module.Drawer()
    gpio.simulate_home_flag(drawer.HME_PIN, 1)

    drawer.home()
    drawer.home()

    samples = homing_records()
    assert len(samples) == 2
    assert samples[0]["id"] != samples[1]["id"]
    assert samples[0]["ts"] and samples[1]["ts"]


# ---------------------------------------------------------------------------
# Cycle 7: production wiring — rotating JSON-lines file, bounded size
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_configure_homing_logger_writes_bounded_json_lines(tmp_path):
    """configure_homing_logger writes JSON-line Samples to a file that rotates
    at a bounded size (asserted via observable file behavior)."""
    from aq_lib import homing_log

    homing_log.configure_homing_logger(log_dir=str(tmp_path),
                                        max_bytes=200, backup_count=3)
    try:
        for _ in range(50):  # well past 200 bytes -> forces a rotation
            homing_log.emit_homing_sample("drawer", steps_to_flag=5, residual=-5,
                                          reached_home=True)

        names = {p.name for p in tmp_path.iterdir()}
        assert "homing.log" in names          # active file
        assert "homing.log.1" in names        # rotated -> the size cap is enforced

        last = (tmp_path / "homing.log").read_text().splitlines()[-1]
        record = json.loads(last)             # every line is a valid JSON Sample
        assert record["motor"] == "drawer"
        assert record["reached_home"] is True
    finally:
        lg = logging.getLogger("aquila.homing")
        for h in list(lg.handlers):
            if getattr(h, "_aquila_homing", False):
                lg.removeHandler(h)
                h.close()
