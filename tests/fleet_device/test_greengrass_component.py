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


def test_app_containers_have_pcr_hardware_access():
    # Without privileged + the device mappings the app serves but can't drive the
    # instrument (Meerstetter serial, I2C, SPI, GPIO) — "can't run anything".
    services = _load_compose()["services"]
    for name in ("backend", "app"):
        svc = services[name]
        assert svc.get("privileged") is True, f"{name} needs privileged for hardware"
        mapped = " ".join(svc.get("devices", []))
        for dev in ("/dev/ttyUSB0", "/dev/i2c-1", "/dev/spidev0.0", "/dev/gpiomem"):
            assert dev in mapped, f"{name} missing device mapping {dev}"


def test_app_containers_reach_greengrass_ipc():
    # The update agent (am#382) talks to the nucleus over Core IPC to publish the
    # Device Shadow and defer component updates. Inside a container that needs the
    # IPC socket bind-mounted plus SVCUID + the socket-path + thing-name env, or the
    # agent can't connect and silently no-ops (no shadow, no operator update gate).
    services = _load_compose()["services"]
    for name in ("backend", "app"):
        svc = services[name]
        env = " ".join(svc.get("environment", []))
        for var in (
            "SVCUID",
            "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT",
            "AWS_IOT_THING_NAME",
        ):
            assert var in env, f"{name} missing IPC env {var}"
        vols = " ".join(svc.get("volumes", []))
        assert "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT" in vols, (
            f"{name} does not bind-mount the Greengrass IPC socket"
        )


def test_app_runs_the_hardware_controller():
    # The `app` service must run application.py (the AssayInterface ready/run/end
    # loop that drives the instrument), NOT the default web-server CMD. If it falls
    # back to the web server, a Run press is accepted by the backend but nothing
    # ever actuates the hardware — the instrument sits idle.
    app = _load_compose()["services"]["app"]
    command = app.get("command")
    assert command, "app has no command — it would run the default web server, not the controller"
    joined = " ".join(command) if isinstance(command, list) else str(command)
    assert "application.py" in joined
    # application.py reaches the web backend over BACKEND_URL.
    env = " ".join(app.get("environment", []))
    assert "BACKEND_URL=http://aquila-backend:8090" in env, "app can't reach the backend"


def test_app_healthcheck_disabled():
    # application.py is not a web server, so the image's /health healthcheck would
    # flag the container unhealthy. The backend answers /health for the gate.
    app = _load_compose()["services"]["app"]
    assert app.get("healthcheck", {}).get("disable") is True


def test_ui_maps_host_port_to_nginx_80():
    # nginx listens on port 80 in the container; the host's 8080 must map to 80, or
    # the kiosk UI is unreachable (8080:8080 hits nothing inside the container).
    ui = _load_compose()["services"]["ui"]
    ports = [str(p) for p in ui.get("ports", [])]
    assert any(p.endswith(":80") for p in ports), f"ui must map to nginx port 80, got {ports}"


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


def test_persists_state_on_host_binds():
    # State is bind-mounted from /opt/aquila (version-independent), NOT relative
    # named volumes. Greengrass runs compose from a per-VERSION artifact dir, so a
    # relative named volume gets a version-scoped project prefix (0114_aquila-data,
    # 0117_aquila-data, …) and every update would start on a fresh EMPTY volume,
    # abandoning prior runs + the unsynced sync-outbox. Host binds persist across
    # updates and carry an existing device's data over on migration.
    compose = _load_compose()
    assert not compose.get("volumes"), "no top-level named volumes — state must be host-bound"

    for name in ("backend", "app"):
        binds = _sources(compose["services"][name].get("volumes"))
        assert binds, f"{name} persists nothing"
        # The sync outbox must be a stable /opt/aquila host bind.
        assert "/opt/aquila/data" in binds, f"{name} sync outbox is not a /opt/aquila host bind"
        # Every state mount (excluding the runtime IPC socket) is an /opt/aquila host bind.
        for src in binds:
            if "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT" in src:
                continue
            assert src.startswith("/opt/aquila/"), (
                f"{name} mounts '{src}' — state must bind /opt/aquila for cross-update persistence"
            )
