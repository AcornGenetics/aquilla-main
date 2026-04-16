"""
Contract test fixtures — FastAPI TestClient with full state reset.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def reset_state(client):
    client.post("/stop/reset")
    client.post("/run_status/reset")
    client.post("/exit/reset")
    client.post("/exit/force/reset")
    client.post("/run/complete/ack/reset")
    client.post("/drawer_status/reset")


@pytest.fixture
def client():
    from aquila_web import main as web_main
    with TestClient(web_main.app) as c:
        reset_state(c)
        yield c
        reset_state(c)


@pytest.fixture
def client_with_profile(client, tmp_path):
    """Client with a profile saved to a temp dir and selected."""
    from aquila_web import main as web_main

    profile_data = {
        "title": "Test Profile",
        "fam_label": "FAM",
        "rox_label": "ROX",
        "steps": [
            {"setpoint": 95, "duration": 1},
            {"setpoint": 55, "duration": 1},
        ],
    }
    # Save profile via API
    resp = client.post("/profiles", json={"name": "test_profile", **profile_data})
    profile_id = resp.json().get("id", "test_profile.json")

    # Select it
    client.post("/profile/select", json={"profile": profile_id})
    client.post("/run/name", json={"name": "run1"})

    # Set drawer closed
    client.post("/drawer/state", json={"open": False, "closed": True})

    yield client, profile_id
