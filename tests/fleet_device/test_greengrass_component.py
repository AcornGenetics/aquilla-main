"""
Static structure checks for the Greengrass on-device component.

Like test_compose_config.py, these parse YAML/JSON without Docker or AWS — they
assert the *shape* of the artifacts a Greengrass deployment runs, so a
misconfiguration is caught before it reaches a device.

The Greengrass compose is a clean-room version of the fleet compose: it runs the
same app stack but drops watchtower and the #314 DNS hacks, and persists state on
named volumes instead of host binds.

Run with:
    pytest tests/fleet_device/test_greengrass_component.py -v
"""
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

GREENGRASS_COMPOSE = Path("fleet-config/greengrass-compose.yaml")


def _load_compose() -> dict:
    assert GREENGRASS_COMPOSE.exists(), f"{GREENGRASS_COMPOSE} not found"
    return yaml.safe_load(GREENGRASS_COMPOSE.read_text())


def test_runs_the_app_stack():
    services = _load_compose().get("services", {})
    for name in ("backend", "app", "ui"):
        assert name in services, f"greengrass compose missing service: {name}"


def test_has_no_watchtower():
    compose = _load_compose()
    # Greengrass owns updates now — no watchtower service, no enable labels.
    assert "watchtower" not in compose.get("services", {})
    blob = yaml.safe_dump(compose)
    assert "watchtower" not in blob.lower(), "watchtower reference must be gone"


def test_has_no_dns_hacks():
    compose = _load_compose()
    services = compose.get("services", {})
    for name, svc in services.items():
        assert "dns" not in svc, f"{name} still pins dns (the #314 host-DNS hack)"
    # No hardcoded bridge IPs anywhere (the #314 forwarder gateway).
    blob = yaml.safe_dump(compose)
    assert "172.18.0.1" not in blob, "hardcoded bridge IP (#314 DNS hack) must be gone"


def _sources(mounts):
    out = []
    for m in mounts or []:
        out.append(m.split(":", 1)[0] if isinstance(m, str) else m.get("source", ""))
    return out


def test_persists_state_on_named_volumes():
    compose = _load_compose()
    named = compose.get("volumes") or {}
    assert named, "no top-level named volumes defined"

    backend = compose["services"]["backend"]
    sources = _sources(backend.get("volumes"))
    assert sources, "backend persists nothing"
    # Named volumes, not host binds — Greengrass state must not depend on /opt paths.
    for src in sources:
        assert not src.startswith("/"), f"backend uses a host bind ({src}); use a named volume"
        assert src in named, f"backend mounts '{src}' but it is not a declared named volume"
