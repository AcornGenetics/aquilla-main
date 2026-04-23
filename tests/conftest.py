"""
Top-level shared fixtures available to all test layers.
"""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
