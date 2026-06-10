"""
State-layer conftest: stubs out hardware-only modules so that state_run_assay
can be imported on a development machine without a Raspberry Pi or serial
adapter attached.

This file runs before any test module in tests/state/ is collected, so the
stubs are in place when test_stop_flow.py does ``import state_run_assay``.
"""
import os
import sys
import types

# Config() reads hostname at import time; give it a known device name so the
# host_config.json lookup succeeds on developer machines.
os.environ.setdefault("DEVICE_HOSTNAME", "sn01")


def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    # Allow attribute access without AttributeError by returning a new stub module
    mod.__getattr__ = lambda item: types.ModuleType(f"{name}.{item}")  # type: ignore[attr-defined]
    return mod


def _inject_hardware_stubs() -> None:
    """Inject minimal stubs for C-extension / Pi-only packages."""

    # ── RPi.GPIO ──────────────────────────────────────────────────────────────
    if "RPi" not in sys.modules:
        rpi = _make_stub("RPi")
        gpio = _make_stub("RPi.GPIO")
        # Constants used by aq_lib modules
        gpio.BCM = 11
        gpio.IN = 1
        gpio.OUT = 0
        gpio.HIGH = 1
        gpio.LOW = 0
        gpio.setmode = lambda *a, **kw: None
        gpio.setup = lambda *a, **kw: None
        gpio.output = lambda *a, **kw: None
        gpio.input = lambda *a, **kw: 0
        gpio.cleanup = lambda *a, **kw: None
        rpi.GPIO = gpio
        sys.modules["RPi"] = rpi
        sys.modules["RPi.GPIO"] = gpio

    # ── pyserial ──────────────────────────────────────────────────────────────
    if "serial" not in sys.modules:
        serial_stub = _make_stub("serial")

        class _FakeSerial:
            def __init__(self, *a, **kw):
                pass
            def read(self, *a, **kw):
                return b""
            def write(self, *a, **kw):
                pass
            def close(self):
                pass

        serial_stub.Serial = _FakeSerial
        serial_stub.SerialException = Exception
        sys.modules["serial"] = serial_stub

    # serial.tools and serial.tools.list_ports must be real submodule stubs
    if "serial.tools" not in sys.modules:
        tools_stub = _make_stub("serial.tools")
        sys.modules["serial"].tools = tools_stub  # type: ignore[attr-defined]
        sys.modules["serial.tools"] = tools_stub

    if "serial.tools.list_ports" not in sys.modules:
        lp_stub = _make_stub("serial.tools.list_ports")
        lp_stub.comports = lambda: []
        sys.modules["serial.tools"].list_ports = lp_stub  # type: ignore[attr-defined]
        sys.modules["serial.tools.list_ports"] = lp_stub

    # ── spidev ────────────────────────────────────────────────────────────────
    if "spidev" not in sys.modules:
        spidev = _make_stub("spidev")

        class _FakeSpiDev:
            def open(self, *a, **kw): pass
            def xfer2(self, *a, **kw): return [0]
            def close(self): pass
            max_speed_hz = 0
            mode = 0

        spidev.SpiDev = _FakeSpiDev
        sys.modules["spidev"] = spidev

    # ── smbus / smbus2 ────────────────────────────────────────────────────────
    for smbus_name in ("smbus", "smbus2"):
        if smbus_name not in sys.modules:
            smbus = _make_stub(smbus_name)

            class _FakeSMBus:
                def __init__(self, *a, **kw): pass
                def read_byte_data(self, *a, **kw): return 0
                def write_byte_data(self, *a, **kw): pass

            smbus.SMBus = _FakeSMBus
            sys.modules[smbus_name] = smbus


_inject_hardware_stubs()
