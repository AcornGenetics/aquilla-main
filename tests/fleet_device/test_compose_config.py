"""
Static analysis of Docker Compose files to catch misconfigurations that cause
containers to crash-loop on device.

These tests run without Docker — they parse the YAML and check structural
rules. A failure here indicates a configuration problem that will affect all
devices on next deploy.

Run with:
    pytest tests/fleet_device/test_compose_config.py -v
"""
import yaml
from pathlib import Path

FLEET_COMPOSE = Path("fleet-config/docker-compose.yml")
LOCAL_COMPOSE = Path("docker/docker-compose.yml")


def _load(path: Path) -> dict:
    assert path.exists(), f"{path} not found"
    return yaml.safe_load(path.read_text())


# ---------------------------------------------------------------------------
# Fleet compose (the one that runs on every device)
# ---------------------------------------------------------------------------

class TestFleetCompose:

    def test_required_services_present(self):
        """backend, app, ui, and watchtower must all be defined."""
        services = _load(FLEET_COMPOSE)["services"]
        for name in ("backend", "app", "ui", "watchtower"):
            assert name in services, f"Missing service: {name}"

    def test_ui_service_has_extra_hosts(self):
        """
        The ui service must declare extra_hosts so host.docker.internal
        resolves inside the nginx container on Linux.
        """
        ui = _load(FLEET_COMPOSE)["services"]["ui"]
        extra_hosts = ui.get("extra_hosts", [])
        assert extra_hosts, "ui service has no extra_hosts — host.docker.internal will not resolve on Linux"

    def test_ui_extra_hosts_maps_host_docker_internal(self):
        """
        extra_hosts must include an entry for host.docker.internal.
        Without it nginx crashes at startup on Linux (the SN01 incident).
        """
        ui = _load(FLEET_COMPOSE)["services"]["ui"]
        extra_hosts = ui.get("extra_hosts", [])
        matches = [h for h in extra_hosts if "host.docker.internal" in h]
        assert matches, (
            "ui extra_hosts does not map host.docker.internal.\n"
            f"Current extra_hosts: {extra_hosts}"
        )

    def test_backend_has_restart_policy(self):
        """Critical services must restart automatically on failure."""
        services = _load(FLEET_COMPOSE)["services"]
        for name in ("backend", "app", "ui"):
            policy = services[name].get("restart", "")
            assert policy in ("always", "unless-stopped", "on-failure"), (
                f"Service '{name}' has no restart policy — it won't recover from crashes"
            )

    def test_no_hardcoded_bridge_ips(self):
        """
        Compose files must not contain hardcoded Docker bridge IPs (172.x.x.x).
        Use host.docker.internal or service names instead.
        """
        import re
        content = FLEET_COMPOSE.read_text()
        matches = re.findall(r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+", content)
        assert not matches, (
            f"fleet-config/docker-compose.yml contains hardcoded bridge IPs: {matches}"
        )

    def test_watchtower_label_on_all_app_services(self):
        """
        All app services must have the watchtower label so OTA updates work.
        """
        services = _load(FLEET_COMPOSE)["services"]
        for name in ("backend", "app", "ui"):
            labels = services[name].get("labels", [])
            label_str = " ".join(labels) if isinstance(labels, list) else str(labels)
            assert "watchtower.enable=true" in label_str, (
                f"Service '{name}' missing watchtower label — it won't receive OTA updates"
            )

    def test_ui_exposes_port_8080(self):
        """UI must be reachable on port 8080 from the host."""
        ui = _load(FLEET_COMPOSE)["services"]["ui"]
        ports = [str(p) for p in ui.get("ports", [])]
        assert any("8080" in p for p in ports), (
            f"ui service doesn't expose port 8080. Ports: {ports}"
        )

    def test_backend_exposes_port_8090(self):
        """Backend API must be reachable on port 8090."""
        backend = _load(FLEET_COMPOSE)["services"]["backend"]
        ports = [str(p) for p in backend.get("ports", [])]
        assert any("8090" in p for p in ports), (
            f"backend service doesn't expose port 8090. Ports: {ports}"
        )
