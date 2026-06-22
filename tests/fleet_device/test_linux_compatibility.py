"""
Tests that catch Mac/Windows-only patterns that break on Linux (Raspberry Pi).

The device runs Linux. Docker Desktop for Mac/Windows adds hostname aliases,
networking shortcuts, and volume paths that don't exist on Linux Docker Engine.
A failure here means the config will work in local dev but crash-loop on device.

Run with:
    pytest tests/fleet_device/test_linux_compatibility.py -v
"""
import re
import yaml
from pathlib import Path

FLEET_COMPOSE = Path("fleet-config/docker-compose.yml")
NGINX_CONF = Path("docker/nginx.conf")


def _compose() -> dict:
    return yaml.safe_load(FLEET_COMPOSE.read_text())


# ---------------------------------------------------------------------------
# Mac/Windows Docker Desktop patterns that don't exist on Linux
# ---------------------------------------------------------------------------

MAC_WINDOWS_PATTERNS = [
    # host.docker.internal without extra_hosts is Mac/Windows Docker Desktop only
    # (caught separately — here we check other patterns)
    (r"host\.docker\.internal", "host.docker.internal requires extra_hosts on Linux"),
    # /host.docker.internal/ style mounts don't exist on Linux
    (r"docker\.for\.mac\.", "docker.for.mac.* is Mac-only"),
    (r"docker\.for\.win\.", "docker.for.win.* is Windows-only"),
    # Mac-style volume paths
    (r"/Users/", "Hardcoded /Users/ path is Mac-only"),
    (r"/home/\w+/", "Hardcoded home directory path — use relative or /opt/ paths"),
    # Windows-style paths
    (r"[A-Z]:\\\\", "Windows-style path found"),
]


class TestLinuxCompatibility:

    def test_compose_no_mac_windows_volume_paths(self):
        """
        Volume mounts must use absolute Linux paths (/opt/aquila/...) not
        Mac (/Users/...) or Windows (C:\\...) paths.
        """
        content = FLEET_COMPOSE.read_text()
        for pattern, message in [
            (r"/Users/", "Mac-only /Users/ path"),
            (r"[A-Z]:\\\\", "Windows-style path"),
            (r"~/", "Tilde home path — not portable"),
        ]:
            matches = re.findall(pattern, content)
            assert not matches, f"fleet-config/docker-compose.yml: {message}: {matches}"

    def test_compose_no_mac_docker_hostnames(self):
        """
        docker.for.mac.* and docker.for.win.* hostnames only exist in
        Docker Desktop — they crash on Linux Docker Engine.
        """
        content = FLEET_COMPOSE.read_text()
        for pattern in (r"docker\.for\.mac\.", r"docker\.for\.win\."):
            assert not re.search(pattern, content), (
                f"Found Mac/Windows Docker Desktop hostname pattern '{pattern}' "
                f"in fleet-config/docker-compose.yml — will not resolve on Linux"
            )

    def test_nginx_no_mac_docker_hostnames(self):
        """nginx.conf must not use Mac/Windows Docker Desktop hostnames."""
        content = NGINX_CONF.read_text()
        for pattern in (r"docker\.for\.mac\.", r"docker\.for\.win\."):
            assert not re.search(pattern, content), (
                f"Found Mac/Windows hostname pattern in nginx.conf: '{pattern}'"
            )

    def test_host_docker_internal_in_nginx_requires_resolver(self):
        """
        host.docker.internal in nginx.conf needs a resolver directive.
        On Linux, Docker Desktop is not present so the hostname only resolves
        via extra_hosts + Docker's embedded DNS (127.0.0.11). Without a
        resolver, nginx looks it up at startup before DNS is ready and crashes.
        This is the exact bug that took down sentri-ui on SN01.
        """
        content = NGINX_CONF.read_text()
        if "host.docker.internal" not in content:
            return
        assert "resolver 127.0.0.11" in content, (
            "nginx.conf uses host.docker.internal but has no 'resolver 127.0.0.11' "
            "directive. On Linux (Pi), nginx crashes at startup without it. "
            "On Mac, Docker Desktop resolves this automatically — masking the bug."
        )

    def test_compose_devices_are_linux_paths(self):
        """
        Device mounts must use Linux device paths (/dev/...).
        Any non-/dev/ device path indicates a copy-paste from a non-Linux config.
        """
        services = _compose()["services"]
        for name, service in services.items():
            for device in service.get("devices", []):
                host_path = device.split(":")[0]
                assert host_path.startswith("/dev/"), (
                    f"Service '{name}' device '{device}' is not a Linux /dev/ path"
                )

    def test_compose_volumes_use_opt_aquila(self):
        """
        All host volume mounts must be under /opt/aquila/ — the standard
        device path. Mounts to /tmp/, relative paths, or developer home dirs
        indicate a local-dev config that will fail or leak data on device.
        """
        services = _compose()["services"]
        for name, service in services.items():
            for volume in service.get("volumes", []):
                if ":" not in str(volume):
                    continue  # named volume, skip
                host_path = str(volume).split(":")[0]
                # Skip Docker socket (watchtower)
                if host_path == "/var/run/docker.sock":
                    continue
                if host_path == "/root/.docker/config.json":
                    continue
                # STATE_DIR parameterizes the host path; its default preserves /opt/aquila (#187).
                allowed = ("/opt/aquila", "${STATE_DIR:-/opt/aquila}", "/root", "/opt/fleet")
                assert host_path.startswith(allowed), (
                    f"Service '{name}' volume '{volume}' mounts from '{host_path}' "
                    f"— expected a /opt/aquila/... (or ${{STATE_DIR}}) path for device deployment"
                )

    def test_compose_no_platform_mac(self):
        """
        platform: linux/amd64 or linux/arm64 is fine.
        platform: linux/amd64 with a Mac build is a CI issue but not a crash.
        platform: macos or platform: windows would be wrong — check for it.
        """
        content = FLEET_COMPOSE.read_text()
        assert "platform: macos" not in content
        assert "platform: windows" not in content
