"""
Unit tests for sentri_lib/regulate.py (_load_lid_heater_config, lid_heater_worker).

regulate.py runs GPIO setup and ADS1115 construction at module level, so all
hardware dependencies (RPi.GPIO, smbus2, sentri_lib.lid_temperature) must be
injected into sys.modules before the module is imported.  Each test calls
_import_regulate() which force-reimports the module under fresh mocks.
"""
import importlib
import io
import json
import os
import sys
import tempfile
import time
import types
from threading import Event, Thread
from unittest.mock import MagicMock, patch

import pytest

from tests.unit.conftest import MockGPIO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_gpio_module(gpio_instance):
    """Build a fake RPi.GPIO *module* object backed by gpio_instance."""
    fake_rpi_pkg = types.ModuleType("RPi")

    fake = types.ModuleType("RPi.GPIO")
    fake.BCM = MockGPIO.BCM
    fake.OUT = MockGPIO.OUT
    fake.IN = MockGPIO.IN
    fake.HIGH = MockGPIO.HIGH
    fake.LOW = MockGPIO.LOW
    fake.setmode = gpio_instance.setmode
    fake.setwarnings = gpio_instance.setwarnings
    fake.setup = gpio_instance.setup
    fake.output = gpio_instance.output
    fake.input = gpio_instance.input
    fake.cleanup = gpio_instance.cleanup

    return fake_rpi_pkg, fake


def _make_fake_adc_module():
    """Return (mock_adc_instance, fake_sentri_lib_lid_temperature_module, fake_smbus_module)."""
    mock_adc = MagicMock()
    mock_adc.read_continuous.return_value = 0.25  # inside default heating band

    fake_lid_temp = types.ModuleType("sentri_lib.lid_temperature")
    fake_lid_temp.ADS1115 = MagicMock(return_value=mock_adc)

    fake_smbus = types.ModuleType("smbus2")
    fake_smbus.SMBus = MagicMock()

    return mock_adc, fake_lid_temp, fake_smbus


def _import_regulate(gpio_instance=None):
    """
    Force-import sentri_lib.regulate with all hardware dependencies mocked.

    Returns
    -------
    (mod, gpio_instance, mock_adc)
        mod           — the freshly imported sentri_lib.regulate module
        gpio_instance — MockGPIO whose .output() / .setup() were wired in
        mock_adc      — the MagicMock ADS1115 instance the module got
    """
    if gpio_instance is None:
        gpio_instance = MockGPIO()

    fake_rpi_pkg, fake_gpio = _make_fake_gpio_module(gpio_instance)
    mock_adc, fake_lid_temp, fake_smbus = _make_fake_adc_module()

    overrides = {
        "RPi": fake_rpi_pkg,
        "RPi.GPIO": fake_gpio,
        "smbus2": fake_smbus,
        "sentri_lib.lid_temperature": fake_lid_temp,
    }

    with patch.dict(sys.modules, overrides):
        sys.modules.pop("sentri_lib.regulate", None)
        mod = importlib.import_module("sentri_lib.regulate")

    # After the context manager exits, sys.modules["RPi.GPIO"] is restored to
    # whatever it was before (likely None / absent on non-Pi).  The module
    # object `mod` however retains its own `GPIO` attribute pointing to the
    # fake_gpio we gave it during import — so mod.GPIO.output == gpio_instance.output.
    return mod, gpio_instance, mock_adc


# ---------------------------------------------------------------------------
# _load_lid_heater_config — happy path
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_load_lid_heater_config_reads_lower_and_upper_bound():
    """Config file with both keys loads lower_bound and upper_bound correctly."""
    mod, _, _ = _import_regulate()

    data = {"lower_bound": 0.15, "upper_bound": 0.42}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fp:
        json.dump(data, fp)
        tmp_path = fp.name

    try:
        cfg = mod._load_lid_heater_config(config_path=tmp_path)
        assert cfg["lower_bound"] == pytest.approx(0.15)
        assert cfg["upper_bound"] == pytest.approx(0.42)
    finally:
        os.unlink(tmp_path)


@pytest.mark.unit
def test_load_lid_heater_config_partial_file_keeps_default_for_missing_key():
    """A config file with only upper_bound keeps the default lower_bound."""
    mod, _, _ = _import_regulate()

    data = {"upper_bound": 0.50}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fp:
        json.dump(data, fp)
        tmp_path = fp.name

    try:
        cfg = mod._load_lid_heater_config(config_path=tmp_path)
        assert cfg["lower_bound"] == pytest.approx(mod.DEFAULT_LID_HEATER_CONFIG["lower_bound"])
        assert cfg["upper_bound"] == pytest.approx(0.50)
    finally:
        os.unlink(tmp_path)


