"""
Top-level shared fixtures available to all test layers.
"""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# config_module.Config() resolves this machine's device identity from
# DEVICE_HOSTNAME (falling back to socket.gethostname()) against
# config_files/host_config.json, which only knows real devices (sn01-sn03). On a
# dev machine or CI the hostname is not a device, so any module that constructs
# Config() at import time (e.g. aq_lib.state_requests) fails to import -- breaking
# collection outright, or failing at runtime depending on sys.modules caching.
# Pin a canonical test device so those imports resolve on any machine. setdefault
# keeps a real device's / CI's own identity; tests that exercise hostname
# behaviour still override this per-test via monkeypatch.setenv. Set before any
# test module is imported for collection.
os.environ.setdefault("DEVICE_HOSTNAME", "sn01")

def pytest_collection_modifyitems(config, items):
    """Auto-skip @pytest.mark.hardware tests when real Pi hardware is absent.

    pytest.ini documents the `hardware` marker as "requires real Pi hardware --
    skipped in CI", but nothing enforced that skip, so those tests failed on a dev
    machine at `import RPi.GPIO`. Skip them when RPi.GPIO can't be imported (i.e.
    off-device); on a Pi they run as before.
    """
    try:
        import RPi.GPIO  # noqa: F401
        return  # real hardware present -- run them
    except Exception:
        skip_hardware = pytest.mark.skip(reason="requires real Pi hardware (RPi.GPIO unavailable)")
        for item in items:
            # Match the explicit @pytest.mark.hardware marker only -- NOT
            # item.keywords, which also contains parent names (e.g. the
            # `hardware/` directory) and would skip the mocked hardware tests
            # under it that run fine off-device.
            if item.get_closest_marker("hardware") is not None:
                item.add_marker(skip_hardware)


# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _reset_web_state(client: TestClient) -> None:
    """Reset all backend globals to a clean state between tests."""
    client.post("/stop/reset")
    client.post("/run_status/reset")
    client.post("/exit/reset")
    client.post("/exit/force/reset")
    client.post("/run/complete/ack/reset")
    client.post("/drawer_status/reset")
    client.post("/timer", json={"action": "reset"})


@pytest.fixture
def client():
    """FastAPI TestClient with clean state before each test."""
    from aquila_web import main as web_main
    with TestClient(web_main.app) as c:
        _reset_web_state(c)
        yield c
        _reset_web_state(c)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def optics_log(fixtures_dir) -> Path:
    return fixtures_dir / "optics" / "sample_run.log"


@pytest.fixture
def minimal_optics_log(fixtures_dir) -> Path:
    return fixtures_dir / "optics" / "minimal_run.log"


@pytest.fixture
def detected_results(fixtures_dir) -> dict:
    return json.loads((fixtures_dir / "results" / "detected.json").read_text())


@pytest.fixture
def not_detected_results(fixtures_dir) -> dict:
    return json.loads((fixtures_dir / "results" / "not_detected.json").read_text())


@pytest.fixture
def inconclusive_results(fixtures_dir) -> dict:
    return json.loads((fixtures_dir / "results" / "inconclusive.json").read_text())


@pytest.fixture
def basic_profile(fixtures_dir) -> dict:
    return json.loads((fixtures_dir / "profiles" / "basic_pcr.json").read_text())


@pytest.fixture
def basic_profile_path(fixtures_dir) -> Path:
    return fixtures_dir / "profiles" / "basic_pcr.json"
