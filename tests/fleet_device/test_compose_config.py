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
        Compose files must not contain hardcoded Docker bridge IPs (172.16–31.x.x)
        — use host.docker.internal or service names — EXCEPT the fleet DNS
        forwarder gateway. That one must be a literal IP because Docker's `dns:`
        field cannot take a hostname (the resolver can't resolve itself), so it
        is exempted here (#314).
        """
        import re
        data = _load(FLEET_COMPOSE)
        # IPs legitimately allowed to be literal bridge addresses: the DNS
        # forwarder gateway referenced from each service's dns: list, plus the
        # subnet/gateway of a network we intentionally pin so that gateway is
        # deterministic (#314).
        allowed = set()
        for svc in data.get("services", {}).values():
            allowed.update(str(x) for x in (svc.get("dns") or []))
        for net in (data.get("networks") or {}).values():
            for cfg in ((net or {}).get("ipam") or {}).get("config", []) or []:
                if "gateway" in cfg:
                    allowed.add(str(cfg["gateway"]))
                if "subnet" in cfg:
                    allowed.add(str(cfg["subnet"]).split("/")[0])
        content = FLEET_COMPOSE.read_text()
        found = re.findall(r"172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+", content)
        offenders = [ip for ip in found if ip not in allowed]
        assert not offenders, (
            "fleet-config/docker-compose.yml contains hardcoded bridge IPs "
            f"(not the DNS forwarder): {offenders}"
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

    def test_backend_persists_ota_sentinel_directory(self):
        """
        The OTA auto-reboot sentinel (/opt/fleet/last_update.json) must sit on a
        host-backed bind mount so it survives the Watchtower container swap.

        /update/apply writes the sentinel, then Watchtower DESTROYS the old backend
        container and creates a new one; the new container reads the sentinel on
        startup to decide whether to reboot the host. If only /opt/fleet/.env is
        mounted (not the directory), the sentinel lands in the old container's
        ephemeral layer and is discarded — the device never auto-reboots.

        Regression guard for the #183 auto-reboot: the sentinel's parent directory
        (/opt/fleet) must be bind-mounted into the backend service, not just the
        single .env file.
        """
        backend = _load(FLEET_COMPOSE)["services"]["backend"]
        volumes = backend.get("volumes", [])
        # host_path:container_path[:opts] — collect the container-side targets.
        targets = [str(v).split(":")[1] for v in volumes if ":" in str(v)]
        assert "/opt/fleet" in targets, (
            "backend service must bind-mount the /opt/fleet directory so the OTA "
            "reboot sentinel (/opt/fleet/last_update.json) survives the container "
            f"swap. Mounting only /opt/fleet/.env is not enough. Volumes: {volumes}"
        )

    def test_backend_persists_sync_outbox(self):
        """
        The sync outbox (/opt/aquila/data/db/app.db) holds completed runs not yet
        pushed to the cloud. It must sit on a host-backed bind mount so it
        survives a container recreate (update / --force-recreate); otherwise
        every update silently discards unsynced runs.

        enqueue_event + the sync poller live only in the backend (aquila_web), so
        the backend is the sole owner of the queue and the one to persist it.
        """
        backend = _load(FLEET_COMPOSE)["services"]["backend"]
        volumes = backend.get("volumes", [])
        targets = [str(v).split(":")[1] for v in volumes if ":" in str(v)]
        assert "/opt/aquila/data" in targets, (
            "backend service must bind-mount /opt/aquila/data so the sync outbox "
            "(app.db) survives container recreation; otherwise unsynced runs are "
            f"lost on every update. Volumes: {volumes}"
        )


# ---------------------------------------------------------------------------
# Container DNS resilience (#314): the containers that make outbound calls must
# forward DNS to a resolver that FOLLOWS the host, not the stale upstream Docker
# freezes at network-creation time. Without this, in-container name resolution
# silently dies when host DNS changes (e.g. Tailscale MagicDNS takeover) — the
# sn06 sync/OTA outage where the backend could not resolve ingest/renew/ghcr.
# ---------------------------------------------------------------------------

# The fleet_default bridge gateway — the address at which the host-side DNS
# forwarder (dnsmasq) is reachable from inside the containers.
FLEET_FORWARDER_IP = "172.18.0.1"


def _dns(service: str) -> list[str]:
    svc = _load(FLEET_COMPOSE)["services"][service]
    return [str(x) for x in svc.get("dns", [])]


class TestFleetContainerDns:

    def test_backend_forwards_dns_to_host_first(self):
        """
        The backend (which runs Sync + cert renew) must forward DNS to the
        host-side forwarder first, so resolution follows the host instead of a
        frozen upstream. Regression guard for the sn06 sync outage (#314).
        """
        dns = _dns("backend")
        assert dns, (
            "backend has no dns: — container DNS will drift from the host "
            "resolver and silently fail when host DNS changes (sn06 outage)"
        )
        assert dns[0] == FLEET_FORWARDER_IP, (
            f"backend dns must forward to the host bridge gateway "
            f"{FLEET_FORWARDER_IP} first; got {dns}"
        )

    def test_backend_has_public_dns_fallback(self):
        """
        If the host forwarder is briefly unavailable, the backend must still
        resolve via public DNS — so a down forwarder never blackholes sync/OTA.
        Public fallbacks must come AFTER the host forwarder (#314).
        """
        dns = _dns("backend")
        assert dns[0] == FLEET_FORWARDER_IP, (
            f"host forwarder must be first so it is preferred; got {dns}"
        )
        fallback = dns[1:]
        assert "1.1.1.1" in fallback and "8.8.8.8" in fallback, (
            "backend dns must include public fallbacks 1.1.1.1 and 8.8.8.8 after "
            f"the host forwarder; got {dns}"
        )

    def test_fleet_network_pins_forwarder_gateway(self):
        """
        The bridge gateway must be PINNED so the forwarder address is
        deterministic on every device. Docker otherwise auto-assigns bridge
        subnets in creation order, so 172.18.0.1 is not guaranteed fleet-wide.
        A compose network must declare an explicit gateway == FLEET_FORWARDER_IP
        (#314).
        """
        data = _load(FLEET_COMPOSE)
        gateways = []
        for net in (data.get("networks") or {}).values():
            for cfg in ((net or {}).get("ipam") or {}).get("config", []) or []:
                if "gateway" in cfg:
                    gateways.append(str(cfg["gateway"]))
        assert FLEET_FORWARDER_IP in gateways, (
            f"No compose network pins gateway {FLEET_FORWARDER_IP}; the forwarder "
            "address would be non-deterministic across devices. Declared "
            f"gateways: {gateways}"
        )

    def test_app_forwards_dns_with_fallback(self):
        """
        The app container (cert renewal via aq_lib.renew, outbound calls) must
        use the same policy: host forwarder first, public fallbacks after (#314).
        """
        dns = _dns("app")
        assert dns[:1] == [FLEET_FORWARDER_IP], (
            f"app dns must forward to the host gateway first; got {dns}"
        )
        assert "1.1.1.1" in dns[1:] and "8.8.8.8" in dns[1:], (
            f"app dns must include public fallbacks after the forwarder; got {dns}"
        )

    def test_watchtower_forwards_dns_with_fallback(self):
        """
        Watchtower pulls images from ghcr.io; the same broken container DNS that
        stopped Sync also blocks OTA. It must use the host forwarder first with
        public fallbacks (#314).
        """
        dns = _dns("watchtower")
        assert dns[:1] == [FLEET_FORWARDER_IP], (
            f"watchtower dns must forward to the host gateway first; got {dns}"
        )
        assert "1.1.1.1" in dns[1:] and "8.8.8.8" in dns[1:], (
            f"watchtower dns must include public fallbacks after the forwarder; got {dns}"
        )

    def test_ui_has_no_dns_override(self):
        """
        The ui service serves static assets and makes no outbound calls, so it is
        intentionally left on default DNS (#314 scope).
        """
        assert _dns("ui") == [], (
            f"ui was not expected to override dns; got {_dns('ui')}"
        )