@pytest.mark.unit
def test_load_lid_heater_config_returns_float_types():
    """Values read from JSON are cast to float."""
    mod, _, _ = _import_regulate()

    data = {"lower_bound": "0.10", "upper_bound": "0.45"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fp:
        json.dump(data, fp)
        tmp_path = fp.name

    try:
        cfg = mod._load_lid_heater_config(config_path=tmp_path)
        assert isinstance(cfg["lower_bound"], float)
        assert isinstance(cfg["upper_bound"], float)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# _load_lid_heater_config — missing / corrupt file falls back to defaults
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_load_lid_heater_config_missing_file_uses_defaults():
    """A missing config file silently returns the hardcoded defaults."""
    mod, _, _ = _import_regulate()

    cfg = mod._load_lid_heater_config(config_path="/nonexistent/path/lid.json")
    assert cfg["lower_bound"] == pytest.approx(mod.DEFAULT_LID_HEATER_CONFIG["lower_bound"])
    assert cfg["upper_bound"] == pytest.approx(mod.DEFAULT_LID_HEATER_CONFIG["upper_bound"])


@pytest.mark.unit
def test_load_lid_heater_config_corrupt_file_uses_defaults():
    """A corrupt JSON file falls back to defaults without raising."""
    mod, _, _ = _import_regulate()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fp:
        fp.write("THIS IS NOT JSON {{{")
        tmp_path = fp.name

    try:
        cfg = mod._load_lid_heater_config(config_path=tmp_path)
        assert cfg["lower_bound"] == pytest.approx(mod.DEFAULT_LID_HEATER_CONFIG["lower_bound"])
        assert cfg["upper_bound"] == pytest.approx(mod.DEFAULT_LID_HEATER_CONFIG["upper_bound"])
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Default constant values
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_default_lid_heater_config_lower_bound():
    """DEFAULT_LID_HEATER_CONFIG lower_bound must be 0.2."""
    mod, _, _ = _import_regulate()
    assert mod.DEFAULT_LID_HEATER_CONFIG["lower_bound"] == pytest.approx(0.2)


@pytest.mark.unit
def test_default_lid_heater_config_upper_bound():
    """DEFAULT_LID_HEATER_CONFIG upper_bound must be 0.34."""
    mod, _, _ = _import_regulate()
    assert mod.DEFAULT_LID_HEATER_CONFIG["upper_bound"] == pytest.approx(0.34)


# ---------------------------------------------------------------------------
# lid_heater_worker — stop_event pre-set
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stop_event_pre_set_exits_immediately():
    """Worker must exit almost immediately if stop_event is already set."""
    mod, gpio_inst, mock_adc = _import_regulate()

    stop_event = Event()
    stop_event.set()

    start = time.time()
    mod.lid_heater_worker(stop_event)
    elapsed = time.time() - start

    assert elapsed < 2.0


@pytest.mark.unit
def test_stop_event_pre_set_adc_never_read():
    """If stop_event is pre-set, adc.read_continuous() is never called."""
    mod, gpio_inst, mock_adc = _import_regulate()

    stop_event = Event()
    stop_event.set()
    mod.lid_heater_worker(stop_event)

    mock_adc.read_continuous.assert_not_called()


# ---------------------------------------------------------------------------
# lid_heater_worker — thread exits cleanly
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_worker_thread_exits_cleanly_within_2_seconds():
    """Worker thread exits within 2 seconds after stop_event is set."""
    mod, gpio_inst, mock_adc = _import_regulate()

    stop_event = Event()
    quiet_event = Event()
    quiet_event.set()  # suppress GPIO toggling

    thread = Thread(
        target=mod.lid_heater_worker,
        kwargs={
            "stop_event": stop_event,
            "quiet_event": quiet_event,
            "setpoint": 0.34,
            "lower_bound": 0.20,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.05)
    stop_event.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive(), "Worker thread did not exit within 2 seconds"


# ---------------------------------------------------------------------------
# lid_heater_worker — quiet_event suppresses GPIO HIGH
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_quiet_event_suppresses_gpio_high_output():
    """While quiet_event is set, the GPIO pin must never be driven HIGH."""
    mod, gpio_inst, mock_adc = _import_regulate()

    # ADC returns a value inside the heating band so the worker *would* fire
    mock_adc.read_continuous.return_value = 0.25

    stop_event = Event()
    quiet_event = Event()
    quiet_event.set()  # heater suppressed

    output_calls = []

    original_output = gpio_inst.output

    def tracking_output(pin, value):
        output_calls.append((pin, value))
        original_output(pin, value)

    # Point the module's GPIO.output at our wrapper
    mod.GPIO.output = tracking_output

    thread = Thread(
        target=mod.lid_heater_worker,
        kwargs={
            "stop_event": stop_event,
            "quiet_event": quiet_event,
            "setpoint": 0.34,
            "lower_bound": 0.20,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.05)
    stop_event.set()
    thread.join(timeout=2.0)

    high_calls = [(p, v) for (p, v) in output_calls if v == MockGPIO.HIGH]
    assert high_calls == [], f"GPIO was driven HIGH despite quiet_event: {high_calls}"


# ---------------------------------------------------------------------------
# lid_heater_worker — pin is LOW on exit
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_worker_sets_pin_low_on_exit():
    """Worker must drive pin LOW when it exits after stop_event is set."""
    mod, gpio_inst, mock_adc = _import_regulate()

    output_calls = []
    original_output = gpio_inst.output

    def tracking_output(pin, value):
        output_calls.append((pin, value))
        original_output(pin, value)

    mod.GPIO.output = tracking_output

    stop_event = Event()
    quiet_event = Event()
    quiet_event.set()

    thread = Thread(
        target=mod.lid_heater_worker,
        kwargs={
            "stop_event": stop_event,
            "quiet_event": quiet_event,
            "setpoint": 0.34,
            "lower_bound": 0.20,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.05)
    stop_event.set()
    thread.join(timeout=2.0)

    assert output_calls, "GPIO.output was never called"
    pin_number = mod.pin_number
    last_pin, last_val = output_calls[-1]
    assert last_pin == pin_number, f"Last GPIO call was on pin {last_pin}, expected {pin_number}"
    assert last_val == MockGPIO.LOW, f"Last GPIO value was {last_val}, expected LOW"
